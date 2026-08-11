#!/usr/bin/env bash
# TeammateIdle hook: refuse to let an orchestrator agent go idle as a teammate without
# having delivered its output over SendMessage.
#
# The failure this closes: a subagent's final assistant message IS its return value, but a
# teammate is an independent session with no tool result — its final message is never
# delivered to anyone, and only SendMessage crosses the boundary. All eight agent
# definitions are written for the subagent contract ("return the output block"), so
# dispatched as teammates they produced their report, ended the turn, and the lead saw a
# bare "finished" with no body. The `## Delivery` section in each definition now says to
# send; this guard is what makes that a guarantee rather than a request.
#
# Three things this hook does NOT do the way its neighbours do, each for a reason:
#   1. It signals with exit 2 + stderr, not `decision: "block"`. TeammateIdle supports
#      exit 2 (teammate receives stderr and keeps working) and
#      `{"continue": false, ...}` (stop it entirely) — there is no `decision` field here,
#      so the SubagentStop guard's JSON would parse as ordinary stdout and wave every
#      teammate through.
#   2. It scopes itself. TeammateIdle takes no matcher and fires for EVERY teammate, and
#      the payload carries `teammate_name` rather than `agent_type`. The team config's
#      member entry carries the agent type the lead named at spawn, so that is where the
#      scoping decision comes from. A teammate spawned with no orchestrator agent type is
#      none of this guard's business — it may legitimately deliver by writing a file.
#   3. It caps at two nudges. A teammate that ignores the instruction would otherwise be
#      blocked from idling forever, converting a missing report into a hung session. Two
#      rounds then release, mirroring the "verify after write, max 2 rounds" invariant;
#      the release path prints a warning so a genuinely undelivered report is still
#      visible to the user rather than silently dropped.
set -euo pipefail

INPUT=$(cat)

TEAMMATE=$(printf '%s' "$INPUT" | jq -r '.teammate_name // empty' 2>/dev/null || true)
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)
TEAM_NAME=$(printf '%s' "$INPUT" | jq -r '.team_name // empty' 2>/dev/null || true)
TRANSCRIPT=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null || true)

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
NUDGE_DIR="$PROJECT_DIR/.claude/pipeline/.idle-nudge"

# Nudge accounting is plain filesystem so it works even when jq is missing below.
nudge_count() {
  [ -f "$NUDGE_DIR/$1" ] && cat "$NUDGE_DIR/$1" 2>/dev/null || echo 0
}

record_nudge() {
  mkdir -p "$NUDGE_DIR" 2>/dev/null || true
  printf '%s' "$2" > "$NUDGE_DIR/$1" 2>/dev/null || true
}

# $1 = message delivered to the teammate as feedback; it keeps working instead of idling.
nudge() {
  local n
  n=$(nudge_count "$SAFE_NAME")
  case "$n" in ''|*[!0-9]*) n=0 ;; esac
  if [ "$n" -ge 2 ]; then
    echo "[orchestrator-hooks] WARNING: teammate '$TEAMMATE' went idle without calling SendMessage after 2 nudges. Its output block was never delivered — it exists only in that teammate's transcript. Ask it directly (SendMessage to '$TEAMMATE' resumes it from its transcript) or re-dispatch the agent as a subagent, where its final message is the return value." >&2
    exit 0
  fi
  record_nudge "$SAFE_NAME" "$((n + 1))"
  echo "$1" >&2
  exit 2
}

[ -n "$TEAMMATE" ] || exit 0
SAFE_NAME=$(printf '%s' "$TEAMMATE" | tr -c 'A-Za-z0-9._-' '_')

if ! command -v jq >/dev/null 2>&1; then
  # Without jq the transcript cannot be parsed, so delivered and undelivered are
  # indistinguishable. Blocking every teammate for the whole session would be a false
  # positive on the honest ones and, with no counter to parse, unbounded — so nudge once
  # (the cap above still applies, it is filesystem-based) and then let it go.
  nudge "[orchestrator] jq is not installed, so this guard cannot confirm you delivered your output. If you have SendMessage in your tool list, you are a teammate: your final message reaches nobody. Send your full output block to \"main\" via SendMessage now, then end your turn. If you already sent it, end your turn."
