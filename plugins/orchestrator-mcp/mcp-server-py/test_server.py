"""Tests for the Plan Event Log write path (Task 1 of
spec/spec-architecture-plan-event-log.md v8.1) — write_plan_event, _append, the
dedup cache, and the platform shim. Run via:
    uv run --with pytest --with 'fastmcp>=2.0.0' pytest plugins/orchestrator-mcp/mcp-server-py
"""

import errno
import importlib.util
import json
import multiprocessing
import os
import threading
import time
import typing
from pathlib import Path
from typing import Any

import pytest

_SERVER_PATH = Path(__file__).parent / "server.py"
_spec = importlib.util.spec_from_file_location("server", str(_SERVER_PATH))
assert _spec is not None and _spec.loader is not None
server: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)

write_plan_event = getattr(server.write_plan_event, "fn", server.write_plan_event)
read_plan_events = getattr(server.read_plan_events, "fn", server.read_plan_events)
get_plan_state = getattr(server.get_plan_state, "fn", server.get_plan_state)
write_findings = getattr(server.write_findings, "fn", server.write_findings)
write_report = getattr(server.write_report, "fn", server.write_report)

PLAN = "2026-09-24-test-plan"


@pytest.fixture
def plan(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "PROJECT_DIR", tmp_path)
    server._CACHE.clear()
    plans_dir = tmp_path / ".claude" / "plans"
    plans_dir.mkdir(parents=True)
    (plans_dir / f"{PLAN}.md").write_text("# test plan\n")
    return PLAN


def _log_path(plan_stem):
    return server.PROJECT_DIR / ".claude" / "plans" / f"{plan_stem}.jsonl"


def _lines(plan_stem):
    """Mirrors server._fold's REQ-019 behaviour: unparseable lines are skipped,
    never raised."""
    path = _log_path(plan_stem)
    if not path.exists():
        return []
    lines = []
    for l in path.read_text().splitlines():
        if not l:
            continue
        try:
            lines.append(json.loads(l))
        except ValueError:
            continue
    return lines


def _archive(plan_stem, archive="a", title="t"):
    return write_plan_event(
        server.PlanArchived(kind="plan_archived", plan=plan_stem, archive=archive, title=title),
        plan_stem,
    )


# --- AC-001 -------------------------------------------------------------------


def test_ac_001(plan):
    _archive(plan)
    lines = _lines(plan)
    assert len(lines) == 1
    assert lines[0]["kind"] == "plan_archived"

    write_plan_event(
        server.TaskCreated(kind="task_created", task=1, deliverable="x", files=None),
        plan,
    )
    lines = _lines(plan)
    assert len(lines) == 2
    assert "plan" not in lines[1]


# --- AC-002 -------------------------------------------------------------------


def test_ac_002(plan):
    missing = "2026-09-24-does-not-exist"
    with pytest.raises(ValueError):
        write_plan_event(
            server.PlanArchived(kind="plan_archived", plan=missing, archive="a", title="t"),
            missing,
        )
    assert not _log_path(missing).exists()


# --- AC-002a ------------------------------------------------------------------


def test_ac_002a(plan):
    with pytest.raises(ValueError):
        write_plan_event(
            server.TaskCreated(kind="task_created", task=1, deliverable="x", files=None),
            plan,
        )
    # A zero-byte file MAY exist (O_CREAT), but no line was ever written.
    path = _log_path(plan)
    if path.exists():
        assert path.stat().st_size == 0
    assert _lines(plan) == []


# --- AC-002b ------------------------------------------------------------------


def test_ac_002b(plan):
    _archive(plan)  # plan_archived's own `plan` field == PLAN

    # Simulate a caller bug: a `<other>.jsonl` file whose own first-line identity
    # (`plan_archived.plan`) disagrees with the `plan` parameter used to target it —
    # e.g. the file was copied/misnamed on disk.
    other = "2026-09-24-other-plan"
    (server.PROJECT_DIR / ".claude" / "plans" / f"{other}.md").write_text("# other\n")
    other_jsonl = _log_path(other)
    other_jsonl.write_bytes(_log_path(plan).read_bytes())
    server._CACHE.clear()

    with pytest.raises(ValueError, match="identity mismatch"):
        write_plan_event(
            server.TaskCreated(kind="task_created", task=1, deliverable="x", files=None),
            other,
        )


# --- AC-002c ------------------------------------------------------------------


def test_ac_002c(plan, monkeypatch):
    """Plan decision M2: B must open the file WHILE A still holds the lock (between
    A's open and A's release), not after A has already finished and released it."""
    real_lock = server._lock
    real_open = os.open

    a_locked = threading.Event()
    b_opened = threading.Event()
    c_done = threading.Event()

    def patched_lock(fd):
        name = threading.current_thread().name
        if name == "callerA":
            real_lock(fd)
            a_locked.set()
            assert (
                b_opened.wait(timeout=5)
            ), "timed out waiting for B to open while A holds the lock"
        elif name == "callerB":
            assert c_done.wait(timeout=5), "timed out waiting for C to finish"
            real_lock(fd)
        else:
            real_lock(fd)

    def patched_open(path_arg, flags, mode=0o777, *, dir_fd=None):
        fd = real_open(path_arg, flags, mode, dir_fd=dir_fd)
        if threading.current_thread().name == "callerB":
            b_opened.set()
        return fd

    results = {}

    def call_a():
        with pytest.raises(ValueError):
            write_plan_event(
                server.TaskCreated(kind="task_created", task=1, deliverable="x", files=None),
                plan,
            )

    def call_b():
        try:
            results["b"] = write_plan_event(
                server.TaskCreated(kind="task_created", task=4, deliverable="y", files=None),
                plan,
            )
        except Exception as e:  # noqa: BLE001 — surfaced via results, not swallowed
            results["b_error"] = e

    monkeypatch.setattr(server, "_lock", patched_lock)
    monkeypatch.setattr(server.os, "open", patched_open)
    a_thread = threading.Thread(target=call_a, name="callerA")
    a_thread.start()
    assert a_locked.wait(timeout=5), "timed out waiting for A to acquire the lock"

    b_thread = threading.Thread(target=call_b, name="callerB")
    b_thread.start()
    assert b_opened.wait(timeout=5), "timed out waiting for B to open while A holds the lock"

    a_thread.join(timeout=5)
    assert not a_thread.is_alive(), "caller A did not finish"

    # Caller C: the real first write.
    write_plan_event(
        server.PlanArchived(kind="plan_archived", plan=plan, archive="a", title="t"),
        plan,
    )
    c_done.set()
    b_thread.join(timeout=5)
    assert not b_thread.is_alive(), "caller B did not finish"

    assert "b_error" not in results, f"caller B raised: {results.get('b_error')!r}"
    b_events = json.loads(results["b"].removeprefix("events: "))
    assert b_events[0]["status"] == "written"

    lines = _lines(plan)
    assert len(lines) == 2
    assert lines[0]["kind"] == "plan_archived"
    assert lines[1]["kind"] == "task_created"
    assert lines[1]["task"] == 4


# --- AC-006 -------------------------------------------------------------------


def _mp_worker(server_path_str, project_dir_str, plan_stem, seq_start, count):
    spec = importlib.util.spec_from_file_location("server_mp_worker", server_path_str)
    assert spec is not None and spec.loader is not None
    mod: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.PROJECT_DIR = Path(project_dir_str)
    fn = getattr(mod.write_plan_event, "fn", mod.write_plan_event)
    for i in range(count):
        ev = mod.Decision(kind="decision", text="mp", who="orchestrator", seq=seq_start + i)
        fn(ev, plan_stem)


def test_ac_006(plan):
    _archive(plan)

    n_threads = 8
    per_thread = 25
    errors = []

    def worker(idx):
        try:
            for i in range(per_thread):
                seq = 1000 + idx * per_thread + i
                write_plan_event(
                    server.Decision(kind="decision", text="t", who="orchestrator", seq=seq),
                    plan,
                )
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors

    n_proc = 2
    per_proc = 25
    procs = []
    for p in range(n_proc):
        seq_start = 5000 + p * per_proc
        proc = multiprocessing.Process(
            target=_mp_worker,
            args=(str(_SERVER_PATH), str(server.PROJECT_DIR), plan, seq_start, per_proc),
        )
        procs.append(proc)
        proc.start()
    for proc in procs:
        proc.join(timeout=15)
        assert proc.exitcode == 0

    lines = _lines(plan)
    assert len(lines) == 1 + n_threads * per_thread + n_proc * per_proc
    for line in lines:
        json.dumps(line)  # every line parsed cleanly already; re-affirm well-formed
    seqs = [l["seq"] for l in lines if l["kind"] == "decision"]
    assert len(seqs) == len(set(seqs))


