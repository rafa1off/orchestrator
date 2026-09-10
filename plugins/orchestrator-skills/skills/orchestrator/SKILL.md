---
name: orchestrator
description: "Agent dispatch guide and routing protocol for all development work in this codebase. Defines the 7-agent catalog (reader, researcher, thinker, writer, checker, reviewer, tester), the 3 core invariants that govern every task, and the flexible working loop."
when_to_use: "Load at the start of every session — before any code change, bug fix, refactor, or documentation update of any size. Always load before writing any code."
---

# Orchestrator

The main Claude Code session acts as orchestrator. Agents are tools — call them whenever you need their capability, as many times as needed, in whatever order the task requires. There is no fixed pipeline.

---

## Agent Catalog

| Agent | Model | Effort | Type | When to call |
|-------|-------|--------|------|--------------|
| Explore *(built-in)* | haiku | *(none)* | readonly | Broad codebase discovery — "survey the repo", "find all usages of X". Use `Agent(subagent_type="Explore", ...)` |
| orchestrator-agents:reader | haiku | *(none)* | readonly | Map files, interfaces, and conventions before writing. Writes guarded reports to `reader-report.json`; call multiple times as new paths surface. |
| orchestrator-agents:researcher | sonnet | low | readonly | External APIs, library patterns, prior decisions in `docs/`. Writes guarded reports to `researcher-report.json`. |
| orchestrator-agents:thinker | opus | medium | readonly | Analysis, brainstorming, architectural decisions. Isolates verbose reasoning from main context. Writes guarded reports to `thinker-report.json`. |
| orchestrator-agents:writer | sonnet | low | read+write | Produce code changes from a context block. Writes guarded reports to `writer-report.json`. |
| orchestrator-agents:checker | haiku | *(none)* | readonly | Lint + typecheck + build checks only — no diff review. Writes guarded findings to `checker-findings.json`; call any time. |
| orchestrator-agents:reviewer | opus | medium | readonly | Diff review only — no lint/typecheck. Writes guarded findings to `reviewer-findings.json`; always spawn fresh for a clean diff baseline. |
| orchestrator-agents:tester | sonnet | low | readonly | Run the suite and diagnose each failure (regression vs stale test vs flaky). Never writes or fixes tests. Writes guarded findings to `tester-findings.json`. |

> **Trust is in the guard, not the agent's word.** All seven agents return through a
> validated tool call — `checker`, `reviewer`, and `tester` write structured findings through
> `write_findings`; `reader`, `researcher`, `thinker`, and `writer` write structured reports
> through `write_report`. A final markdown message is no longer any agent's deliverable.
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

On session start, or after a context compaction, read `.claude/plans/progress.md` before doing anything else — it carries deliverable status and recorded decisions. Also read `.claude/pipeline/pre-compact-snapshot.md` if it exists.

When `progress.md`'s `**Auto-commit:**` field (read by its first whitespace-delimited token)
is `confirmed`, also read the plan's ledger — `.claude/plans/<same stem as **Plan:**>.jsonl`
— and validate each line's `sha` (when not `null`) with `git merge-base --is-ancestor <sha>
HEAD` (treat any non-zero exit as failed validation, not specifically exit code 1) — this
reconstructs each task's status marker. Each line is validated independently; a line that
fails validation reverts only that task's status to unknown, with no fallback to an earlier
line for the same task — an unknown last line means unknown status, never a resurrected
earlier "complete". The ledger is branch-local and history-rewrite-fragile: after a rebase,
expect every prior line to re-validate as unknown rather than trusting a coincidentally-
resolving sha. When the token is `declined`, or before it is ever confirmed, the ledger has
no lines to read (it may not even exist yet — it is created on its first append) and this
read is a no-op — it never resets an orchestrator-set checkbox back to pending. Resuming does
not dispatch anything and does not perform `## Run Start`'s writes (Base, WIP snapshot,
confirmation) — those belong solely to `## Run Start`, below.

Reports in `.claude/pipeline/*-report.json` are not part of this resume step — they are
cleared alongside findings on session start/end and are current-turn scratch, already
delivered to you by the `PostToolUse` auto-injection the moment they were written. There is
nothing stale to recover from them across a compaction the way there is for `progress.md`.

---

## Run Start

For a plan-backed run (one with `.claude/plans/progress.md`), before the first writer
dispatch of each **epoch** (session start, and again at every compaction-resume — these are
not the same thing), the orchestrator confirms auto-commit, captures `**Base:**`, and
snapshots WIP state, so per-task commits and the final full-branch review below have what
they need. Read [verification.md](verification.md#run-start) for the full trigger, the
3-step algorithm, and every degraded/edge case (declined confirmation, a rebased Base, Bash
unavailable, in-flight-task exclusion from the WIP snapshot) before any plan-backed run's
first writer dispatch.

---

## Final Full-Branch Review

For a plan-backed run, once every file-authoring task is `complete`/`complete-with-parked`
(and, for L2/L3, after the existing integration pass in `dispatch-levels.md`), dispatch one
fresh `reviewer` scoped to the whole branch, diffed against the recorded `Base` — this
applies to multi-task L1 work too, not only L2/L3. Read
[verification.md](verification.md#final-full-branch-review) for the precondition, the
`<files>` union, and why it diffs against `Base` rather than `git merge-base`.

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
