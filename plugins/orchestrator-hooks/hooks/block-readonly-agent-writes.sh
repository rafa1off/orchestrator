#!/usr/bin/env bash
# PreToolUse hook: confine thinker and researcher writes to their memory directory.
#
# Reason this has to be a hook, not frontmatter: `memory: project` auto-grants Read,
# Write, and Edit so the agent can manage `.claude/agent-memory/<agent>/MEMORY.md`.
# The grant is not path-scoped, and it cannot be narrowed in frontmatter — removing
# Write/Edit from the tools allowlist does not revoke it, and putting them in
# disallowedTools breaks memory writes outright. So both agents ship with
# unrestricted write access while their contracts say "you never write source files".
# That invariant was prompt-enforced only; this hook is the actual enforcement point.
#
# Enforcement is on the write target, not the tool: memory paths pass, everything
# else is refused with the reason surfaced back to the agent.
set -euo pipefail

command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat)
AGENT=$(echo "$INPUT" | jq -r '.agent_type // empty' 2>/dev/null)
# `agent_type` is the definition type when dispatched as a subagent, but the teammate's
# NAME in team mode. Resolve both to the definition type so this guard covers either
# dispatch path — matching the raw value silently no-ops on every teammate.
# shellcheck source=lib-resolve-agent-identity.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib-resolve-agent-identity.sh"
AGENT=$(resolve_agent_identity "$AGENT" "$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)")
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty' 2>/dev/null)

# Empty agent_type means the main thread, which is not governed by this hook.
[ -z "$AGENT" ] && exit 0
[ -z "$FILE" ] && exit 0

case "$AGENT" in
  orchestrator-agents:thinker|orchestrator-agents:researcher) ;;
  *) exit 0 ;;
esac

# Normalise to a project-relative path so absolute and relative targets compare alike.
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
REL="${FILE#"$PROJECT_DIR"/}"

# Reject traversal before matching the prefix — `.claude/agent-memory/../../etc/x`
# is prefixed correctly but escapes the directory.
case "$REL" in
  */../*|*/..|../*|..)
    echo "[orchestrator-hooks] BLOCKED: $AGENT attempted a write to a path containing '..' ($FILE). Write to your memory file by its direct path." >&2
    exit 2
    ;;
esac

case "$REL" in
  .claude/agent-memory/*) exit 0 ;;
esac

echo "[orchestrator-hooks] BLOCKED: $AGENT attempted to write outside its memory directory ($FILE). This agent is read-only — its Write/Edit access exists solely to maintain .claude/agent-memory/. Return the change you want made to the orchestrator so a writer agent can make it." >&2
exit 2
