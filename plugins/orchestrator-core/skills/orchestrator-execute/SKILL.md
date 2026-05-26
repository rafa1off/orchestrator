---
name: orchestrator-execute
description: "Start implementation after a plan has been approved. Use when the user gives the green light to begin building — phrases like \"go ahead\", \"looks good\", \"proceed\", \"approved\", \"start implementing\", \"begin implementation\", or \"execute the plan\". Also use when the user explicitly names a plan file path (e.g. .claude/plans/foo.md) and says to run, execute, or implement it. This skill drives the full execution lifecycle: dispatching reader/writer/tester/documenter agents in order, running checker+reviewer verification, and producing a final summary. Skip this skill when the user is still planning, writing a spec, brainstorming, or asking to read/review a plan without building."
---

# Orchestrator Execute

**Announce at start:** "Using orchestrator-execute to implement the plan."

---

## Step 1 — Load and Review

1. Read the plan file from `.claude/plans/`
2. Review critically — raise concerns before starting if:
   - A writer stage has no preceding reader stage and context is missing
   - A stage depends on a prior stage that was marked ✗ but the dependency isn't met
   - File paths are missing or ambiguous
3. Check for **Mode** field in the plan header:
   - `mode: team` → call `Skill("/orchestrator-core:orchestrator-team")` passing the plan file path, then **stop** — do not proceed to Step 2.
   - `mode: execute` or field absent → continue.
4. If clean: proceed to Step 2

---

## Step 2 — Create Tasks

Read the plan's Tasks and Stages sections. Tasks reflect **what is being done** — not which agent does it.

**For each work item** (reader, researcher, thinker, individual writer task, tester, documenter):
```
TaskCreate("[work description]")
```
Strip any "Stage N — [agent]:" prefix. Use only the work description.

Example: `"Stage 2 — writer: add rate limiting to api.py"` → `TaskCreate("add rate limiting to api.py")`

**For each verify checkpoint** (checker + reviewer pair), create **one** task:
```
TaskCreate("verify [scope] — checker + reviewer")
```
Checker and reviewer always run as an atomic pair — they share one task, not two.

Example: `"Stage 3a — checker / 3b — reviewer: scoped to api.py"` → `TaskCreate("verify api.py — checker + reviewer")`

**progress.md:** Create `.claude/pipeline/progress.md` only when the plan has 5+ stages or the work is explicitly expected to span multiple sessions. For normal plans, the task list alone is sufficient:

```markdown
# Pipeline Progress — [task name from plan Goal]

## Status
Step: [first stage]

## Completed
(none yet)

## Pending
- [ ] [work description — task 1]
- [ ] [work description — task 2]
- [ ] verify [step N scope] — checker + reviewer
...

## Key Decisions
(none yet)

## Open Issues
(none yet)
```

---

## Step 3 — Execute Stages

Work through stages in plan order. The 5 invariants are non-negotiable — they override anything in the plan.

### The 5 Invariants

1. **Read before write** — if a writer stage is reached without prior reader output in this session, run reader first.
2. **checker + reviewer always together** — dispatch both in the same message turn; never one before the other.
3. **One writer per overlapping file set** — serialize writers that share files; parallel only when file sets are disjoint.
4. **Max 2 verify rounds** — after 2 full checker+reviewer cycles with remaining findings, stop and surface to user.
5. **Plan mode blocks writes** — if plan mode is active, only reader/researcher/thinker may run.

---

### Session Registry

After every `Agent()` dispatch, save the returned `agent_id` in a working-memory map keyed by agent type. Before dispatching any agent, check the registry and the stage annotation to decide whether to reuse or spawn fresh.

**Dispatch decision:**

```
if registry[agent_type] exists AND stage is marked *(reuse: true)*:
    SendMessage(to: registry[agent_type], message: task_prompt)
else:
    agent_id = Agent(agent_type, task_prompt)
    registry[agent_type] = agent_id
```

**Default reuse policy:**

| Agent type | Default |
|---|---|
| reader | `reuse: true` — reader is called by nearly every stage; warm context pays off |
| checker | `reuse: false` always — haiku, one-shot, no multi-turn benefit |
| all others | follow the plan annotation; absent annotation = `false` |

**Staleness guard:** when loading a plan file, compare its path to the last-loaded path stored in working memory. If the path differs (new task boundary), clear all registry entries before proceeding.

```
if last_plan_path != current_plan_path:
    registry.clear()
    last_plan_path = current_plan_path
```

---

### reader

```
TaskUpdate(id, status="in_progress")
Agent(reader, "[instruction from plan stage]")
TaskUpdate(id, status="completed")
```

If progress.md exists: move stage to Completed with a one-line note on what was found.

---

### researcher

```
TaskUpdate(id, status="in_progress")
Agent(researcher, "[instruction from plan stage]")
TaskUpdate(id, status="completed")
```

---

### thinker

```
TaskUpdate(id, status="in_progress")
Agent(thinker, """
[context block]
[question or decision from plan stage]
""")
TaskUpdate(id, status="completed")
```

---

### writer

**Single task (one file or one logical unit):**

```
TaskUpdate(id, status="in_progress")
Agent(writer, """
## Context
[reader output and researcher findings relevant to this stage]

## Task
[instruction from plan stage]

## Files to modify
[exact paths from plan]
""")
TaskUpdate(id, status="completed")
```

**Multiple tasks with disjoint file sets (parallel):**

When the plan marks tasks as parallel (disjoint files), dispatch all writers in the same message turn and update all their task IDs:

```
TaskUpdate(task1_id, status="in_progress")
TaskUpdate(task2_id, status="in_progress")

Agent(writer, "## Context\n[...]\n## Task\n[task 1]\n## Files to modify\n[file1]")
Agent(writer, "## Context\n[...]\n## Task\n[task 2]\n## Files to modify\n[file2]")

// after both complete:
TaskUpdate(task1_id, status="completed")
TaskUpdate(task2_id, status="completed")
```

**Multiple tasks sharing a file (serialize):**

When tasks share a file, run writers sequentially — one per task, completing before starting the next.

---

### checker + reviewer

Checker and reviewer share the single verify checkpoint task. Always dispatch both in the same message turn.

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

**If either has findings:**
Send merged batch to writer:
```
## Batch Fixes Required

### Checker errors
[from checker-findings.json, or "none"]

### Reviewer issues
[from reviewer-findings.json, or "none"]
```

Re-verify (back to `rm -f` step). After **2 full rounds** with remaining findings: stop, surface all findings to user, ask for direction. Never continue silently.

---

### tester

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

### documenter

```
TaskUpdate(id, status="in_progress")
Agent(documenter, """
Changed public surface: [what changed]
Files modified: [list]
Update: [doc targets specified in plan]
""")
TaskUpdate(id, status="completed")
```

---

## Step 4 — Final Summary

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
