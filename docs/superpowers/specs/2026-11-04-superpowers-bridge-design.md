# Superpowers Bridge — Design

Date: 2026-11-04 · Status: draft for approval

## Intent and why

The user moved from the orchestrator ecosystem to superpowers because orchestrator runs burned
too much of the 5-hour and weekly usage limits. On the last real orchestrator task (a WhatsApp
API integration) the subagents paid off in implementation, test and review speed, but the cost
was too high.

Two things have changed since then:

- Claude Code changes from 2.1.261 to 2.1.318: effort is no longer inherited by subagents on
  another model, there are `CLAUDE_CODE_SUBAGENT_EFFORT` and `omitClaudeMd`, subagents have an
  `autoCompactWindow`, cache fixes landed for resumed subagents, and background shells keep the
  cache warm.
- On 2026-11-04 @ClaudeDevs announced a server-side change. The 30-second status-line update of
  a background subagent used to re-read the subagent's whole conversation. Haiku 5.5 now writes
  it from short notes, about 99% cheaper.

The user wants **superpowers' organization and structure** (brainstorming → spec → plan →
execution with ledgered rulings → finishing the branch) combined with **orchestrator's
speed and guarantees** (specialized parallel subagents, fail-closed hooks, findings with real
exit codes, an auditable Plan Event Log).

Superpowers decides *what happens and when*. Orchestrator decides *who does it and how it is
proven*.

## Goals

1. Cut the cost of `orchestrator-agents` using the new Claude Code levers.
2. Add an opt-in skill `orchestrator-skills:superpowers-bridge` that makes the superpowers
   skills dispatch orchestrator agents. Our hooks and MCP then apply automatically, because the
   hooks match on `orchestrator-agents:*`.
3. Retire `orchestrator-skills:orchestrator-plan`. Planning now belongs to superpowers alone
   (`brainstorming` + `writing-plans`).
4. Measure whether the bridge is affordable before it becomes the default workflow (see
   Evaluation).

## Non-goals

- Editing the superpowers plugin. It lives in the plugin cache and is overwritten on update,
  so all adaptation lives in our plugins.
- Making the bridge the default. It stays opt-in until the user has seen the evaluation
  results.
- Changing the MCP server or hook contracts. Do it only if the bridge cannot work without the
  change, and record the reason.

## Anti-goals (failure even if it technically works)

- **Two systems competing for control:** two ledgers, two plan formats, or superpowers
  dispatching `general-purpose` agents around the bridge and spending without our guarantees.
- **Weaker guarantees:** no guard, hook or findings contract loosened to save cost. The
  writer gets no Bash.
- **Hidden stalls:** the bridge stops for the user where superpowers would have ruled and moved
  on, outside the hybrid rule below.

## Decisions made with the user

| Topic | Decision |
|---|---|
| Default execution mode under the bridge | `subagent-driven-development` (SDD); `executing-plans` stays the cheap mode |
| Ledger | The Plan Event Log (`.claude/plans/<plan>.jsonl`) is the single source of truth. Superpowers rulings become `ruling` events. |
| Plan format | The superpowers `writing-plans` format, which replaces `orchestrator-plan` |
| Guarantees | All kept: hooks, guards, findings with exit codes, the event log |
| TDD | **Option 1:** `writer` writes the test → `tester` confirms red → `writer` implements → `tester` confirms green |
| Tester diagnoses (invariant 3) vs "rulings, not stalls" | **Hybrid:** when the plan or spec settles REGRESSION vs STALE_TEST, record a `ruling` and continue. When nothing settles it, stop and ask the user. |
| Activation | Opt-in, never the default before the evaluation |

## How superpowers skills map under the bridge

The bridge is a set of overrides that sits on top of the superpowers skills. Superpowers gives
user instructions (CLAUDE.md) precedence over its skills, and the bridge is activated through
the project CLAUDE.md, so its overrides win. The bridge must name each override explicitly,
because the superpowers text says `general-purpose`.

| Superpowers skill | Under the bridge |
|---|---|
| `brainstorming` | The builder check runs on `orchestrator-agents:thinker` |
| `writing-plans` | Keeps the format. Before writing, a readonly fan-out (`reader`/`researcher` in parallel, `Explore` when paths are unknown), which is what is worth keeping from `orchestrator-plan` Steps 2–3 (research + blast radius). After approval: `plan_archived` + one `task_created` per task. |
| `subagent-driven-development` | Per task: `writer` → `checker` + `tester` (+ `reviewer` as the task review) → the orchestrator commits through the existing Commit Recipe. Fix rounds 1–3 resume the `writer` (resume is now cache-safe), rounds 4–5 dispatch a fresh `writer` with a model override. The final review is the existing Final Full-Branch Review (`branch_round`). The superpowers `progress.md` is not the ledger. |
| `executing-plans` | The session implements. At the end: `checker` + `tester` + `reviewer` with `branch_round` |
| `requesting-code-review` | `reviewer` (+ `checker`) instead of a `general-purpose` code reviewer |
| `dispatching-parallel-agents` | One `writer` per domain, with disjoint file sets, each on its own `pipeline` track |
| `test-driven-development` | The red/green flow from the Decisions table, both steps attested by `tester` findings |
| `systematic-debugging` | Phase 1 evidence comes from `tester` (classified failures) and `reader` (code paths) |
| `verification-before-completion` | The evidence is the findings JSON (`checks[]` with exit codes) |
| `receiving-code-review` | Applies to `reviewer` findings |
| `finishing-a-development-branch` | Preconditions: a clean `branch_round` + `plan_complete` |
| `using-git-worktrees` | Compatible. `.claude/plans/` and `.claude/pipeline/` live inside the worktree. |
| `writing-skills`, `diagnosing-superpowers`, `using-superpowers` | Unchanged |

