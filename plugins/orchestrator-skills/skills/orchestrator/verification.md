# Verification — Reference

Read this file when deciding whether, and how, to verify a write.

---

## When to verify

Verification is discretionary, not mandatory — the orchestrator or operator decides based
on the plan or the current task. Weigh:

- the plan's acceptance criteria — does it call for a check before the task is considered done?
- the blast radius of the change — a one-line fix in an isolated module needs less scrutiny than a shared interface or a hot path;
- whether anything executable changed — pure documentation or comment edits rarely warrant a full pass.

There is no round ceiling and no requirement to dispatch checker, reviewer, and tester
together. Call whichever of the three the task needs, whenever it's warranted.

---

## Steps

**1 — Clear stale findings:**
```bash
rm -f .claude/pipeline/checker-findings.json .claude/pipeline/reviewer-findings.json .claude/pipeline/tester-findings.json
# or for multi-track:
rm -f .claude/pipeline/<track>/checker-findings.json .claude/pipeline/<track>/reviewer-findings.json .claude/pipeline/<track>/tester-findings.json
```

**Note:** reviewer is always spawned fresh (never reused) — a deliberate correctness-over-cache
choice. A clean diff baseline each time is worth paying a cold cache; do not optimize it into
warm reuse.

**2 — Dispatch what the task calls for:**
```
Agent({ description: "Checker: lint + typecheck + build",  subagent_type: "orchestrator-agents:checker",  prompt: "Files: [list]. Pipeline: .claude/pipeline/[track if multi]." })
Agent({ description: "Reviewer: diff review",              subagent_type: "orchestrator-agents:reviewer", prompt: "Task: [desc]. Modified files: [list]. Pipeline: .claude/pipeline/[track if multi]." })
Agent({ description: "Tester: run and diagnose tests",     subagent_type: "orchestrator-agents:tester",   prompt: "Task: [desc]. Intended behavior change: [what the change was meant to alter]. Changed files: [list]. Test: [what]." })
```
Any subset, in any combination, is valid — there is no requirement to run all three, or to
run them in the same turn.

**3 — Read findings after dispatched agents complete:**

Each writes structured findings via `write_findings`; a `PostToolUse` hook auto-injects each
file's contents into your context as it lands, so you usually receive them without a manual
read. This mirrors the auto-injection for reports written by `write_report`, though reports
are not this file's concern — findings are the proof-of-execution signal verification acts
on. To read explicitly:
```bash
cat .claude/pipeline/checker-findings.json .claude/pipeline/reviewer-findings.json .claude/pipeline/tester-findings.json
```
`checker-findings.json` carries `checks[]` only (no `issues[]`). `reviewer-findings.json`
carries `issues[]` at `file:line` plus a `checks[]` entry for the review pass.
`tester-findings.json` carries the per-suite `checks` table plus a `failures` list, each
`{ test, classification, evidence, recommendation }`.

**4 — Branch on result. The two signals are handled differently:**

*Checker / reviewer findings (lint / typecheck / diff review)* — translate directly into an
ordinary writer dispatch:
- `status: PASS` + `review: APPROVED` → that side is clear
- `FAIL` or open `issues[]` → read the findings file(s) and dispatch a writer with its single
  input contract:
  - `## Context` — the findings from `checker-findings.json` / `reviewer-findings.json`
  - `## Task` — the required fix, lint and typecheck failures addressed before diff-review issues
  - `## Files to modify` — the affected files

*Tester diagnoses (test failures)* — **do NOT auto-fix.** Tester is readonly and classifies
each failure as REGRESSION / STALE_TEST / FLAKY / UNCLEAR. Because REGRESSION (fix the code)
and STALE_TEST (update the test) have opposite fixes, the orchestrator **presents the
diagnoses to the user and asks them to decide** what to do. Only after the user decides do you
dispatch a writer — with the decision folded into its `## Task` — to act on it. Never guess
which side a failure falls on, and never dispatch a test-authoring or test-fixing writer
without a user decision.

---

## Final Summary

Return this block when the task is complete:

```
## Done

**Task:** [original task]
**Status:** Done / Escalated

**Changes:**
- [file] — [what changed]

**Tests:** [N new, all passing / N failing]
**Verify:** not run / APPROVED / [open issues]
```
