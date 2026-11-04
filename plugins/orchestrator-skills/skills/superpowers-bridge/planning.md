# Planning under the bridge — Reference

Read this when `superpowers:writing-plans` runs with the bridge loaded. The plan keeps the
superpowers format; this file adds the research that grounds it and the archive step that
puts it under the Plan Event Log. (It replaces the retired `orchestrator-plan` skill.)

---

## Research — before writing the plan

**The plan is the design.** Every decision the implementation could otherwise resolve on its
own gets made in the plan, so the research has to be good enough to make them. What the plan
leaves open, someone downstream decides by guessing.

Dispatch readonly agents rather than reading inline, in one turn so they run in parallel:

| Need | Dispatch | Ask for |
|---|---|---|
| Which files are even involved | `Explore` | the paths, when the target set is unknown |
| The files themselves | `orchestrator-agents:reader` | interfaces, **conventions with `file:line`**, entry points, test files |
| A precedent to mirror | `orchestrator-agents:reader` | the closest existing feature of the same shape, in full |
| External library API, prior decisions | `orchestrator-agents:researcher` | API reference + caveats; skip if the task is purely internal |
| A genuinely open design question | `orchestrator-agents:thinker` | the tradeoff analysis, before committing to an approach |

Two demands are non-negotiable:

- **Conventions arrive with line references.** Ask reader for the `file:line` behind each
  one. A convention you cannot cite is a preference, and it will not survive review.
- **Call sites are enumerated, not recalled.** For every symbol whose signature the change
  touches, get its references from `LSP` (or `rg` as fallback) and keep the `file:line` list.

## Blast radius — before writing the tasks

Research tells you what exists; this tells you what the change disturbs. Answer each from
evidence you hold, and go back to Research for any you cannot — filling one from memory is
how a plan comes out confident and wrong:

- **Call sites** of every changed signature, and whether each still compiles and behaves.
- **Persisted state** — schemas, files on disk, caches, event logs — and what reads old data.
- **Tests that will change result**, and which failures are expected (they go in the plan).
- **Runtime effects** — new processes, network calls, env vars, permissions.
- **Backward compatibility** for anything external callers or other plugins depend on.
- **Hooks and CI** that the change trips or must satisfy.
- **Concurrency** — parallel writers, shared files, ordering assumptions.

What you find lands in the plan's Global Constraints, Review Focus, and each task's
`**Files:**` and Interfaces — not in a separate section.

---

## Archive — after the user approves the plan

Execute this immediately after approval, before any execution skill runs. The MCP server
rejects every event for a plan whose archive `.md` does not exist, so the copy comes first.

1. **Copy** the approved plan to `.claude/plans/<stem>.md`, where `<stem>` is the plan file's
   basename without extension (superpowers names plans `YYYY-MM-DD-<slug>.md`, which already
   matches the stem pattern). The superpowers plan stays where it is; the copy is what
   Resuming and `get_plan_state` find.
   - **If this plan replaces a still-active plan** (one whose `get_plan_state(old).closed` is
     false and that this plan supersedes rather than continues), set `supersedes` on the new
     plan's `plan_archived`, and write `plan_abandoned{why, superseded_by: <new stem>}` on the
     old plan so it stops being a Resuming candidate.
2. **Write the first events** with `write_plan_event`, `plan` = `<stem>`, in order:
   - `plan_archived{plan: <stem>, archive: "<original superpowers plan path>", title, supersedes?}`
     — must be the log's first line.
   - One `task_created{task: N, deliverable, files}` per `### Task N`, in order — `files` is
     that task's `**Files:**` list (created + modified + test paths), or `null` (never `[]`)
     for a verification-only task.
   - One `decision{text, who: "user", seq}` per decision the user made in the spec (its
     decisions table), `seq` numbered 1, 2, ….

Execution state is read back with `get_plan_state(<stem>)`; nothing further is written here.