# --- AC-007 -------------------------------------------------------------------


def test_ac_007(plan):
    _archive(plan)
    ev = server.VerifyRound(
        kind="verify_round",
        task=3,
        attempt=2,
        source="checker",
        seq=1,
        status="PASS",
        findings_total=0,
        forced_fix=False,
    )
    first = server._append(plan, [ev.model_dump(mode="json", exclude_none=True)])
    assert first[0]["status"] == "written"
    original_ts = first[0]["ts"]

    retry = server._append(plan, [ev.model_dump(mode="json", exclude_none=True)])
    assert retry == [{"kind": "verify_round", "status": "duplicate", "ts": original_ts}]

    lines = _lines(plan)
    assert sum(1 for l in lines if l["kind"] == "verify_round") == 1


# --- AC-008 -------------------------------------------------------------------


def test_ac_008(plan):
    _archive(plan)
    write_plan_event(
        server.Decision(kind="decision", text="same text", who="orchestrator", seq=1), plan
    )
    write_plan_event(
        server.Decision(kind="decision", text="same text", who="orchestrator", seq=2), plan
    )
    lines = [l for l in _lines(plan) if l["kind"] == "decision"]
    assert len(lines) == 2


# --- AC-013 -------------------------------------------------------------------


def test_ac_013(plan):
    _archive(plan)
    write_plan_event(
        server.TaskCreated(kind="task_created", task=1, deliverable="x", files=None), plan
    )
    write_plan_event(server.Decision(kind="decision", text="t", who="user", seq=1), plan)
    kinds = [l["kind"] for l in _lines(plan)]
    assert kinds == ["plan_archived", "task_created", "decision"]


# --- AC-014 -------------------------------------------------------------------


def test_ac_014():
    import typing

    union_type, *_ = typing.get_args(server.PlanEvent)
    members = typing.get_args(union_type)
    plan_event_kinds = {
        typing.get_args(m.model_fields["kind"].annotation)[0] for m in members
    }
    assert len(plan_event_kinds) == 16
    subagent_kinds = {"verify_round", "branch_check", "branch_review", "branch_test"}
    # escalation's task-scoped trigger is already counted via PlanEvent's
    # plan-level `escalation` (same kind string); writer_returned is the 5th
    # subagent-exclusive kind.
    all_kinds = plan_event_kinds | subagent_kinds | {"writer_returned"}
    assert len(all_kinds) == 21


# --- AC-019 -------------------------------------------------------------------


def test_ac_019(plan):
    assert "ts" not in server.PlanArchived.model_fields
    assert "ts" not in server.Decision.model_fields
    _archive(plan)
    write_plan_event(server.Decision(kind="decision", text="t", who="user", seq=1), plan)
    for line in _lines(plan):
        assert "ts" in line  # merged in server-side


# --- AC-020 -------------------------------------------------------------------


def test_ac_020(plan):
    _archive(plan)
    write_plan_event(server.Decision(kind="decision", text="t", who="user", seq=1), plan)
    decision_line = next(l for l in _lines(plan) if l["kind"] == "decision")
    assert decision_line["kind"] == "decision"


# --- AC-022 -------------------------------------------------------------------


def test_ac_022():
    cache = server._PlanCache(
        plan_identity="p", offset=0, size=0, mtime_ns=0, key_to_ts={}, dispatch_reason={}
    )
    good = json.dumps({"kind": "plan_archived", "plan": "p", "ts": 1}).encode()
    torn = b'{"kind": "decision", "text": "trunc'  # not valid JSON, no trailing brace
    data = good + b"\n" + torn
    server._fold(cache, data)  # must not raise
    assert cache.key_to_ts == {("plan_archived",): 1}


# --- AC-023 -------------------------------------------------------------------


def test_ac_023(plan):
    _archive(plan)
    big_text_a = "a" * 9000
    big_text_b = "b" * 9000
    errors = []

    def writer(text, seq):
        try:
            write_plan_event(
                server.Ruling(kind="ruling", task=None, seq=seq, text=text), plan
            )
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    t1 = threading.Thread(target=writer, args=(big_text_a, 1))
    t2 = threading.Thread(target=writer, args=(big_text_b, 2))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert not errors

    lines = _lines(plan)
    rulings = [l for l in lines if l["kind"] == "ruling"]
    assert len(rulings) == 2
    texts = {r["text"] for r in rulings}
    assert texts == {big_text_a, big_text_b}


# --- AC-024 -------------------------------------------------------------------


def test_ac_024(plan):
    _archive(plan)
    ev = server.Ruling(kind="ruling", task=3, seq=1, text="ruling text")
    write_plan_event(ev, plan)
    write_plan_event(ev, plan)  # retried
    rulings = [l for l in _lines(plan) if l["kind"] == "ruling" and l.get("task") == 3]
    assert len(rulings) == 1


# --- AC-025 -------------------------------------------------------------------


def test_ac_025(plan):
    _archive(plan)
    for i in range(50):
        write_plan_event(server.Decision(kind="decision", text="t", who="user", seq=i + 2), plan)

    server._CACHE.clear()  # simulate a fresh process

    calls = []
    real_read_at = server._read_at

    def spying_read_at(fd, offset, n):
        calls.append(offset)
        return real_read_at(fd, offset, n)

    server._read_at = spying_read_at
    try:
        write_plan_event(server.Decision(kind="decision", text="t", who="user", seq=60), plan)
        first_call_count = len([c for c in calls if c == 0])
        assert first_call_count == 1  # exactly one full (offset-0) read to seed the cache

        # Append a line from OUTSIDE the server so the cache's (size, mtime_ns)
        # goes stale relative to the file, forcing the next call to fold the tail.
        offset_before_external_write = _log_path(plan).stat().st_size
        with open(_log_path(plan), "ab") as f:
            f.write(json.dumps({"kind": "decision", "text": "external", "who": "user",
                                 "seq": 999, "ts": 1}).encode() + b"\n")

        calls.clear()
        write_plan_event(server.Decision(kind="decision", text="t", who="user", seq=61), plan)
        assert 0 not in calls  # subsequent calls read only the incremental tail
        assert offset_before_external_write in calls  # the tail read starts at the old offset
    finally:
        server._read_at = real_read_at


# --- AC-026 -------------------------------------------------------------------


def test_ac_026(plan):
    _archive(plan)
    # Two-field key (task_created).
    write_plan_event(
        server.TaskCreated(kind="task_created", task=1, deliverable="a", files=None), plan
    )
    write_plan_event(
        server.TaskCreated(kind="task_created", task=1, deliverable="b", files=None), plan
    )
    task_created = [l for l in _lines(plan) if l["kind"] == "task_created"]
    assert len(task_created) == 1  # deliverable isn't part of the key -> deduped

    # Five-field key (verify_round: task, attempt, source, seq, kind).
    vr1 = server.VerifyRound(
        kind="verify_round", task=2, attempt=1, source="checker", seq=1,
        status="PASS", findings_total=0, forced_fix=False,
    )
    vr2 = server.VerifyRound(
        kind="verify_round", task=2, attempt=1, source="checker", seq=2,
        status="FAIL", findings_total=3, forced_fix=False,
    )
    server._append(plan, [vr1.model_dump(mode="json", exclude_none=True)])
    server._append(plan, [vr2.model_dump(mode="json", exclude_none=True)])
    vrs = [l for l in _lines(plan) if l["kind"] == "verify_round"]
    assert len(vrs) == 2  # distinct seq -> distinct events

    # escalation: null task (plan-level) vs int task (task-scoped) never collide.
    write_plan_event(
        server.PlanEscalation(kind="escalation", topic="wip_dirty", seq=1, detail="d"), plan
    )
    server._append(
        plan,
        [
            server.TaskEscalation(
                kind="escalation", task=3, attempt=1, topic="writer_blocked", detail="d"
            ).model_dump(mode="json", exclude_none=True)
        ],
    )
    escalations = [l for l in _lines(plan) if l["kind"] == "escalation"]
    assert len(escalations) == 2

    # ruling: nullable task, same seq, never collides.
    write_plan_event(server.Ruling(kind="ruling", task=None, seq=9, text="branch"), plan)
    write_plan_event(server.Ruling(kind="ruling", task=5, seq=9, text="task5"), plan)
    rulings = [l for l in _lines(plan) if l["kind"] == "ruling" and l.get("seq") == 9]
    assert len(rulings) == 2


