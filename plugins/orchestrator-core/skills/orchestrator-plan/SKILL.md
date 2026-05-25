---
name: orchestrator-plan
description: "Write an orchestrator-native implementation plan before starting any multi-step development task. Use this skill whenever a task touches multiple files, introduces new function signatures, adds dependencies, or requires coordinating reader → writer → verify stages. Maps each step to specific agents, respects the 5 invariants, and saves a decision-record plan to .claude/plans/ ready for orchestrator-execute. When in doubt whether a task needs a plan, use this skill — the overhead is low and the alignment benefit is high."
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
Agent(reader,     "Map the relevant modules for: [task]. Return files, interfaces, entry points, conventions.")
Agent(researcher, "Find external patterns or prior decisions in docs/ relevant to: [task].")  // omit if not needed
```

---

## Step 3 — Decide

Run thinker with the gathered context to decide which agents apply and why.

```
Agent(thinker, """
Task: [description]

Reader output:
[paste reader result]

Researcher output (if run):
[paste researcher result or "not run"]

Produce an agent map for this task. List only the agents that are needed with a one-line reason each — omit agents that clearly don't apply. For writer stages, name the files. For tester, note what new logic needs tests. For documenter, note what public surface changes.

Then list the ordered stages with dependencies.
""")
```

---

## Step 4 — Write the Plan

Write the plan to **the file path specified in the plan mode system message** — that is the path ExitPlanMode will read. Do not write to `.claude/plans/` here; Write is blocked in plan mode.

Use this content format:

```markdown
# [Feature Name] — Orchestrator Plan

> **For execution:** Use `orchestrator-execute` to run this plan. It enforces the 5 invariants automatically.

**Goal:** [one sentence]
**Date:** YYYY-MM-DD

---

## Context

[2-3 sentences summarizing what reader and researcher found — enough for execute to skip re-reading]

## Files

| Action | Path | Purpose |
|--------|------|---------|
| Create | `path/to/file.py` | ... |
| Modify | `path/to/existing.py` | ... |

## Agent Map

Agents marked ✗ are explicitly excluded from this plan.

| Agent | Included | Reason |
|-------|----------|--------|
| reader | ✓ | Map [module] before writing |
| researcher | ✗ | No external APIs or prior decisions involved |
| thinker | ✗ | No architectural decision point |
| writer | ✓ | Implement [feature] in [files] |
| checker+reviewer | ✓ | After write phase |
| tester | ✓ | New logic in [file] needs tests |
| documenter | ✗ | No public API changes |

## Tasks

List every individual work item. Each becomes one entry in the Claude Code task list during execution.

1. [work description] — `file1.py`
2. [work description] — `file2.py`
3. [work description] — `file3.py`

## Stages

Stages describe how agents execute the tasks above. Each verify checkpoint is one atomic gate — checker and reviewer always run together.

- [ ] **Stage 1 — reader:** [specific instruction — what to map]
- [ ] **Stage 2 — writer:**
  - task 1: [description] — `file1.py`
  - task 2: [description] — `file2.py` *(parallel with task 1 — disjoint files)*
- [ ] **Stage 3 — verify:** checker + reviewer scoped to `file1.py`, `file2.py`
  - If findings → writer fixes → re-verify (max 2 rounds)
- [ ] **Stage 4 — writer:**
  - task 3: [description] — `file3.py`
- [ ] **Stage 5 — verify:** checker + reviewer scoped to `file3.py`
  - If findings → writer fixes → re-verify (max 2 rounds)
- [ ] **Stage 6 — tester:** [what logic to test, which files to cover]

> When a writer stage lists multiple tasks with disjoint files, mark them `*(parallel)*`. Tasks sharing a file must be serialized — omit the parallel marker.

## Risks

- [risk or unknown 1]
- [risk or unknown 2]
```

---

## Step 5 — Present for Approval

Call `ExitPlanMode`. Claude Code reads the plan file from Step 4 and presents it to the user. The user chooses to approve (and picks a permission mode) or keep planning.

---

## Step 6 — Archive and Execute

After the user approves (plan mode is now exited, Write is unblocked):

1. Write the plan to `.claude/plans/YYYY-MM-DD-<feature-name>.md`. The system plan file from Step 4 is session-scoped and will not survive a new session — this archive is what makes deferred or repeated execution possible, and what gets committed to git as a decision record.
2. Call `Skill("/orchestrator-core:orchestrator-execute")` to begin implementation.
