# Superpowers bridge — cost comparison

- **Spec:** `docs/superpowers/specs/2026-11-04-superpowers-bridge-design.md` (Evaluation section)
- **Benchmark plan:** `docs/superpowers/plans/2026-11-04-hook-test-suite.md`
- **BASE:** `7c01f54b4082269d7e6e74e8d13f617ab2fbba32`
- **Claude Code version:** v2.1.318
- **Main-session model / effort:** Opus 5.5 with medium effort

| Metric | Run A (superpowers) | Run B (+ bridge) | How measured |
|---|---|---|---|
| 5-hour limit used (before → after) | 22% -> 41% | 41% -> 77% | `/usage`, read by the user right before pasting the kickoff and right after the run stops |
| Weekly limit used (before → after) | 32% -> 35% | 36% -> 41% | `/usage`, same moments as above |
| Tokens per model (input / cache read / cache write / output) | Opus 5.5: 200 / 9.04M / 284k / 54.6k (main 7.78M / 175k / 37.6k); Sonnet 5.5: 144 / 3.16M / 413k / 57.6k; Haiku 5.5: 10 / 129k / 99k / 5.8k | Opus 5.5: 590 / 30.4M / 712k / 156k (main 27.4M / 280k / 83k; reviewer 3.0M / 432k / 73k); Haiku 5.5: 330 / 2.31M / 313k / 114k (tester + checker); Sonnet 5.5: 106 / 1.08M / 261k / 37k (writer)
| Subagents dispatched (by type) | 17 `general-purpose`: 14 sonnet, 2 haiku, 1 opus (final review) | 58: 15 writer (sonnet), 16 tester (haiku), 14 checker (haiku), 13 reviewer (opus)
| Wall-clock time (kickoff → stop) | 21 min (kickoff 12:35:36 → 12:56:24 UTC) | 35 min (kickoff 13:18:17 → 13:53:30 UTC)
| Fix rounds | 2 task-level (Task 1, Task 4) + 1 final-review fix wave | 5 task-level (T1, T3, T4 ×2, T5) + the TDD green step + 1 final-review fix wave (3 `branch_fix` writers)
| Final-review findings (Critical / Important / Minor) | 0 / 2 / 3 (all fixed in one wave) | round 1: 4 findings (3 fixed, minors parked); round 2: 3 test-strength findings parked → `plan_complete{parked}` (the reviewer schema carries no severity)
| Hook bugs recorded as `xfail` | 6 (5 predicted + `post-tool-findings.sh` exits 2 when no findings file exists); suite 161 passed / 6 xfailed | 6 (the same 6 as A); suite 161 passed / 6 xfailed
| Times the session stopped to ask the user | 0 | 0 (0 `escalation` events)

## Verdict

<!-- Filled in by the user: does the bridge become the default workflow? -->

**Claude's analysis (not the verdict):**

- **Cost:** B used 36 points of the 5-hour window against A's 19 (1.9×) and 5 weekly points against 3, for the same outcome (identical 6 bugs, identical suite). B also took 1.7× the wall-clock time.
- **Where B's cost goes:** the main session, not the subagents. B's main session made 139 model calls reading 27.4M cached tokens; A's made 64 reading 7.8M (3.5×). Every task round is an event write, three verifier dispatches and their handbacks, plus the orchestrator skill, `verification.md` and the bridge resident in context on every call. Subagent cache reads were 6.4M (B) vs 4.6M (A).
- **Second driver:** 13 reviewer dispatches on Opus (frontmatter) — 3.0M cache read — where A's per-task reviews ran on Sonnet; plus 14 checker runs A never paid for.
- **What B bought:** an auditable event log (15 writer dispatches, 42 verify rounds with exit codes, 10 rulings) and stricter gating (5 task-level fix rounds vs 2; a second final-review round that parked 3 residual findings A never surfaced). No extra bugs found, no stop-and-ask.
- **Defects the run exposed in the bridge:** the Plan Event Log and pipeline land in the main checkout, not the worktree (the MCP and hooks use the session's start directory); the Commit Recipe's SHA validation reads the wrong repo as a result; one tester round was lost; a zsh glob made the between-round pipeline cleanup a silent no-op.

