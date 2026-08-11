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

# Which enforcement path applies to this call, as the existing guards would see it:
#   subagent — agent_type present, so the agent_type-keyed guards engage
#   session  — agent_type absent; either the main session or a teammate. The guards that
#              key off agent_type do nothing here, whether or not that was intended.
ENFORCEMENT="session"
[ -n "$AGENT_TYPE" ] && ENFORCEMENT="subagent"

# Can the actor be resolved to a team member without agent_type? This is the open design
# question for teammate-mode enforcement: the team config records agentType per member but
# no per-member session id, so a lookup keyed on session_id may well find nothing. Record
# the outcome either way rather than assuming it.
TEAM_MATCH="not-attempted"
if [ "$ENFORCEMENT" = "session" ] && [ -n "$SESSION_ID" ]; then
  TEAM_CONFIG="${HOME}/.claude/teams/session-$(printf '%s' "$SESSION_ID" | cut -c1-8)/config.json"
  if [ -f "$TEAM_CONFIG" ]; then
    TEAM_MATCH=$(jq -r '
      (.members // []) | map(select(.agentType != "team-lead"))
      | if length == 0 then "team-exists-no-members"
        elif length == 1 then "single-member:" + (.[0].agentType // "untyped")
        else "ambiguous-" + (length | tostring) + "-members"
        end' "$TEAM_CONFIG" 2>/dev/null || echo "config-unreadable")
  else
    TEAM_MATCH="no-team-config"
  fi
fi

printf '%s' "$INPUT" | jq -c \
  --arg enforcement "$ENFORCEMENT" \
  --arg team_match "$TEAM_MATCH" \
  '{
     at: (now | todate),
     event: (.hook_event_name // ""),
     tool: (.tool_name // ""),
     enforcement: $enforcement,
     team_match: $team_match,
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
