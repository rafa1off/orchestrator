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
| `executing-plans` | The session implements; no `writer_dispatched` is written. Run Start fires once per epoch, the first time in that epoch the session is about to implement a task. Per task: commit through the Commit Recipe (paths: the files the session changed for the task ∩ `TaskState.files`), then `task_complete{attempt: 1, sha}`. Once `ready_for_final_review` is true, the orchestrator's Final Full-Branch Review (checker + tester + reviewer at one `branch_round`) replaces the `general-purpose` code reviewer. |
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
now ([planning.md](planning.md) § Archive). Run the orchestrator's Run Start **once per
epoch** (session start, and again after every compaction — see `verification.md` § Run Start):
auto-commit confirmation (asked only the first time), Base, WIP snapshot. It replaces "the
implementer commits".

**Read before write (invariant 1).** The plan's research fan-out ([planning.md](planning.md))
plus the task text satisfy invariant 1 for files the task's `**Files:**` lists. Do not add a
per-task reader by default; dispatch one only when a task must touch a file its plan text
does not describe.

**Per task**, using the orchestrator's `verification.md` Steps (a TDD task follows §4):

1. `writer_dispatched{attempt: last_attempt + 1, reason: "initial"}` → a **fresh**
   `orchestrator-agents:writer` with `## Context` (the task text from the plan, the spec path,
   the task's Interfaces block, and every `ruling` that touches it) / `## Task` /
   `## Files to modify` (the task's `**Files:**`), plus `plan: <stem>, task: N, attempt: <n>`.
2. `orchestrator-agents:checker` + `orchestrator-agents:tester` + `orchestrator-agents:reviewer`
   in one turn, each carrying `plan`, `task`, the attempt under review and its own `seq`. The
   reviewer is superpowers' task review — give it the spec path and the task text so it can
   judge spec compliance as well as quality. Always fresh.
3. Clean → the Commit Recipe (paths: the union of `in_scope` across the task's attempts) →
   `task_complete`.

**Fix rounds.** Every round is a new attempt: `writer_dispatched{attempt: last_attempt + 1,
reason: "fix"}`, then a **fresh** writer (never a `SendMessage` resume — a resumed writer would
echo its original attempt, and the hooks' start stamp would not cover it) carrying the
findings and `plan`, `task`, the new `attempt`. Then the same checker + tester + reviewer turn
as step 2, at the new attempt — this **replaces** SDD's `re-review-prompt.md`.

- **Counting.** The cap is the orchestrator's: `TaskState.round_count` from
  `get_plan_state`, which survives compaction and counts the initial round too. A task is at
  the cap when `round_count` reaches **5** (a TDD task: **6**, because its red step is a round
  of its own). Then adjudicate per `verification.md` § Adjudication Protocol — parked findings
  and forced fixes are `ruling` / `forced_fix` events.
- **Model escalation.** Before dispatching a fix, read `round_count`: the fix about to go out
  is number `F = round_count` (TDD task: `round_count − 1`). For `F ≥ 4` — superpowers'
  "rounds 4–5" — set `model` one tier above the writer's frontmatter model (sonnet → opus);
  otherwise omit `model`.

**SDD steps you skip or replace:**

| SDD step | Under the bridge |
|---|---|
| `scripts/sdd-workspace`, `scripts/task-brief`, `progress.md` | Skipped — the plan event log is the ledger; briefs are the dispatch prompts above. |
| implementer self-review + commit | Replaced by step 2's three verifiers and the orchestrator's Commit Recipe. |
| `scripts/review-package` + task reviewer | Replaced by `orchestrator-agents:reviewer` (it diffs the task itself). |
| `re-review-prompt.md` after a fix | Replaced by the full checker + tester + reviewer turn at the new attempt. |
| "Resume from the ledger" | Skip every task whose `TaskState.ready` is true; resume the first one that is not. |
| final code reviewer | The orchestrator's Final Full-Branch Review, then `superpowers:finishing-a-development-branch`. |
| Finish: "Rulings I made" | `read_plan_events(plan, kind="ruling")`, in order, each with its cost-if-wrong. Deferred minors are the parked rulings. |
| Never parallel implementers | Holds — one task at a time. Parallel writers only through `dispatching-parallel-agents` (§2). |

## 4. TDD under the bridge

The writer has no Bash, so the tester attests both halves. A TDD task's sequence:

1. **Red — attempt n, `reason: "initial"`.** A fresh writer writes only the test. Then dispatch
   only the tester, with `Intended behavior change: <test> is written ahead of <feature> and
   must fail now because <predicted reason>. A failure for any other reason — including an
   error in the new test itself — is not EXPECTED_RED: classify it UNCLEAR.` Required result:
   every new test's failure classified `EXPECTED_RED`.
2. **Green — attempt n + 1, `reason: "fix"`.** A fresh writer implements (its `## Context`
   names the test written at attempt n). Then the full checker + tester + reviewer turn of §3
   step 2; the tester must PASS.
3. Commit (the union of `in_scope` across both attempts includes the test file) →
   `task_complete`.

An unexpected red — any classification other than `EXPECTED_RED` — is handled by §5.

## 5. Rulings and tester diagnoses (the hybrid rule)

Superpowers rules instead of stalling; orchestrator invariant 3 never guesses a tester
diagnosis. Under the bridge:

- **REGRESSION / STALE_TEST settled by the plan or spec** (for example a plan rule "bugs found
  are recorded with `xfail`, never fixed"): rule on it with
  `write_plan_event(Ruling(kind="ruling", task=N, seq=next_seq["ruling"], text="<decision> — <why, quoting the plan/spec text> — <cost if wrong>"), plan)`
  and continue.
- **Not settled by either, and every FLAKY or UNCLEAR**: stop and ask the user — record the
  `escalation{topic: "tester_diagnosis"}` exactly as `verification.md` says. Never turn this
  case into a ruling. (A FLAKY call may first be confirmed by the tester's single re-run.)
- Every other superpowers ruling (plan defects, interface mismatches, adjudications) is also
  a `ruling` event; it never goes to a separate ledger.

## 6. Model

Omit `model` on every dispatch — each agent's frontmatter decides model and effort. Only two
exceptions: the fix-round escalation (§3) and a superpowers step that explicitly asks for the
most capable model (e.g. the final review), where you set it.

## 7. Planning

When `writing-plans` runs, read [planning.md](planning.md) before writing the plan.
