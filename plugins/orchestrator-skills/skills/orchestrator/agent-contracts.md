# Agent Contracts & Session Registry — Reference

Read this file when you need the full input/output contract for a specific agent, or to implement the session registry (warm agent reuse).

---

## Agent Contracts

| Agent | Invoke with | Returns |
|-------|------------|---------|
| orchestrator-agents:reader | task + file paths + taskId / tasks (for plan tasks) | `Relevant Files / Interfaces / Conventions / Entry Points / Test Files` — or `## Cannot Proceed` |
| orchestrator-agents:researcher | task + research question + taskId / tasks (for plan tasks) | `Prior Decisions / API Reference / Approach / Caveats` |
| orchestrator-agents:thinker | context block + question + taskId / tasks (for plan tasks) | `Analysis / Brainstorming / Q&A`; reads its own context via `Read`/`LSP` and emits a `## Context Request` when it needs broad mapping or external research |
| orchestrator-agents:writer | `## Context` + `## Task` + `## Files to modify` + taskId / tasks (for plan tasks) (initial); `## Batch Fixes Required` (retry) | `## Modified Files` with exact paths |
| orchestrator-agents:checker | files to check (optional) + taskId / tasks (for plan tasks) | `## Check Results` table; raw output on failure |
| orchestrator-agents:reviewer | task context + modified files list + taskId / tasks (for plan tasks) | `## Review Results`; issues list or APPROVED |
| orchestrator-agents:verify | modified files list + pipeline path + taskId / tasks (for plan tasks) | `## Verify Results`; writes `<pipeline>/verify-findings.json` |
| orchestrator-agents:tester | task + intended behavior change + changed files + what to test + pipeline path + taskId / tasks (for plan tasks) | writes `<pipeline>/tester-findings.json` (`checks` table + `failures[]` classified REGRESSION / STALE_TEST / FLAKY / UNCLEAR with evidence) + a short text summary; readonly (never edits code or tests) |

---

## Session Registry

Before any `Agent()` dispatch, check working memory for a saved `agent_id` of that type:

1. **Found** → `SendMessage(to: saved_id)` — resumes the warm agent (cache hit on file content, no cold-start overhead).
2. **Not found** → `Agent(...)` → save the returned `agent_id` keyed by type.

**Cache TTL:** subagent caches use a ~5-minute TTL. Warm reuse via `SendMessage` only yields a cache hit within ~5 minutes of the agent's last activity — beyond that the agent's cache is cold and a fresh spawn is equivalent.

**Availability:** `SendMessage` does **not** require agent teams — resuming a stopped subagent by its `agent_id` or name works in normal dispatch (the stopped agent auto-resumes in the background on receipt). Only structured team-protocol messages (`shutdown_request`, `plan_approval_response`) need `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`. If a name has since been reused by a newer agent, address the earlier one by its `agent_id`.

**Hard exception:** `orchestrator-agents:verify` — always step 2. Never reuse a verify agent; always spawn fresh.

**Best reuse target:** `orchestrator-agents:reader` — called most frequently; highest cache value from file content.

---

## Context Requests

A leaf agent that needs more than it can reach with its own read tools returns a `## Context Request` (e.g. thinker needing external/web research, which it has no tools for) and stops. To fulfil one:

1. Run the reader/researcher (or other agent) that produces the missing context.
2. Resume the **same** requesting agent via `SendMessage(to: its agent_id)` with the findings — it continues warm, retaining its prior reasoning, rather than restarting cold from a fresh `Agent()` dispatch.

This is the sanctioned replacement for the removed nested-dispatch path: agents no longer spawn helpers themselves, so a context gap becomes one orchestrator-visible round-trip instead of a hidden nested subagent.
