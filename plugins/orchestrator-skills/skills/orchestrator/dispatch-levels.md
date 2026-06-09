# Dispatch Levels — Reference

Read this file when starting a Level 2 (multi-track) or Level 3 (teammate) task.

---

## Level 1 — Single track (default)

```
Wave 1 (parallel):  reader [+ researcher if external APIs needed] [+ thinker if design question]
Wave 2 (inline):    orchestrator synthesizes → presents plan → user approves
Wave 3:             writer
Wave 4 (parallel):  verify + tester
Wave 5 (if needed): writer fixes → verify reruns (once max)
```

---

## Level 2 — Multi-track (2–3 independent file sets, ≤15 files total)

- Assign each track a pipeline path: `.claude/pipeline/track-a/`, `.claude/pipeline/track-b/`, etc.
- **Worktree decision** — before dispatching writers, check whether the target files share the main repo:
  ```bash
  git -C <target-dir> rev-parse --show-toplevel 2>/dev/null
  ```
  If the result differs from `git rev-parse --show-toplevel` (i.e., targets live in a subrepo or git-ignored subtree with its own `.git`), omit `isolation: "worktree"` — the disjoint-file invariant is sufficient. Otherwise include it.
- Dispatch all writers simultaneously with `background: true` (add `isolation: "worktree"` when targets share the main repo):
  ```
  Agent({ description: "Writer: track-a — [task]", subagent_type: "orchestrator-agents:writer", background: true, isolation: "worktree", prompt: "## Context\n...\ntaskId: [track-a-task-id]." })
  Agent({ description: "Writer: track-b — [task]", subagent_type: "orchestrator-agents:writer", background: true, isolation: "worktree", prompt: "## Context\n...\ntaskId: [track-b-task-id]." })
  ```
- Dispatch verify + tester per track in parallel (4 agents at once for 2 tracks), each scoped to its pipeline path.
- **Commit each worktree before consolidating.** The writer has no `Bash` tool and cannot commit. After a writer returns `## Modified Files`, the orchestrator commits from the worktree path:
  ```bash
  git -C <worktree-path> add <file1> <file2> ...
  git -C <worktree-path> commit -m "track-a: <one-line task summary>"
  ```
  The worktree path is returned in the Agent result alongside the branch name.
- **Consolidate — do NOT use `cp`.** After all tracks verify clean, cherry-pick each branch in sequence:
  ```bash
  git cherry-pick <track-a-branch>
  git cherry-pick <track-b-branch>
  ```
  If cherry-pick fails: the disjoint-file invariant was violated — planning error, not a merge scenario. Abort and escalate:
  ```bash
  git cherry-pick --abort
  ```
  Report which files conflicted, which tracks touched them, and that tracks must be replanned with truly disjoint file sets.
- After all cherry-picks complete: serial integration pass on shared files (`pyproject.toml`, lock files, `conftest.py`).

---

## Level 3 — Teammate sessions (3+ tracks OR >15 files total)

- **Worktree decision** — same check as L2: if targets are in a subrepo, tell each teammate in its prompt not to use worktree isolation for those files.
- Dispatch each track as a teammate via `TeamCreate` — one teammate per track, each with its own worktree:
  ```
  TeamCreate({ name: "track-a", prompt: "Implement track-a of .claude/plans/<plan>.md. Pipeline: .claude/pipeline/track-a." })
  TeamCreate({ name: "track-b", prompt: "Implement track-b of .claude/plans/<plan>.md. Pipeline: .claude/pipeline/track-b." })
  ```
- Each teammate runs the full loop (read → write → verify → test) independently.
- Each teammate writes status when done: `{"track":"track-a","status":"done","modified":["file.py"],"branch":"<worktree-branch>"}`
- Status values: `"working"` | `"done"` | `"escalated"` | `"failed"`
- Wait for all teammates to report `done` or `escalated` (via `TeammateIdle` hook or polling).
- **Consolidate:** each teammate must commit before reporting `done` (teammates have Bash access). Cherry-pick each branch into the main working tree in plan order — never use `cp`. If a teammate didn't commit, the orchestrator commits from the worktree: `git -C <worktree-path> add <files> && git -C <worktree-path> commit -m "<track>: <summary>"` before cherry-picking.
- After all cherry-picks complete: serial integration pass.

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