fi

# Scope: only agents from this ecosystem. The lead's own entry carries `team-lead`, and a
# teammate spawned without a subagent definition omits the field entirely.
[ -n "$TEAM_NAME" ] || TEAM_NAME="session-$(printf '%s' "$SESSION_ID" | cut -c1-8)"
TEAM_CONFIG="${HOME}/.claude/teams/${TEAM_NAME}/config.json"

# Same name-keyed resolution the PreToolUse guards use, so both paths agree on identity.
# shellcheck source=lib-resolve-agent-identity.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib-resolve-agent-identity.sh"
AGENT_TYPE=$(resolve_agent_identity "$TEAMMATE" "$SESSION_ID")
[ -n "$AGENT_TYPE" ] || exit 0

# verify and tester owe findings, not just a message. As subagents that is enforced at
# SubagentStop; for a teammate it cannot be, because agent_type there is the teammate's
# NAME and a name cannot contain a colon, so `^orchestrator-agents:(verify|tester)$` can
# never match however that event fires. Without this branch the third layer of the
# findings chain — the one covering "called nothing at all" — is simply absent in team
# mode, which is the shape of fail-open this suite exists to prevent.
case "$AGENT_TYPE" in
  *:verify|*:tester)
    SOURCE="${AGENT_TYPE##*:}"
    if ! find "$PROJECT_DIR/.claude/pipeline" -name "${SOURCE}-findings.json" 2>/dev/null | read -r _; then
      nudge "[orchestrator] You are ${SOURCE} and you have written no ${SOURCE}-findings.json. Call write_findings now with source=\"${SOURCE}\", one checks[] entry per check or suite you actually ran, and the real process exit_code for each. A check that could not execute must be status=\"ERROR\" with exit_code=null, never PASS. Then deliver your summary via SendMessage and end your turn."
    fi
    ;;
esac

[ -f "$TRANSCRIPT" ] || exit 0

# Did this teammate call SendMessage during the turn that is now ending? The turn boundary
# is the last genuine inbound message: tool results are recorded as `user` entries too, so
# an entry counts as a boundary only when its content is a string or carries no
# tool_result block. Without that filter every tool call would look like a new turn and
# the check would only ever see the final tool use.
DELIVERED=$(jq -rs '
  def boundary:
    .type == "user"
    and ((.message.content | type) == "string"
         or ((.message.content | type) == "array"
             and ([.message.content[] | select(.type == "tool_result")] | length) == 0));
  def sent:
    .type == "assistant"
    and (.message.content | type) == "array"
    and ([.message.content[] | select(.type == "tool_use" and .name == "SendMessage")] | length) > 0;
  [ .[] | select(type == "object") ] as $entries
  | ([ $entries | to_entries[] | select(.value | boundary) | .key ] | last // -1) as $start
  | if ([ $entries | to_entries[] | select(.key > $start) | select(.value | sent) ] | length) > 0
    then "yes" else "no" end
' "$TRANSCRIPT" 2>/dev/null || echo "unknown")

# "unknown" means the transcript did not parse. Treat it like "not delivered": a guard that
# waves through whatever it cannot read is the fail-open hole this suite exists to avoid,
# and the two-nudge cap bounds the cost of being wrong.
if [ "$DELIVERED" = "yes" ]; then
  rm -f "$NUDGE_DIR/$SAFE_NAME" 2>/dev/null || true
  exit 0
fi

nudge "[orchestrator] You are running as a team teammate, not a subagent: your final message is NOT delivered to anyone, and you ended your turn without calling SendMessage. Send your complete output block — the whole thing, not a summary, because the recipient cannot read your transcript — to \"main\" via SendMessage now. If your work also produced a file on disk, name its path in the message. Then end your turn."
