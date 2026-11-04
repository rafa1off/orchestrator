# Run B kickoff — superpowers + bridge

**Before either run (user, once).** Both sessions already exist, so `--plugin-dir` is not
available. Install the bridge into them:

1. Push the plugins (orchestrator-skills ≥ 2.0.0, orchestrator-agents ≥ 1.28.0,
   orchestrator-mcp ≥ 1.12.0).
2. In **both** sessions, run `/plugin update` for the orchestrator plugins, then
   `/reload-plugins`.

Run A keeps seeing the same installed plugins as today's setup and simply never loads the
bridge.

**Before pasting (user):**

- Run A must be finished.
- Note `/usage` (5-hour and weekly) in `comparison.md` right before you paste.
- Use the same `<BASE>` as Run A.

---

Paste everything below this line into the Run B session.

---

Create an isolated worktree and work only inside it:

```bash
git worktree add ../orchestrator-run-b -b bench/run-b <BASE>
cd ../orchestrator-run-b
```

Before anything else, load `Skill("/orchestrator-skills:orchestrator")` and then
`Skill("/orchestrator-skills:superpowers-bridge")`. Follow the bridge's overrides for
everything below.

Then execute the plan `docs/superpowers/plans/2026-11-04-hook-test-suite.md` with
`superpowers:subagent-driven-development`. Run every task to the end without pausing to
check in.

Standing answers, so you don't need to ask:

- Run Start auto-commit confirmation: **confirmed**. Commit per task, inside the worktree, on
  branch `bench/run-b`. Never push or merge.
- If a test exposes a bug in a hook script, do not fix the hook. Mark that test
  `pytest.mark.xfail(strict=True, reason="<the bug>")` and continue. The plan says the same,
  so this settles REGRESSION vs STALE_TEST under the bridge's hybrid rule: record a `ruling`.
- Do not modify anything under `plugins/orchestrator-hooks/hooks/`.

When the final full-branch review is clean, stop. Do not run `finishing-a-development-branch`'s
merge or PR options. Report the list of bugs recorded as `xfail`.
