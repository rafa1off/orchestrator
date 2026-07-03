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
    Rule: if stream B needs stream A's output interface before it can write, serialize as L1 — not L2.
    Option: adversarial-review lens-split — run security / correctness / tests as parallel review
            subagents after the write phase for broader coverage.

FOUR or MORE streams, OR scope unknown at dispatch time
├── Known item list, fully independent, no cross-stream state
│   └── L3a: Workflow pipeline()/parallel() over the item list
│       Single barrier before the serial integration pass; no barrier between independent tracks.
├── Unknown scope — "find all X", open-ended discovery
│   └── L3a + loop-until-dry: keep running until K consecutive rounds find nothing new (K=3)
└── Streams must negotiate mid-flight (shared interface, dependent design decisions)
    └── L3b: Teammates — full Claude sessions as mini-orchestrators
        Gate: requires CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1; fallback to L3a + shared findings file.
        Option: adversarial-review lens-split as teammates for perspective-diverse quality gates.
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
└── L3a pipeline(): each item flows through stages independently; single barrier before integration
```

---

## Teammate vs Subagent Boundary

A **subagent** (L2 writer, verify, tester, reader) is a leaf node for write/check work: it returns a result and does not coordinate peers. Any of the 8 agents may nest-dispatch `reader`, `researcher`, `thinker`, or `reviewer` for its own missing context (all read-only, no heavy subprocesses) — but a `PreToolUse` hook in `orchestrator-hooks` (`block-nested-restricted-agents.sh`) blocks every agent from spawning `writer`, `tester`, `verify`, or `checker`. Those four stay orchestrator-only: writer/tester because a nested write would bypass the read-before-write and one-writer-per-file-set invariants, verify/checker because they run lint/typecheck/build subprocesses that shouldn't stack uncontrolled, and verify specifically because its lifecycle (pipeline path, 2-round cap, always-fresh) is orchestrator-managed. This is enforced by the hook, not by per-agent frontmatter — Claude Code's `Agent(agent_type)` scoping syntax only restricts a main-thread agent, not a subagent spawning its own subagents, so frontmatter can only grant or deny `Agent` wholesale.

A **teammate** (L3b) is a mini-orchestrator: owns its own context window, runs its own read → write → verify → test loop, spawns its own subagents, can send inter-agent messages.

**Rule:** if a track is independent enough to hand a context block to and walk away — no mid-flight questions, no shared design decisions — use a subagent or L3a Workflow, not a teammate. Teammates are warranted only when tracks must make decisions that react to other tracks still in flight. A teammate that does nothing but write one file should have been an L2 writer subagent.

---

## Smells & Corrections

| Symptom | Wrong | Correct | Why |
|---|---|---|---|
| Teammates each writing one file | L3b | L2 | Teammates are mini-orchestrators; leaf writes waste a full session context |
| Writer B needed Writer A's output interface first | L2 parallel | L1 sequential or L3a pipeline | Parallel writers assume no ordering dependency — violated here |
| L3a Workflow for 2–3 independent file sets | L3a | L2 | Scripting overhead not justified below 4 tracks |
| L1 for a task touching 8 disjoint modules | L1 | L2 or L3a | Single-writer context bloats; parallel dispatch keeps context focused |
| Verify loop ran 3+ rounds | Uncapped loop | Escalate after round 2 | The cap surfaces broken agents rather than papering over them |
| Budget loop on a write task | Budget loop | Fixed L1/verify loop | Writes need deterministic scope; depth-scaling is for analysis |
| Orchestrator dispatching verify for files a teammate owns | Split ownership | Teammate owns its full loop | Double verification creates merge confusion |
| Sharing one interface file justified L3b | L3b | L3a pipeline | File artifact sharing is a pipeline dependency, not inter-agent coordination |
| Spawning verify/checker directly as teammates | L3b verify teammate | Each teammate runs its own verify loop internally | Top-level verify teammates muddy ownership; the teammate is already a mini-orchestrator |
| Workflow-ifying the standard 2-round verify loop | L3a workflow | Inline verify loop | Wrong scale; the 2-round loop is inline and user-in-loop by design |

---

## Level 1 — Single track (default)

```
Wave 1 (parallel):  reader [+ researcher if external APIs needed] [+ thinker if design question]
Wave 2 (inline):    orchestrator synthesizes → presents plan → user approves
Wave 3:             writer [background: true if parallelism is warranted]
Wave 4 (parallel):  verify + tester
Wave 5 (if needed): writer fixes → verify reruns (once max)
```

**Reader fan-out:** for tasks spanning multiple disjoint modules, dispatch multiple reader agents in ONE message (concurrent) — one per module or logical grouping — then synthesize their outputs before writing. Keeps each reader's context focused and cuts wall time.

```
Agent({ description: "Reader: map module X", subagent_type: "orchestrator-agents:reader", background: true, prompt: "..." })
Agent({ description: "Reader: map module Y", subagent_type: "orchestrator-agents:reader", background: true, prompt: "..." })
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

