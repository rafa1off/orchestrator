---
name: orchestrator-execute
description: Execute an orchestrator-native plan from .claude/plans/, dispatching agents per the plan's agent map and enforcing the 5 invariants throughout.
when_to_use: Use after orchestrator-plan has produced a plan document. Handles TaskCreate, agent dispatch, the verification loop, and the final summary.
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
3. If clean: proceed to Step 2

---

## Step 2 — Create Tasks

Read the plan's Stages list. Create one task per stage using the **exact stage description from the plan**:

```
TaskCreate("Stage N — [agent]: [exact description from plan]")
```

For `Stage Na — checker` and `Stage Nb — reviewer` entries, create **two separate tasks** — one for each:

```
TaskCreate("Stage Na — checker: [exact scope from plan]")
TaskCreate("Stage Nb — reviewer: [exact scope from plan]")
```

If the plan has 3+ stages, also create `.claude/pipeline/progress.md`:

```markdown
# Pipeline Progress — [task name from plan Goal]

## Status
Step: Stage 1

## Completed
(none yet)

## Pending
- [ ] Stage 1 — [agent]: [exact description from plan]
- [ ] Stage 2 — [agent]: [exact description from plan]
- [ ] Stage 3a — checker: [exact scope from plan]
- [ ] Stage 3b — reviewer: [exact scope from plan]
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

### reader

```
TaskUpdate(id, status="in_progress")
Agent(reader, "[instruction from plan stage]")
TaskUpdate(id, status="completed")
```

Update `progress.md`: move stage to Completed with a one-line note on what was found.

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

Serialize if file sets overlap with another active writer stage.

```
TaskUpdate(id, status="in_progress")
Agent(writer, """
## Context
[reader output relevant to this stage]

## Task
[instruction from plan stage]

## Files to modify
[exact paths from plan]
""")
TaskUpdate(id, status="completed")
```

---

### checker + reviewer

Always dispatched together in the same message turn.

```bash
rm -f .claude/pipeline/checker-findings.json .claude/pipeline/reviewer-findings.json
```

```
TaskUpdate(checker_id, status="in_progress")
TaskUpdate(reviewer_id, status="in_progress")

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
TaskUpdate(checker_id, status="completed")
TaskUpdate(reviewer_id, status="completed")
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
