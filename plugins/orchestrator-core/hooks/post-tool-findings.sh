#!/usr/bin/env bash
# PostToolUse hook: after write_findings succeeds, inject findings content as additionalContext
# so the orchestrator receives results automatically without a manual cat step.
set -euo pipefail

INPUT=$(cat)
SOURCE=$(echo "$INPUT" | jq -r '.tool_input.source // empty' 2>/dev/null)
[ -z "$SOURCE" ] && exit 0

FILE="${CLAUDE_PROJECT_DIR}/.claude/pipeline/${SOURCE}-findings.json"
[ -f "$FILE" ] || exit 0

STATUS=$(jq -r '.status // "unknown"' "$FILE" 2>/dev/null || echo "unknown")
CONTENT=$(cat "$FILE")

jq -nc \
  --arg src "$SOURCE" \
  --arg status "$STATUS" \
  --arg content "$CONTENT" \
  '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: ("[orchestrator] \($src) findings ready (status: \($status)):\n\($content)")}}'
