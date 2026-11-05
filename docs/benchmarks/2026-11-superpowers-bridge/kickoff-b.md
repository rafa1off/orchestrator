# Run B kickoff — superpowers + bridge

**Before either run (user, once).** Both sessions already exist, so `--plugin-dir` is not
available, and the branch is not merged, so the GitHub marketplace (default branch) does not
have the bridge. Point the marketplace at the local checkout instead:

1. Keep `/home/rafaelg/Projetos/orchestrator` checked out on `feat/superpowers-bridge` for the
   whole benchmark — a local marketplace reads that working copy.
2. In one session: `/plugin marketplace remove orchestrator-plugins`, then
   `/plugin marketplace add /home/rafaelg/Projetos/orchestrator`, then reinstall the six
   plugins (`/plugin install <name>@orchestrator-plugins` for orchestrator-mcp,
   orchestrator-hooks, orchestrator-agents, orchestrator-skills, ty-lsp, tsgo-lsp).
3. Confirm with `/plugin`: orchestrator-skills 2.0.0, orchestrator-agents 1.28.0,
   orchestrator-mcp 1.12.0.
4. In **both** sessions, run `/reload-plugins`.

Run A sees the same plugins but never loads the orchestrator skill, its agents or the bridge;
the hooks are unchanged on this branch and only match `orchestrator-agents:*`.

**After both runs:** remove the local marketplace and re-add `rafa1off/orchestrator`.

**Before pasting (user):**

- Run A must be finished.
- Note `/usage` (5-hour and weekly) in `comparison.md` right before you paste.
- Use the same `7c01f54b4082269d7e6e74e8d13f617ab2fbba32` as Run A.

---

Paste everything below this line into the Run B session.

---

Create an isolated worktree and work only inside it:

```bash
git worktree add ../orchestrator-run-b -b bench/run-b 7c01f54b4082269d7e6e74e8d13f617ab2fbba32
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
