# Dispatch Levels — Reference

Read this file when starting a Level 2 (multi-track) or Level 3 (teammate) task.

---

## Level 1 — Single track (default)

```
Wave 1 (parallel):  reader [+ researcher if external APIs needed] [+ thinker if design question]
Wave 2 (inline):    orchestrator synthesizes → presents plan → user approves
Wave 3:             writer [background: true if parallelism is warranted]
Wave 4 (parallel):  verify + tester
Wave 5 (if needed): writer fixes → verify reruns (once max)
```

---

## Level 2 — Multi-track (2–3 independent file sets, ≤15 files total)

- Assign each track a pipeline path: `.claude/pipeline/track-a/`, `.claude/pipeline/track-b/`, etc.
- Dispatch all writers simultaneously with `background: true`:
  ```
  Agent({ description: "Writer: track-a — [task]", subagent_type: "orchestrator-agents:writer", background: true, prompt: "## Context\n...\ntaskId: [track-a-task-id]." })
  Agent({ description: "Writer: track-b — [task]", subagent_type: "orchestrator-agents:writer", background: true, prompt: "## Context\n...\ntaskId: [track-b-task-id]." })
  ```
- Each writer edits its disjoint file set directly in the working tree. Wait for all to complete.
- Dispatch verify + tester per track in parallel (4 agents at once for 2 tracks), each scoped to its pipeline path.
- After all tracks verify clean: serial integration pass on shared files (`pyproject.toml`, lock files, `conftest.py`).

> **If files conflict across tracks:** the disjoint-file invariant was violated — a planning error. Escalate: report which files conflicted and which tracks touched them. Tracks must be replanned with truly disjoint file sets.

---

## Level 3 — Large scale (3+ tracks OR >15 files total)

Choose based on whether tracks need to coordinate with each other:

### 3a — Workflow (default: independent parallel work)

Use when tracks are fully independent — no cross-track coordination or peer messaging needed. Workflow moves orchestration into a script outside Claude's context, making runs resumable and context-free.

```javascript
export const meta = {
  name: 'l3-task',
  description: 'Implement [task] across N independent tracks',
  phases: [{ title: 'Read' }, { title: 'Write' }, { title: 'Verify' }],
}

const TRACKS = [
  { label: 'track-a', files: ['path/to/a.py'], task: '...' },
  { label: 'track-b', files: ['path/to/b.py'], task: '...' },
  // ...
]

const results = await pipeline(
  TRACKS,
  t => agent(`Map files for ${t.label}: ${t.files.join(', ')}`, {
    label: `read:${t.label}`, phase: 'Read',
    agentType: 'orchestrator-agents:reader',
  }),
  (ctx, t) => agent(`Implement ${t.task}.\n\nContext:\n${ctx}`, {
    label: `write:${t.label}`, phase: 'Write',
    agentType: 'orchestrator-agents:writer',
  }),
  (_, t) => agent(`Verify changes in ${t.files.join(', ')}. Pipeline: .claude/pipeline/${t.label}.`, {
    label: `verify:${t.label}`, phase: 'Verify',
    agentType: 'orchestrator-agents:verify',
  }),
)
return results
```

After the workflow completes: serial integration pass on shared files (`pyproject.toml`, lock files, `conftest.py`).

### 3b — TeamCreate (coordination-heavy)

Use when teammates need to share findings, challenge each other's work, or coordinate on dependent tasks via direct inter-agent messaging.

```
TeamCreate({ name: "track-a", prompt: "Implement track-a of .claude/plans/<plan>.md. Pipeline: .claude/pipeline/track-a." })
TeamCreate({ name: "track-b", prompt: "Implement track-b of .claude/plans/<plan>.md. Pipeline: .claude/pipeline/track-b." })
```

- Each teammate runs the full loop (read → write → verify → test) independently.
- Each teammate writes status when done: `{"track":"track-a","status":"done","modified":["file.py"]}`
- Status values: `"working"` | `"done"` | `"escalated"` | `"failed"`
- Wait for all teammates to report `done` or `escalated` (via `TeammateIdle` hook or polling).
- After all tracks complete: serial integration pass on shared files.

---

## Parallel Dispatch Examples

**Parallel readonly agents (any level):**
```
Agent({ description: "Reader: map module X",               subagent_type: "orchestrator-agents:reader",     background: true, prompt: "Task: [desc]. Files: [paths]. taskId: [id]." })
Agent({ description: "Researcher: find library pattern Y", subagent_type: "orchestrator-agents:researcher", background: true, prompt: "Task: [desc]. Research question: [question]. taskId: [id]." })
Agent({ description: "Thinker: analyze tradeoff Z",        subagent_type: "orchestrator-agents:thinker",   background: true, prompt: "Task: [desc]. Question: [question]. taskId: [id]." })
```

**Writer handling multiple plan tasks in one call:**
```
Agent({ description: "Writer: implement features A and B", subagent_type: "orchestrator-agents:writer", prompt: "## Context\n...\ntasks: [{taskId: [id1], description: 'add X to api.py'}, {taskId: [id2], description: 'update schema in models.py'}]." })
```
Use this when consecutive plan tasks share enough context that a single writer invocation is more efficient than two. Each task is marked `in_progress`/`completed` individually as the writer works through them.
