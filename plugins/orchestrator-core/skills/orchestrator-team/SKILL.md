---
name: orchestrator-team
description: "Use for large tasks that decompose into 3 or more independent write tracks that would serialize unnecessarily as subagents — parallel feature development across disjoint modules, competing implementation hypotheses to evaluate, or large cross-module refactors with no shared files. Fans out to full Claude Code session teammates, each running the complete orchestrator loop on their own track, coordinated by the lead session. Requires CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1."
---

# Orchestrator — Agent Teams Mode

Agent teams run each write track as a **full Claude Code session** (teammate) with its own context window and task list, coordinated by the lead session. Use this when subagents would be too constrained by the single-context-window limit or when independent tracks genuinely benefit from not sharing context.

> **Prerequisite:** Agent teams are experimental. Enable once before first use:
> ```bash
> export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
> ```
> Or add to your shell profile to persist.

---

## When Agent Teams vs Subagents

| Scenario | Use |
|---|---|
| 3+ independent write tracks with disjoint file sets | Agent teams |
| Sequential pipeline (read → write → verify) | Subagents (standard orchestrator) |
| Single-module change, any size | Subagents |
| Competing hypotheses — want two parallel implementations | Agent teams |
| Large cross-module refactor with disjoint modules | Agent teams |
| Any task where `orchestrator-plan` + `orchestrator-execute` fits | Subagents |

---

## Team Structure

```
Lead (you, main session)
├── Teammate A — track 1 writer + verify loop
├── Teammate B — track 2 writer + verify loop
├── Teammate C — track 3 writer + verify loop
└── (serial) Integration step — you merge and run final tests
```

The lead:
- Decomposes the plan into independent tracks
- Spawns one teammate per track
- Monitors via the shared task list
- Runs the integration step after all teammates finish

Each teammate:
- Follows the standard orchestrator loop for its track: read → write → verify
- Claims tasks from the shared list
- Signals done by completing its tasks

---

## Step-by-Step

### 1 — Decompose into tracks

A track is a set of files that no other track touches. If two tracks share a file, they are not independent — merge them or serialize.

Write the plan to `.claude/plans/team-<task>.md`:

```markdown
# Team Plan — [task name]

## Tracks

### Track A — [name]
Files: src/module-a.py, tests/test_module_a.py
Goal: [one sentence]

### Track B — [name]
Files: src/module-b.py, tests/test_module_b.py
Goal: [one sentence]

### Track C — [name]
Files: src/module-c.py, tests/test_module_c.py
Goal: [one sentence]

## Integration step (lead, serial after all tracks done)
- [list integration actions — e.g., update shared config, run full suite]
```

### 2 — Spawn teammates

Spawn one teammate per track. Pass the track's context directly:

```
Spawn a teammate to implement Track A. Context:
- Files: src/module-a.py, tests/test_module_a.py
- Goal: [goal]
- Follow the standard orchestrator loop: read the files first, write changes, then run checker and reviewer. Write tests after reviewer approves.
- Claim task "Track A" from the task list when starting.
```

Spawn all teammates in the same message turn so they run concurrently.

### 3 — Monitor via task list

Press `Ctrl+T` in agent view to watch the shared task list. Each teammate self-reports progress by updating their claimed task.

If a teammate goes idle unexpectedly, attach to it and check its last message. Common causes:
- Waiting on a permission prompt (auto-denied in background mode — check the transcript)
- Hit a verify escalation (max 2 rounds — teammate should have surfaced findings)
- Discovered a cross-track dependency (merge the tracks and serialize)

### 4 — Integration step (serial, you run this)

After all teammates complete their tracks:

1. Pull all changes into one view: `git diff HEAD`
2. Run the full test suite: `uv run pytest` (or equivalent)
3. If integration tests fail, fix conflicts directly or dispatch a single writer subagent for the integration file set
4. Run checker + reviewer one final time on the integrated diff

---

## Quality Gates with `TeammateIdle`

The orchestrator-core plugin installs a blocking `TeammateIdle` hook globally. When a teammate goes idle with unread findings files present in `.claude/pipeline/`, the hook blocks with exit 2 — enforcing that the lead reads all findings before the teammate closes. No additional configuration is needed.

---

## Invariants Still Apply

The 5 core invariants apply within each teammate's track:

1. **Read before write** — each teammate reads its files before writing
2. **Verify at checkpoints** — each teammate runs checker + reviewer after its write phase
3. **One writer per overlapping file set** — guaranteed by track decomposition (disjoint files)
4. **Max 2 verify rounds** — each teammate escalates to you if findings persist after 2 rounds
5. **Plan mode blocks writes** — not applicable inside teammate sessions (they run in execute mode)

Invariant 3 is the key reason tracks must have disjoint file sets. If a teammate discovers a dependency on another track's files mid-task, it should stop and surface it to you rather than proceeding.

---

## Limitations

- Agent teams require `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
- Each teammate has its own full context window — token cost scales linearly
- No session resumption for in-process teammates — save state to the plan file if interrupted
- One team at a time per lead session
- Teammates cannot spawn sub-teams (no nested teams)
- Integration-owned files (`pyproject.toml`, lock files, `conftest.py`) must be handled by the lead in the serial integration step — never by teammates

---

## Final Summary Template

```
## Done

**Task:** [original task]
**Mode:** Agent teams — [N] tracks

**Tracks completed:**
- Track A — [files changed] — APPROVED
- Track B — [files changed] — APPROVED
- Track C — [files changed] — APPROVED

**Integration:** [what the lead did — full suite result]
**Tests:** [N total, all passing / N failing]
**Docs:** [updated / not needed]
```
