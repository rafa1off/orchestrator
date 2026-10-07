---
name: orchestrator
description: "Agent dispatch guide and routing protocol for all development work in this codebase. Defines the 7-agent catalog (reader, researcher, thinker, writer, checker, reviewer, tester), the 3 core invariants that govern every task, and the flexible working loop."
when_to_use: "Load at the start of every session — before any code change, bug fix, refactor, or documentation update of any size. Always load before writing any code."
---

# Orchestrator

The main Claude Code session acts as orchestrator. Agents are tools — call them whenever you need their capability, as many times as needed, in whatever order the task requires. There is no fixed pipeline.

---

## Agent Catalog

| Agent | Model | Effort | Type | When to call | Give it |
|-------|-------|--------|------|--------------|---------|
| Explore *(built-in)* | haiku | not configurable | readonly | You don't know yet which files matter — "survey the repo", "find all usages of X". Returns locations and excerpts; it does not review code. | A search goal and breadth (`medium` / `very thorough`) |
| orchestrator-agents:reader | haiku | medium | readonly | You know which files matter and need their interfaces, conventions, and call paths before writing or reviewing. Paths still unknown → Explore first. | Task description + file paths (without paths it stops with a `context_request`) |
| orchestrator-agents:researcher | haiku | medium | readonly | The task depends on knowledge outside the code: a library or API, an external pattern, or a prior decision recorded in project docs. | Task description + one specific research question |
| orchestrator-agents:thinker | opus | medium | readonly | There is a question to decide rather than code to change: architecture, tradeoffs, brainstorming, root-cause analysis, "what should we do". | The question + reader/researcher output if any; it may answer with a `context_request` |
| orchestrator-agents:writer | sonnet | low | read+write | Code must change and the context is already gathered. Never for exploration. | `## Context` (reader/researcher output or files you read) + bounded `## Task` + exact `## Files to modify` |
| orchestrator-agents:checker | haiku | low | readonly | You need to know whether the code lints, typechecks, and builds — after a change or any time. Not a diff review. | Optional: files to scope lint, stack hint, pipeline path |
| orchestrator-agents:reviewer | opus | medium | readonly | A diff needs judging for correctness against the task, breakage in its callers, and project conventions. Not lint/typecheck. Always spawn fresh. | Task context (what and why) + modified files; diff base only for the full-branch review |
| orchestrator-agents:tester | haiku | high | readonly | You need the tests run and every failure diagnosed — after a change, or as a status check outside a plan. Never fixes anything. | Task + intended behavior change (`none (status check)` when nothing changed) + changed files + what to test |
| general-purpose *(built-in)* | haiku — pass `model="haiku"`, otherwise it inherits the session model | low = extract/reformat · medium = summarise/classify by given criteria · high = judgment-heavy triage | read+write, unguarded | Bulk readonly work none of the seven own: log triage, classifying a list, extracting fields from many files. Its result is input to your reasoning, never verification evidence; design judgment → thinker. | Output shape (fields or table), permission to answer `unknown`, and "do not edit files" |

> **Trust is in the guard, not the agent's word.** All seven agents return through a
> validated tool call — `checker`, `reviewer`, and `tester` write structured findings through
> `write_findings`; `reader`, `researcher`, `thinker`, and `writer` write structured reports
> through `write_report` — landing in `.claude/pipeline/<agent>-<label>-findings.json` or
> `-report.json`. A final markdown message is no longer any agent's deliverable.
> Findings additionally carry proof-of-execution (every check must carry a real process exit
> code recorded during the run being judged); reports carry presence and freshness only,
> because those four agents run no commands to attest to. The `SubagentStop` guard enforces
> both shapes — none of the seven can finish without a fresh, substantiated result. The guard
> is what makes a green result mean something, not the prose summary attached to it.

> Read [agent-contracts.md](agent-contracts.md) for full input/output contracts and session registry (warm agent reuse).

---

## Core Invariants

These rules hold regardless of task size or route. Never violate them.

1. **Read before write** — invoke reader before calling writer on those files. Direct inline reads are for single known files only — anything broader warrants a reader agent.
2. **Serialize writers on overlapping files** — one active writer per overlapping file set. Writers with fully disjoint file sets may run in parallel.
3. **Never auto-fix a tester diagnosis** — tester is readonly and classifies each test failure as REGRESSION / STALE_TEST / FLAKY / UNCLEAR. Because REGRESSION (fix the code) and STALE_TEST (update the test) have opposite fixes, guessing is unsafe: surface the diagnoses to the user and dispatch a writer only on the user's decision, with the decision folded into the writer's `## Task`. Read [verification.md](verification.md) for the full protocol.

---

## Resuming

