#!/usr/bin/env bash
# PostToolUse hook: after write_findings succeeds, inject findings content as additionalContext
# so the orchestrator receives results automatically without a manual cat step.
set -euo pipefail

command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat)
SOURCE=$(echo "$INPUT" | jq -r '.tool_input.source // empty' 2>/dev/null)
[ -z "$SOURCE" ] && exit 0

FILE="${CLAUDE_PROJECT_DIR}/.claude/pipeline/${SOURCE}-findings.json"
[ -f "$FILE" ] || exit 0

STATUS=$(jq -r '.status // "unknown"' "$FILE" 2>/dev/null || echo "unknown")
CONTENT=$(cat "$FILE")

# Proof-of-execution guard: block verify findings that indicate checks could not run.
# Backgrounded verify agents can have Bash auto-denied; this catches silent skips.
if [ "$SOURCE" = "verify" ]; then
  # Trigger if overall status is ERROR
  IS_ERROR=false
  if [ "$STATUS" = "ERROR" ]; then
    IS_ERROR=true
  fi

  # Trigger if any checks[] entry has status ERROR
  if [ "$IS_ERROR" = "false" ]; then
    HAS_CHECK_ERROR=$(jq -r '[.checks[]? | select(.status == "ERROR")] | length > 0' "$FILE" 2>/dev/null || echo "false")
    if [ "$HAS_CHECK_ERROR" = "true" ]; then
      IS_ERROR=true
    fi
  fi

  # Trigger if any checks[] entry has status PASS with null or missing exit_code
  if [ "$IS_ERROR" = "false" ]; then
    HAS_UNPROVEN_PASS=$(jq -r '[.checks[]? | select(.status == "PASS" and (.exit_code == null or .exit_code == ""))] | length > 0' "$FILE" 2>/dev/null || echo "false")
    if [ "$HAS_UNPROVEN_PASS" = "true" ]; then
      IS_ERROR=true
    fi
  fi

  if [ "$IS_ERROR" = "true" ]; then
    echo "[orchestrator] BLOCKED: verify findings contain ERROR status or unproven PASS (exit_code null). The backgrounded verify agent likely had a Bash check auto-denied. Add the required Bash allow-rules documented in the README so lint/typecheck can execute, then re-run verify." >&2
    exit 2
  fi
fi

jq -nc \
  --arg src "$SOURCE" \
  --arg status "$STATUS" \
  --arg content "$CONTENT" \
  '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: ("[orchestrator] \($src) findings ready (status: \($status)):\n\($content)")}}'
