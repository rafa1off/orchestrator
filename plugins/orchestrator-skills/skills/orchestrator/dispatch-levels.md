# Dispatch Levels — Reference

Read this file when starting a Level 2 (multi-track) or Level 3 (teammate) task.

---

## Choosing a Level

**How many independent work streams does the task decompose into?**

```
ONE stream
└── L1: reader → writer → verify + tester

TWO or THREE streams, disjoint files, no ordering dependency between streams
└── L2: parallel orchestrator-agents:writer subagents (one per file set)
    Rule: if stream B needs stream A's output before it can write, serialize as L1 — not L2.

FOUR or MORE streams, OR scope unknown at dispatch time
├── Known item list, fully independent, no cross-stream state
│   └── L3a: Workflow pipeline()/parallel() over the item list
├── Unknown scope — "find all X", open-ended discovery
│   └── L3a + loop-until-dry: keep running until K consecutive rounds find nothing new (K=3)
└── Streams must negotiate mid-flight (shared interface, dependent design decisions)
    └── L3b: TeamCreate — full Claude sessions as mini-orchestrators
```

**Scope uncertainty — which loop pattern?**

```
"Did the write introduce regressions?" (known scope, unknown correctness)
└── Verify loop: write → verify → fix → verify; hard cap at 2 rounds; escalate if still failing

"How many items exist?" (unknown quantity, discovered as work proceeds)
└── loop-until-dry: while (dry_rounds < K) inside L3a Workflow

"How deep should I go?" (thoroughness scales to token budget — analysis tasks only, not writes)
└── Budget loop: while (budget.remaining() > threshold)

"Process N known items through M stages"
└── L3a pipeline(): each item flows through stages independently, no barrier between items
```

---

## Teammate vs Subagent Boundary

A **subagent** (L2 writer, verify, tester, reader) is a leaf node: one focused role, no dispatch authority, returns a result.

A **teammate** (L3b TeamCreate) is a mini-orchestrator: owns its own context window, runs its own read → write → verify → test loop, spawns its own subagents, can send inter-agent messages.

**Rule:** if a track is independent enough to hand a context block to and walk away — no mid-flight questions, no shared design decisions — use a subagent or L3a Workflow, not a teammate. Teammates are warranted only when tracks must make decisions that react to other tracks still in flight. A teammate that does nothing but write one file should have been an L2 writer subagent.

---

## Smells & Corrections

| Symptom | Wrong | Correct | Why |
|---|---|---|---|
| TeamCreate teammates each writing one file | L3b | L2 | Teammates are mini-orchestrators; leaf writes waste a full session context |
| Writer B needed Writer A's output interface first | L2 parallel | L1 sequential or L3a pipeline | Parallel writers assume no ordering dependency — violated here |
| L3a Workflow for 2–3 independent file sets | L3a | L2 | Scripting overhead not justified below 4 tracks |
| L1 for a task touching 8 disjoint modules | L1 | L2 or L3a | Single-writer context bloats; parallel dispatch keeps context focused |
| Verify loop ran 3+ rounds | Uncapped loop | Escalate after round 2 | The cap surfaces broken agents rather than papering over them |
| Budget loop on a write task | Budget loop | Fixed L1/verify loop | Writes need deterministic scope; depth-scaling is for analysis |
| Orchestrator dispatching verify for files a teammate owns | Split ownership | Teammate owns its full loop | Double verification creates merge confusion |
| Sharing one interface file justified L3b | L3b | L3a pipeline | File artifact sharing is a pipeline dependency, not inter-agent coordination |

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
