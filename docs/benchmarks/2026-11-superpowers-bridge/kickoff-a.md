# Run A kickoff — superpowers only

**Before pasting (user):**

- This run comes first.
- Note `/usage` (5-hour and weekly) in `comparison.md` right before you paste.
- `BASE` is the commit that contains the benchmark plan. Use the same `BASE` for Run B, and
  record it in `comparison.md`.

---

Paste everything below this line into the Run A session.

---

Create an isolated worktree and work only inside it:

```bash
git worktree add ../orchestrator-run-a -b bench/run-a 7c01f54b4082269d7e6e74e8d13f617ab2fbba32
cd ../orchestrator-run-a
```

Execute the plan `docs/superpowers/plans/2026-11-04-hook-test-suite.md` with
`superpowers:subagent-driven-development`. Run every task to the end without pausing to
check in.

Standing answers, so you don't need to ask:

- Commit per task, inside the worktree, on branch `bench/run-a`. Never push or merge.
- If a test exposes a bug in a hook script, do not fix the hook. Mark that test
  `pytest.mark.xfail(strict=True, reason="<the bug>")` and continue. The plan says the same.
- Do not modify anything under `plugins/orchestrator-hooks/hooks/`.

When the final review is clean, stop. Do not run `finishing-a-development-branch`'s merge or
PR options. Report the list of bugs recorded as `xfail`.
