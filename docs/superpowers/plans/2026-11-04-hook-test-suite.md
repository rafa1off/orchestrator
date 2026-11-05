# Hook Test Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pytest suite that pins the behavior of every `orchestrator-hooks` script, plus a small manifest checker built test-first.

**Architecture:** Tests run each hook as a real subprocess (`bash <script>`, JSON payload on stdin) inside a temporary project directory and a temporary `HOME`, then assert on the exit code, stdout JSON and files written. Shared fixtures live in one `conftest.py`. The manifest checker is a standalone Python module next to the hooks, not inside `hooks/`.

**Tech Stack:** Python ≥ 3.14, pytest (repo `dev` group), bash, jq, uv.

**Spec:** `docs/superpowers/specs/2026-11-04-superpowers-bridge-design.md` (§ Evaluation — this plan is the benchmark task it describes).

## Global Constraints

- **Never modify anything under `plugins/orchestrator-hooks/hooks/`.** Only test files, the new `tools/` module and `pyproject.toml` change.
- **Bugs the tests find are recorded, not fixed.** Each test below states the hook's intended behavior (taken from the hook's own header comments and its siblings). When a hook disagrees with that behavior, the hook has a bug: mark that test `@pytest.mark.xfail(strict=True, reason="<one-line description of the bug>")` and continue. A test that fails because the *test* is wrong (bad fixture, wrong path) is fixed instead.
- Hooks never see the real environment: every run sets `HOME` to a temp dir and `CLAUDE_PROJECT_DIR` to a temp project dir (unless a test removes it on purpose).
- No new dependencies. jq must be on `PATH`; if `shutil.which("jq")` is `None`, the hook test modules skip at module level.
- Commands, from the repo root: `uv run pytest`, `uv run ruff check`, `uv run ty check` — all three green at the end of every task (xfail counts as green).

## Review Focus

1. **Real-environment leakage** — a fixture that forgets to override `HOME` makes `lib-resolve-agent-identity.sh` read the developer's real `~/.claude/teams`; every test must be hermetic.
2. **Timing flakiness** — stamp/elapsed/freshness assertions must use ranges, never exact seconds.
3. **xfail discipline** — every xfail is `strict=True` with a reason naming the bug; no `skip`, no loosened assertion to make a hook pass.
4. **Exit code vs JSON channel** — PreToolUse/PostToolUse guards block with exit 2 + stderr; the SubagentStop guard blocks with exit 0 + `{"decision": "block"}` on stdout. Tests must assert the channel each hook actually uses.
5. **Collection coexistence** — the new test directory must not collide with `plugins/orchestrator-mcp/mcp-server-py` (no duplicate test module basenames, no shared `conftest` names that shadow).

---

### Task 1: Test infrastructure + start/stop stamp hooks

**Files:**
- Modify: `pyproject.toml` (`[tool.pytest.ini_options].testpaths`)
- Create: `plugins/orchestrator-hooks/tests/conftest.py`
- Create: `plugins/orchestrator-hooks/tests/test_stamps.py`

**Interfaces:**
- Produces (fixtures in `conftest.py`, used by every later hook test):
  - `HOOKS_DIR: Path` — `plugins/orchestrator-hooks/hooks`, resolved from `conftest.py`'s location.
  - `HookResult` — dataclass `returncode: int`, `stdout: str`, `stderr: str`, method `json() -> dict` (`json.loads(stdout)`).
  - fixture `home_dir(tmp_path) -> Path` — `tmp_path / "home"`, created.
  - fixture `project_dir(tmp_path) -> Path` — `tmp_path / "proj"` with `.claude/pipeline/` created.
  - fixture `run_hook(project_dir, home_dir) -> Callable[..., HookResult]` — `run_hook(script: str, payload: dict, *, env: dict[str, str | None] | None = None) -> HookResult`. Runs `[shutil.which("bash"), HOOKS_DIR / script]` with `input=json.dumps(payload)`, `cwd=project_dir`, `timeout=10`, env = `{"PATH": os.environ["PATH"], "HOME": str(home_dir), "CLAUDE_PROJECT_DIR": str(project_dir)}` updated with `env`; a value of `None` removes that key.
  - fixture `write_team(home_dir) -> Callable[[str, list[dict]], Path]` — writes `home_dir/.claude/teams/<team_dir>/config.json` as `{"members": members}`, returns the path.
  - fixture `write_pipeline_json(project_dir) -> Callable[..., Path]` — `write_pipeline_json(name: str, body: dict | str, *, subdir: str | None = None) -> Path` writes `.claude/pipeline[/subdir]/<name>` (dict → JSON, str → raw text).
