# Agent Contracts & Session Registry — Reference

Read this file when you need the full input/output contract for a specific agent, or to implement the session registry (warm agent reuse).

---

## Agent Contracts

| Agent | Invoke with | Returns |
|-------|------------|---------|
| orchestrator-agents:reader | task + file paths | `Relevant Files / Interfaces / Conventions / Entry Points / Test Files` — or `## Cannot Proceed` |
| orchestrator-agents:researcher | task + research question | `Prior Decisions / API Reference / Approach / Caveats` |
| orchestrator-agents:thinker | context block + question | `Analysis / Brainstorming / Q&A`; reads its own context via `Read`/`Grep`/`Glob` and emits a `## Context Request` when it needs broad mapping or external research |
| orchestrator-agents:writer | `## Context` + `## Task` + `## Files to modify` | `## Modified Files` with exact paths |
| orchestrator-agents:checker | files to check (optional) + pipeline path (optional, for track isolation) | `## Check Results` table; writes `<pipeline>/checker-findings.json` (`checks[]` only, no `issues[]`) |
| orchestrator-agents:reviewer | task context + modified files list + pipeline path (optional, for track isolation) | `## Review Results`; writes `<pipeline>/reviewer-findings.json` (`issues[]` at `file:line`, plus a `checks[]` entry for the review pass) |
| orchestrator-agents:tester | task + intended behavior change + changed files + what to test + pipeline path | writes `<pipeline>/tester-findings.json` (`checks` table + `failures[]` classified REGRESSION / STALE_TEST / FLAKY / UNCLEAR with evidence) + a short text summary; readonly (never edits code or tests) |

File deletion is an orchestrator action: no agent holds `Bash`, and `Write`/`Edit` cannot remove a file, so a task requiring a file to be deleted must have the orchestrator perform the deletion — a writer asked to do it can only empty the file and report.

---

## Session Registry

Before any `Agent()` dispatch, check working memory for a saved `agent_id` of that type:

1. **Found** → `SendMessage(to: saved_id)` — resumes the warm agent (cache hit on file content, no cold-start overhead).
2. **Not found** → `Agent(...)` → save the returned `agent_id` keyed by type.

**Cache TTL:** prompt-cache TTL is a session property, not a fixed 5 minutes — sessions
commonly run a 1-hour TTL, and usage overage can drop later requests to 5 minutes. Treat
the window as unknown rather than assuming the short one: `SendMessage` reuse costs nothing
extra when the cache has already expired (it is equivalent to a fresh spawn), so prefer
warm reuse whenever the agent is still relevant and do not skip it on the assumption that
minutes have passed. Measure before optimising against a specific number.

**Availability:** `SendMessage` resumes a stopped subagent addressed by its `agent_id` or name, in normal dispatch, and the stopped agent auto-resumes in the background on receipt. If a name has been reused by a newer agent, address the earlier one by `agent_id`.

**Hard exception:** `orchestrator-agents:reviewer` — always step 2. Never reuse a reviewer agent; always spawn fresh so its diff baseline is never stale.

**Best reuse target:** `orchestrator-agents:reader` — called most frequently; highest cache value from file content.

---

## Context Requests

A leaf agent that needs more than it can reach with its own read tools returns a `## Context Request` (e.g. thinker needing external/web research, which it has no tools for) and stops. To fulfil one:

1. Run the reader/researcher (or other agent) that produces the missing context.
2. Resume the **same** requesting agent via `SendMessage(to: its agent_id)` with the findings — it continues warm, retaining its prior reasoning, rather than restarting cold from a fresh `Agent()` dispatch.

This is the sanctioned replacement for the removed nested-dispatch path: agents no longer spawn helpers themselves, so a context gap becomes one orchestrator-visible round-trip instead of a hidden nested subagent.
