#!/usr/bin/env bash
# PreToolUse hook: block writer/verify/tester from running git push or opening/merging/editing PRs.
# Reason: Claude Code v2.1.198+ makes background agents auto-commit/push/open draft PRs on completion.
# writer/verify/tester run background:true routinely in this ecosystem, and there's no user in the
# loop to confirm a push from inside a subagent — so it's blocked outright, not just asked for.
set -euo pipefail

command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat)
AGENT=$(echo "$INPUT" | jq -r '.agent_type // empty' 2>/dev/null)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

[ -z "$AGENT" ] && exit 0
[ -z "$CMD" ] && exit 0

case "$AGENT" in
  orchestrator-agents:writer|orchestrator-agents:verify|orchestrator-agents:tester) ;;
  *) exit 0 ;;
esac

if echo "$CMD" | grep -qE '(^|&&|;|\|)[[:space:]]*(git push|gh pr (create|merge|edit))'; then
  echo "[orchestrator-hooks] BLOCKED: $AGENT attempted a remote-facing operation ($CMD). Subagents may not push, open, or merge PRs — return the result to the orchestrator instead." >&2
  exit 2
fi

exit 0