- Module-level skip in `conftest.py` when jq is missing.

- [ ] **Step 1: Add the test path.** `testpaths = ["plugins/orchestrator-mcp/mcp-server-py", "plugins/orchestrator-hooks/tests"]`.

- [ ] **Step 2: Write `conftest.py`** with the fixtures above.

- [ ] **Step 3: Write `test_stamps.py`** (`subagent-start-stamp.sh`, `subagent-stop-clear-stamp.sh`):

```python
def test_start_stamp_writes_epoch(run_hook, project_dir):
    r = run_hook("subagent-start-stamp.sh", {"agent_id": "a1", "agent_type": "orchestrator-agents:writer"})
    assert r.returncode == 0
    stamp = int((project_dir / ".claude/pipeline/.starts/a1").read_text())
    assert abs(stamp - time.time()) <= 5

def test_start_stamp_skips_without_agent_id(run_hook, project_dir):
    # payload {"agent_type": "orchestrator-agents:writer"} → rc 0, .starts/ absent or empty

def test_start_stamp_rejects_path_traversal(run_hook, project_dir):
    # agent_id "../escape" → rc 0 and (project_dir / ".claude/pipeline/escape").exists() is False
    # (clear-stamp guards traversal; start-stamp must not write outside .starts/ either)

def test_clear_stamp_removes_stamp_and_logs_timing(run_hook, project_dir):
    # .starts/a1 = str(int(time.time()) - 7); payload agent_id a1, agent_type orchestrator-agents:writer
    # → stamp gone; last line of .claude/metrics/agent-timings.tsv splits on "\t" into
    #   [<iso ts>, "orchestrator-agents:writer", e] with 7 <= int(e) <= 9

def test_clear_stamp_ignores_traversal_id(run_hook, project_dir):
    # create .claude/pipeline/victim; agent_id "../victim" → victim still exists

def test_clear_stamp_removes_non_numeric_stamp_without_logging(run_hook, project_dir):
    # .starts/a1 = "garbage" → stamp gone, agent-timings.tsv does not exist
```

- [ ] **Step 4: Run** `uv run pytest plugins/orchestrator-hooks/tests/test_stamps.py -v`. Expected: every test passes or is a strict xfail per Global Constraints.

- [ ] **Step 5: Run the full gate** (`uv run pytest`, `uv run ruff check`, `uv run ty check`). Expected: all green; the MCP suite's count is unchanged.

- [ ] **Step 6: Commit** `git add pyproject.toml plugins/orchestrator-hooks/tests && git commit -m "test(hooks): fixtures + start/stop stamp tests"`

### Task 2: PreToolUse guards

**Files:**
- Create: `plugins/orchestrator-hooks/tests/test_pretool_guards.py`

**Interfaces:**
- Consumes: `run_hook`, `project_dir`, `write_team` (Task 1).

Payloads carry `agent_type`, `session_id: "s1abcdef-0000"` and `tool_input`. "Blocked" means `returncode == 2` and `"BLOCKED"` in stderr; "allowed" means `returncode == 0`.

- [ ] **Step 1: Write the tests.**

`block-subagent-git-push.sh` (`tool_input.command`):
- `test_push_blocked_for_writer` — parametrized, agent `orchestrator-agents:writer`, each blocked: `"git push"`, `"git -C /repo push origin main"`, `"git --no-pager -C /r push"`, `"env git push"`, `"echo ok && git push"`, `"x=$(git push)"`, `"ls\ngit push"`, `"gh pr create --fill"`, `"gh pr merge 3"`.
- `test_safe_git_allowed_for_writer` — parametrized, allowed: `"git status"`, `"git commit -m 'push it'"`, `"git log --grep push"`, `"git remote -v"`.
- `test_push_inside_bash_c_is_blocked` — writer, `'bash -c "git push origin main"'` → blocked.
- `test_push_allowed_for_main_session_and_reader` — no `agent_type` → allowed; `orchestrator-agents:reader` → allowed.
- `test_push_blocked_for_teammate_writer` — `write_team("session-s1abcdef", [{"name": "probe-writer", "agentType": "orchestrator-agents:writer"}])`, `agent_type: "probe-writer"` → blocked.

`block-nested-restricted-agents.sh` (`tool_input.subagent_type`, caller `orchestrator-agents:writer`):
- `test_nested_readonly_targets_allowed` — parametrized reader / researcher / thinker / reviewer → allowed.
- `test_nested_target_blocked_with_reason` — parametrized `(target, reason)`: writer → `"file-mutation risk"`, tester → `"file-mutation risk"`, checker → `"runs lint/typecheck/build subprocesses"`, `general-purpose` → `"not an approved nested target"`; blocked and `reason in stderr`.
- `test_main_session_may_spawn_anything` — no `agent_type`, target writer → allowed.