**Adversarial-review lens-split (optional):** after the write phase, dispatch parallel review subagents with distinct lenses — e.g., security, correctness, test coverage — each scoped to the changed files. Collect findings before the integration pass.

> **If files conflict across tracks:** the disjoint-file invariant was violated — a planning error. Escalate: report which files conflicted and which tracks touched them. Tracks must be replanned with truly disjoint file sets.

---

## Level 3 — Large scale (3+ tracks OR >15 files total)

Choose based on whether tracks need to coordinate with each other:

### 3a — Workflow (default: independent parallel work)

Use when tracks are fully independent — no cross-track coordination or peer messaging needed. Workflow moves orchestration into a script outside Claude's context, making runs resumable and context-free.

`pipeline()` runs all tracks in parallel up to a **single barrier** before the serial integration pass. The integration pass legitimately needs all tracks done; no other barriers are needed between independent per-track stages.

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
// ↑ barrier: all tracks done before integration pass below
```

After the workflow completes: serial integration pass on shared files (`pyproject.toml`, lock files, `conftest.py`).

**Divide-and-conquer patterns** (author inline in the workflow as needed):

- **Adversarial / perspective-diverse verify** — after a write phase, fan out N skeptic agents, each with a distinct lens (security, correctness, performance, test coverage). Collect all findings before proceeding. More thorough than a single verify agent; use when the change surface is wide or high-risk.
- **Completeness critic** — after the main work agents finish, spawn a final "what did we miss?" agent that receives all prior outputs and surfaces gaps. Useful for API-design or schema-change tasks where omissions are costly.
- **Loop-until-dry** — keep fanning out finder agents (e.g., "find all callers of deprecated API") until K consecutive rounds (K=3) find nothing new. Use for open-ended discovery before a large-scale rename or removal.

> **Do NOT workflow-ify the standard 2-round verify loop.** That loop is inline, user-in-loop, and at the wrong scale for a workflow script. Keep it as described in `verify-loop.md`.

### 3b — Teammates (coordination-heavy)

**Gate:** requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`. If the env var is not set, teammates cannot be spawned — fall back to L3a Workflow with a shared findings file in `.claude/pipeline/` as the coordination mechanism.

Use when teammates need to share findings, challenge each other's work, or coordinate on dependent tasks via direct inter-agent messaging.

- Spawn each track as a full-session teammate via the Agent tool (pass a `name` to make it addressable by other teammates via `SendMessage`). The team forms automatically when the first teammate is spawned; no setup tool is needed.
- Optionally type a teammate from a subagent definition (e.g., `subagent_type: "orchestrator-agents:writer"`) — the teammate honors that definition's tools and model, with the body appended to its system prompt. Note: a subagent definition's `skills:` and `mcpServers:` frontmatter are NOT applied when running as a teammate; teammates load skills/MCP from project + user settings.
- Each teammate runs the full loop (read → write → verify → test) independently and spawns its own subagents as needed.
- Coordinate via the **native shared task list** (tasks have pending/in_progress/completed states and dependencies that auto-unblock) and `SendMessage` (message a teammate by name). `SendMessage` is also only available when `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`.
- Enforce the verify gate with a `TeammateIdle` hook: exit 2 to send feedback and keep a teammate working if its verify findings are not clean.
- Cleanup is automatic at session exit — no teardown step.
- After all tracks complete: serial integration pass on shared files.

**Adversarial-review lens-split (optional):** spawn parallel review teammates with distinct lenses — security / correctness / tests — that each read the full changeset and report findings to the task list before the integration pass.

> **Never spawn verify/checker directly as top-level teammates.** Each teammate is already a mini-orchestrator running its own verify loop internally. Spawning the findings-writers as separate top-level teammates muddies ownership — it's unclear which teammate's output is authoritative when conflicts arise. Keep verify inside each track's own loop.

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
