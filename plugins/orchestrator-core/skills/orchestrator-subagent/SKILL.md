---
name: orchestrator-subagent
description: "Execute an approved orchestrator plan by dispatching the 8 specialized agents in sequence. Called automatically by orchestrator-execute when the user selects subagent mode. Can also be invoked directly when a plan path is known and subagent execution is already chosen. Drives the full agent dispatch loop — reader, researcher, writer, checker+reviewer, tester, documenter — enforcing the 5 invariants. Skip this skill when the user is still planning or when team mode was selected."
---

# Orchestrator Subagent

**Announce at start:** "Using orchestrator-subagent to dispatch agents and implement the plan."

---

## Step 1 — Load Plan

Read the plan file (from `.claude/plans/` or as provided). Tasks should already exist in the task list from `orchestrator-execute`. If not, create them now from the plan's `## Tasks` section before proceeding.

---

## Step 2 — Stage Mapping

Map each stage type in the plan to the agent(s) that handle it:

| Stage label | Agent(s) |
|---|---|
| Research | `reader`; add `researcher` if external APIs or `docs/` referenced |
| Implement | `writer` — one per task; parallel when files are disjoint |
| Verify | `checker` + `reviewer` — always both, same message turn |
| Test | `tester` |
| Document | `documenter` |

Read the plan's `## Tasks` and `## Explanation` sections to understand ordering and dependencies before dispatching.

---

## Step 3 — Session Registry

After every `Agent()` dispatch, save the returned `agent_id` in a working-memory map keyed by agent type. Before dispatching any agent, check the registry and decide whether to reuse or spawn fresh.

**Dispatch decision:**

```
if registry[agent_type] exists AND stage benefits from warm context:
    SendMessage(to: registry[agent_type], message: task_prompt)
else:
    agent_id = Agent(agent_type, task_prompt)
    registry[agent_type] = agent_id
```

**Default reuse policy:**

| Agent type | Default |
|---|---|
| reader | reuse — called by nearly every stage; warm context pays off |
| checker | never reuse — haiku, one-shot, no multi-turn benefit |
| all others | reuse when called multiple times within the same plan |

**Staleness guard:** when loading a plan file, compare its path to the last-loaded path stored in working memory. If the path differs, clear all registry entries before proceeding.

---

## Step 4 — Execute Stages

Work through the plan's tasks in order, following the 5 invariants. Mark each task `in_progress` before dispatching and `completed` after.

### The 5 Invariants

1. **Read before write** — if an Implement stage is reached without prior Research output in this session, run reader first.
2. **checker + reviewer always together** — dispatch both in the same message turn; never one before the other.
3. **One writer per overlapping file set** — serialize writers that share files; parallel only when file sets are disjoint.
4. **Max 2 verify rounds** — after 2 full checker+reviewer cycles with remaining findings, stop and surface to user.
5. **Plan mode blocks writes** — if plan mode is active, only reader/researcher/thinker may run.

---

### Research stage

```
TaskUpdate(id, status="in_progress")
Agent(reader, "[what to map — from plan context or Explanation]")
// if external APIs or docs/ involved:
Agent(researcher, "[what to find]")
TaskUpdate(id, status="completed")
```

---

### Implement stage

**Single task:**

```
TaskUpdate(id, status="in_progress")
Agent(writer, """
## Context
[reader output and researcher findings relevant to this stage]

## Task
[work item description from plan]

## Files to modify
[exact paths from plan]
""")
TaskUpdate(id, status="completed")
```

**Multiple tasks with disjoint files (parallel):**

```
TaskUpdate(task1_id, status="in_progress")
TaskUpdate(task2_id, status="in_progress")

Agent(writer, "## Context\n[...]\n## Task\n[task 1]\n## Files to modify\n[file1]")
Agent(writer, "## Context\n[...]\n## Task\n[task 2]\n## Files to modify\n[file2]")

// after both complete:
TaskUpdate(task1_id, status="completed")
TaskUpdate(task2_id, status="completed")
```

**Multiple tasks sharing a file:** run writers sequentially — one completes before the next starts.

---

### Verify stage

Always clear stale findings before dispatching, then dispatch checker and reviewer in the **same message turn**.

```bash
rm -f .claude/pipeline/checker-findings.json .claude/pipeline/reviewer-findings.json
```

```
TaskUpdate(verify_id, status="in_progress")

Agent(checker,  "Run scoped checks. Modified files: [list from writer output]")
Agent(reviewer, "[task context and summary of what writer changed]")
```

After both complete:

```bash
cat .claude/pipeline/checker-findings.json
cat .claude/pipeline/reviewer-findings.json
```

**If both PASS/APPROVED:**
```
TaskUpdate(verify_id, status="completed")
```
Continue to next stage.

**If either has findings** — send merged batch to writer:
```
## Batch Fixes Required

### Checker errors
[from checker-findings.json, or "none"]

### Reviewer issues
[from reviewer-findings.json, or "none"]
```

Re-verify (back to `rm -f` step). After **2 full rounds** with remaining findings: stop, surface all findings to the user, ask for direction. Never continue silently.

---

### Test stage

```
TaskUpdate(id, status="in_progress")
Agent(tester, """
Task: [description from plan]
Changed files: [list]
Write and run tests for: [what the plan specifies]
""")
TaskUpdate(id, status="completed")
```

---

### Document stage

```
TaskUpdate(id, status="in_progress")
Agent(documenter, """
Changed public surface: [what changed]
Files modified: [list]
Update: [doc targets from plan or CLAUDE.md conventions]
""")
TaskUpdate(id, status="completed")
```

---

## Step 5 — Final Summary

```
## Done

**Task:** [original task from plan Goal]
**Status:** ✅ Done / ⚠️ Escalated

**Changes:**
- [file] — [what changed]

**Tests:** [N new, all passing / N failing / not applicable]
**Docs:** [updated / not needed]
**Review:** APPROVED / [open issues]
```
