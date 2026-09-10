#!/usr/bin/env python3
# /// script
# dependencies = ["fastmcp>=2.0.0"]
# ///
"""MCP dev-tools server — pipeline findings and report writer."""

import json
import os
import time
import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

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


# --- Ledger model --------------------------------------------------------------
# One line per commit event in a plan's append-only .claude/plans/<plan>.jsonl. Unlike
# findings/reports, this does not cross a subagent boundary — the orchestrator both runs
# the `git commit`/`git revert` and calls this tool in the same breath, so there is no
# proof-of-execution to attest (no `checks[]`, no exit code). What this model buys is
# schema validation only: a malformed line would otherwise silently corrupt a file every
# later Resuming/Run Start/Adjudication Protocol read depends on parsing correctly.


class LedgerEntry(_Strict):
    task: int
    sha: str | None  # null ONLY on the degraded, Bash-unavailable path
    status: Literal["complete", "complete-with-parked", "reverted"] | None = None
    files: list[str] | None = None
    ruling: str | None = None  # set only when status == "complete-with-parked"
    reverts: str | None = None  # set only when status == "reverted"


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


def _plan_ledger_path(plan: str) -> Path:
    plans_dir = PROJECT_DIR / ".claude/plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    return plans_dir / f"{plan}.jsonl"


@mcp.tool()
def write_ledger_entry(entry: LedgerEntry, plan: PlanSlug) -> str:
    """
    Append one line to .claude/plans/<plan>.jsonl — the per-plan commit ledger. Always
    append, never rewrite an existing line — a task may accumulate more than one line
    (e.g. a commit, then a later revert); the last line per task number is that task's
    current status.
    plan: the plan's archive stem exactly as recorded in progress.md's **Plan:** field
        (e.g. "2026-09-09-orchestrator-plan-and-commit-ledger", no directory, no
        extension). The ledger is named identically with a `.jsonl` extension, alongside
        the plan's own `.md` file under `.claude/plans/`, and is never overwritten across
        different plans — unlike `progress.md`, the single "current effort" view, which
        is overwritten each time a new plan archives. The file is created on first
        append; nothing needs to pre-create it.
    `sha` is required on every entry — use `null` only on the degraded, Bash-unavailable
    path (where `status`/`files` are also omitted, since neither is known). `status`,
    `files`, `ruling`, `reverts` are included only when applicable to that line's outcome;
    unset fields are omitted from the written line, never written as an explicit `null`
    placeholder (except `sha`, which is always present, sometimes `null`).
    """
    _PLAN_ADAPTER.validate_python(plan)
    path = _plan_ledger_path(plan)
    payload = entry.model_dump(mode="json", exclude_none=True)
    payload["sha"] = entry.sha  # always present, even when null (degraded path) —
    # exclude_none above would otherwise drop it like any other None field
    with path.open("a") as f:
        f.write(json.dumps(payload) + "\n")
    return f"appended to .claude/plans/{path.name}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
