#!/usr/bin/env bash
# PreToolUse hook: allowlist nested subagent dispatch to reader/researcher/thinker/
# reviewer only — they're read-only and don't run heavy subprocesses. Everything
# else is blocked, including general-purpose, since a full-tool subagent spawning
# a full-tool subagent on an inherited model is the primary risk this hook exists
# to prevent (it bypasses read-before-write, one-writer-per-file-set, and can stack
# concurrent heavy processes uncontrolled).
#
# Reason this has to be a hook, not frontmatter: Claude Code's Agent(agent_type)
# scoping syntax only restricts a main-thread agent (`claude --agent`); a subagent
# spawning its own subagents gets all-or-nothing Agent access, so per-agent
# allow/deny lists in tools/disallowedTools frontmatter cannot express "reader may
# nest-dispatch but writer may not." This hook is the actual enforcement point.
set -euo pipefail

command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat)
AGENT=$(echo "$INPUT" | jq -r '.agent_type // empty' 2>/dev/null)
TARGET=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // empty' 2>/dev/null)

[ -z "$AGENT" ] && exit 0
[ -z "$TARGET" ] && exit 0

case "$TARGET" in
  orchestrator-agents:reader|orchestrator-agents:researcher|orchestrator-agents:thinker|orchestrator-agents:reviewer)
    exit 0
    ;;
  orchestrator-agents:writer|orchestrator-agents:tester)
    REASON="file-mutation risk"
    ;;
  orchestrator-agents:verify|orchestrator-agents:checker)
    REASON="runs lint/typecheck/build subprocesses"
    ;;
  *)
    REASON="not an approved nested target"
    ;;
esac

echo "[orchestrator-hooks] BLOCKED: $AGENT attempted to spawn $TARGET ($REASON). This agent may only be dispatched by the orchestrator — surface the need back up instead." >&2
exit 2
