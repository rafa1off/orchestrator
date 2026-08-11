#!/usr/bin/env bash
# PreToolUse observer: record which identity fields a payload actually carries, for the
# tools the enforcement guards care about. Never blocks — this hook exists to make the
# guard suite observable, not to add another rule.
#
# Why this exists: every enforcement guard in this plugin keys off `agent_type`, which the
# harness populates "when the hook fires inside a subagent". A teammate is an independent
# session, not a subagent, so in team mode that field is absent and four guards
# (block-readonly-agent-writes, block-subagent-git-push, block-nested-restricted-agents,
# track-writer-overlap) silently degrade to no-ops. Nothing surfaced that: a guard that
# no-ops looks exactly like a guard that passed. This hook is the missing signal.
#
# It records the payload's full key set rather than a fixed list, so a field that only
# appears on some dispatch path shows up in the log instead of being invisible to a
# schema someone guessed in advance. It also records whether the acting agent could be
# resolved to a team member, which is the question that decides whether an agent-specific
# rule can be enforced at all in team mode.
set -euo pipefail

INPUT=$(cat)

# Never let auditing break a tool call. Every failure path below exits 0.
command -v jq >/dev/null 2>&1 || exit 0

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
LOG="$PROJECT_DIR/.claude/pipeline/identity-audit.jsonl"
mkdir -p "$(dirname "$LOG")" 2>/dev/null || exit 0

AGENT_TYPE=$(printf '%s' "$INPUT" | jq -r '.agent_type // ""' 2>/dev/null || echo "")
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // ""' 2>/dev/null || echo "")

# On lifecycle events the actor is the subject of the event, not the caller. TeammateIdle
# names it in `teammate_name` and carries no agent_type at all; falling back to it keeps
# one identity column meaningful across every event this hook observes.
if [ -z "$AGENT_TYPE" ]; then
  AGENT_TYPE=$(printf '%s' "$INPUT" | jq -r '.teammate_name // ""' 2>/dev/null || echo "")
fi

# Which dispatch path this call came from. `agent_type` carries a different value shape
# per path, which is the distinction the guards were missing:
#   main      — agent_type empty; no guard should engage
#   subagent  — agent_type is the definition type, e.g. orchestrator-agents:thinker
#   teammate  — agent_type is the teammate's NAME, e.g. probe-thinker
ENFORCEMENT="main"
case "$AGENT_TYPE" in
  "") ;;
  orchestrator-agents:*) ENFORCEMENT="subagent" ;;
  *) ENFORCEMENT="teammate-or-builtin" ;;
esac

# Resolve a name-shaped agent_type to its definition type. The name is the key into the
# team config, so this is exact — no session-level ambiguity.
#
# The first version of this hook keyed the lookup on session_id instead, and its very
# first recorded row was a false positive: a teammate shares the lead's session id, so a
# main-session call resolved to whichever teammate was in the team. Keying on the name is
# what removed that, and main-session rows stay unattributed because agent_type is empty.
TEAM_MATCH="not-attempted"
if [ "$ENFORCEMENT" = "teammate-or-builtin" ] && [ -n "$SESSION_ID" ]; then
  TEAM_CONFIG="${HOME}/.claude/teams/session-$(printf '%s' "$SESSION_ID" | cut -c1-8)/config.json"
  if [ -f "$TEAM_CONFIG" ]; then
    TEAM_MATCH=$(jq -r --arg n "$AGENT_TYPE" '
      ((.members // []) | map(select(.name == $n)) | .[0] | .agentType) // "name-not-in-team"
      ' "$TEAM_CONFIG" 2>/dev/null || echo "config-unreadable")
  else
    TEAM_MATCH="no-team-config"
  fi
fi

printf '%s' "$INPUT" | jq -c \
  --arg enforcement "$ENFORCEMENT" \
  --arg team_match "$TEAM_MATCH" \
  --arg actor "$AGENT_TYPE" \
  '{
     at: (now | todate),
     event: (.hook_event_name // ""),
     tool: (.tool_name // ""),
     enforcement: $enforcement,
     team_match: $team_match,
     # `actor` is the identity this hook reasoned about; `agent_type` is the raw field.
     # They differ on lifecycle events, where the subject is named elsewhere in the
     # payload — recording only the raw field would make those rows look anonymous.
     actor: (if $actor == "" then null else $actor end),
     agent_type: (.agent_type // null),
     agent_id: (.agent_id // null),
     session_id: (.session_id // null),
     transcript: (.transcript_path // null),
     permission_mode: (.permission_mode // null),
     payload_keys: (keys | sort)
   }' >> "$LOG" 2>/dev/null || exit 0

# Bounded: this fires on every write and every Bash call, so an unbounded log would grow
# without limit across a long session.
LINES=$(wc -l < "$LOG" 2>/dev/null || echo 0)
case "$LINES" in ''|*[!0-9]*) LINES=0 ;; esac
if [ "$LINES" -gt 2000 ]; then
  tail -n 1000 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG" 2>/dev/null || true
fi

exit 0
