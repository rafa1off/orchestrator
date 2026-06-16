---
name: orchestrator-plan
description: "Use this skill when the user wants to plan out a multi-step coding task before writing any code. Triggers on: \"plan this out\", \"write up a plan\", \"map out how we'd\", \"let's plan\", \"before we start\", or any request to design/outline an implementation spanning multiple files, schema changes, API additions, or refactors. Creates a structured plan saved to .claude/plans/ for later execution. After approval, dispatches directly following the orchestrator L1/L2/L3 pattern. Use when the user is thinking ahead — not yet implementing, but scoping what needs to change and in what order."
---

# Orchestrator Plan

**Announce at start:** "Using orchestrator-plan to write the implementation plan."

---

## Step 1 — Enter Plan Mode

Check whether plan mode is already active by inspecting your system context: if the plan mode read-only enforcement preamble and ExitPlanMode protocol footer are already present (session was started with `--permission-mode plan`, `/plan` prefix, or Shift+Tab before the prompt), **skip this step** — the plan file path is already specified and calling `EnterPlanMode` again is unnecessary.

Otherwise, call `EnterPlanMode`. The session is now read-only — file edits are blocked until the plan is approved.

---

## Step 2 — Research

Run reader and researcher **in parallel** to gather context. Skip researcher if the task is purely internal (no external library APIs, no prior decisions in `docs/`).

```
Agent({ description: "Reader: map modules for [task]",      subagent_type: "orchestrator-agents:reader",     prompt: "Task: [task]. Return files, interfaces, entry points, conventions." })
Agent({ description: "Researcher: prior decisions for [task]", subagent_type: "orchestrator-agents:researcher", prompt: "Task: [task]. Find external patterns or prior decisions in docs/." })  // omit if not needed
```

---

## Step 3 — Write the Plan

Using the research from Step 2, reason directly and write the plan. You are the orchestrator — you have the full context. Synthesize what reader and researcher returned into the format below.

Write the plan to **the file path specified in the plan mode system message** — that is the path ExitPlanMode will read. Do not write to `.claude/plans/` here; Write is blocked in plan mode.

Use this content format:

```markdown
# [Feature Name] — Orchestrator Plan

**Goal:** [one sentence]
**Date:** YYYY-MM-DD

---

## Explanation

[Claude writes a prose explanation of this specific plan: what was found during research, what the implementation approach is, why it's structured this way, what dependencies or constraints matter, and any tradeoffs made. This is the plan's own rationale — written for a human reviewer to understand what's being done and why before approving.]

## Files

| Action | Path | Purpose |
|--------|------|---------|
| Create | `path/to/file.py` | ... |
| Modify | `path/to/existing.py` | ... |

## Tasks

List every deliverable — what needs to be built, changed, or tested. Name them after *what changes*, not *who makes the change*. Each numbered item becomes one `TaskCreate` call at the start of execution.

1. [what to build/change] — `file1.py`
2. [what to build/change] — `file2.py`
3. verify [scope] — `checker` + `reviewer` (or `verify` if post-write loop)
4. [what to test] — `tests/test_foo.py`
```

---

## Step 4 — Present for Approval

Call `ExitPlanMode`. Claude Code reads the plan file from Step 3 and presents it to the user. The user chooses to approve (and picks a permission mode) or keep planning.

> **When approval arrives — whether in the same turn (hook path) or as a new turn (dialog path) — proceed immediately to Step 5. Do not wait for further user input.**

---

## Step 5 — Archive and Execute

**The plan was just approved. Execute this step now — no further user input is needed.**

1. Write the plan to `.claude/plans/YYYY-MM-DD-<feature-name>.md`. The system plan file from Step 3 is session-scoped and will not survive a new session — this archive is what makes deferred or repeated execution possible, and what gets committed to git as a decision record.
2. Create tasks from the plan's `## Tasks` section — call `TaskCreate` for each numbered item in order, using the item text as the title and `status: "pending"`. Pass each task's ID to the agent dispatched for that task via `taskId: [id]` in the prompt. Agents own all status transitions — they mark themselves `in_progress` on invocation and `completed` on return. Do not call `TaskUpdate` from the orchestrator.
3. Determine the dispatch level from the plan's `## Tasks` section:
   ```
   Plan has 1 track?           → Level 1
   2–3 tracks AND ≤15 files?   → Level 2
   3+ tracks OR >15 files?     → Level 3
   ```
4. Dispatch following the level:
   - **Level 1** — single track: run the agent loop sequentially in this session (reader → writer → verify + tester).
   - **Level 2** — 2–3 independent tracks, ≤15 files, disjoint file sets: dispatch all writers simultaneously with `background: true`; each writer edits its track directly in the working tree. Assign each track a pipeline path (`.claude/pipeline/track-a/`, etc.). After all writers complete, dispatch verify + tester per track in parallel. Serial integration pass on shared files last.
   - **Level 3a (default)** — 3+ independent tracks or >15 files, no cross-track coordination needed: use `Workflow(...)` to pipeline across tracks (read → write → verify per track). After the workflow completes, serial integration pass on shared files.
   - **Level 3b** — 3+ tracks where tracks need to share findings or coordinate: use `TeamCreate` for each track; wait for all to report `done` or `escalated`; serial integration pass last.

   Do not call `orchestrator-execute` or `orchestrator-subagent`.
