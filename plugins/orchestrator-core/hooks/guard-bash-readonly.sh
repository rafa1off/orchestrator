#!/usr/bin/env bash
# PreToolUse guard: block write and destructive Bash operations in read-only agents.
# Used by checker and reviewer via frontmatter hooks.
# permissionMode: plan already blocks Edit/Write/NotebookEdit; this covers shell-level writes.

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$CMD" ] && exit 0

if echo "$CMD" | grep -qE \
  '(^|[[:space:]])(rm|mv)[[:space:]]|\s>|>>|git[[:space:]]+(commit|push|reset|stash|checkout[[:space:]]--)|pip[[:space:]]+install|uv[[:space:]]+add|npm[[:space:]]+(install|ci)'; then
  echo "[orchestrator] Blocked: write or destructive Bash command not permitted in read-only agent" >&2
  exit 2
fi
