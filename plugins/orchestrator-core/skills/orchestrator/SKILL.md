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
| Explore | haiku | readonly | Broad codebase discovery — "survey the repo", "find all usages of X". Built-in; use `Agent(subagent_type="Explore", ...)` |
| orchestrator-core:reader | haiku | readonly | Map files, interfaces, and conventions before writing. Call multiple times as new paths surface. |
| orchestrator-core:researcher | sonnet | readonly | External APIs, library patterns, prior decisions in `docs/`. |
| orchestrator-core:thinker | sonnet | readonly | Analysis, brainstorming, architectural decisions. Isolates verbose reasoning from main context. |
| orchestrator-core:writer | sonnet | read+write | Produce code changes from a context block. |
| orchestrator-core:checker | haiku | readonly | Lint + typecheck + build checks only — no diff review. Ad-hoc quality gate; call any time. |
| orchestrator-core:reviewer | sonnet | readonly | Diff review only — no lint/typecheck. Use for PR reviews or reviewing a change set after checker passes. |
| orchestrator-core:verify | sonnet | readonly | Lint + typecheck + diff review in one pass. Post-write loop only. Always `background: true`. Never reused — always spawn fresh. |
| orchestrator-core:tester | sonnet | read+write | Write and run tests after verify approves. |

---

## Agent Contracts

| Agent | Invoke with | Returns |
|-------|------------|---------|
| orchestrator-core:reader | task + file paths | `Relevant Files / Interfaces / Conventions / Entry Points / Test Files` — or `## Cannot Proceed` |
| orchestrator-core:researcher | task + research question | `Prior Decisions / API Reference / Approach / Caveats` |
| orchestrator-core:thinker | context block + question | `Analysis / Brainstorming / Q&A` — or `## Context Request` |
| orchestrator-core:writer | `## Context` + `## Task` + `## Files to modify` (initial); `## Batch Fixes Required` (retry) | `## Modified Files` with exact paths |
| orchestrator-core:checker | files to check (optional) | `## Check Results` table; raw output on failure |
| orchestrator-core:reviewer | task context + modified files list | `## Review Results`; issues list or APPROVED |
| orchestrator-core:verify | modified files list + pipeline path | `## Verify Results`; writes `<pipeline>/verify-findings.json` |
| orchestrator-core:tester | task + changed files + what to test | `## Test Results` with written files + pass/fail table |

---

## Core Invariants

These rules hold regardless of task size or route. Never violate them.

1. **Read before write** — invoke reader (or read files directly for trivial changes) before calling writer on those files.
2. **Verify after write, max 2 rounds** — after any write phase, dispatch verify. If findings: writer fixes, verify reruns once. Second round with remaining findings: escalate to user. Never silently loop.
3. **Serialize writers on overlapping files** — one active writer per overlapping file set. Writers with fully disjoint file sets may run in parallel.

---

## Dispatch Levels

**Routing decision:**
```
Plan has 1 track?           → Level 1
2–3 tracks AND ≤15 files?   → Level 2
3+ tracks OR >15 files?     → Level 3
```

### Level 1 — Single track (default)

```
Wave 1 (parallel):  reader [+ researcher if external APIs needed] [+ thinker if design question]
Wave 2 (inline):    orchestrator synthesizes → presents plan → user approves
Wave 3:             writer
Wave 4 (parallel):  verify + tester
Wave 5 (if needed): writer fixes → verify reruns (once max)
```

### Level 2 — Multi-track (2–3 independent file sets, ≤15 files total)

- Assign each track a pipeline path: `.claude/pipeline/track-a/`, `.claude/pipeline/track-b/`, etc.
- Dispatch all writers simultaneously with `background: true` and `isolation: "worktree"` (disjoint files = no conflict; worktree prevents cross-track interference):
  ```
  Agent({ description: "Writer: track-a — [task]", subagent_type: "orchestrator-core:writer", background: true, isolation: "worktree", prompt: "## Context\n..." })
  Agent({ description: "Writer: track-b — [task]", subagent_type: "orchestrator-core:writer", background: true, isolation: "worktree", prompt: "## Context\n..." })
  ```
- Dispatch verify + tester per track in parallel (4 agents at once for 2 tracks), each scoped to its pipeline path.
- After all tracks clear: serial integration pass on shared files (`pyproject.toml`, lock files, `conftest.py`).

