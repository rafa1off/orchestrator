# Verify Loop — Reference

Read this file before entering the post-write verify loop.

---

## Steps

**1 — Clear stale findings:**
```bash
rm -f .claude/pipeline/verify-findings.json .claude/pipeline/tester-findings.json
# or for multi-track:
rm -f .claude/pipeline/<track>/verify-findings.json .claude/pipeline/<track>/tester-findings.json
```

**Note:** verify is always spawned fresh (never reused) — a deliberate correctness-over-cache choice. A clean diff baseline each round is worth paying a cold cache; do not optimize it into warm reuse.

**2 — Dispatch verify + tester in the same message turn:**
```
Agent({ description: "Verify: post-write pass",      subagent_type: "orchestrator-agents:verify", background: true, prompt: "Modified files: [list]. Pipeline: .claude/pipeline/[track if multi]. taskId: [verify-task-id]." })
Agent({ description: "Tester: run and diagnose tests", subagent_type: "orchestrator-agents:tester", background: true, prompt: "Task: [desc]. Intended behavior change: [what the change was meant to alter]. Changed files: [list]. Test: [what]. taskId: [tester-task-id]." })
```

**3 — Read findings after both complete:**

Both agents write structured findings; a PostToolUse hook auto-injects each file's contents into your context as it lands, so you usually receive them without a manual read. To read explicitly:
```bash
cat .claude/pipeline/verify-findings.json .claude/pipeline/tester-findings.json
```
`verify-findings.json` carries `checks` + `issues`; `tester-findings.json` carries the per-suite `checks` table plus a `failures` list, each `{ test, classification, evidence, recommendation }`.

**4 — Branch on result. The two signals are handled differently:**

*Verify findings (lint / typecheck / diff review)* — auto-loop:
- `status: PASS` + `review: APPROVED` → verify side is clear
- `FAIL` or `ISSUES` → send batch to writer:

```
## Batch Fixes Required

### Verify errors
[from verify-findings.json]
```

*Tester diagnoses (test failures)* — **do NOT auto-fix.** Tester is readonly and classifies each failure as REGRESSION / STALE TEST / FLAKY / UNCLEAR. Because REGRESSION (fix the code) and STALE TEST (update the test) have opposite fixes, the orchestrator **presents the diagnoses to the user and asks them to decide** what to do. Only after the user decides do you dispatch a writer to act on that decision. Never guess which side a failure falls on, and never dispatch a test-authoring or test-fixing writer without a user decision.

**5 — Re-verify:** loop the verify side back to step 1. After **2 full rounds** with remaining verify findings, or on **any** tester failure, surface everything to the user and ask for direction.

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
**Verify:** APPROVED / [open issues]
```