# --- AC-029 -------------------------------------------------------------------


def test_ac_029(plan, monkeypatch):
    def boom(*_a, **_kw):
        raise AssertionError("fsync must never be called")

    monkeypatch.setattr(os, "fsync", boom)
    _archive(plan)
    write_plan_event(server.Decision(kind="decision", text="t", who="user", seq=1), plan)


# --- AC-030 -------------------------------------------------------------------


def test_ac_030(plan):
    _archive(plan)
    for i in range(299):
        write_plan_event(server.Decision(kind="decision", text="t", who="user", seq=i + 2), plan)
    assert len(_lines(plan)) == 300  # 1 plan_archived + 299 decisions, before timing the 301st

    server._CACHE.clear()
    start = time.monotonic()
    write_plan_event(server.Decision(kind="decision", text="t", who="user", seq=999), plan)
    elapsed_ms = (time.monotonic() - start) * 1000
    assert elapsed_ms < 50

    plans_dir = server.PROJECT_DIR / ".claude" / "plans"
    idx_files = list(plans_dir.glob(f"{plan}.idx")) + list(plans_dir.glob("*.idx"))
    assert idx_files == []


# --- AC-032 -------------------------------------------------------------------


def test_ac_032(plan):
    _archive(plan)
    path = _log_path(plan)

    # Simulate a crash mid-write: a short os.write that never got retried before
    # the process died appends a partial line with no trailing newline. Bytes
    # already on disk are untouched — the file only ever grows (REQ-011/CON-012).
    fragment = b'{"kind": "decision", "text": "torn'
    with open(path, "ab") as f:
        f.write(fragment)

    # A genuine crash also kills the crashing process's own in-memory cache; a new
    # process picks the file up cold.
    server._CACHE.clear()

    write_plan_event(server.Decision(kind="decision", text="t", who="user", seq=1), plan)

    raw = path.read_bytes()
    parts = raw.split(b"\n")
    assert len(parts) == 4  # plan_archived, torn fragment, new event, trailing ""
    assert json.loads(parts[0])["kind"] == "plan_archived"
    assert parts[1] == fragment  # the torn fragment stays as its own, unchanged line
    assert json.loads(parts[2])["kind"] == "decision"  # new event, cleanly parseable
    assert parts[3] == b""  # trailing newline after the new event


# --- fix 1: cache goes cold when the file shrinks ------------------------------


def test_append_after_file_shrinks(plan):
    _archive(plan)
    write_plan_event(server.Decision(kind="decision", text="t", who="user", seq=1), plan)
    path = _log_path(plan)
    assert server._CACHE[plan].offset == path.stat().st_size  # cache is warm

    # File shrinks: truncated, or deleted and recreated shorter, out from under a
    # warm cache.
    path.write_bytes(
        json.dumps({"kind": "plan_archived", "plan": plan, "archive": "a", "title": "t",
                    "ts": 1}).encode() + b"\n"
    )

    # Must not raise (no negative-length pread) and must re-seed from the file.
    write_plan_event(server.Decision(kind="decision", text="t", who="user", seq=2), plan)
    lines = _lines(plan)
    assert [l["kind"] for l in lines] == ["plan_archived", "decision"]
    assert lines[1]["seq"] == 2


# --- AC-033 -------------------------------------------------------------------


def test_ac_033(plan):
    _archive(plan)
    write_plan_event(server.Decision(kind="decision", text="one", who="user", seq=1), plan)
    path = _log_path(plan)
    with open(path, "a") as f:
        f.write("{not valid json at all\n")
    write_plan_event(server.Decision(kind="decision", text="two", who="user", seq=2), plan)

    server._CACHE.clear()
    cache = server._PlanCache(
        plan_identity=plan, offset=0, size=0, mtime_ns=0, key_to_ts={}, dispatch_reason={}
    )
    data = path.read_bytes()
    server._fold(cache, data)  # must not raise despite the mid-file garbage line
    assert ("plan_archived",) in cache.key_to_ts
    assert ("decision", 1) in cache.key_to_ts
    assert ("decision", 2) in cache.key_to_ts

    # L1: the write path's own subsequent append still succeeds past the garbage.
    write_plan_event(server.Decision(kind="decision", text="three", who="user", seq=3), plan)
    decisions = [l for l in _lines(plan) if l["kind"] == "decision"]
    assert {d["seq"] for d in decisions} == {1, 2, 3}


# --- AC-034 -------------------------------------------------------------------


def test_ac_034(plan):
    assert not _log_path(plan).exists()
    _archive(plan)  # first-ever write: identity seeded from the incoming event

    write_plan_event(
        server.TaskCreated(kind="task_created", task=1, deliverable="x", files=None), plan
    )
    lines = _lines(plan)
    assert len(lines) == 2

    # M3: a plan_archived whose own `plan` field mismatches the call parameter,
    # on the very first write, is rejected.
    other = "2026-09-24-other-plan"
    (server.PROJECT_DIR / ".claude" / "plans" / f"{other}.md").write_text("# other\n")
    with pytest.raises(ValueError, match="identity mismatch"):
        write_plan_event(
            server.PlanArchived(kind="plan_archived", plan=plan, archive="a", title="t"),
            other,
        )
    assert _lines(other) == []


# --- fix 2: cache is unchanged when the write fails ----------------------------


def test_cache_unchanged_when_write_fails(plan, monkeypatch):
    _archive(plan)
    cache_before = dict(server._CACHE[plan].key_to_ts)

    real_write = os.write
    calls = {"n": 0}

    def failing_write(fd, data):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(errno.ENOSPC, "simulated ENOSPC")
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", failing_write)
    ev = server.Decision(kind="decision", text="t", who="user", seq=1)
    with pytest.raises(OSError):
        write_plan_event(ev, plan)

    # The cache must be exactly as before the failed call — no stale key.
    assert server._CACHE[plan].key_to_ts == cache_before

    monkeypatch.setattr(os, "write", real_write)
    outcome = write_plan_event(ev, plan)
    events = json.loads(outcome.removeprefix("events: "))
    assert events[0]["status"] == "written"  # not "duplicate" — actually written this time

    lines = [l for l in _lines(plan) if l["kind"] == "decision"]
    assert len(lines) == 1


# --- round-2 fix: M3 on first write, deferred cache store ---------------------


def test_first_write_failure_then_mismatched_retry(plan, monkeypatch):
    assert not _log_path(plan).exists()

    real_write = os.write
    calls = {"n": 0}

    def failing_write(fd, data):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(errno.ENOSPC, "simulated ENOSPC")
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", failing_write)
    with pytest.raises(OSError):
        _archive(plan)
    assert plan not in server._CACHE
    monkeypatch.setattr(os, "write", real_write)

    other = "2026-09-24-other-plan-2"
    (server.PROJECT_DIR / ".claude" / "plans" / f"{other}.md").write_text("# other\n")
    with pytest.raises(ValueError, match="identity mismatch"):
        write_plan_event(
            server.PlanArchived(kind="plan_archived", plan=other, archive="a", title="t"),
            plan,
        )
    assert plan not in server._CACHE

    _archive(plan)
    lines = _lines(plan)
    assert len(lines) == 1
    assert lines[0]["kind"] == "plan_archived"


# --- fix 3: task_amended explicit null files vs omitted files -----------------


def test_task_amended_explicit_null_files(plan):
    _archive(plan)
    write_plan_event(
        server.TaskAmended(kind="task_amended", task=1, seq=1, files=None, why="clearing files"),
        plan,
    )
    write_plan_event(
        server.TaskAmended(kind="task_amended", task=1, seq=2, why="no files change"),
        plan,
    )
    amended = [l for l in _lines(plan) if l["kind"] == "task_amended"]
    assert amended[0]["seq"] == 1
    assert "files" in amended[0]
    assert amended[0]["files"] is None
    assert amended[1]["seq"] == 2
    assert "files" not in amended[1]


