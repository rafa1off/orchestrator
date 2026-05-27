---
name: orchestrator-execute
description: "Start implementation after a plan has been approved. Use when the user gives the green light to begin building — phrases like \"go ahead\", \"looks good\", \"proceed\", \"approved\", \"start implementing\", \"begin implementation\", or \"execute the plan\". Also use when the user explicitly names a plan file path (e.g. .claude/plans/foo.md) and says to run, execute, or implement it. Creates tasks from the plan and asks how to proceed: subagent (sequential dispatch in this session) or team (parallel write tracks). Skip this skill when the user is still planning, writing a spec, brainstorming, or asking to read/review a plan without building."
---

# Orchestrator Execute

**Announce at start:** "Using orchestrator-execute to set up tasks and select execution mode."

---

## Step 1 — Load and Review

1. Read the plan file from `.claude/plans/`
2. Review critically — raise concerns before starting if:
   - File paths are missing or ambiguous
   - Tasks section is empty or missing
3. If clean: proceed to Step 2

---

## Step 2 — Create Tasks

Read the plan's `## Tasks` section. Call `TaskCreate` for **each numbered item, exactly as written** — do not rename, rephrase, or add agent names. Tasks describe *what changes*, not *which agent makes the change*.

```
TaskCreate("[item 1 text from plan Tasks section]")
TaskCreate("[item 2 text from plan Tasks section]")
TaskCreate("verify [scope] — checker + reviewer")   // one per verify checkpoint listed in Tasks
...
```

Do this **before** any mode analysis. Only after all tasks exist, proceed to Step 3.

---

## Step 3 — Determine Mode

Analyze the plan's `## Files` and `## Tasks` sections:

Count independent implement groups — sets of files with no overlap between groups.

- **subagent** — one sequential chain: research → implement → verify → test. Recommended for most plans.
- **team** — 3 or more fully disjoint implement groups (no file appears in more than one group). Recommended when parallel write tracks would meaningfully reduce wall-clock time.

---

## Step 4 — Ask the User

Present the mode choice with the recommendation:

```
Tasks created. How should this plan be executed?

1. subagent [recommended / not recommended] — sequential agent dispatch in this session
2. team [recommended / not recommended] — parallel write tracks via orchestrator-team

Recommendation: [subagent | team] — [one sentence reason based on plan structure]
```

Wait for user selection before proceeding.

---

## Step 5 — Route

- User selects **subagent** → `Skill("/orchestrator-core:orchestrator-subagent")`
- User selects **team** → `Skill("/orchestrator-core:orchestrator-team")`
