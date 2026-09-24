#!/usr/bin/env python3
# /// script
# dependencies = ["fastmcp>=2.0.0"]
# ///
"""MCP dev-tools server — pipeline findings and report writer."""

import errno
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
DEFAULT_PIPELINE = ".claude/pipeline"

LABEL_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
Label = Annotated[str, Field(pattern=LABEL_PATTERN, min_length=1, max_length=40)]

# A plan's archive stem, e.g. "2026-09-09-orchestrator-plan-and-commit-ledger" — the
# same stem `.claude/plans/<stem>.md` is archived under, with no directory and no
# extension. The ledger is named identically, `.jsonl` in place of `.md`.
PLAN_PATTERN = r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(-[a-z0-9]+)*$"
PlanSlug = Annotated[str, Field(pattern=PLAN_PATTERN, min_length=11, max_length=200)]
_PLAN_ADAPTER = TypeAdapter(PlanSlug)
# `Label`'s Field(pattern=...) only self-enforces when used as a BaseModel field (like
# Findings/Report below) or when FastMCP validates a real tool call against the generated
# schema. write_findings/write_report take `label` as a bare function parameter, so a
# direct Python call — including every call in this file's own test suite, which invokes
# the unwrapped function to exercise it in-process — bypasses that validation entirely.
# This adapter re-validates explicitly inside each tool body so an unsafe label is
# rejected on every call path, not only the MCP protocol one.
_LABEL_ADAPTER = TypeAdapter(Label)


class _Strict(BaseModel):
    # extra="forbid" is load-bearing, not decorative: the default extra="ignore"
    # silently drops unknown fields, so a schema guarantee (e.g. CheckerFindings
    # has no `issues`) degrades back into a mere convention. It also protects
    # against typos — a misspelled optional field would otherwise validate
    # silently with its declared default, instead of failing loudly.
    model_config = ConfigDict(extra="forbid")


# --- Findings models -------------------------------------------------------
# A findings payload is a verification claim: it asserts that checks actually ran.
# `checks: list[...] = Field(min_length=1)` on every findings model below rejects an
# empty-checks payload at the schema layer, before the tool body ever runs — see the
# note at the bottom of the module on why the old runtime check is now redundant.


class Check(_Strict):
    name: str
    status: Literal["PASS", "FAIL", "ERROR"]
    exit_code: int | None  # null ONLY when status == "ERROR"
    output: str


class Issue(_Strict):
    file: str
    line: int | None = None  # None when the issue is file-level, not line-level
    description: str


class Failure(_Strict):
    test: str
    classification: Literal["REGRESSION", "STALE_TEST", "FLAKY", "UNCLEAR"]
    evidence: str
    recommendation: str


class CheckerFindings(_Strict):
    source: Literal["checker"]
    status: Literal["PASS", "FAIL", "ERROR"]
    checks: list[Check] = Field(min_length=1)
    # NO `issues` field. checker performs no diff review, so reporting one is
    # unrepresentable rather than merely discouraged.


class ReviewerFindings(_Strict):
    source: Literal["reviewer"]
    status: Literal["PASS", "FAIL", "ERROR"]
    checks: list[Check] = Field(min_length=1)
    issues: list[Issue] = []


class TesterFindings(_Strict):
    source: Literal["tester"]
    status: Literal["PASS", "FAIL", "ERROR"]
    checks: list[Check] = Field(min_length=1)
    failures: list[Failure] = []


Findings = Annotated[
    CheckerFindings | ReviewerFindings | TesterFindings,
    Field(discriminator="source"),
]


# --- Report models -----------------------------------------------------------
# Reports are not proof-of-execution: reader, writer, thinker, and researcher run no
# commands, so there is no `checks[]` and no exit code here. The `SubagentStop` guard
# demands presence and freshness for reports, never exit codes.


class ContextRequest(_Strict):
    needs: list[str]  # what is missing, specifically
    why: str  # why the agent cannot proceed without it


class FileEntry(_Strict):
    path: str
    role: str  # what the file IS, not what was done to it


class Interface(_Strict):
    location: str  # "file:line"
    signature: str  # signature only, no body


class Convention(_Strict):
    rule: str
    precedent: str  # "file:line" — REQUIRED. No citation, no convention.
    split: str | None = None  # set when the rule holds in some files and not others


class ReaderReport(_Strict):
    source: Literal["reader"]
    relevant_files: list[FileEntry]
    interfaces: list[Interface] = []
    conventions: list[Convention] = []
    entry_points: list[str] = []
    test_files: list[str] = []
    context_request: ContextRequest | None = None