# --- REQ-019 / CON-012 regression tests ----------------------------------------


@pytest.mark.parametrize(
    "first_line",
    [
        "not json at all garbage",
        json.dumps([1, 2]),
        json.dumps(42),
        json.dumps({"kind": "decision", "text": "t", "who": "user", "seq": 1, "ts": 1}),
    ],
)
def test_line1_invalid_raises_con012(plan, first_line):
    path = _log_path(plan)
    path.write_text(first_line + "\n")
    server._CACHE.clear()

    with pytest.raises(ValueError) as exc_info:
        write_plan_event(server.Decision(kind="decision", text="t", who="user", seq=2), plan)
    assert str(exc_info.value) == "plan log has no valid plan_archived first line"


def test_fold_skips_valid_json_invalid_events(plan):
    good = json.dumps({"kind": "plan_archived", "plan": plan, "archive": "a", "title": "t",
                        "ts": 1}).encode()
    bad_array = json.dumps([1]).encode()
    bad_number = json.dumps(7).encode()
    missing_ts = json.dumps(
        {"kind": "decision", "seq": 1, "text": "x", "who": "user"}
    ).encode()
    unhashable_key = json.dumps(
        {"kind": "decision", "ts": 1, "seq": [1], "text": "x", "who": "user"}
    ).encode()
    missing_reason = json.dumps(
        {"kind": "writer_dispatched", "ts": 1, "task": 1, "attempt": 1, "files": ["a"]}
    ).encode()
    data = b"\n".join(
        [good, bad_array, bad_number, missing_ts, unhashable_key, missing_reason]
    ) + b"\n"
    path = _log_path(plan)
    path.write_bytes(data)
    server._CACHE.clear()

    write_plan_event(server.Decision(kind="decision", text="new", who="user", seq=99), plan)

    cache = server._CACHE[plan]
    assert set(cache.key_to_ts) == {("plan_archived",), ("decision", 99)}
    assert cache.key_to_ts[("plan_archived",)] == 1
    assert cache.dispatch_reason == {}


# --- Task 2: read_plan_events / get_plan_state ---------------------------------


def _vr(plan_stem, task, attempt, source, seq, forced_fix=False, status="PASS"):
    server._append(
        plan_stem,
        [
            server._serialize(
                server.VerifyRound(
                    kind="verify_round", task=task, attempt=attempt, source=source, seq=seq,
                    status=status, findings_total=0, forced_fix=forced_fix,
                )
            )
        ],
    )


def _returned(plan_stem, task, attempt):
    server._append(
        plan_stem,
        [
            server._serialize(
                server.WriterReturned(
                    kind="writer_returned", task=task, attempt=attempt,
                    in_scope=["f.py"], out_of_scope=[], context_request=None,
                )
            )
        ],
    )


# --- AC-001a --------------------------------------------------------------------


def test_ac_001a():
    src = _SERVER_PATH.read_text()
    assert "progress.md" not in src
    assert "write_ledger_entry" not in src


# --- AC-002d ----------------------------------------------------------------------


def test_ac_002d(plan):
    path = _log_path(plan)
    path.touch()
    assert path.stat().st_size == 0
    with pytest.raises(ValueError):
        get_plan_state(plan)


def test_ac_002d_missing_file(plan):
    assert not _log_path(plan).exists()
    with pytest.raises(ValueError):
        get_plan_state(plan)


def test_ac_002d_torn_first_line(plan):
    path = _log_path(plan)
    good = json.dumps({"kind": "plan_archived", "plan": plan, "ts": 1}).encode()
    path.write_bytes(b'{"kind": "decision", "text": "trunc\n' + good + b"\n")
    with pytest.raises(ValueError):
        get_plan_state(plan)


def test_ac_002d_blank_first_line(plan):
    path = _log_path(plan)
    good = json.dumps({"kind": "plan_archived", "plan": plan, "ts": 1}).encode()
    path.write_bytes(b"\n" + good + b"\n")
    with pytest.raises(ValueError):
        get_plan_state(plan)


def test_ac_002d_non_plan_archived_first_line(plan):
    path = _log_path(plan)
    bad_first = json.dumps({"kind": "decision", "text": "t", "who": "user", "seq": 1}).encode()
    path.write_bytes(bad_first + b"\n")
    with pytest.raises(ValueError):
        get_plan_state(plan)


# --- AC-009 -------------------------------------------------------------------


def test_ac_009(plan):
    import subprocess as sp

    repo = server.PROJECT_DIR
    sp.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    sp.run(["git", "config", "user.email", "a@b.c"], cwd=repo, capture_output=True, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=repo, capture_output=True, check=True)
    (repo / "f.txt").write_text("1")
    sp.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    sp.run(["git", "commit", "-m", "c1"], cwd=repo, capture_output=True, check=True)
    old_sha = sp.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    _archive(plan)
    write_plan_event(
        server.TaskCreated(kind="task_created", task=1, deliverable="x", files=["f.txt"]), plan
    )
    write_plan_event(server.Decision(kind="decision", text="t", who="user", seq=1), plan)
    _vr(plan, 1, 1, "checker", 1)
    write_plan_event(server.Ruling(kind="ruling", task=1, seq=1, text="ok"), plan)
    write_plan_event(
        server.BaseRecorded(kind="base_recorded", sha=old_sha, seq=1, reason="initial"), plan
    )

    # Rewrite history: old_sha is no longer an ancestor of the new HEAD.
    (repo / "f.txt").write_text("2")
    sp.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    sp.run(
        ["git", "commit", "--amend", "-m", "c1-amended"], cwd=repo, capture_output=True, check=True
    )

    state = get_plan_state(plan, validate_shas=True)
    assert state.base_sha_valid is False

    events = read_plan_events(plan)
    kinds = [e["kind"] for e in events]
    assert "task_created" in kinds
    assert "decision" in kinds
    assert "verify_round" in kinds
    assert "ruling" in kinds


# --- AC-010 -------------------------------------------------------------------


def test_ac_010(plan, monkeypatch):
    _archive(plan)
    write_plan_event(
        server.TaskCreated(kind="task_created", task=1, deliverable="x", files=["f.py"]), plan
    )
    write_plan_event(
        server.WriterDispatched(
            kind="writer_dispatched", task=1, attempt=1, reason="initial", files=["f.py"]
        ),
        plan,
    )
    write_plan_event(
        server.TaskComplete(
            kind="task_complete", task=1, attempt=1, status="complete", sha="a" * 40,
            files=["f.py"], no_sha_reason=None,
        ),
        plan,
    )
    write_plan_event(
        server.BaseRecorded(kind="base_recorded", sha="b" * 40, seq=1, reason="initial"), plan
    )

    def boom(*_a, **_kw):
        raise FileNotFoundError()

    monkeypatch.setattr(server.subprocess, "run", boom)

    state = get_plan_state(plan, validate_shas=True)
    assert state.base_sha_valid is None
    assert state.tasks[1].sha_valid is None


# --- AC-011 (closed half) ------------------------------------------------------


def test_ac_011(plan):
    _archive(plan)
    write_plan_event(server.PlanComplete(kind="plan_complete", status="clean"), plan)
    state = get_plan_state(plan)
    assert state.closed is True


# --- AC-016 -------------------------------------------------------------------


def test_ac_016(plan):
    _archive(plan)
    write_plan_event(
        server.TaskCreated(kind="task_created", task=3, deliverable="x", files=["f.py"]), plan
    )
    write_plan_event(
        server.WriterDispatched(
            kind="writer_dispatched", task=3, attempt=1, reason="initial", files=["f.py"]
        ),
        plan,
    )
    write_plan_event(
        server.TaskComplete(
            kind="task_complete", task=3, attempt=1, status="complete", sha="a" * 40,
            files=["f.py"], no_sha_reason=None,
        ),
        plan,
    )
    write_plan_event(
        server.TaskReverted(kind="task_reverted", task=3, attempt=1, sha="b" * 40, reverts="a" * 40),
        plan,
    )
    write_plan_event(
        server.WriterDispatched(
            kind="writer_dispatched", task=3, attempt=2, reason="redo", files=["f.py"]
        ),
        plan,
    )
    write_plan_event(
        server.TaskComplete(
            kind="task_complete", task=3, attempt=2, status="complete", sha="c" * 40,
            files=["f.py"], no_sha_reason=None,
        ),
        plan,
    )

    state = get_plan_state(plan, validate_shas=False)
    ts = state.tasks[3]
    assert ts.status == "complete"
    assert ts.ready is True
    assert ts.last_attempt == 2

    lines = [l for l in _lines(plan) if l["kind"] == "task_complete"]
    assert len(lines) == 2
    assert {l["attempt"] for l in lines} == {1, 2}