### Level 3 — Teammate sessions (3+ tracks OR >15 files total)

- Dispatch each track as a teammate via `TeamCreate` — one teammate per track, each with its own worktree:
  ```
  TeamCreate({ name: "track-a", prompt: "Implement track-a of .claude/plans/<plan>.md. Pipeline: .claude/pipeline/track-a." })
  TeamCreate({ name: "track-b", prompt: "Implement track-b of .claude/plans/<plan>.md. Pipeline: .claude/pipeline/track-b." })
  ```
- Each teammate runs the full loop (read → write → verify → test) independently.
- Each teammate writes status when done: `{"track":"track-a","status":"done","modified":["file.py"]}`
- Status values: `"working"` | `"done"` | `"escalated"` | `"failed"`
- Wait for all teammates to report `done` or `escalated` (via `TeammateIdle` hook or polling).
- After all tracks complete: serial integration pass.

---

## Parallel Dispatch Rules

- **orchestrator-core:reader + orchestrator-core:researcher + orchestrator-core:thinker** — unlimited parallel (all readonly)
- **orchestrator-core:checker + orchestrator-core:reviewer** — may run in parallel; ad-hoc, no pipeline dependency
- **orchestrator-core:verify + orchestrator-core:tester** — always dispatched together in the same message turn after a write phase
- **orchestrator-core:writer** — parallel only when file sets are fully disjoint
- **orchestrator-core:verify** — never reused; always spawn fresh; post-write loop only

**Example — parallel readonly agents:**
```
Agent({ description: "Reader: map module X",              subagent_type: "orchestrator-core:reader",     prompt: "Task: [desc]. Files: [paths]." })
Agent({ description: "Researcher: find library pattern Y", subagent_type: "orchestrator-core:researcher", prompt: "Task: [desc]. Research question: [question]." })
Agent({ description: "Thinker: analyze tradeoff Z",        subagent_type: "orchestrator-core:thinker",   prompt: "Task: [desc]. Question: [question]." })
```

---

## Verify Loop

**1 — Clear stale findings:**
```bash
rm -f .claude/pipeline/verify-findings.json
# or for multi-track:
rm -f .claude/pipeline/<track>/verify-findings.json
```

**2 — Dispatch verify + tester in the same message turn:**
```
Agent({ description: "Verify: post-write pass",        subagent_type: "orchestrator-core:verify", background: true, prompt: "Modified files: [list]. Pipeline: .claude/pipeline/[track if multi]" })
Agent({ description: "Tester: write and run tests",    subagent_type: "orchestrator-core:tester",          prompt: "Task: [desc]. Changed files: [list]. Test: [what]" })
```

**3 — Read findings after both complete:**
```bash
cat .claude/pipeline/verify-findings.json
```

**4 — Branch on result:**
- `status: PASS` + `review: APPROVED` → done
- `FAIL` or `ISSUES` → send batch to writer:

```
## Batch Fixes Required

### Verify errors
[from verify-findings.json]
```

**5 — Re-verify:** back to step 1. After **2 full rounds** with remaining findings: surface all findings to the user and ask for direction.

---

## Session Registry

Before any `Agent()` dispatch, check working memory for a saved `agent_id` of that type:

1. **Found** → `SendMessage(to: saved_id)` — resumes the warm agent (cache hit on file content, no cold-start overhead).
2. **Not found** → `Agent(...)` → save the returned `agent_id` keyed by type.

**Hard exception:** `orchestrator-core:verify` — always step 2. Never reuse a verify agent; always spawn fresh.

**Best reuse target:** `orchestrator-core:reader` — called most frequently; highest cache value from file content.

---

## Routing Special Cases

**Trivial tasks** (single file, ≤15 lines, no new signatures): read the file directly, edit inline, spawn `orchestrator-core:verify` only.

**Analytical tasks** (questions, brainstorming, design): dispatch `orchestrator-core:thinker` directly. If thinker returns `## Context Request` with `Needed:` / `For reader:` / `For researcher:` / `Why:` fields — dispatch requested agents in parallel, re-invoke thinker with their output.

---

## Final Summary

```
## Done

**Task:** [original task]
**Status:** Done / Escalated

**Changes:**
- [file] — [what changed]

**Tests:** [N new, all passing / N failing]
**Verify:** APPROVED / [open issues]
```
