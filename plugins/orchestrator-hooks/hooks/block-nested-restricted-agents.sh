#!/usr/bin/env bash
# PreToolUse hook: block any subagent from nesting into writer/tester (file-mutation
# risk — nested writes bypass the orchestrator's read-before-write and
# one-writer-per-file-set invariants) or verify/checker (runs lint/typecheck/build
# subprocesses — nested spawns can stack concurrent heavy processes on the user's
# machine uncontrolled, and verify's lifecycle — pipeline path, 2-round cap,
# always-fresh — is orchestrator-managed).
#
# Reason this has to be a hook, not frontmatter: Claude Code's Agent(agent_type)
# scoping syntax only restricts a main-thread agent (`claude --agent`); a subagent
# spawning its own subagents gets all-or-nothing Agent access, so per-agent
# allow/deny lists in tools/disallowedTools frontmatter cannot express "reader may
# nest-dispatch but writer may not." This hook is the actual enforcement point.
#
# reader, researcher, thinker, and reviewer ARE allowed as nested targets — they're
# read-only and don't run heavy subprocesses.
set -euo pipefail

command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat)
AGENT=$(echo "$INPUT" | jq -r '.agent_type // empty' 2>/dev/null)
TARGET=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // empty' 2>/dev/null)

[ -z "$AGENT" ] && exit 0
[ -z "$TARGET" ] && exit 0

case "$TARGET" in
  orchestrator-agents:writer|orchestrator-agents:tester)
    REASON="file-mutation risk"
    ;;
  orchestrator-agents:verify|orchestrator-agents:checker)
    REASON="runs lint/typecheck/build subprocesses"
    ;;
  *)
    exit 0
    ;;
esac

echo "[orchestrator-hooks] BLOCKED: $AGENT attempted to spawn $TARGET ($REASON). This agent may only be dispatched by the orchestrator — surface the need back up instead." >&2
exit 2