# --- AC-017 -------------------------------------------------------------------


def test_ac_017(plan):
    _archive(plan)
    write_plan_event(
        server.TaskCreated(kind="task_created", task=3, deliverable="x", files=["f.py"]), plan
    )
    write_plan_event(
        server.WriterDispatched(
            kind="writer_dispatched", task=3, attempt=1, reason="initial", files=["f.py"]
        ),
        plan,
    )
    write_plan_event(
        server.TaskComplete(
            kind="task_complete", task=3, attempt=1, status="complete", sha="a" * 40,
            files=["f.py"], no_sha_reason=None,
        ),
        plan,
    )
    write_plan_event(
        server.TaskReverted(kind="task_reverted", task=3, attempt=1, sha="b" * 40, reverts="a" * 40),
        plan,
    )

    state = get_plan_state(plan, validate_shas=False)
    assert state.tasks[3].ready is False
    assert state.ready_for_final_review is False


# --- AC-017a --------------------------------------------------------------------


def test_ac_017a(plan):
    _archive(plan)
    write_plan_event(
        server.TaskCreated(kind="task_created", task=3, deliverable="x", files=["f.py"]), plan
    )
    write_plan_event(
        server.WriterDispatched(
            kind="writer_dispatched", task=3, attempt=1, reason="initial", files=["f.py"]
        ),
        plan,
    )
    write_plan_event(
        server.TaskComplete(
            kind="task_complete", task=3, attempt=1, status="complete", sha="a" * 40,
            files=["f.py"], no_sha_reason=None,
        ),
        plan,
    )
    write_plan_event(
        server.WriterDispatched(
            kind="writer_dispatched", task=3, attempt=2, reason="fix", files=["f.py"]
        ),
        plan,
    )

    state = get_plan_state(plan, validate_shas=False)
    ts = state.tasks[3]
    assert ts.status == "complete"
    assert ts.in_flight is True
    assert ts.ready is False


# --- AC-017b --------------------------------------------------------------------


def test_ac_017b(plan):
    _archive(plan)
    write_plan_event(
        server.TaskCreated(kind="task_created", task=3, deliverable="x", files=["f.py"]), plan
    )
    write_plan_event(
        server.WriterDispatched(
            kind="writer_dispatched", task=3, attempt=1, reason="initial", files=["f.py"]
        ),
        plan,
    )
    write_plan_event(
        server.TaskComplete(
            kind="task_complete", task=3, attempt=1, status="complete", sha="a" * 40,
            files=["f.py"], no_sha_reason=None,
        ),
        plan,
    )
    write_plan_event(
        server.WriterDispatched(
            kind="writer_dispatched", task=3, attempt=2, reason="fix", files=["f.py"]
        ),
        plan,
    )
    _returned(plan, 3, 2)

    state = get_plan_state(plan, validate_shas=False)
    ts = state.tasks[3]
    assert ts.in_flight is False
    assert ts.ready is False


# --- AC-027 -------------------------------------------------------------------


def test_ac_027(plan):
    _archive(plan)
    write_plan_event(
        server.TaskCreated(kind="task_created", task=4, deliverable="x", files=["f.py"]), plan
    )
    for i in range(1, 4):
        write_plan_event(
            server.WriterDispatched(
                kind="writer_dispatched", task=4, attempt=i,
                reason="initial" if i == 1 else "fix", files=["f.py"],
            ),
            plan,
        )
    for seq in range(1, 5):
        write_plan_event(server.Decision(kind="decision", text="t", who="user", seq=seq), plan)

    state = get_plan_state(plan, validate_shas=False)
    assert state.tasks[4].last_attempt == 3
    assert state.next_seq["decision"] == 5


# --- AC-027a --------------------------------------------------------------------


def test_ac_027a(plan):
    _archive(plan)
    path = _log_path(plan)
    with open(path, "a") as f:
        f.write(
            json.dumps(
                {"kind": "branch_check", "round": 1, "seq": 1, "status": "PASS",
                 "findings_total": 0, "ts": 1}
            ) + "\n"
        )
        f.write(
            json.dumps(
                {"kind": "branch_review", "round": 1, "seq": 1, "status": "PASS",
                 "findings_total": 0, "ts": 1}
            ) + "\n"
        )

    state = get_plan_state(plan, validate_shas=False)
    assert state.current_branch_round == 1
    assert set(state.current_branch_round_verifiers) == {"branch_check", "branch_review"}
    assert state.current_branch_round_verifiers == sorted(state.current_branch_round_verifiers)
    assert state.branch_round_complete is False

    with open(path, "a") as f:
        f.write(
            json.dumps(
                {"kind": "branch_test", "round": 1, "seq": 1, "status": "PASS",
                 "findings_total": 0, "ts": 1}
            ) + "\n"
        )

    state2 = get_plan_state(plan, validate_shas=False)
    assert state2.current_branch_round == 1
    assert state2.branch_round_complete is True
    assert state2.current_branch_round + 1 == 2


# --- AC-031 -------------------------------------------------------------------


def test_ac_031(plan):
    _archive(plan)
    write_plan_event(
        server.TaskCreated(kind="task_created", task=3, deliverable="x", files=["f.py"]), plan
    )

    write_plan_event(
        server.WriterDispatched(
            kind="writer_dispatched", task=3, attempt=1, reason="initial", files=["f.py"]
        ),
        plan,
    )
    _vr(plan, 3, 1, "checker", 1)
    write_plan_event(
        server.WriterDispatched(
            kind="writer_dispatched", task=3, attempt=2, reason="fix", files=["f.py"]
        ),
        plan,
    )
    _vr(plan, 3, 2, "checker", 2)
    write_plan_event(
        server.WriterDispatched(
            kind="writer_dispatched", task=3, attempt=3, reason="forced_fix", files=["f.py"]
        ),
        plan,
    )
    _vr(plan, 3, 3, "checker", 3)  # server-derives forced_fix=True from dispatch_reason
    write_plan_event(
        server.TaskComplete(
            kind="task_complete", task=3, attempt=3, status="complete", sha="a" * 40,
            files=["f.py"], no_sha_reason=None,
        ),
        plan,
    )

    state = get_plan_state(plan, validate_shas=False)
    ts = state.tasks[3]
    assert ts.round_count == 2
    assert ts.forced_fix_used is True

    write_plan_event(
        server.TaskReverted(kind="task_reverted", task=3, attempt=3, sha="b" * 40, reverts="a" * 40),
        plan,
    )
    write_plan_event(
        server.WriterDispatched(
            kind="writer_dispatched", task=3, attempt=4, reason="redo", files=["f.py"]
        ),
        plan,
    )
    _vr(plan, 3, 4, "checker", 4)
    _vr(plan, 3, 4, "reviewer", 5)

    state = get_plan_state(plan, validate_shas=False)
    ts = state.tasks[3]
    assert ts.round_count == 1
    assert ts.forced_fix_used is False

    write_plan_event(
        server.TaskComplete(
            kind="task_complete", task=3, attempt=4, status="complete", sha="c" * 40,
            files=["f.py"], no_sha_reason=None,
        ),
        plan,
    )
    write_plan_event(
        server.TaskReverted(kind="task_reverted", task=3, attempt=4, sha="d" * 40, reverts="c" * 40),
        plan,
    )
    write_plan_event(
        server.WriterDispatched(
            kind="writer_dispatched", task=3, attempt=5, reason="redo", files=["f.py"]
        ),
        plan,
    )
    _vr(plan, 3, 5, "checker", 6)

    state = get_plan_state(plan, validate_shas=False)
    ts = state.tasks[3]
    assert ts.round_count == 1
    assert ts.last_attempt == 5


# --- Task 3: write_findings / write_report plan-scoped parameters --------------


