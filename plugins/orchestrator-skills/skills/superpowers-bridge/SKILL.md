---
name: superpowers-bridge
description: "Opt-in bridge that runs the superpowers workflow (brainstorming → spec → plan → subagent-driven execution → finishing the branch) on the orchestrator's agents, hooks, findings contract and Plan Event Log. Superpowers decides what happens and when; the orchestrator decides who does it and how it is proven."
when_to_use: "Load only when explicitly asked to (a Skill(...) line in CLAUDE.md / CLAUDE.local.md, or the user naming it), and always together with orchestrator-skills:orchestrator, which it builds on. Never load it on your own initiative: it is opt-in while its cost is being evaluated."
---

# Superpowers Bridge

**Announce at start:** "Using superpowers-bridge: superpowers process, orchestrator agents."

Load `orchestrator-skills:orchestrator` first if it is not already loaded — this skill only
adds overrides on top of it; dispatch rules, Run Start, verification, the Commit Recipe, and
the Final Full-Branch Review all stay exactly as that skill and its `verification.md` define
them.

## 1. Precedence

This skill is a user instruction. Where it and a superpowers skill disagree, **this skill
wins** — superpowers gives user instructions precedence over its skills. Superpowers still
owns the process: which skill runs when, the spec as the binding authority, rulings over
stalls, continuous execution. The orchestrator owns who executes and what counts as proof:
its seven agents, the hooks that guard them, findings with real exit codes, and the Plan
Event Log as the only ledger.

## 2. Override table

Every superpowers dispatch of `general-purpose` (or "a fresh subagent") is replaced as below.
A superpowers skill not listed runs unchanged.

| Superpowers skill | Under the bridge |
|---|---|
| `brainstorming` | The builder check runs on `orchestrator-agents:thinker` (mode `qa`), the builder-check prompt as its question. |
| `writing-plans` | Keeps its format. Before writing, run the readonly research fan-out, and after approval archive the plan to the Plan Event Log — both in [planning.md](planning.md). |
| `subagent-driven-development` | §3 below. |
| `executing-plans` | The session implements. Its final review is the orchestrator's Final Full-Branch Review (checker + tester + reviewer at one `branch_round`), not a `general-purpose` code reviewer. Run Start (§3) still applies, once. |
| `requesting-code-review` | `orchestrator-agents:reviewer` (plus `orchestrator-agents:checker` when lint/typecheck state is unknown) instead of the `general-purpose` code reviewer; the code-reviewer template's content goes into the reviewer's task context. |
| `dispatching-parallel-agents` | One `orchestrator-agents:writer` per independent domain, with disjoint `## Files to modify`, each on its own `pipeline` track (`.claude/pipeline/<track>`). Verify each track with checker/tester on the same track. Invariant 2 (no overlapping writers) holds. |
| `test-driven-development` | §4 below. |
| `systematic-debugging` | Phase 1 evidence: `orchestrator-agents:tester` (classified failures) and `orchestrator-agents:reader` (code paths). Fixes go through a writer, never the tester. |
| `verification-before-completion` | The evidence is the findings JSON — `checks[]` with real exit codes — not a command you ran inline. |
| `receiving-code-review` | Applies to `orchestrator-agents:reviewer` findings. |
| `finishing-a-development-branch` | Precondition: the plan's last `branch_round` is clean and `plan_complete` is written. |
| `using-git-worktrees` | Unchanged. `.claude/plans/` and `.claude/pipeline/` live inside the worktree. |
| `writing-skills`, `diagnosing-superpowers`, `using-superpowers` | Unchanged — their subagents test skills or sessions, not code, and stay `general-purpose`. |

## 3. Subagent-driven development under the bridge

**Setup.** Do not run `scripts/sdd-workspace` and do not create `progress.md` — the Plan Event
Log (`.claude/plans/<plan>.jsonl`) is the ledger. If the plan is not archived yet, archive it
now ([planning.md](planning.md) § Archive). Then run the orchestrator's Run Start once
(auto-commit confirmation, Base, WIP snapshot) — this is the only planned question before
execution and it replaces "the implementer commits".

**Per task**, using the orchestrator's `verification.md` Steps:

1. `writer_dispatched` → `orchestrator-agents:writer` with `## Context` (the task text from the
   plan, the spec path, the task's Interfaces block, and any rulings that touch it) /
   `## Task` / `## Files to modify` (the task's `**Files:**`). A TDD task follows §4 instead.
2. `orchestrator-agents:checker` + `orchestrator-agents:tester` + `orchestrator-agents:reviewer`
   in one turn — the reviewer is superpowers' task review (spec compliance + quality), always
   fresh.
3. Clean → the Commit Recipe → `task_complete`.

**Fix rounds** (superpowers' cap of 5 holds):
- Rounds 1–3: resume the same writer with `SendMessage`, carrying the findings — resumed
  subagents keep their prompt cache.
- Rounds 4–5: a fresh writer with `model` set one tier above the writer's frontmatter model.
- Each round is a new `writer_dispatched` with `reason: "fix"` and a new attempt.
- At the cap, adjudicate as superpowers says; each adjudication is a `ruling` event.

**Final review**: the orchestrator's Final Full-Branch Review, then
`superpowers:finishing-a-development-branch`.

## 4. TDD under the bridge

The writer has no Bash, so the tester attests both halves:

1. **Red.** The writer writes only the test. Dispatch the tester with
   `Intended behavior change: <test> is written ahead of <feature> and must fail now because
   <predicted reason>`. Required result: every new test's failure classified `EXPECTED_RED`.
2. **Green.** Resume the writer to implement. The tester runs again and must PASS.

An unexpected red — any classification other than `EXPECTED_RED`, including an error in the
new test itself — is handled like any other tester diagnosis (§5).

## 5. Rulings and tester diagnoses (the hybrid rule)

Superpowers rules instead of stalling; orchestrator invariant 3 never guesses a tester
diagnosis. Under the bridge:

- **REGRESSION / STALE_TEST settled by the plan or spec** (for example a plan rule "bugs found
  are recorded with `xfail`, never fixed"): rule on it with
  `write_plan_event(Ruling(kind="ruling", task=N, seq=next_seq["ruling"], text="<decision> — <why, quoting the plan/spec text> — <cost if wrong>"), plan)`
  and continue.
- **Not settled by either**: stop and ask the user — record the `escalation{topic:
  "tester_diagnosis"}` exactly as `verification.md` says. Never turn this case into a ruling.
- Every other superpowers ruling (plan defects, interface mismatches, adjudications) is also
  a `ruling` event; it never goes to a separate ledger.

## 6. Model

Omit `model` on every dispatch — each agent's frontmatter decides model and effort. Only two
exceptions: the round 4–5 escalation (§3) and a superpowers step that explicitly asks for the
most capable model (e.g. the final review), where you set it.

## 7. Planning

When `writing-plans` runs, read [planning.md](planning.md) before writing the plan.
