---
name: orchestrator
description: "Agent dispatch guide and routing protocol for all development work in this codebase. Load this skill at the start of every session — before any code change, bug fix, refactor, or documentation update of any size. It defines the 8-agent catalog (reader, researcher, writer, thinker, checker, reviewer, tester, documenter), the 5 core invariants that govern every task, and the flexible working loop. Always load before writing any code."
---

# Orchestrator

The main Claude Code session acts as orchestrator. Agents are tools — call them whenever you need their capability, as many times as needed, in whatever order makes sense for the task. There is no fixed pipeline.

---

## Agent Catalog

| Agent | Type | Model | When to call |
|-------|------|-------|--------------|
| Explore | readonly | haiku | **Broad codebase investigation** — "survey the repo", "find all usages of X", "where is Y defined", open-ended discovery spanning many files. Built-in subagent type — no `.claude/agents/explore.md` needed. Use `Agent(subagent_type="Explore", ...)`. |
| reader | readonly | haiku | Anytime you need to understand files before touching them. Can be called multiple times — e.g., once to map a module, again to inspect a specific file path mid-task. |
| researcher | readonly | sonnet | When the task involves external APIs or library patterns, or anything with prior decisions in `docs/`. |
| thinker | readonly | sonnet | Questions, analysis, architectural decisions, brainstorming. Safe to call anytime, including from plan mode. |
| writer | read+write | sonnet | Produce code changes from a context block. One active writer per overlapping file set — see invariants. |
| checker | readonly | haiku | Run after a meaningful write phase. Always paired with reviewer in the same message turn. |
| reviewer | readonly | sonnet | Run after a meaningful write phase. Always paired with checker in the same message turn. |
| tester | read+write | sonnet | Write unit tests and run the suite after reviewer approves. |
| documenter | read+write | sonnet | Update `docs/` and `CLAUDE.md` when a public API, env var, or module behavior changes. |

---

## Agent Contracts

Quick-reference for dispatching agents and reading their output. Canonical `## Input` / `## Output` definitions live in each agent's own file — this is the coordinator's read-only summary.

| Agent | Invoke with | Returns |
|-------|------------|---------|
| reader | task + file paths | `Relevant Files / Interfaces / Conventions / Entry Points / Test Files` — or `## Cannot Proceed` |
| researcher | task + research question | `Prior Decisions / API Reference / Approach / Caveats` |
| thinker | context block (reader + researcher output) + question | `Analysis / Brainstorming / Q&A` — or `## Context Request` |
| writer | `## Context` + `## Task` + `## Files to modify` (initial); `## Batch Fixes Required` (retry) | `## Modified Files` with exact paths |
| checker | writer's `## Modified Files` list; optional `pipeline` path for team tracks | `## Check Results` table; writes `<pipeline>/checker-findings.json` |
| reviewer | task context + `## Modified Files` list; optional `pipeline` path (reads diff itself via `git diff HEAD`) | `APPROVED` or `ISSUES` with `file:line`; writes `<pipeline>/reviewer-findings.json` |
| tester | task + changed files + what to test | `## Test Results` with written files + pass/fail table |
| documenter | changed surface description + modified files | `Updated:` list of changed doc files |

---

## Core Invariants

These rules hold regardless of task size, route, or mode. Never violate them.

1. **Read before write** — always invoke reader (or read files yourself for trivial changes) before calling writer on those files.
2. **Verify at checkpoints** — run checker + reviewer after a meaningful write phase, or as explicitly defined in the plan. They do not need to run after every individual writer invocation. When invoked, they always run together in the same message turn — never one before the other.
3. **One writer per overlapping file set** — serialize writers that share files. Two writers with disjoint file sets may run in parallel.
4. **Max 2 verify rounds** — if findings remain after 2 full checker+reviewer cycles, stop and escalate to the user. Never silently loop.
5. **Plan mode blocks all writes** — in plan mode, only reader, researcher, and thinker may run. writer, checker, reviewer, tester, and documenter are blocked until after `ExitPlanMode`.

---

## How to Work

There is no required sequence. Reason about what you need and call agents accordingly.

**The general pattern for most tasks:**

Understand → Write → Verify → (repeat until clean or escalate) → Test → Document

The actual loop is flexible:

- Call reader once upfront to map the module, then again mid-task if you discover an unfamiliar file path. If reader returns a `## Cannot Proceed` block, run Explore first to discover file paths, then re-invoke reader with that list.
- Call researcher only when the implementation requires library knowledge you don't have
- Call thinker when you hit a decision point — architectural tradeoff, ambiguous requirement, unfamiliar pattern
- Call writer to produce changes; dispatch checker + reviewer when the write phase for a task or plan step is complete
- If verify finds issues, call writer again with the merged batch, then re-verify — up to 2 total rounds
- Call tester after the verify loop clears
- Call documenter at the end if the task changed any public surface

**For purely analytical tasks** (questions, brainstorming, design review): call thinker directly. If thinker needs context it returns a `## Context Request` block with `Needed:`, `For reader:`, `For researcher:`, and `Why:` fields. Dispatch the requested agents in parallel, then re-invoke thinker with their output appended to the original prompt. Thinker may only emit one Context Request per invocation.