def _checker_findings(status="PASS", n_fail=0):
    checks = [server.Check(name="c", status="PASS", exit_code=0, output="")]
    checks += [
        server.Check(name=f"f{i}", status="FAIL", exit_code=1, output="")
        for i in range(n_fail)
    ]
    return server.CheckerFindings(source="checker", status=status, checks=checks)


def _reviewer_findings(status="PASS", n_issues=0):
    checks = [server.Check(name="c", status="PASS", exit_code=0, output="")]
    issues = [
        server.Issue(file="f.py", line=None, description="d") for _ in range(n_issues)
    ]
    return server.ReviewerFindings(source="reviewer", status=status, checks=checks, issues=issues)


def _tester_findings(status="PASS", n_fail=0):
    checks = [server.Check(name="c", status="PASS", exit_code=0, output="")]
    failures = [
        server.Failure(test="t", classification="REGRESSION", evidence="e", recommendation="r")
        for _ in range(n_fail)
    ]
    return server.TesterFindings(source="tester", status=status, checks=checks, failures=failures)


def _writer_report(modified=None, context_request=None):
    return server.WriterReport(
        source="writer", modified=modified or [], context_request=context_request
    )


def _reader_report():
    return server.ReaderReport(source="reader", relevant_files=[])


def _event_path(result):
    """Extracts the pipeline-file path out of a write_findings/write_report result,
    tolerating both the plan-absent and the ' | events: ...'-suffixed forms."""
    body = result[len("wrote "):]
    return body.split(" | events:")[0].strip()


# --- AC-003 ---------------------------------------------------------------------


def test_ac_003(plan):
    _archive(plan)
    result = write_findings(_checker_findings(), "lbl", plan=plan, task=3, attempt=2, seq=1)
    assert (server.PROJECT_DIR / _event_path(result)).exists()
    lines = [l for l in _lines(plan) if l["kind"] == "verify_round"]
    assert len(lines) == 1
    assert lines[0]["source"] == "checker"
    assert lines[0]["task"] == 3
    assert lines[0]["attempt"] == 2


# --- AC-004 ---------------------------------------------------------------------


def test_ac_004(plan):
    _archive(plan)
    write_findings(_checker_findings(), "lbl", plan=plan, branch_round=1, seq=1)
    lines = _lines(plan)
    assert any(l["kind"] == "branch_check" for l in lines)
    assert not any(l["kind"] == "verify_round" for l in lines)


# --- AC-005 ---------------------------------------------------------------------


def test_ac_005(plan):
    with pytest.raises(ValueError, match="reader/researcher/thinker"):
        write_report(_reader_report(), "lbl", plan=plan)
    assert not _log_path(plan).exists()
    assert not (server.PROJECT_DIR / server.DEFAULT_PIPELINE).exists()


# --- AC-012 ---------------------------------------------------------------------


def test_ac_012(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "PROJECT_DIR", tmp_path)
    result = write_findings(_checker_findings(), "lbl", pipeline=None)
    assert result == f"wrote {server.DEFAULT_PIPELINE}/checker-lbl-findings.json"
    assert not (tmp_path / ".claude" / "plans").exists()

    result2 = write_report(_writer_report(), "lbl2", pipeline=None)
    assert result2 == f"wrote {server.DEFAULT_PIPELINE}/writer-lbl2-report.json"
    assert not (tmp_path / ".claude" / "plans").exists()

    with pytest.raises(ValueError):
        write_findings(_checker_findings(), "lbl3", task=1)
    with pytest.raises(ValueError):
        write_report(_writer_report(), "lbl4", task=1)


# --- AC-015 ---------------------------------------------------------------------


def test_ac_015(plan):
    with pytest.raises(ValueError):
        write_findings(_checker_findings(), "lbl", task=1)
    with pytest.raises(ValueError):
        write_report(_writer_report(), "lbl", task=1)
    assert not _log_path(plan).exists()
    assert not (server.PROJECT_DIR / server.DEFAULT_PIPELINE).exists()


# --- AC-015a --------------------------------------------------------------------


def test_ac_015a(plan):
    with pytest.raises(ValueError, match="attempt"):
        write_findings(_checker_findings(), "lbl", plan=plan, attempt=1, branch_round=1, seq=1)
    with pytest.raises(ValueError):
        write_findings(_checker_findings(), "lbl", attempt=1)
    assert not _log_path(plan).exists()
    assert not (server.PROJECT_DIR / server.DEFAULT_PIPELINE).exists()


# --- AC-015b --------------------------------------------------------------------


def test_ac_015b(plan):
    with pytest.raises(ValueError):
        write_findings(
            _checker_findings(), "lbl", plan=plan, task=1, attempt=1, branch_round=1, seq=1
        )
    assert not _log_path(plan).exists()
    assert not (server.PROJECT_DIR / server.DEFAULT_PIPELINE).exists()


# --- AC-015c --------------------------------------------------------------------


def test_ac_015c(plan):
    with pytest.raises(ValueError):
        write_findings(_checker_findings(), "lbl", plan=plan, task=1, attempt=1)
    with pytest.raises(ValueError):
        write_findings(_checker_findings(), "lbl", plan=plan, branch_round=1)
    assert not _log_path(plan).exists()
    assert not (server.PROJECT_DIR / server.DEFAULT_PIPELINE).exists()


# --- AC-018 ---------------------------------------------------------------------


def test_ac_018(plan, monkeypatch):
    _archive(plan)
    report = _writer_report(modified=[server.ModifiedFile(path="f.py", change="c")])

    real_write = server._write_report_file
    state = {"n": 0}

    def fake_write(*a, **kw):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("boom")
        return real_write(*a, **kw)

    monkeypatch.setattr(server, "_write_report_file", fake_write)

    with pytest.raises(RuntimeError):
        write_report(report, "lbl", plan=plan, task=1, attempt=1)

    lines = [l for l in _lines(plan) if l["kind"] == "writer_returned"]
    assert len(lines) == 1

    result = write_report(report, "lbl", plan=plan, task=1, attempt=1)
    events = json.loads(result.split(" | events: ")[1])
    assert events == [{"kind": "writer_returned", "status": "duplicate", "ts": lines[0]["ts"]}]
    assert (server.PROJECT_DIR / _event_path(result)).exists()

    lines_after = [l for l in _lines(plan) if l["kind"] == "writer_returned"]
    assert len(lines_after) == 1


# --- AC-021 ---------------------------------------------------------------------


def test_ac_021(plan):
    _archive(plan)
    findings = _checker_findings()
    r1 = write_findings(findings, "lbl-a", pipeline=None)
    r2 = write_findings(findings, "lbl-b", plan=plan, task=1, attempt=1, seq=1)

    d1 = json.loads((server.PROJECT_DIR / _event_path(r1)).read_text())
    d2 = json.loads((server.PROJECT_DIR / _event_path(r2)).read_text())
    d1.pop("written_at")
    d2.pop("written_at")
    assert d1 == d2


# --- AC-028 ---------------------------------------------------------------------


def test_ac_028(plan):
    _archive(plan)
    seq = 1
    for source, findings in (
        ("checker", _checker_findings()),
        ("reviewer", _reviewer_findings()),
        ("tester", _tester_findings()),
    ):
        write_findings(findings, f"{source}-t", plan=plan, task=1, attempt=1, seq=seq)
        seq += 1
        write_findings(findings, f"{source}-b", plan=plan, branch_round=1, seq=seq)
        seq += 1

    for source, report in (
        ("reader", _reader_report()),
        ("researcher", server.ResearcherReport(source="researcher", recommended_approach="x")),
        ("thinker", server.ThinkerReport(source="thinker", mode="qa", recommendation="r")),
    ):
        with pytest.raises(ValueError):
            write_report(report, f"{source}-x", plan=plan)
        write_report(report, f"{source}-y")  # ad-hoc path, no plan — must succeed

    write_report(_writer_report(), "writer-a", plan=plan, task=2, attempt=1)
    write_report(
        _writer_report(context_request=server.ContextRequest(needs=["x"], why="y")),
        "writer-b",
        plan=plan,
        task=3,
        attempt=1,
    )

    lines = _lines(plan)
    assert not any(l["kind"] in ("decision", "ruling") for l in lines)


# --- write_report escalation pair (writer_returned then escalation) -------------