class ModifiedFile(_Strict):
    path: str
    change: str  # one line: what changed
    in_scope: bool = True  # False = was not in `## Files to modify`
    note: str | None = None  # why, when in_scope is False


class WriterReport(_Strict):
    source: Literal["writer"]
    modified: list[ModifiedFile]
    context_request: ContextRequest | None = None


class Option(_Strict):
    name: str
    summary: str
    tradeoffs: str


class ThinkerReport(_Strict):
    source: Literal["thinker"]
    mode: Literal["analysis", "brainstorming", "qa"]
    findings: str | None = None  # analysis mode
    assessment: str | None = None  # analysis mode
    options: list[Option] = []  # brainstorming mode
    answer: str | None = None  # qa mode
    evidence: str | None = None  # qa mode
    recommendation: str  # REQUIRED in every mode
    caveats: list[str] = []
    context_request: ContextRequest | None = None


class Reference(_Strict):
    claim: str
    source: str  # URL or doc path — REQUIRED
    checked: str | None = None  # date or version the claim was true for


class ResearcherReport(_Strict):
    source: Literal["researcher"]
    prior_decisions: list[Reference] = []
    api_reference: list[Reference] = []
    recommended_approach: str
    caveats: list[str] = []
    context_request: ContextRequest | None = None


Report = Annotated[
    ReaderReport | WriterReport | ThinkerReport | ResearcherReport,
    Field(discriminator="source"),
]


# --- Plan Event models ----------------------------------------------------------
# One line per event in a plan's append-only .claude/plans/<plan>.jsonl — see
# spec/spec-architecture-plan-event-log.md (v8.1) for the full vocabulary. `ts` is
# never a model field (REQ-006a); it is merged in server-side at write time, exactly
# like write_findings/write_report already do with `written_at`.


class PlanArchived(_Strict):
    kind: Literal["plan_archived"]
    plan: str
    archive: str
    title: str
    supersedes: str | None = None


class TaskCreated(_Strict):
    kind: Literal["task_created"]
    task: int
    deliverable: str
    files: list[str] | None  # null marks a verification-only task
    track: str | None = None


class TaskAmended(_Strict):
    kind: Literal["task_amended"]
    task: int
    seq: int
    deliverable: str | None = None
    files: list[str] | None = None
    why: str


class TaskDropped(_Strict):
    kind: Literal["task_dropped"]
    task: int
    why: str


class Decision(_Strict):
    kind: Literal["decision"]
    text: str
    who: Literal["user", "orchestrator"]
    seq: int


class AutoCommit(_Strict):
    kind: Literal["auto_commit"]
    status: Literal["confirmed", "declined"]
    seq: int


class BaseRecorded(_Strict):
    kind: Literal["base_recorded"]
    sha: str
    seq: int
    reason: Literal["initial", "rebase_accepted"]


class EpochStart(_Strict):
    kind: Literal["epoch_start"]
    epoch: int
    wip: list[str] | None
    excluded_tasks: list[int]
    after_compaction: bool


class PlanEscalation(_Strict):
    # The plan-level trigger of the shared `escalation` kind — `task` is always
    # null here; the task-scoped trigger is `TaskEscalation` below, reachable only
    # through write_report, never through write_plan_event.
    kind: Literal["escalation"]
    topic: Literal[
        "tester_diagnosis",
        "base_rebased",
        "wip_dirty",
        "forced_fix_exhausted",
        "writer_report_lost",
        "base_unavailable",
    ]
    task: None = None
    seq: int
    detail: str


class PlanComplete(_Strict):
    kind: Literal["plan_complete"]
    status: Literal["clean", "parked"]


class PlanAbandoned(_Strict):
    kind: Literal["plan_abandoned"]
    why: str
    superseded_by: str | None = None


class WriterDispatched(_Strict):
    kind: Literal["writer_dispatched"]
    task: int
    attempt: int
    reason: Literal[
        "initial", "fix", "forced_fix", "redo", "report_lost", "branch_fix"
    ]
    files: list[str]
    track: str | None = None


class Ruling(_Strict):
    kind: Literal["ruling"]
    task: int | None  # null = branch-level ruling
    seq: int
    text: str


class TaskComplete(_Strict):
    kind: Literal["task_complete"]
    task: int
    attempt: int
    status: Literal["complete", "complete-with-parked"]
    sha: str | None
    files: list[str] | None
    no_sha_reason: Literal["verification_only", "auto_commit_declined"] | None


