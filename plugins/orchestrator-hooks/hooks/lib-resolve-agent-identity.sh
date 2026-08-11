#!/usr/bin/env bash
# Shared identity resolution for the agent_type-keyed guards. Source it; call
# `resolve_agent_identity "$AGENT_TYPE" "$SESSION_ID"` and read the canonical definition
# type from stdout (empty when the call is not from one of our agents).
#
# Why this is needed: `agent_type` carries a different value shape depending on how the
# agent was dispatched.
#
#   dispatched as subagent  -> "orchestrator-agents:thinker"   (the definition type)
#   dispatched as teammate  -> "probe-thinker"                 (the teammate's NAME)
#   main session            -> "" / absent
#
# Every guard here matched the definition type as an exact string, so a teammate fell
# through to the catch-all and the guard no-opped. Confirmed live: a thinker teammate wrote
# outside .claude/agent-memory/ with no interception, and the same name-shaped agent_type
# appeared on its Bash calls, so the mismatch spans every guarded tool rather than one.
#
# The teammate's name is the key into the team config, which records agentType per member.
# A teammate shares the lead's session id, so `session-<first 8>` locates that config from
# either side and the name disambiguates within it — no session-level ambiguity, and the
# main session stays distinguishable because its agent_type is empty rather than a name.
#
# Note the earlier dead end preserved here as a warning: resolving by session id alone
# cannot work. It matches the lead's own session too, so it attributes main-session calls
# to whichever teammate happens to be in the team.

resolve_agent_identity() {
  local agent_type="$1" session_id="${2:-}" team_config resolved

  # Main session, or a payload without the field: not one of ours.
  [ -n "$agent_type" ] || return 0

  # Already the definition type — the subagent path, unchanged.
  case "$agent_type" in
    orchestrator-agents:*) printf '%s' "$agent_type"; return 0 ;;
  esac

  # Otherwise treat it as a teammate name and resolve it through the team config. A
  # built-in subagent type (Explore, general-purpose) simply will not match a member name,
  # which is the correct outcome: it is not one of ours either.
  [ -n "$session_id" ] || return 0
  command -v jq >/dev/null 2>&1 || return 0

  team_config="${HOME}/.claude/teams/session-$(printf '%s' "$session_id" | cut -c1-8)/config.json"
  [ -f "$team_config" ] || return 0

  resolved=$(jq -r --arg n "$agent_type" \
    '((.members // []) | map(select(.name == $n)) | .[0] | .agentType) // ""' \
    "$team_config" 2>/dev/null || printf '')

  case "$resolved" in
    orchestrator-agents:*) printf '%s' "$resolved" ;;
  esac
}