def test_write_report_escalation_pair(plan):
    _archive(plan)
    report = _writer_report(
        modified=[server.ModifiedFile(path="f.py", change="c")],
        context_request=server.ContextRequest(needs=["a", "b"], why="blocked"),
    )
    write_report(report, "lbl", plan=plan, task=5, attempt=2)

    lines = [l for l in _lines(plan) if l.get("task") == 5 and l.get("attempt") == 2]
    assert [l["kind"] for l in lines] == ["writer_returned", "escalation"]
    assert lines[1]["detail"] == "blocked (needs: a, b)"


# --- findings_total per source, task-scoped and branch-scoped ------------------


@pytest.mark.parametrize(
    "source, findings, expected_total",
    [
        ("checker", _checker_findings(status="FAIL", n_fail=2), 2),
        ("reviewer", _reviewer_findings(status="FAIL", n_issues=3), 3),
        ("tester", _tester_findings(status="FAIL", n_fail=1), 1),
    ],
)
def test_findings_total_per_source(plan, source, findings, expected_total):
    _archive(plan)

    write_findings(findings, "task-scoped", plan=plan, task=1, attempt=1, seq=1)
    task_line = next(l for l in _lines(plan) if l["kind"] == "verify_round")
    assert task_line["findings_total"] == expected_total

    write_findings(findings, "branch-scoped", plan=plan, branch_round=1, seq=2)
    branch_kind = {"checker": "branch_check", "reviewer": "branch_review", "tester": "branch_test"}[
        source
    ]
    branch_line = next(l for l in _lines(plan) if l["kind"] == branch_kind)
    assert branch_line["findings_total"] == expected_total


# --- branch routing: reviewer -> branch_review, tester -> branch_test ----------


def test_branch_routing_reviewer_and_tester(plan):
    _archive(plan)
    write_findings(_reviewer_findings(), "lbl-r", plan=plan, branch_round=1, seq=1)
    write_findings(_tester_findings(), "lbl-t", plan=plan, branch_round=1, seq=2)

    lines = _lines(plan)
    assert any(l["kind"] == "branch_review" for l in lines)
    assert any(l["kind"] == "branch_test" for l in lines)
    assert not any(l["kind"] in ("branch_check", "verify_round") for l in lines)


# --- write_report in_scope/out_of_scope split -----------------------------------


def test_write_report_in_scope_split(plan):
    _archive(plan)
    report = _writer_report(
        modified=[
            server.ModifiedFile(path="a.py", change="c1", in_scope=True),
            server.ModifiedFile(path="b.py", change="c2", in_scope=False, note="unplanned"),
        ]
    )
    write_report(report, "lbl", plan=plan, task=1, attempt=1)

    line = next(l for l in _lines(plan) if l["kind"] == "writer_returned")
    assert line["in_scope"] == ["a.py"]
    assert line["out_of_scope"] == ["b.py"]


# --- writer_returned + escalation round-trip via get_plan_state/read_plan_events -


def test_writer_returned_escalation_round_trip(plan):
    _archive(plan)
    write_plan_event(
        server.TaskCreated(kind="task_created", task=9, deliverable="x", files=["f.py"]), plan
    )
    write_plan_event(
        server.WriterDispatched(
            kind="writer_dispatched", task=9, attempt=1, reason="initial", files=["f.py"]
        ),
        plan,
    )
    report = _writer_report(
        modified=[server.ModifiedFile(path="f.py", change="c")],
        context_request=server.ContextRequest(needs=["x"], why="blocked"),
    )
    write_report(report, "lbl", plan=plan, task=9, attempt=1)

    state = get_plan_state(plan, validate_shas=False)
    assert state.tasks[9].in_flight is False

    events = read_plan_events(plan, task=9)
    kinds = [e["kind"] for e in events if e["kind"] in ("writer_returned", "escalation")]
    assert kinds == ["writer_returned", "escalation"]
    assert all(e["task"] == 9 and e["attempt"] == 1 for e in events if e["kind"] in kinds)
    escalation = next(e for e in events if e["kind"] == "escalation")
    assert escalation["topic"] == "writer_blocked"


# --- write_findings forced_fix derivation ---------------------------------------


def test_write_findings_forced_fix_derived(plan):
    _archive(plan)
    write_plan_event(
        server.WriterDispatched(
            kind="writer_dispatched", task=7, attempt=1, reason="forced_fix", files=["f.py"]
        ),
        plan,
    )
    write_findings(_checker_findings(), "lbl", plan=plan, task=7, attempt=1, seq=1)
    lines = [l for l in _lines(plan) if l["kind"] == "verify_round"]
    assert len(lines) == 1
    assert lines[0]["forced_fix"] is True


# --- Plan decision M4: round_count excludes branch_fix attempts -----------------


def test_round_count_excludes_branch_fix_attempts(plan):
    _archive(plan)
    write_plan_event(
        server.TaskCreated(kind="task_created", task=1, deliverable="x", files=["f.py"]), plan
    )
    write_plan_event(
        server.WriterDispatched(
            kind="writer_dispatched", task=1, attempt=1, reason="initial", files=["f.py"]
        ),
        plan,
    )
    _vr(plan, 1, 1, "checker", 1)
    write_plan_event(
        server.TaskComplete(
            kind="task_complete", task=1, attempt=1, status="complete", sha="a" * 40,
            files=["f.py"], no_sha_reason=None,
        ),
        plan,
    )

    # A Final Full-Branch Review fix wave touches this task's files at attempt 2.
    write_plan_event(
        server.WriterDispatched(
            kind="writer_dispatched", task=1, attempt=2, reason="branch_fix", files=["f.py"]
        ),
        plan,
    )
    _vr(plan, 1, 2, "checker", 2)
    write_plan_event(
        server.TaskComplete(
            kind="task_complete", task=1, attempt=2, status="complete", sha="b" * 40,
            files=["f.py"], no_sha_reason=None,
        ),
        plan,
    )

    state = get_plan_state(plan, validate_shas=False)
    assert state.tasks[1].round_count == 1  # attempt 2's round is excluded (branch_fix)


# --- read_plan_events filters ---------------------------------------------------


def test_read_plan_events_filters(plan):
    assert read_plan_events(plan) == []  # missing file -> []

    _archive(plan)
    write_plan_event(
        server.TaskCreated(kind="task_created", task=1, deliverable="a", files=None), plan
    )
    write_plan_event(
        server.TaskCreated(kind="task_created", task=2, deliverable="b", files=None), plan
    )
    write_plan_event(server.Decision(kind="decision", text="t", who="user", seq=1), plan)

    all_events = read_plan_events(plan)
    assert len(all_events) == 4

    by_kind = read_plan_events(plan, kind="task_created")
    assert {e["task"] for e in by_kind} == {1, 2}

    by_task = read_plan_events(plan, task=2)
    assert len(by_task) == 1 and by_task[0]["kind"] == "task_created"

    since = all_events[-1]["ts"]
    by_since = read_plan_events(plan, since_ts=since)
    assert all(e["ts"] >= since for e in by_since)

    limited = read_plan_events(plan, limit=2)
    assert limited == all_events[:2]

    assert read_plan_events("2026-09-24-does-not-exist-xyz") == []


# --- next_seq defaults ----------------------------------------------------------


def test_next_seq_defaults_to_one(plan):
    _archive(plan)
    state = get_plan_state(plan)
    assert state.next_seq == {k: 1 for k in server._SEQ_KEYED_KINDS}


# --- REQ-019: readers tolerate valid-JSON-but-wrong-shape lines -----------------