On session start, or after a context compaction, find the active plan before doing anything
else: `Glob` `.claude/plans/*.jsonl`, discard any 0-byte file, rank the rest by mtime (newest
first), and take the first candidate whose `get_plan_state(plan)` succeeds and returns
`closed == false`. A candidate whose `get_plan_state` raises (e.g. an old-format ledger with
no `plan_archived` line) is skipped, not fatal — move to the next candidate. Read
state only from `get_plan_state`'s `PlanState` projection, falling back to
`read_plan_events(plan)` only for a detail the projection doesn't carry. Also read
`.claude/pipeline/pre-compact-snapshot.md` if it exists. Resuming does not dispatch anything
and does not write anything — Run Start's writes (auto-commit confirmation, Base, WIP
snapshot) belong solely to `## Run Start`, below.

Reports in `.claude/pipeline/*-report.json` are not part of this resume step — they are
cleared alongside findings on session start/end and are current-turn scratch, already
delivered to you by the `PostToolUse` auto-injection the moment they were written. There is
nothing stale to recover from them across a compaction the way there is for the plan event log.

---

## Run Start

For a plan-backed run (one with a plan event log), before the first writer dispatch of each
**epoch** (session start, and again at every compaction-resume — these are not the same
thing), the orchestrator records the `auto_commit` decision, the recorded Base, and an
`epoch_start` event carrying a WIP snapshot, so per-task commits and the final full-branch
review below have what they need. Read [verification.md](verification.md#run-start) for the
full trigger, the 3-step algorithm, and every degraded/edge case (declined confirmation, a
rebased Base, Bash unavailable, in-flight-task exclusion from the WIP snapshot) before any
plan-backed run's first writer dispatch.

---

## Final Full-Branch Review

Mandatory for confirmed runs. A declined run (`auto_commit: "declined"`) skips this review
entirely: once `ready_for_final_review` is true, it writes `plan_complete{status: "clean"}`
directly — see [verification.md](verification.md#final-full-branch-review) for that path.

For a `"confirmed"` plan-backed run, once `PlanState.ready_for_final_review` is true (and, for
L2/L3, after the existing integration pass in `dispatch-levels.md`), checker, reviewer, and
tester are dispatched together every round, all carrying the same `branch_round` — reviewer
scoped to the whole branch, diffed against the recorded `PlanState.base_sha`. While
`branch_round_complete` is false, the next action for this plan — in any epoch — is to
dispatch only the missing kind(s) at that same round, never the full triad again and never a
new round; no `writer_dispatched` with `reason: "branch_fix"` may be issued meanwhile. Read
[verification.md](verification.md#final-full-branch-review) for the precondition, the
`<files>` union, and why it diffs against `base_sha` rather than `git merge-base`.

---

## Dispatch Levels

```
1 track                     → Level 1
2–3 tracks AND ≤15 files    → Level 2
4+ tracks OR >15 files      → Level 3
```

> Read [dispatch-levels.md](dispatch-levels.md) before dispatching writers for L2 or L3 tasks.

> **L3a runs on the `Workflow` tool** (dynamic `pipeline()`/`parallel()`), which requires explicit user opt-in before it can be called. **Invoking this skill authorizes Workflow for L3a-scale dispatch** — that is the opt-in. Because a workflow spawns many agents, confirm the scale with the user in one line before spawning (e.g. "L3 task, N tracks — run it as a Workflow (~N agents)?"). If the user declines or Workflow is otherwise unavailable, fall back to batched parallel `Agent()` calls (L2-style, no opt-in needed) — you lose resumability and context isolation but the tracks still run.

---

## Dispatch Rules

| Agent | Notes |
|-------|-------|
| reader, researcher, thinker | save agent_id for warm reuse |
| checker, reviewer | orchestrator blocks on result before next step |

**reviewer** — never reused; always spawn fresh, so the diff baseline is never stale.

---

## Routing Special Cases

**Exploration tasks** (understanding a feature, tracing a flow, mapping an unfamiliar area):
- Files unknown (need to discover what's relevant): use `Explore` built-in.
- Files known (need to read interfaces, conventions, content): dispatch `orchestrator-agents:reader`.

**Research tasks** (external library APIs, framework patterns, prior project decisions in `docs/`): dispatch `orchestrator-agents:researcher` directly.

**Analytical tasks** (questions, brainstorming, design): dispatch `orchestrator-agents:thinker` directly. Thinker reads the context it needs with `Read`/`Grep`/`Glob`; when it needs broad mapping or external/web research it sets `context_request` on its report, which you detect via `report.context_request is not None`, fulfil (e.g. by running researcher), and then resume it warm via `SendMessage` with the findings (see [agent-contracts.md](agent-contracts.md#context-requests)). Dispatch is orchestrator-driven — agents are leaf nodes and do not spawn subagents (see [dispatch-levels.md](dispatch-levels.md#leaf-node-boundary)).