class CommitFailed(_Strict):
    kind: Literal["commit_failed"]
    task: int
    attempt: int
    seq: int
    reason: str
    files: list[str]


class TaskReverted(_Strict):
    kind: Literal["task_reverted"]
    task: int
    attempt: int  # the attempt being reverted
    sha: str  # the revert commit's own sha
    reverts: str  # the sha being reverted


PlanEvent = Annotated[
    PlanArchived
    | TaskCreated
    | TaskAmended
    | TaskDropped
    | Decision
    | AutoCommit
    | BaseRecorded
    | EpochStart
    | PlanEscalation
    | PlanComplete
    | PlanAbandoned
    | WriterDispatched
    | Ruling
    | TaskComplete
    | CommitFailed
    | TaskReverted,
    Field(discriminator="kind"),
]


# --- Internal, server-built event models ------------------------------------------
# Never accepted directly from a caller — write_findings/write_report (Task 3)
# build these from a subagent's Findings/Report plus the caller's plan-scoped
# parameters, and pass the dumped dict into _append.


class VerifyRound(_Strict):
    kind: Literal["verify_round"]
    task: int
    attempt: int
    source: Literal["checker", "reviewer", "tester"]
    seq: int
    status: Literal["PASS", "FAIL", "ERROR"]
    findings_total: int
    forced_fix: bool  # server-derived from dispatch_reason — never caller-supplied


class BranchCheck(_Strict):
    kind: Literal["branch_check"]
    round: int
    seq: int
    status: Literal["PASS", "FAIL", "ERROR"]
    findings_total: int


class BranchReview(_Strict):
    kind: Literal["branch_review"]
    round: int
    seq: int
    status: Literal["PASS", "FAIL", "ERROR"]
    findings_total: int


class BranchTest(_Strict):
    kind: Literal["branch_test"]
    round: int
    seq: int
    status: Literal["PASS", "FAIL", "ERROR"]
    findings_total: int


class WriterReturnedContextRequest(_Strict):
    needs: list[str]
    why: str


class WriterReturned(_Strict):
    kind: Literal["writer_returned"]
    task: int
    attempt: int
    in_scope: list[str]
    out_of_scope: list[str]
    context_request: WriterReturnedContextRequest | None


class TaskEscalation(_Strict):
    # The task-scoped trigger of the shared `escalation` kind — reachable only
    # through write_report, never through write_plan_event's PlanEvent union.
    kind: Literal["escalation"]
    task: int
    attempt: int
    topic: Literal["writer_blocked"]
    detail: str


# --- Plan event write-path constants ----------------------------------------------

# §4.2's "always written, nullable" serialization exception list: these fields are
# written even when None, unlike every other optional field (omitted when unset).
ALWAYS_WRITTEN_NULLABLE: dict[str, frozenset[str]] = {
    "task_created": frozenset({"files"}),
    "task_complete": frozenset({"sha", "files", "no_sha_reason"}),
    "writer_returned": frozenset({"context_request"}),
    "ruling": frozenset({"task"}),
    "escalation": frozenset({"task"}),
    "epoch_start": frozenset({"wip"}),
}

_SHA_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")

# The closed 7-kind list TaskState.last_attempt/ready are defined over (§2, §4.1) —
# no other task-scoped kind carries an `attempt` field at all.
_ATTEMPT_KINDS = frozenset(
    {
        "writer_dispatched",
        "writer_returned",
        "verify_round",
        "escalation",
        "task_complete",
        "commit_failed",
        "task_reverted",
    }
)


# --- Platform shim (locking + positional reads) -----------------------------------
# fcntl/os.pread are POSIX-only; the hooks already target Windows (a73271d), so this
# module must still import and work there. msvcrt.locking retries internally and
# gives up after ~10s, which is what the retry loop below rides on.

_OPEN_FLAGS = os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)

# Windows byte-range locks are mandatory: locking byte 0 (real data, line 1) would
# block any other handle's read of that range while a write holds the lock. Lock a
# sentinel byte far past any realistic EOF instead.
_WIN_LOCK_OFFSET = 0x7FFFFFFF