def test_readers_tolerate_invalid_shapes(plan):
    _archive(plan)
    write_plan_event(
        server.TaskCreated(kind="task_created", task=1, deliverable="d", files=["f.py"]), plan
    )
    write_plan_event(
        server.TaskComplete(
            kind="task_complete", task=1, attempt=1, status="complete", sha="a" * 40,
            files=["f.py"], no_sha_reason=None,
        ),
        plan,
    )
    path = _log_path(plan)
    bad_lines = [
        {"kind": "task_complete", "ts": 1, "task": 1},
        {
            "kind": "writer_dispatched", "ts": 1, "task": 1, "attempt": "x",
            "reason": "fix", "files": [],
        },
        {
            "kind": "verify_round", "ts": "late", "task": 1, "attempt": 1,
            "source": "checker", "seq": 1, "status": "PASS", "findings_total": 0,
            "forced_fix": False,
        },
        {
            "kind": "epoch_start", "ts": 1, "epoch": None, "wip": None,
            "excluded_tasks": [], "after_compaction": False,
        },
        [1],
        7,
        # from reviewer-task2-round2-readers-state-findings.json: valid JSON,
        # wrong-shaped values — must be skipped, never raised on.
        {
            "kind": "task_complete", "ts": 2, "task": 1, "attempt": 2,
            "status": "bogus", "sha": None, "files": None, "no_sha_reason": None,
        },
        {"kind": "task_created", "ts": 3, "task": 2, "deliverable": "d", "files": "a"},
        {
            "kind": "task_complete", "ts": 4, "task": 1, "attempt": 2,
            "status": "complete", "sha": 5, "files": None, "no_sha_reason": None,
        },
        {"kind": "auto_commit", "ts": 5, "status": "maybe", "seq": 1},
        {
            "kind": "epoch_start", "ts": 6, "epoch": 1, "wip": 5,
            "excluded_tasks": [], "after_compaction": False,
        },
        {"kind": ["x"], "ts": 7},
    ]
    with open(path, "a") as f:
        f.writelines(json.dumps(line) + "\n" for line in bad_lines)

    for validate_shas in (True, False):
        state = get_plan_state(plan, validate_shas=validate_shas)  # must not raise
        assert set(state.tasks) == {1}
        assert state.tasks[1].status == "complete"
        assert state.tasks[1].sha == "a" * 40
        assert state.auto_commit is None
        assert state.epoch == 0
        assert state.current_wip is None

    events = read_plan_events(plan, kind="task_complete")  # must not raise
    assert all(e["kind"] == "task_complete" for e in events)
    assert any(e.get("attempt") == 1 and e.get("status") == "complete" for e in events)


# --- AC-022 / AC-033 through the public readers ---------------------------------


def test_ac_022_get_plan_state(plan):
    _archive(plan)
    write_plan_event(server.Decision(kind="decision", text="one", who="user", seq=1), plan)
    path = _log_path(plan)
    with open(path, "a") as f:
        f.write('{"kind": "decision", "text": "trunc')  # torn trailing line, no newline

    state = get_plan_state(plan)  # must not raise despite the torn trailing line
    assert state.next_seq["decision"] == 2

    events = read_plan_events(plan)  # must not raise
    assert [e["kind"] for e in events] == ["plan_archived", "decision"]


def test_ac_033_readers(plan):
    _archive(plan)
    write_plan_event(server.Decision(kind="decision", text="one", who="user", seq=1), plan)
    path = _log_path(plan)
    with open(path, "a") as f:
        f.write("{not valid json at all\n")
    write_plan_event(server.Decision(kind="decision", text="two", who="user", seq=2), plan)

    state = get_plan_state(plan)  # must not raise despite the mid-file garbage line
    assert state.next_seq["decision"] == 3

    events = read_plan_events(plan)  # must not raise
    decisions = [e for e in events if e["kind"] == "decision"]
    assert {d["seq"] for d in decisions} == {1, 2}


def test_deeply_nested_line_is_skipped(plan):
    deeply_nested = ("[" * 100000 + "]" * 100000).encode()

    _archive(plan)
    write_plan_event(server.Decision(kind="decision", text="one", who="user", seq=1), plan)
    path = _log_path(plan)
    with open(path, "ab") as f:
        f.write(deeply_nested + b"\n")
    write_plan_event(server.Decision(kind="decision", text="two", who="user", seq=2), plan)

    state = get_plan_state(plan)  # must not raise despite the deeply nested mid-file line
    assert state.next_seq["decision"] == 3

    events = read_plan_events(plan)  # must not raise
    decisions = [e for e in events if e["kind"] == "decision"]
    assert {d["seq"] for d in decisions} == {1, 2}


def test_deeply_nested_first_line_raises(plan):
    deeply_nested = ("[" * 100000 + "]" * 100000).encode()
    path = _log_path(plan)
    path.write_bytes(deeply_nested + b"\n")

    with pytest.raises(ValueError):
        get_plan_state(plan)


# --- Drift guard: every line shape write_plan_event/write_findings/write_report can
# produce is accepted by _validate_line, and _KIND_TO_MODEL stays in sync with the
# PlanEvent union plus the internal derived models ------------------------------


def _one_of_each_plan_event(plan_stem):
    """One instance of each of the 16 PlanEvent kinds."""
    return [
        server.PlanArchived(kind="plan_archived", plan=plan_stem, archive="a", title="t"),
        server.TaskCreated(kind="task_created", task=1, deliverable="d", files=["f.py"]),
        server.TaskAmended(kind="task_amended", task=1, seq=1, why="w"),
        server.TaskDropped(kind="task_dropped", task=2, why="w"),
        server.Decision(kind="decision", text="t", who="user", seq=2),
        server.AutoCommit(kind="auto_commit", status="confirmed", seq=3),
        server.BaseRecorded(kind="base_recorded", sha="a" * 40, seq=4, reason="initial"),
        server.EpochStart(
            kind="epoch_start", epoch=1, wip=None, excluded_tasks=[], after_compaction=False
        ),
        server.PlanEscalation(kind="escalation", topic="base_rebased", seq=5, detail="d"),
        server.PlanComplete(kind="plan_complete", status="clean"),
        server.PlanAbandoned(kind="plan_abandoned", why="w"),
        server.WriterDispatched(
            kind="writer_dispatched", task=1, attempt=1, reason="initial", files=["f.py"]
        ),
        server.Ruling(kind="ruling", task=1, seq=6, text="t"),
        server.TaskComplete(
            kind="task_complete", task=1, attempt=1, status="complete", sha="b" * 40,
            files=["f.py"], no_sha_reason=None,
        ),
        server.CommitFailed(kind="commit_failed", task=1, attempt=1, seq=7, reason="r", files=["f.py"]),
        server.TaskReverted(kind="task_reverted", task=1, attempt=1, sha="c" * 40, reverts="b" * 40),
    ]


def test_every_line_shape_accepted_by_validate_line(plan):
    for ev in _one_of_each_plan_event(plan):
        write_plan_event(ev, plan)

    write_findings(_checker_findings(), "vr", plan=plan, task=1, attempt=1, seq=1)
    write_findings(_checker_findings(), "bc", plan=plan, branch_round=1, seq=2)
    write_findings(_reviewer_findings(), "br", plan=plan, branch_round=1, seq=3)
    write_findings(_tester_findings(), "bt", plan=plan, branch_round=1, seq=4)

    write_report(_writer_report(), "wr", plan=plan, task=1, attempt=2)
    write_report(
        _writer_report(context_request=server.ContextRequest(needs=["x"], why="y")),
        "wr-esc",
        plan=plan,
        task=1,
        attempt=3,
    )

    lines = _lines(plan)
    seen_kinds = set()
    for line in lines:
        assert server._validate_line(line) is not None, line
        seen_kinds.add(line["kind"])

    expected_kinds = {
        "plan_archived", "task_created", "task_amended", "task_dropped", "decision",
        "auto_commit", "base_recorded", "epoch_start", "escalation", "plan_complete",
        "plan_abandoned", "writer_dispatched", "ruling", "task_complete", "commit_failed",
        "task_reverted", "verify_round", "branch_check", "branch_review", "branch_test",
        "writer_returned",
    }
    assert seen_kinds == expected_kinds
    assert any(
        l["kind"] == "escalation" and l.get("task") == 1 and l.get("attempt") == 3
        for l in lines
    )


def _kind_literal(model):
    return typing.get_args(model.model_fields["kind"].annotation)[0]


def test_kind_to_model_matches_plan_event_and_internal_models():
    plan_event_members = typing.get_args(typing.get_args(server.PlanEvent)[0])
    plan_event_kinds = {_kind_literal(m) for m in plan_event_members}

    internal_models = [
        server.VerifyRound, server.BranchCheck, server.BranchReview, server.BranchTest,
        server.WriterReturned,
    ]
    internal_kinds = {_kind_literal(m) for m in internal_models}

    assert set(server._KIND_TO_MODEL) | {"escalation"} == plan_event_kinds | internal_kinds
