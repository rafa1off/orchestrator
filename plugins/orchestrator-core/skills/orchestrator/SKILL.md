---
name: orchestrator
description: "Agent dispatch guide and routing protocol for all development work in this codebase. Load this skill at the start of every session — before any code change, bug fix, refactor, or documentation update of any size. It defines the 6-agent catalog (reader, researcher, thinker, writer, verify, tester), the 3 core invariants that govern every task, and the flexible working loop. Always load before writing any code."
---

# Orchestrator

The main Claude Code session acts as orchestrator. Agents are tools — call them whenever you need their capability, as many times as needed, in whatever order the task requires. There is no fixed pipeline.

---

## Agent Catalog

| Agent | Model | Type | When to call |
|-------|-------|------|--------------|
| Explore | haiku | readonly | Broad codebase discovery — "survey the repo", "find all usages of X". Built-in; use `Agent(subagent_type="Explore", ...)` |
| reader | haiku | readonly | Map files, interfaces, and conventions before writing. Call multiple times as new paths surface. |
| researcher | sonnet | readonly | External APIs, library patterns, prior decisions in `docs/`. |
| thinker | sonnet | readonly | Analysis, brainstorming, architectural decisions. Isolates verbose reasoning from main context. |
| writer | sonnet | read+write | Produce code changes from a context block. |
| verify | sonnet | readonly | Lint + typecheck + diff review in one pass. Always `background: true`. Never reused — always spawn fresh. |
| tester | sonnet | read+write | Write and run tests after verify approves. |

---

## Agent Contracts

| Agent | Invoke with | Returns |
|-------|------------|---------|
| reader | task + file paths | `Relevant Files / Interfaces / Conventions / Entry Points / Test Files` — or `## Cannot Proceed` |
| researcher | task + research question | `Prior Decisions / API Reference / Approach / Caveats` |
| thinker | context block + question | `Analysis / Brainstorming / Q&A` — or `## Context Request` |
| writer | `## Context` + `## Task` + `## Files to modify` (initial); `## Batch Fixes Required` (retry) | `## Modified Files` with exact paths |
| verify | modified files list + pipeline path | `## Verify Results`; writes `<pipeline>/verify-findings.json` |
| tester | task + changed files + what to test | `## Test Results` with written files + pass/fail table |

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
- Dispatch all writers simultaneously with `background: true` (disjoint files = no conflict).
- Dispatch verify + tester per track in parallel (4 agents at once for 2 tracks), each scoped to its pipeline path.
- After all tracks clear: serial integration pass on shared files (`pyproject.toml`, lock files, `conftest.py`).

### Level 3 — Background sessions (3+ tracks OR >15 files total)

- Dispatch each track as a background session: `claude --bg "Implement track-a of .claude/plans/<plan>.md. Pipeline: .claude/pipeline/track-a."`
- Each background session gets its own worktree and runs the full loop (read → write → verify → test) independently.
- Each session writes status when done: `{"track":"track-a","status":"done","modified":["file.py"]}`
- Status values: `"working"` | `"done"` | `"escalated"` | `"failed"`
- Poll until all tracks report `done` or `escalated`.
- After all tracks complete: serial integration pass.

---

## Parallel Dispatch Rules

- **reader + researcher + thinker** — unlimited parallel (all readonly)
- **verify + tester** — always dispatched together in the same message turn after a write phase
- **writers** — parallel only when file sets are fully disjoint
- **verify** — never reused; always spawn fresh

**Example — parallel readonly agents:**
```
Agent(reader,     "map module X")
Agent(researcher, "find library pattern Y")
Agent(thinker,    "analyze tradeoff Z")
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
Agent(verify, "Modified files: [list]. Pipeline: .claude/pipeline/[track if multi]")
Agent(tester, "Task: [desc]. Changed files: [list]. Test: [what]")
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

After each `Agent()` dispatch, save the returned `agent_id` in working memory keyed by type. Before re-dispatching:

- If `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`: use `SendMessage(to: saved_id)` to resume the warm agent (cache hit on file content).
- Otherwise: spawn fresh (system prompts still cache across calls).

**Two rules:**
1. **reader** — always try to reuse (called most frequently; highest cache value).
2. **verify** — never reuse; always spawn fresh.

---

## Routing Special Cases

**Trivial tasks** (single file, ≤15 lines, no new signatures): read the file directly, edit inline, spawn verify only.

**Analytical tasks** (questions, brainstorming, design): dispatch thinker directly. If thinker returns `## Context Request` with `Needed:` / `For reader:` / `For researcher:` / `Why:` fields — dispatch requested agents in parallel, re-invoke thinker with their output.

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