**Model:** bridge dispatches omit `model`, so the agent's frontmatter decides. The exceptions
are superpowers' fix-round 4–5 escalation and the cases where superpowers asks for "the most
capable model".

**Run Start** (auto-commit confirmation, Base, WIP snapshot) happens once at the start of SDD
execution. It is the only planned question before the run, and it replaces superpowers'
"implementer commits".

## Cost changes to `orchestrator-agents`

Criteria, with the final per-agent choice left to the builder:

- `omitClaudeMd: true` for agents that neither run Bash nor need project conventions. If an
  agent that needs conventions gets it, that agent must explicitly `Read` CLAUDE.md, as `writer`
  already does. `checker` and `tester` need the Commands section and the user's global CLAUDE.md
  (rtk), so they keep it.
- `autoCompactWindow` on agents that can run long (`tester`, `reviewer`).
- Review the fixed `effort` values in light of 2.1.317 (no more effort inheritance), e.g. `tester`
  is `haiku`/`high` today.
- Document `CLAUDE_CODE_SUBAGENT_EFFORT` in the README as a safety net for `general-purpose`
  dispatches that escape the bridge.

## Retiring `orchestrator-plan`

- Remove `plugins/orchestrator-skills/skills/orchestrator-plan/`.
- Content that is still needed moves into the bridge or into `orchestrator/verification.md`:
  - the readonly research fan-out;
  - the archive step (Step 6: `plan_archived`, `task_created`, `decision`);
  - any part of `plan-format.md` the event log depends on.
- Update references: `README.md` (the skills table and the activation section),
  `orchestrator/verification.md:306`. In `dev_tools.py` the string only appears in examples and
  can stay.
- Bump versions: `orchestrator-skills` gets a major bump (a skill is removed),
  `orchestrator-agents` a minor bump, in `plugin.json` and `.claude-plugin/marketplace.json`.

## Evaluation (before the bridge becomes the default)

**Benchmark task:** a pytest suite for the `orchestrator-hooks` hooks. None of the 10 scripts
has tests today. Expect about 5–6 tasks: shared infrastructure (fixtures that build hook JSON
payloads and run the scripts) plus one task per hook or group of hooks. Only test files are
added; the hooks are not changed.

**Bugs the tests find are recorded, not fixed.** That rule is in the plan, so it falls under
the hybrid rule's "the plan settles it". *(Claude's call)* Each test that exposes a bug is
marked `pytest.mark.xfail(strict=True, reason="<bug>")`, so the task can complete while the bug
stays recorded.

**TDD task (user decision):** the plan also includes at least one small piece of new
functionality. It forces the red/green path in both runs, so the bridge's most expensive path
is measured. The builder picks a feature that is small, useful and reversible.

**The plan is written once,** with `writing-plans`, after the bridge is built. The same file is
used by both runs.

**Scope of the build** *(Claude's call)*: the bridge, the agent changes, the retirement of
`orchestrator-plan`, the benchmark plan, a kickoff prompt for each run, and an empty comparison
template. Claude does not run the evaluation. The user runs it in two interactive sessions,
then Claude analyzes the transcripts.

**Protocol:**

- Two blank interactive sessions, already created by the user, run one after the other (never
  in parallel). Same main-session model and effort, each run on its own worktree from the same
  base.
- Run A is pure superpowers: SDD without the bridge, the user's current setup.
- Run B is superpowers + the bridge: SDD with the bridge activated. *(Claude's call)* The
  bridge is activated by Run B's kickoff prompt or by an uncommitted `CLAUDE.local.md` in
  worktree B, never by the shared base, so Run A cannot see it.
- The user pastes the kickoff prompt and answers any question the session asks (the Run Start
  confirmation, a stop under the hybrid rule).
- Measure, per run:
  - `/usage` before and after (5-hour and weekly), read by the user;
  - tokens per model, the subagent count and wall-clock time, from the session transcripts
    under `~/.claude/projects/`, analyzed by Claude afterwards;
  - fix rounds;
  - final-review findings;
  - bugs recorded in the hooks.
- The results go into the comparison document in the repo. The user decides on making the
  bridge the default from that document. `executing-plans` + bridge is not measured.

**Minimum Claude Code version:** 2.1.317, for `omitClaudeMd`, `autoCompactWindow` and no effort
inheritance. The installed version is 2.1.318.

**Plan archive** *(verified)*: the MCP requires `.claude/plans/<stem>.md` to exist. The bridge
copies the superpowers plan there when it writes `plan_archived`, so no contract changes.

**Expected red** *(Claude's call)*: if the findings contract cannot express an expected red as
anything other than a failure to classify, the builder may make the smallest possible addition
to the schema and guard, recording why. Otherwise the contracts stay as they are.

## Left to the builder

- The bridge's exact text, structure and lazy-loaded references (follow the pattern of the
  `orchestrator` skill).
- How the bridge is activated (expected: a `Skill(...)` line in the project CLAUDE.md, which
  run A does not have).
- How `plan_archived` points at the superpowers plan, so long as `get_plan_state` and Resuming
  keep working.
- The per-agent choices under the criteria above.
- Where the comparison document lives and its format.
