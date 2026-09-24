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
from pathlib import Path
from typing import Any

import pytest

_SERVER_PATH = Path(__file__).parent / "server.py"
_spec = importlib.util.spec_from_file_location("server", str(_SERVER_PATH))
assert _spec is not None and _spec.loader is not None
server: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)

write_plan_event = getattr(server.write_plan_event, "fn", server.write_plan_event)

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
