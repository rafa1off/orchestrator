# Agent Contracts & Session Registry — Reference

Read this file when you need the full input/output contract for a specific agent, or to implement the session registry (warm agent reuse).

---

## Agent Contracts

| Agent | Invoke with | Returns |
|-------|------------|---------|
| orchestrator-agents:reader | task + file paths | writes `<pipeline>/reader-<label>-report.json` via `write_report` (`relevant_files` / `interfaces` / `conventions` / `entry_points` / `test_files`, plus `context_request` when blocked) |
| orchestrator-agents:researcher | task + research question | writes `<pipeline>/researcher-<label>-report.json` via `write_report` (`prior_decisions` / `api_reference` / `recommended_approach` / `caveats`, plus `context_request` when blocked) |
| orchestrator-agents:thinker | context block + question | writes `<pipeline>/thinker-<label>-report.json` via `write_report` (`mode`-specific fields plus a required `recommendation`); reads its own context via `Read`/`Grep`/`Glob` and sets `context_request` when it needs broad mapping or external research |
| orchestrator-agents:writer | `## Context` + `## Task` + `## Files to modify` | writes `<pipeline>/writer-<label>-report.json` via `write_report` (`modified[]` with exact paths, `in_scope` flagged per entry) |
| orchestrator-agents:checker | files to check (optional) + pipeline path (optional, for track isolation) | writes `<pipeline>/checker-<label>-findings.json` via `write_findings` (`checks[]` only, no `issues[]`) |
| orchestrator-agents:reviewer | task context + modified files list + pipeline path (optional, for track isolation) | writes `<pipeline>/reviewer-<label>-findings.json` via `write_findings` (`issues[]` at `file:line`, plus a `checks[]` entry for the review pass) |
| orchestrator-agents:tester | task + intended behavior change + changed files + what to test + pipeline path | writes `<pipeline>/tester-<label>-findings.json` via `write_findings` (`checks` table + `failures[]` classified REGRESSION / STALE_TEST / FLAKY / UNCLEAR with evidence); readonly (never edits code or tests) |

`<label>` is a required, agent-supplied kebab-case slug describing what that call's result
covers (e.g. `checker-lint-typecheck-build-findings.json`) — it is what lets two agents of
the same type running in parallel land on distinct filenames instead of overwriting each
other; a real on-disk collision is resolved server-side with a random suffix.

Both paths are validated tool calls, guarded by the same `SubagentStop` check for presence
and freshness — a final markdown message is no longer any agent's deliverable. They diverge
on what they can claim: findings additionally carry proof-of-execution, one `checks[]` entry
per check actually run with a real exit code, because checker, reviewer, and tester ran
commands. Reports carry no `checks[]` and no exit code, because reader, researcher, thinker,
and writer run none — the guard demands only that the report is present and fresh, never
that it is substantiated by a process outcome.

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

A leaf agent that needs more than it can reach with its own read tools sets `context_request`
(`needs` + `why`) on its report (e.g. thinker needing external/web research, which it has no
tools for) and stops. Every report type carries this field; the orchestrator's detection is a
single check: `report.context_request is not None`. To fulfil one:

1. Run the reader/researcher (or other agent) that produces the missing context.
2. Resume the **same** requesting agent via `SendMessage(to: its agent_id)` with the findings — it continues warm, retaining its prior reasoning, rather than restarting cold from a fresh `Agent()` dispatch.

This is the sanctioned replacement for the removed nested-dispatch path: agents no longer spawn helpers themselves, so a context gap becomes one orchestrator-visible round-trip instead of a hidden nested subagent.
