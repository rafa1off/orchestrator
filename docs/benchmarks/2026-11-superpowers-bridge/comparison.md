# Superpowers bridge — cost comparison

- **Spec:** `docs/superpowers/specs/2026-11-04-superpowers-bridge-design.md` (Evaluation section)
- **Benchmark plan:** `docs/superpowers/plans/2026-11-04-hook-test-suite.md`
- **BASE:** `7c01f54b4082269d7e6e74e8d13f617ab2fbba32`
- **Claude Code version:**
- **Main-session model / effort:**

| Metric | Run A (superpowers) | Run B (+ bridge) | How measured |
|---|---|---|---|
| 5-hour limit used (before → after) | | | `/usage`, read by the user right before pasting the kickoff and right after the run stops |
| Weekly limit used (before → after) | | | `/usage`, same moments as above |
| Tokens per model (input / cache read / cache write / output) | | | session transcripts under `~/.claude/projects/`, including subagent transcripts; analyzed by Claude |
| Subagents dispatched (by type) | | | session transcripts; analyzed by Claude |
| Wall-clock time (kickoff → stop) | | | first and last transcript timestamps |
| Fix rounds | | | A: git log of `bench/run-a` plus the SDD ledger; B: `writer_dispatched` events with `reason: "fix"` in the plan event log |
| Final-review findings (Critical / Important / Minor) | | | each run's final review output |
| Hook bugs recorded as `xfail` | | | `rg -n "xfail\(strict=True" --glob "test_*.py"` in each worktree |
| Times the session stopped to ask the user | | | user's count; for B, also `escalation` events |

## Verdict

<!-- Filled in by the user: does the bridge become the default workflow? -->