`block-readonly-agent-writes.sh` (`tool_input.file_path` / `notebook_path`):
- `test_thinker_memory_write_allowed` — parametrized: `f"{project_dir}/.claude/agent-memory/thinker/MEMORY.md"` and `".claude/agent-memory/thinker/MEMORY.md"` → allowed.
- `test_thinker_source_write_blocked` — `f"{project_dir}/src/app.py"` → blocked, `"outside its memory directory"` in stderr.
- `test_traversal_blocked` — `".claude/agent-memory/../../etc/x"` → blocked, `"containing '..'"` in stderr.
- `test_researcher_notebook_blocked` — `notebook_path: f"{project_dir}/nb.ipynb"` → blocked.
- `test_writer_not_governed` — writer, `src/app.py` → allowed.
- `test_dot_slash_memory_path_allowed` — thinker, `"./.claude/agent-memory/thinker/MEMORY.md"` → allowed.

- [ ] **Step 2: Run** `uv run pytest plugins/orchestrator-hooks/tests/test_pretool_guards.py -v`. Expected: pass or strict xfail.

- [ ] **Step 3: Full gate**, as Task 1 Step 5.

- [ ] **Step 4: Commit** `git add plugins/orchestrator-hooks/tests/test_pretool_guards.py && git commit -m "test(hooks): PreToolUse guard tests"`.

### Task 3: PostToolUse findings guard

**Files:**
- Create: `plugins/orchestrator-hooks/tests/test_post_tool_findings.py`

**Interfaces:**
- Consumes: `run_hook`, `project_dir`, `write_pipeline_json` (Task 1).

Payload: `{"tool_name": "mcp__plugin_orchestrator-mcp_dev-tools__write_findings", "tool_input": {"findings": {"source": SRC}}}` (reports: key `report` instead of `findings`). The file the hook reads is `<source>-t-findings.json` written with `write_pipeline_json`. A PASS check is `{"name": "pytest", "status": "PASS", "exit_code": 0, "output": ""}`.

- [ ] **Step 1: Write the tests.**
- `test_valid_findings_injected` — tester, `{"source": "tester", "status": "PASS", "checks": [PASS check]}` → rc 0; `r.json()["hookSpecificOutput"]["additionalContext"]` starts with `"[orchestrator] tester findings ready (status: PASS)"`.
- `test_no_checks_blocked` — checker, `{"source": "checker", "status": "PASS"}` → rc 2, `"no checks[] recorded"` in stderr.
- `test_pass_without_exit_code_blocked` — reviewer, a PASS check with `"exit_code": None` → rc 2, `"no real exit_code"` in stderr.
- `test_pass_over_errored_check_blocked` — tester, status PASS, checks `[PASS check, {"name": "lint", "status": "ERROR", "exit_code": None, "output": ""}]` → rc 2, `"a checks[] entry is ERROR"` in stderr.
- `test_fail_with_errored_check_flagged` — same checks, status FAIL → rc 0, additionalContext contains `"ERRORED CHECKS: lint"`.
- `test_report_injected_without_proof_check` — `tool_input.report.source = "writer"`, file `writer-t-report.json` = `{"source": "writer", "modified": []}` → rc 0, additionalContext starts with `"[orchestrator] writer report ready:"`.
- `test_track_override_is_guarded` — findings without checks written with `subdir="track-a"`, payload `tool_input.pipeline = ".claude/pipeline/track-a"` → rc 2.
- `test_missing_file_is_silent` — no file → rc 0, stdout empty.
- `test_falls_back_to_pwd_without_project_dir` — no-checks checker findings in the default pipeline, `env={"CLAUDE_PROJECT_DIR": None}` (cwd is still `project_dir`) → rc 2, as every sibling hook falls back to `$PWD`.

- [ ] **Step 2: Run** `uv run pytest plugins/orchestrator-hooks/tests/test_post_tool_findings.py -v`. Expected: pass or strict xfail.
- [ ] **Step 3: Full gate.**
- [ ] **Step 4: Commit** `git add plugins/orchestrator-hooks/tests/test_post_tool_findings.py && git commit -m "test(hooks): PostToolUse findings guard tests"`

### Task 4: SubagentStop findings guard

**Files:**
- Create: `plugins/orchestrator-hooks/tests/test_subagent_stop_guard.py`

