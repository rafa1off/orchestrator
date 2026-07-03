---
name: orchestrator
description: "Agent dispatch guide and routing protocol for all development work in this codebase. Load this skill at the start of every session — before any code change, bug fix, refactor, or documentation update of any size. It defines the 8-agent catalog (reader, researcher, thinker, writer, checker, reviewer, verify, tester), the 3 core invariants that govern every task, and the flexible working loop. Always load before writing any code."
---

# Orchestrator

The main Claude Code session acts as orchestrator. Agents are tools — call them whenever you need their capability, as many times as needed, in whatever order the task requires. There is no fixed pipeline.

---

## Agent Catalog

| Agent | Model | Type | When to call |
|-------|-------|------|--------------|
| Explore *(built-in)* | haiku | readonly | Broad codebase discovery — "survey the repo", "find all usages of X". Use `Agent(subagent_type="Explore", ...)` |
| orchestrator-agents:reader | haiku | readonly | Map files, interfaces, and conventions before writing. Call multiple times as new paths surface. |
| orchestrator-agents:researcher | sonnet | readonly | External APIs, library patterns, prior decisions in `docs/`. |
| orchestrator-agents:thinker | sonnet | readonly | Analysis, brainstorming, architectural decisions. Isolates verbose reasoning from main context. |
| orchestrator-agents:writer | sonnet | read+write | Produce code changes from a context block. |
| orchestrator-agents:checker | haiku | readonly | Lint + typecheck + build checks only — no diff review. Ad-hoc quality gate; call any time. |
| orchestrator-agents:reviewer | sonnet | readonly | Diff review only — no lint/typecheck. Use for PR reviews or reviewing a change set after checker passes. |
| orchestrator-agents:verify | sonnet | readonly | Lint + typecheck + diff review in one pass. Post-write loop only. Always `background: true`. Never reused — always spawn fresh. |
| orchestrator-agents:tester | sonnet | read+write | Write and run tests after verify approves. |

> **Task tracking:** pass task context when dispatching any agent — `taskId: [id]` for a single plan task, or `tasks: [{taskId, description}, ...]` when delegating multiple sequential plan items. Agents self-manage all status transitions.

> Read [agent-contracts.md](agent-contracts.md) for full input/output contracts and session registry (warm agent reuse).

---

## Core Invariants

These rules hold regardless of task size or route. Never violate them.

1. **Read before write** — invoke reader before calling writer on those files. Direct inline reads are for single known files only — anything broader warrants a reader agent.
2. **Verify after write, max 2 rounds** — after any write phase, dispatch verify + tester together. If findings remain after 2 rounds: escalate to user. Read [verify-loop.md](verify-loop.md) for the step-by-step protocol.
3. **Serialize writers on overlapping files** — one active writer per overlapping file set. Writers with fully disjoint file sets may run in parallel.

---

## Dispatch Levels

```
Plan has 1 track?           → Level 1
2–3 tracks AND ≤15 files?   → Level 2
3+ tracks OR >15 files?     → Level 3
```

> Read [dispatch-levels.md](dispatch-levels.md) before dispatching writers for L2 or L3 tasks.

---

## Dispatch Rules

| Agent | Background | Notes |
|-------|------------|-------|
| reader, researcher, thinker | always `background: true` | save agent_id for warm reuse |
| verify, tester | always `background: true` | dispatched together in the same message turn |
| checker, reviewer | never (in-session) | orchestrator blocks on result before next step |
| writer | orchestrator's choice | use `background: true` when parallelism is warranted |

**verify** — never reused; always spawn fresh.

---

## Routing Special Cases

**Exploration tasks** (understanding a feature, tracing a flow, mapping an unfamiliar area):
- Files unknown (need to discover what's relevant): use `Explore` built-in.
- Files known (need to read interfaces, conventions, content): dispatch `orchestrator-agents:reader`.

**Research tasks** (external library APIs, framework patterns, prior project decisions in `docs/`): dispatch `orchestrator-agents:researcher` directly.

**Analytical tasks** (questions, brainstorming, design): dispatch `orchestrator-agents:thinker` directly. Thinker resolves its own missing-context needs by dispatching `orchestrator-agents:reader`/`orchestrator-agents:researcher` itself — no orchestrator round-trip needed. (Every agent can nest-dispatch reader/researcher/thinker/reviewer this way; a `PreToolUse` hook, not agent-specific scoping, is what blocks nested writer/tester/verify/checker — see [dispatch-levels.md](dispatch-levels.md#teammate-vs-subagent-boundary).)
