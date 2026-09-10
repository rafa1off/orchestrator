---
name: orchestrator-plan
description: "Designs the implementation before any code is written: previews every artifact and side effect the change produces, pins the exact interface contracts against discovered project conventions, and saves the plan to .claude/plans/. Describes the code, not the work of producing it — execution and dispatch stay with the orchestrator routing guide."
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

**The plan is the design.** Every decision the implementation could otherwise resolve on
its own gets made here, so the research has to be good enough to make them. What the plan
leaves open, someone downstream will decide by guessing.

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
plan comes out confident and wrong.

---

## Step 4 — Write the Plan

Write the plan to **the file path specified in the plan mode system message** — that is the
path ExitPlanMode will read. Do not write to `.claude/plans/` here; Write is blocked in
plan mode.

Follow the nine-section format in **[plan-format.md](plan-format.md)** — read it now if
you have not. In brief:

| § | Section | Carries |
|---|---|---|
| 1 | Header | goal, date, in scope, **out of scope**, Architecture, Tech Stack, Spec, Global Constraints |
| 2 | Explanation | rationale and the rejected alternative, for the human approving |
| 3 | Conventions in Force | discovered rules, each with a `file:line` precedent |
| 4 | Artifacts | everything that will exist afterwards — source, tests, deps, schema, config, env, generated output, docs, versions, CI |
| 5 | Side Effects & Blast Radius | call sites, data, test churn, compat, hooks, concurrency |
| 6 | Change Contracts | per file: exact signatures, types, error behavior, precedent to mirror — **no bodies** |
| 7 | Tasks | deliverables, each with its file set (file-authoring tasks) or none (verification-only tasks) and the contracts it implements |
| 8 | Acceptance & Verification | what done means; which test failures are expected |
| 9 | Risks & Rollback | what could go wrong and how to undo it |

Run No Placeholders, then the Coherence Pass, then the Completeness Gate — the Coherence
Pass is prose judgment, the Gate is mechanical checklist, run in that order. Do not proceed
to Step 5 with a failing Gate line.

---

## Step 5 — Present for Approval

Call `ExitPlanMode`. Claude Code reads the plan file from Step 4 and presents it to the user. The user chooses to approve (and picks a permission mode) or keep planning.

> **When approval arrives — whether in the same turn (hook path) or as a new turn (dialog path) — proceed immediately to Step 6. Do not wait for further user input.**

---

## Step 6 — Archive

**The plan was just approved. Execute this step now — no further user input is needed.**

1. Write the plan to `.claude/plans/YYYY-MM-DD-<feature-name>.md`. The system plan file from Step 4 is session-scoped and will not survive a new session — this archive is what makes deferred or repeated execution possible, and what gets committed to git as a decision record.
2. Create `.claude/plans/progress.md` from the plan's `## Tasks` section — one line per numbered item (`- [ ] N. <deliverable> — <file set>`, or `- [ ] N. <deliverable>` with no trailing `—` at all when the task is verification-only, no file set), plus a `**Plan:**` header pointing at the archive path from step 1, an `**Updated:**` timestamp, a `**Base:**` header line reading `not yet captured`, an `**Auto-commit:**` header line reading `not yet confirmed`, a `## Decisions` section seeded with any decisions the user made while planning, and an empty `## Verify Rounds` section. Overwrite any existing `progress.md` — it describes one active effort.
3. Create an empty `.claude/plans/progress.jsonl` alongside it — an append-only ledger of per-task commit events, populated as the orchestrator executes the plan (see `verification.md` and `orchestrator/SKILL.md`'s `## Run Start`/`## Resuming`). Overwrite any existing `progress.jsonl` the same way — a stale one from an earlier effort would have shas that still validate as genuine ancestors of HEAD, silently rendering the previous effort's completion status instead of this one's.

```markdown
# Progress — <feature name>

**Plan:** `.claude/plans/YYYY-MM-DD-<feature>.md`
**Updated:** YYYY-MM-DDTHH:MMZ
**Base:** not yet captured
**Auto-commit:** not yet confirmed

## Deliverables

- [x] 1. <deliverable> — `file`, `file`
- [ ] 2. <deliverable> — `file`
- [ ] 3. <deliverable>

## Decisions

- <decision> (YYYY-MM-DD, user)

## Verify Rounds

- Task 1: writer dispatched.
- Task 1, round 1: 3 findings.
- Task 1, round 2: 0 findings.
```

`**Auto-commit:**` is read by its first whitespace-delimited token (the stored value carries
a trailing date). When that token is `confirmed`, a file-authoring deliverable's marker is
sourced from `progress.jsonl`, never hand-edited: `[ ]` is pending (including reverted), `[x]`
is complete, `[x~]` is complete with a parked finding — rendered inline as `- [x~] N.
<deliverable> — \`file\` (parked: <ruling text>)`, so every session renders it the same way
rather than inventing a footnote scheme — `[!]` needs attention (a commit could not be made,
or its recorded sha no longer validates). If the Deliverables rendering ever disagrees with a
fresh read of `progress.jsonl` (e.g. a hand-edit was made to `progress.md`), the jsonl wins —
`progress.md`'s markers are a cached rendering, not an independent record; this comparison is
never made for a `declined` plan (nothing in the jsonl to compare against) or for a
verification-only task (which never has a jsonl line). When the token is `declined`, or
before it is ever confirmed (`not yet confirmed` or absent), or for a verification-only
deliverable (no file set) regardless of Auto-commit, only `[ ]`/`[x]` are used, set directly
by the orchestrator based on the outcome of the check it names — there is no ledger line to
source from in any of these cases. The numeric prefix makes each line a unique edit target
even when two deliverables share text. One line per numbered §7 task, full stop: a task's
`**Consumes:**`/`**Produces:**` sub-lines are plan content, not Deliverables-list content —
they are never rendered into `progress.md`'s Deliverables list.

The plan is now done. Execution is the orchestrator's.