**Interfaces:**
- Consumes: `run_hook`, `project_dir`, `write_pipeline_json` (Task 1).

Payload: `{"agent_type": "orchestrator-agents:tester", "agent_id": "t1", "last_assistant_message": "done"}` unless stated. Stamp: `.claude/pipeline/.starts/t1` = `now - 60`. "Blocked" means rc 0 and `r.json()["decision"] == "block"`. Findings carry `"written_at": <epoch int>`.

- [ ] **Step 1: Write the tests.**
- `test_fresh_valid_findings_accepted` — PASS findings, `written_at = now` → rc 0, additionalContext contains `"[tester] stopped — status=PASS"`.
- `test_missing_findings_blocked` — no file → blocked; reason contains `"No tester-findings.json written during this run"` and `'Your final message was: "done"'`.
- `test_stale_findings_blocked` — `written_at = now - 3600` → blocked, reason contains `"predates this run"`.
- `test_fresh_findings_without_checks_blocked` — reason contains `"no checks[] at all"`.
- `test_fresh_pass_without_exit_code_blocked` — reason contains `"claims PASS with no real exit_code"`.
- `test_pass_over_errored_check_blocked` — status PASS with a PASS check and an ERROR check → blocked (the PostToolUse guard rejects the same file; the stop guard must not accept what it rejects).
- `test_track_subdir_findings_accepted` — fresh valid findings with `subdir="track-b"` → rc 0, not blocked.
- `test_writer_report_accepted` — agent `orchestrator-agents:writer`, agent_id `w1`, stamp `w1`, fresh `writer-t-report.json` with `written_at` → additionalContext contains `"[writer] stopped — report at"`.
- `test_unparseable_report_blocked` — writer, report file raw text `"not json"` (fresh by mtime) → blocked, reason contains `"not readable as JSON"`.
- `test_without_stamp_uses_15_minute_window` — no stamp; `written_at = now - 600` → accepted; separate case `now - 1200` → blocked.
- `test_other_agents_ignored` — `agent_type: "general-purpose"` → rc 0, stdout empty.
- `test_missing_jq_fails_loudly` — `env={"PATH": str(bin_dir)}` where `bin_dir` holds only a symlink to `shutil.which("cat")` → rc 2, `"jq is not installed"` in stderr.

- [ ] **Step 2: Run** `uv run pytest plugins/orchestrator-hooks/tests/test_subagent_stop_guard.py -v`. Expected: pass or strict xfail.
- [ ] **Step 3: Full gate.**
- [ ] **Step 4: Commit** `git add plugins/orchestrator-hooks/tests/test_subagent_stop_guard.py && git commit -m "test(hooks): SubagentStop findings guard tests"`

### Task 5: Observer hooks (writer overlap, identity audit)

**Files:**
- Create: `plugins/orchestrator-hooks/tests/test_observers.py`

**Interfaces:**
- Consumes: `run_hook`, `project_dir`, `write_team` (Task 1).

- [ ] **Step 1: Write the tests.**

`track-writer-overlap.sh` — payload `{"agent_type": "orchestrator-agents:writer", "agent_id": ID, "tool_input": {"file_path": f"{project_dir}/src/a.py"}}`:
- `test_first_write_logged_silently` — `w1` → rc 0, stdout empty; `write-log.tsv` has one line whose first two tab fields are `w1`, `src/a.py`.
- `test_concurrent_writer_reported` — `w1` writes, `.starts/w1` exists, then `w2` writes → `w2`'s additionalContext contains `"WRITER OVERLAP: src/a.py"` and `"w1"`.
- `test_finished_writer_not_reported` — `w1` writes, no `.starts/w1`, then `w2` → stdout empty.
- `test_same_writer_not_reported` — `w1` twice with its stamp present → stdout empty.
- `test_non_writer_not_logged` — agent `orchestrator-agents:reviewer` → `write-log.tsv` does not exist.

`agent-identity-audit.sh` — each run appends one JSON line to `.claude/pipeline/identity-audit.jsonl`; read the last line:
- `test_main_session_row` — `{"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "s1abcdef-0000"}` → `enforcement == "main"`, `actor is None`, `payload_keys == ["hook_event_name", "session_id", "tool_name"]`.
- `test_subagent_row` — `agent_type: "orchestrator-agents:thinker"` → `enforcement == "subagent"`, `team_match == "not-attempted"`.
- `test_teammate_rows` — parametrized `(team members, expected team_match)`: `[{"name": "probe-thinker", "agentType": "orchestrator-agents:thinker"}]` → `"orchestrator-agents:thinker"`; `[]` → `"name-not-in-team"`; no team config written → `"no-team-config"`; `agent_type: "probe-thinker"`, team dir `session-s1abcdef`.
- `test_teammate_idle_actor` — `{"hook_event_name": "TeammateIdle", "teammate_name": "probe-thinker"}` → `actor == "probe-thinker"`, `agent_type is None`.
- `test_log_is_bounded` — pre-fill the log with 2001 lines of `{}` → after one run it has exactly 1000 lines.