**For trivial tasks** (single file, ≤15 lines changed, no new function signatures, no new dependencies): read the file directly, edit inline, then spawn checker to verify.

**Calling the same agent more than once is normal:**

```
# First call — map the module before writing
Agent(reader, "Map the [module] module. Task: [task description].")

# ... writer produces changes ...

# Second call — inspect test fixture structure after writer's changes
Agent(reader, "Find which fixtures exist for [module] in tests/.")
```

---

## Parallel Dispatch Rules

- **Readonly agents** (reader, researcher, thinker, checker, reviewer) — unlimited parallel dispatch
- **writer, tester, documenter** — one active at a time per overlapping file set
- **checker + reviewer** — when invoked, always dispatched together in the same message turn, never one before the other

**Example — multiple readonly agents at once:**
```
Agent(reader,     "map module X")
Agent(researcher, "find library pattern Y")
Agent(thinker,    "analyze tradeoff Z")
```

All three fire simultaneously. Wait for all before acting on their outputs.

---

## Verification Loop

When checker + reviewer are invoked:

**1 — Clear stale findings:**
```bash
rm -f .claude/pipeline/checker-findings.json .claude/pipeline/reviewer-findings.json
```

**2 — Dispatch checker + reviewer in the same message turn:**
```
Agent(checker,  "Run scoped checks. Modified files: [list from writer]")
Agent(reviewer, "[task context]")
```

**3 — Merge findings** after both complete:
```bash
cat .claude/pipeline/checker-findings.json
cat .claude/pipeline/reviewer-findings.json
```

If both PASS/APPROVED → continue (tester, documenter, or done).

If either has findings → send merged batch to writer:
```
## Batch Fixes Required

### Checker errors
[from checker-findings.json, or "none"]

### Reviewer issues
[from reviewer-findings.json, or "none"]
```

**4 — Re-verify:** go back to step 1. After **2 full rounds** with remaining findings: surface all findings to the user and ask for direction. Never continue silently.

---

## Plan Mode — Two-Phase Execution

When plan mode is active (system prompt explicitly states it):

### Stage compatibility

| Stage | Plan mode | Execute mode |
|-------|-----------|--------------|
| reader | ✅ compatible | ✅ compatible |
| researcher | ✅ compatible | ✅ compatible |
| thinker | ✅ compatible | ✅ compatible |
| writer | ❌ BLOCKED | runs normally |
| checker | ❌ BLOCKED | runs normally |
| reviewer | ❌ BLOCKED | runs normally |
| tester | ❌ BLOCKED | runs normally |
| documenter | ❌ BLOCKED | runs normally |

### Phase 1 — Plan (in plan mode)

1. Run reader + researcher as needed.
2. Invoke thinker with context block: produce a plan listing exact files to modify, approach per file, expected test cases, risks.
3. Write plan to plan file.
4. Call `ExitPlanMode`.

Even for trivial tasks: write a one-line plan and exit plan mode. If plan mode activates mid-task: stop, write gathered context to the plan file, call `ExitPlanMode`.

### Phase 2 — Execute (after approval)

Read the plan file, reconstruct context, invoke writer and proceed through the loop.

---

## Task List Integration

For any task involving more than one agent, create tasks upfront. Skip for trivial path.

```
TaskCreate("reader [+ researcher if needed]")
TaskCreate("writer")
TaskCreate("checker + reviewer")
TaskCreate("tester")      // only if planned
TaskCreate("documenter")  // only if planned
```

Before each stage: `TaskUpdate(id, status="in_progress")`
After each stage: `TaskUpdate(id, status="completed")`

Tasks are session-scoped. Use `progress.md` for cross-session continuity.

---

## Progress Artifact

For long tasks, maintain `.claude/pipeline/progress.md`. Create it when the task spans more than one session or the plan has 5+ stages. Skip for everything else — the task list alone is sufficient.

```markdown
# Pipeline Progress — [task name]

## Status
Step: [current]

## Completed
- [x] reader — found N relevant files
- [x] writer — modified file-a.py, file-b.py

## Pending
- [ ] checker + reviewer
- [ ] tester

## Key Decisions
- [rationale that drove an agent call or approach choice]

## Open Issues
- [escalated or deferred items]
```

---

## Integration-Owned Files

Never touched by parallel feature writers. A serial integration step runs after all feature writers complete.

| File pattern | Why |
|---|---|
| `pyproject.toml` / `package.json` / `go.mod` / `Cargo.toml` | Dependency additions conflict |
| Lock files (`uv.lock`, `package-lock.json`, `go.sum`, `Cargo.lock`) | Always regenerated; writers never run install |
| Shared test fixtures / `conftest.py` | Parallel edits conflict |

---

## Final Summary

```
## Done

**Task:** [original task]
**Status:** ✅ Done / ⚠️ Escalated

**Changes:**
- [file] — [what changed]

**Tests:** [N new, all passing / N failing]
**Docs:** [updated / not needed]
**Review:** APPROVED / [open issues]
```