def _lock(fd: int) -> None:
    if sys.platform == "win32":
        os.lseek(fd, _WIN_LOCK_OFFSET, os.SEEK_SET)
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                return
            except OSError as e:
                if e.errno in (errno.EDEADLK, errno.EACCES):
                    continue
                raise
    else:
        fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        os.lseek(fd, _WIN_LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _read_at(fd: int, offset: int, n: int) -> bytes:
    if sys.platform == "win32":
        os.lseek(fd, offset, os.SEEK_SET)
        return os.read(fd, n)
    return os.pread(fd, n, offset)


# --- Dedup cache -------------------------------------------------------------------


@dataclass
class _PlanCache:
    plan_identity: str
    offset: int
    size: int
    mtime_ns: int
    key_to_ts: dict[tuple, int]
    dispatch_reason: dict[tuple[int, int], str]


_CACHE: dict[str, _PlanCache] = {}


def _natural_key(ev: dict) -> tuple:
    """The per-kind natural dedup key — spec REQ-014, cross-checked against §4.2."""
    kind = ev["kind"]
    if kind == "escalation":
        if ev.get("task") is None:
            return (kind, ev["topic"], ev["seq"])
        return (kind, ev["task"], ev["attempt"])
    if kind in ("plan_archived", "plan_complete", "plan_abandoned"):
        return (kind,)
    if kind in ("task_created", "task_dropped"):
        return (kind, ev["task"])
    if kind == "task_amended":
        return (kind, ev["task"], ev["seq"])
    if kind in ("decision", "auto_commit"):
        return (kind, ev["seq"])
    if kind == "base_recorded":
        return (kind, ev["sha"], ev["seq"])
    if kind == "epoch_start":
        return (kind, ev["epoch"])
    if kind in ("branch_check", "branch_review", "branch_test"):
        return (kind, ev["round"], ev["seq"])
    if kind in ("writer_dispatched", "writer_returned", "task_complete", "task_reverted"):
        return (kind, ev["task"], ev["attempt"])
    if kind == "verify_round":
        return (kind, ev["task"], ev["attempt"], ev["source"], ev["seq"])
    if kind == "ruling":
        return (kind, ev["task"], ev["seq"])
    if kind == "commit_failed":
        return (kind, ev["task"], ev["attempt"], ev["seq"])
    raise ValueError(f"unknown event kind for natural key: {kind!r}")


def _fold(cache: _PlanCache, data: bytes) -> None:
    """Folds every complete line in `data` into `cache`'s dedup/dispatch maps.
    Unparseable lines are skipped silently (REQ-019) — never raised."""
    for line in data.split(b"\n"):
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        try:
            key = _natural_key(ev)
            ts = ev["ts"]
            reason = ev["reason"] if ev.get("kind") == "writer_dispatched" else None
            cache.key_to_ts[key] = ts
            if reason is not None:
                cache.dispatch_reason[(ev["task"], ev["attempt"])] = reason
        except (KeyError, TypeError, ValueError):
            continue


def _append(plan: str, events: list[dict]) -> list[dict]:
    """Implements REQ-011 steps 0-7 for one or more already-validated event dicts,
    under a single lock acquisition. Returns [{"kind", "status", "ts"}, ...]."""
    md_path = PROJECT_DIR / ".claude/plans" / f"{plan}.md"
    if not md_path.exists():
        raise ValueError(f"plan archive not found: .claude/plans/{plan}.md")

    plans_dir = PROJECT_DIR / ".claude/plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    path = plans_dir / f"{plan}.jsonl"

    fd = os.open(str(path), _OPEN_FLAGS)
    try:
        _lock(fd)
        try:
            size = os.fstat(fd).st_size
            if size == 0 and events[0]["kind"] != "plan_archived":
                raise ValueError("plan log is empty: first event must be plan_archived")
            if size == 0 and events[0].get("plan") != plan:
                raise ValueError(
                    f"plan identity mismatch: file is {events[0].get('plan')}, "
                    f"call is {plan}"
                )

            cache = _CACHE.get(plan)
            if cache is not None and size < cache.offset:
                # The file shrank (truncated, or deleted and recreated) since the
                # cache was last warm — treat it as cold and re-seed from scratch,
                # including the identity re-check below.
                _CACHE.pop(plan, None)
                cache = None

            seed_deferred = False
            if cache is None:
                if size == 0:
                    # First-ever write to this file: seed identity from the
                    # incoming plan_archived event itself (REQ-017 special case).
                    # Identity already validated above (M3). Not stored into
                    # `_CACHE` until after the write below succeeds.
                    cache = _PlanCache(
                        plan_identity=plan,
                        offset=0,
                        size=0,
                        mtime_ns=0,
                        key_to_ts={},
                        dispatch_reason={},
                    )
                    seed_deferred = True
                else:
                    data = _read_at(fd, 0, size)
                    first_line = data.split(b"\n", 1)[0]
                    try:
                        first_ev = json.loads(first_line)
                    except ValueError:
                        first_ev = None
                    if (
                        not isinstance(first_ev, dict)
                        or first_ev.get("kind") != "plan_archived"
                        or not isinstance(first_ev.get("plan"), str)
                    ):
                        raise ValueError("plan log has no valid plan_archived first line")
                    cache = _PlanCache(
                        plan_identity=first_ev["plan"],
                        offset=0,
                        size=0,
                        mtime_ns=0,
                        key_to_ts={},
                        dispatch_reason={},
                    )
                    _fold(cache, data)
                    st = os.fstat(fd)
                    cache.offset = size
                    cache.size = size
                    cache.mtime_ns = st.st_mtime_ns
                if not seed_deferred:
                    _CACHE[plan] = cache
            else:
                st = os.fstat(fd)
                if (size, st.st_mtime_ns) != (cache.size, cache.mtime_ns):
                    new_data = _read_at(fd, cache.offset, size - cache.offset)
                    _fold(cache, new_data)
                    cache.offset = size
                    cache.size = size
                    cache.mtime_ns = st.st_mtime_ns

            if size > 0 and cache.plan_identity != plan:
                raise ValueError(
                    f"plan identity mismatch: file is {cache.plan_identity}, call is {plan}"
                )

            # Step 3a: torn-line repair.
            prefix = b""
            if size > 0:
                last_byte = _read_at(fd, size - 1, 1)
                if last_byte != b"\n":
                    prefix = b"\n"

            # New keys/reasons are staged locally and merged into `cache` only after
            # `os.write` below has fully succeeded — if it raises, `cache` must be
            # left exactly as it was before this call.
            outcomes: list[dict] = []
            to_write = bytearray(prefix)
            new_key_to_ts: dict[tuple, int] = {}
            new_dispatch_reason: dict[tuple[int, int], str] = {}
            for ev in events:
                key = _natural_key(ev)
                if key in cache.key_to_ts or key in new_key_to_ts:
                    ts_existing = new_key_to_ts.get(key, cache.key_to_ts.get(key))
                    outcomes.append(
                        {"kind": ev["kind"], "status": "duplicate", "ts": ts_existing}
                    )
                    continue
                if ev["kind"] == "verify_round":
                    ev["forced_fix"] = (
                        cache.dispatch_reason.get((ev["task"], ev["attempt"])) == "forced_fix"
                    )
                ts = int(time.time())
                ev_out = dict(ev)
                ev_out["ts"] = ts
                to_write.extend(json.dumps(ev_out).encode("utf-8") + b"\n")
                new_key_to_ts[key] = ts
                if ev["kind"] == "writer_dispatched":
                    new_dispatch_reason[(ev["task"], ev["attempt"])] = ev["reason"]
                outcomes.append({"kind": ev["kind"], "status": "written", "ts": ts})

            payload = bytes(to_write)
            if payload:
                written = 0
                while written < len(payload):
                    n = os.write(fd, payload[written:])
                    written += n
                st = os.fstat(fd)
                cache.offset = size + len(payload)
                cache.size = size + len(payload)
                cache.mtime_ns = st.st_mtime_ns

            cache.key_to_ts.update(new_key_to_ts)
            cache.dispatch_reason.update(new_dispatch_reason)
            _CACHE[plan] = cache

            return outcomes
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


mcp = FastMCP("dev-tools")


def _pipeline_dir(pipeline: str | None) -> Path:
    pipeline_dir = PROJECT_DIR / (pipeline or DEFAULT_PIPELINE)
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    return pipeline_dir


def _unique_path(pipeline_dir: Path, source: str, label: str, kind: str) -> Path:
    """kind is 'findings' or 'report'. Returns a path that does not yet exist —
    the common case is the label alone; a collision (two agents picked the same
    label) is resolved by appending a short random suffix rather than overwriting."""
    path = pipeline_dir / f"{source}-{label}-{kind}.json"
    while path.exists():
        path = pipeline_dir / f"{source}-{label}-{uuid.uuid4().hex[:4]}-{kind}.json"
    return path


@mcp.tool()
def write_findings(
    findings: Findings, label: Label, pipeline: str | None = None
) -> str:
    """
    Write findings to .claude/pipeline/<source>-<label>-findings.json. Always call — even
    on PASS. `exit_code` is null only when a check's own `status` is "ERROR"; a check that
    could not execute at all must still be reported as a checks[] entry with
    status="ERROR" (exit_code=null), never omitted — omission is indistinguishable from
    a run that never happened.
    label: a short kebab-case slug describing what this call's result covers (e.g.
        "lint-typecheck-build") — specific enough that two agents of the same type
        running in parallel are unlikely to pick the same one. On an actual on-disk
        collision, a random 4-hex-char disambiguator is appended rather than
        overwriting the earlier file.
    pipeline: optional override for multi-track runs, e.g. '.claude/pipeline/track-a'
    """
    _LABEL_ADAPTER.validate_python(label)
    pipeline_dir = _pipeline_dir(pipeline)

    payload = findings.model_dump(mode="json")
    payload.pop("source", None)
    payload.pop("status", None)
    out = {
        "source": findings.source,
        "status": findings.status,
        "written_at": int(time.time()),
        **payload,
    }

    out_path = _unique_path(pipeline_dir, findings.source, label, "findings")
    out_path.write_text(json.dumps(out, indent=2))
    return f"wrote {pipeline or DEFAULT_PIPELINE}/{out_path.name}"


@mcp.tool()
def write_report(report: Report, label: Label, pipeline: str | None = None) -> str:
    """
    Write a report to .claude/pipeline/<source>-<label>-report.json. Always call, even
    when there is nothing noteworthy to say. `context_request` is how an agent signals it
    cannot proceed — set it instead of writing a "## Context Request" heading in prose;
    the orchestrator branches on `report.context_request is not None`. A report is not
    proof-of-execution: it carries no checks[] or exit codes.
    label: a short kebab-case slug describing what this call's result covers (e.g.
        "add-priority-field") — specific enough that two agents of the same type
        running in parallel are unlikely to pick the same one. On an actual on-disk
        collision, a random 4-hex-char disambiguator is appended rather than
        overwriting the earlier file.
    pipeline: optional override for multi-track runs, e.g. '.claude/pipeline/track-a'
    """
    _LABEL_ADAPTER.validate_python(label)
    pipeline_dir = _pipeline_dir(pipeline)

    payload = report.model_dump(mode="json")
    payload.pop("source", None)
    out = {
        "source": report.source,
        "written_at": int(time.time()),
        **payload,
    }

    out_path = _unique_path(pipeline_dir, report.source, label, "report")
    out_path.write_text(json.dumps(out, indent=2))
    return f"wrote {pipeline or DEFAULT_PIPELINE}/{out_path.name}"


@mcp.tool()
def write_plan_event(event: PlanEvent, plan: PlanSlug) -> str:
    """
    Append one event to .claude/plans/<plan>.jsonl — the per-plan, append-only Plan
    Event Log (spec/spec-architecture-plan-event-log.md). Orchestrator-only: this tool
    MUST NOT appear in any subagent's tool list. Supports exactly these 16 kinds:
    plan_archived, task_created, task_amended, task_dropped, decision, auto_commit,
    base_recorded, epoch_start, escalation (plan-level trigger, task=null),
    plan_complete, plan_abandoned, writer_dispatched, ruling, task_complete,
    commit_failed, task_reverted. The first event ever written for a plan MUST be
    plan_archived — any other kind against an empty/absent log is rejected.
    plan: the plan's archive stem exactly as recorded at `.claude/plans/<plan>.md`
        (e.g. "2026-09-09-orchestrator-plan-and-commit-ledger"), no directory, no
        extension. The log is named identically with a `.jsonl` extension and is never
        overwritten across different plans. The file is created on first append;
        nothing needs to pre-create it.
    Returns "events: " followed by a JSON array of {"kind", "status", "ts"} objects —
    status is "written" or "duplicate" (a retried call reports the ORIGINAL ts).
    """
    _PLAN_ADAPTER.validate_python(plan)
    dumped = event.model_dump(mode="json", exclude_none=True)
    for field in ALWAYS_WRITTEN_NULLABLE.get(event.kind, frozenset()):
        dumped[field] = getattr(event, field)
    if event.kind == "task_amended" and "files" in event.model_fields_set:
        dumped["files"] = event.files
    outcomes = _append(plan, [dumped])
    return "events: " + json.dumps(outcomes)


if __name__ == "__main__":
    mcp.run(transport="stdio")