- [ ] **Step 2: Run** `uv run pytest plugins/orchestrator-hooks/tests/test_observers.py -v`. Expected: pass or strict xfail.
- [ ] **Step 3: Full gate.**
- [ ] **Step 4: Commit** `git add plugins/orchestrator-hooks/tests/test_observers.py && git commit -m "test(hooks): writer-overlap and identity-audit tests"`

### Task 6: Manifest checker (TDD)

New functionality, built test-first: a checker that catches `hooks.json` wiring mistakes — a command pointing at a script that does not exist, a script that is not executable, or a script nothing references.

**Files:**
- Create: `plugins/orchestrator-hooks/tools/verify_manifest.py`
- Create: `plugins/orchestrator-hooks/tests/test_verify_manifest.py`
- Modify: `pyproject.toml` (`[tool.pytest.ini_options].pythonpath`, `[tool.ty.environment].root`)

**Interfaces:**
- Produces:
  - `manifest_problems(manifest: dict, hooks_dir: Path) -> list[str]` — sorted list of problems.
  - `main(argv: list[str] | None = None) -> int` — `argv[0]` (optional) is the plugin root, default `Path(__file__).resolve().parent.parent`; loads `<root>/hooks/hooks.json`, prints each problem on its own stdout line, returns 1 if any, else 0. Module ends with `if __name__ == "__main__": sys.exit(main())`.
- Rules: script references are every match of `r"/hooks/([A-Za-z0-9_.-]+\.sh)"` in any `command` string under `manifest["hooks"][<event>][i]["hooks"][j]`; inline commands with no match are ignored. Problems: `f"missing script: {name}"`, `f"not executable: {name}"` (exists but not `os.access(path, os.X_OK)`), `f"unreferenced script: {name}"` (a `*.sh` in `hooks_dir` whose name does not start with `lib-` and is never referenced).

- [ ] **Step 1: Wire the import path.** `pythonpath = ["plugins/orchestrator-hooks/tools"]` in pytest options; append `"plugins/orchestrator-hooks/tools"` to ty's `root`.

- [ ] **Step 2: Write the failing tests** in `test_verify_manifest.py` (fixture: a `tmp_path / "hooks"` dir; helper `manifest(*scripts)` returns `{"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": f'bash "${{CLAUDE_PLUGIN_ROOT}}/hooks/{s}"'} for s in scripts]}]}}`):
- `test_clean_manifest_has_no_problems` — `a.sh` (mode 0o755) referenced → `[]`.
- `test_missing_script_reported` — reference `gone.sh`, no file → `["missing script: gone.sh"]`.
- `test_non_executable_reported` — `a.sh` mode 0o644, referenced → `["not executable: a.sh"]`.
- `test_unreferenced_script_reported` — `a.sh` referenced, `orphan.sh` present → `["unreferenced script: orphan.sh"]`.
- `test_lib_scripts_exempt` — `lib-x.sh` present, unreferenced → `[]`.
- `test_inline_commands_ignored` — a SessionStart command `'rm -f "$P"/x.json; true'` → `[]`.
- `test_main_reports_and_fails` — plugin root in `tmp_path` with `hooks/hooks.json` referencing `gone.sh` → `main([str(root)]) == 1` and `capsys` stdout is `"missing script: gone.sh\n"`.
- `test_real_manifest_is_clean` — `main([str(<repo>/plugins/orchestrator-hooks)])` → `0`.

- [ ] **Step 3: Run** `uv run pytest plugins/orchestrator-hooks/tests/test_verify_manifest.py -v`. Expected: FAIL — `ModuleNotFoundError: No module named 'verify_manifest'`.

- [ ] **Step 4: Implement** `verify_manifest.py` with the interfaces above.

- [ ] **Step 5: Run** the same command. Expected: 8 passed.

- [ ] **Step 6: Full gate.**

- [ ] **Step 7: Commit** `git add pyproject.toml plugins/orchestrator-hooks/tools plugins/orchestrator-hooks/tests/test_verify_manifest.py && git commit -m "feat(hooks): hooks.json manifest checker"`
