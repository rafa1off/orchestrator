---
name: orchestrator-plan
description: "Designs the implementation before any code is written: previews every artifact and side effect the change produces, pins the exact interface contracts against discovered project conventions, and saves the plan to .claude/plans/. After approval, archives the plan, creates its tasks, and feeds the contracts to writers — handing dispatch to the orchestrator routing guide."
when_to_use: "Use when the user is thinking ahead — scoping what needs to change and in what order, not yet implementing. Triggers on: \"plan this out\", \"write up a plan\", \"map out how we'd\", \"let's plan\", \"before we start\", or any request to design/outline an implementation spanning multiple files, schema changes, API additions, or refactors."
argument-hint: "[task description]"
---

# Orchestrator Plan

**Announce at start:** "Using orchestrator-plan to write the implementation plan."

---

## Step 1 — Enter Plan Mode

Check whether plan mode is already active by inspecting your system context: if the plan mode read-only enforcement preamble and ExitPlanMode protocol footer are already present (session was started with `--permission-mode plan`, `/plan` prefix, or Shift+Tab before the prompt), **skip this step** — the plan file path is already specified and calling `EnterPlanMode` again is unnecessary.

Otherwise, call `EnterPlanMode`. The session is now read-only — file edits are blocked until the plan is approved.

> **Cache note (opusplan model setting):** entering or exiting plan mode is a model switch that cold-starts the prompt cache. To preserve cache hits across the planning and execution phases, fix your model and effort level at session start — plan mode is cache-safe on a fixed model.

---

## Step 2 — Research

**The plan is the design.** Every decision a writer could otherwise make on its own gets
made here, so the research has to be good enough to make them — the writer receives the
plan's contracts and supplies bodies, not judgment.

Dispatch readonly agents rather than reading inline; they are readonly, so plan mode
permits them. Run them in one turn so they go in parallel.

| Need | Dispatch | Ask for |
|---|---|---|
| Which files are even involved | `Explore` | the paths, when the target set is unknown |
| The files themselves | `orchestrator-agents:reader` | interfaces, **conventions with `file:line`**, entry points, test files |
| A precedent to mirror | `orchestrator-agents:reader` | the closest existing feature of the same shape, in full |
| External library API, prior decisions | `orchestrator-agents:researcher` | API reference + caveats; skip if the task is purely internal |
| A genuinely open design question | `orchestrator-agents:thinker` | the tradeoff analysis, before you commit to an approach |

Two demands are non-negotiable, because the plan's later sections cannot be written
honestly without them:

- **Conventions must arrive with line references.** Ask reader for the `file:line` behind
  each one. A convention you cannot cite is a preference, and it will not survive review.
- **Call sites must be enumerated, not recalled.** For every symbol whose signature the
  change touches, get its references from `LSP` (or `rg` as fallback) and keep the
  `file:line` list. This is the raw material for the blast-radius section.

---

## Step 3 — Trace the Blast Radius

Research tells you what exists; this step tells you what the change disturbs. Work through
the side-effect categories in [plan-format.md](plan-format.md) §5 and answer each one from
evidence you now hold — call sites, persisted state, tests that will change result,
runtime effects, backward compatibility, hooks and CI, concurrency.

Where an answer is missing, go back to Step 2 for it. Filling one from memory is how a
plan produces a confidently wrong writer.

---

## Step 4 — Write the Plan

Write the plan to **the file path specified in the plan mode system message** — that is the
path ExitPlanMode will read. Do not write to `.claude/plans/` here; Write is blocked in
plan mode.

Follow the nine-section format in **[plan-format.md](plan-format.md)** — read it now if
you have not. In brief:

| § | Section | Carries |
|---|---|---|
| 1 | Header | goal, date, in scope, **out of scope** |
| 2 | Explanation | rationale and the rejected alternative, for the human approving |
| 3 | Conventions in Force | discovered rules, each with a `file:line` precedent |
| 4 | Artifacts | everything that will exist afterwards — source, tests, deps, schema, config, env, generated output, docs, versions, CI |
| 5 | Side Effects & Blast Radius | call sites, data, test churn, compat, hooks, concurrency |
| 6 | Change Contracts | per file: exact signatures, types, error behavior, precedent to mirror — **no bodies** |
| 7 | Tasks | deliverables, each with its file set and the contracts it implements |
| 8 | Acceptance & Verification | what done means; which test failures are expected |
| 9 | Risks & Rollback | what could go wrong and how to undo it |

Then run the **Completeness Gate** at the end of plan-format.md. It is a real gate — do not
proceed to Step 5 with a failing line.

---

## Step 5 — Present for Approval

Call `ExitPlanMode`. Claude Code reads the plan file from Step 4 and presents it to the user. The user chooses to approve (and picks a permission mode) or keep planning.

> **When approval arrives — whether in the same turn (hook path) or as a new turn (dialog path) — proceed immediately to Step 6. Do not wait for further user input.**

---

## Step 6 — Archive and Execute

**The plan was just approved. Execute this step now — no further user input is needed.**

1. Write the plan to `.claude/plans/YYYY-MM-DD-<feature-name>.md`. The system plan file from Step 4 is session-scoped and will not survive a new session — this archive is what makes deferred or repeated execution possible, and what gets committed to git as a decision record.
2. Create tasks from the plan's `## Tasks` section — call `TaskCreate` for each numbered item in order, using the item text as the title and `status: "pending"`.
3. **Hand dispatch to the orchestrator routing guide.** The plan does not choose a dispatch
   level and never records one — a level depends on the thresholds in force, on whether
   `Workflow` is available, and on the user's L3a opt-in, none of which are properties of
   the change being planned. An archived plan re-executed in a later session must be free
   to dispatch differently.

   What the plan hands over is the **file sets in §7**: sets that intersect are one
   serialized track, disjoint sets are separate tracks. Take those to the routing guide and
   follow it for the level thresholds, the per-level dispatch rules, and the `Workflow`
   opt-in. Do not restate any of them here. Executing an approved plan carries the same
   L3a `Workflow` authorization the guide grants — the guide's scale-confirmation rule
   still applies.

   **One thing the plan does override:** §7 may record a *logical* dependency between tasks
   whose file sets are disjoint — task B imports what task A creates. Invariant 3 permits
   those to run in parallel; the plan does not. Sequence them as §7 says.
4. **Compose each writer dispatch from the plan, not from memory.** The plan's sections map
   onto the writer's input contract directly:

   | Writer input | Comes from |
   |---|---|
   | `## Context` | §3 Conventions in Force + the relevant §5 rows (call sites it must update) |
   | `## Task` | §6 Change Contracts for this task's files, **verbatim** |
   | `## Files to modify` | the task's file set from §7 |
   | `taskId` / `tasks` | the `TaskCreate` ids from step 2 |

   Copy the contracts through unedited. Paraphrasing a signature is how a writer ends up
   inventing one. If §6 has a `New convention introduced` block covering these files,
   include it — it is the stated reason the writer needs before departing from precedent.

   > **Invariant 1 (read before write) is satisfied by Step 2** for the files the plan
   > covers: reader ran on them, and its output is in §3 and §6. Any file that surfaces
   > *after* approval was never planned — dispatch reader on it before a writer touches it.
