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
Agent(orchestrator-core:reader,     "Map the relevant modules for: [task]. Return files, interfaces, entry points, conventions.")
Agent(orchestrator-core:researcher, "Find external patterns or prior decisions in docs/ relevant to: [task].")  // omit if not needed
```

---

## Step 3 — Write the Plan

Using the research from Step 2, reason directly and write the plan. You are the orchestrator — you have the full context. Synthesize what reader and researcher returned into the format below.

Write the plan to **the file path specified in the plan mode system message** — that is the path ExitPlanMode will read. Do not write to `.claude/plans/` here; Write is blocked in plan mode.

Use this content format:

```markdown
# [Feature Name] — Orchestrator Plan

> **For execution:** Use `orchestrator-execute` to run this plan.

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
3. verify [scope] — checker + reviewer
4. [what to test] — `tests/test_foo.py`
```

---

## Step 4 — Present for Approval

Call `ExitPlanMode`. Claude Code reads the plan file from Step 3 and presents it to the user. The user chooses to approve (and picks a permission mode) or keep planning.

---

## Step 5 — Archive and Execute

After the user approves (plan mode is now exited, Write is unblocked):

1. Write the plan to `.claude/plans/YYYY-MM-DD-<feature-name>.md`. The system plan file from Step 3 is session-scoped and will not survive a new session — this archive is what makes deferred or repeated execution possible, and what gets committed to git as a decision record.
2. Dispatch directly following the orchestrator guide's dispatch levels:
   - **Level 1** — single-track plan (one logical sequence of tasks, no independent write tracks): run the agent loop sequentially in this session.
   - **Level 2** — 2–3 independent tracks (disjoint file sets, tasks that could run in parallel): fan out with `SendMessage` per track within this session, then consolidate.
   - **Level 3** — 3+ independent tracks or >15 files changed: use `TeamCreate` to launch parallel teammate sessions, one per track.

   Do not call `orchestrator-execute` or `orchestrator-subagent`.
