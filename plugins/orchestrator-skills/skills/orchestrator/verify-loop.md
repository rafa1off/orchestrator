# Verify Loop — Reference

Read this file before entering the post-write verify loop.

---

## Steps

**1 — Clear stale findings:**
```bash
rm -f .claude/pipeline/verify-findings.json
# or for multi-track:
rm -f .claude/pipeline/<track>/verify-findings.json
```

**2 — Dispatch verify + tester in the same message turn:**
```
Agent({ description: "Verify: post-write pass",      subagent_type: "orchestrator-agents:verify", background: true, prompt: "Modified files: [list]. Pipeline: .claude/pipeline/[track if multi]. taskId: [verify-task-id]." })
Agent({ description: "Tester: write and run tests",  subagent_type: "orchestrator-agents:tester", background: true, prompt: "Task: [desc]. Changed files: [list]. Test: [what]. taskId: [tester-task-id]." })
```

**3 — Read findings after both complete:**
```bash
cat .claude/pipeline/verify-findings.json
```

**4 — Branch on result:**
- `status: PASS` + `review: APPROVED` → done
- `FAIL` or `ISSUES` → send batch to writer:

```
## Batch Fixes Required

### Verify errors
[from verify-findings.json]
```

**5 — Re-verify:** back to step 1. After **2 full rounds** with remaining findings: surface all findings to the user and ask for direction.

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
