# Agent Contracts & Session Registry — Reference

Read this file when you need the full input/output contract for a specific agent, or to implement the session registry (warm agent reuse).

---

## Agent Contracts

| Agent | Invoke with | Returns |
|-------|------------|---------|
| orchestrator-agents:reader | task + file paths + taskId / tasks (optional) | `Relevant Files / Interfaces / Conventions / Entry Points / Test Files` — or `## Cannot Proceed` |
| orchestrator-agents:researcher | task + research question + taskId / tasks (optional) | `Prior Decisions / API Reference / Approach / Caveats` |
| orchestrator-agents:thinker | context block + question + taskId / tasks (optional) | `Analysis / Brainstorming / Q&A` — or `## Context Request` |
| orchestrator-agents:writer | `## Context` + `## Task` + `## Files to modify` + taskId / tasks (optional) (initial); `## Batch Fixes Required` (retry) | `## Modified Files` with exact paths |
| orchestrator-agents:checker | files to check (optional) + taskId / tasks (optional) | `## Check Results` table; raw output on failure |
| orchestrator-agents:reviewer | task context + modified files list + taskId / tasks (optional) | `## Review Results`; issues list or APPROVED |
| orchestrator-agents:verify | modified files list + pipeline path + taskId / tasks (optional) | `## Verify Results`; writes `<pipeline>/verify-findings.json` |
| orchestrator-agents:tester | task + changed files + what to test + taskId / tasks (optional) | `## Test Results` with written files + pass/fail table |

---

## Session Registry

Before any `Agent()` dispatch, check working memory for a saved `agent_id` of that type:

1. **Found** → `SendMessage(to: saved_id)` — resumes the warm agent (cache hit on file content, no cold-start overhead).
2. **Not found** → `Agent(...)` → save the returned `agent_id` keyed by type.

**Hard exception:** `orchestrator-agents:verify` — always step 2. Never reuse a verify agent; always spawn fresh.

**Best reuse target:** `orchestrator-agents:reader` — called most frequently; highest cache value from file content.
