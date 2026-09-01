#!/usr/bin/env bash
# SubagentStop hook: refuse to let checker, reviewer, or tester finish without fresh,
# substantiated findings — and refuse to let reader, writer, thinker, or researcher finish
# without a fresh report. Covers all seven agents — the previous matcher was
# `^orchestrator-agents:verify$` only, so tester could stop having written nothing and
# nothing objected.
#
# Three fail-open holes this closes, in the order they bit:
#   1. `find … | head -1` picked an ARBITRARY track's findings in a multi-track run, and
#      any stale file that parsed as JSON was accepted as this agent's own result.
#      Now: candidates are filtered by `written_at` against this agent's start stamp.
#   2. A file that merely parsed as JSON counted as valid, so `{"status":"PASS"}` with no
#      checks at all passed. Now: the same substantiation rule as the PostToolUse guard.
#   3. Missing jq meant "assume valid", i.e. the guard silently disabled itself. The whole
#      point of these guards is that their presence is what makes a green result
#      trustworthy, so absence must fail loudly rather than wave the result through.
#
# Reports are NOT proof-of-execution (cs3-schema.md Part 2, "Deliberate non-goals"):
# reader/writer/thinker/researcher run no commands, so a report has no checks[] and no
# exit codes. That branch demands presence and freshness only — never substantiation.
#
# Blocking uses `decision: "block"` with a reason rather than exit 2: on SubagentStop that
# keeps the subagent running and hands it the reason as its next instruction, so a missing
# write_findings/write_report call self-corrects instead of dead-ending in the orchestrator.
set -euo pipefail

INPUT=$(cat)

block() {
  # $1 = reason delivered to the subagent as its next instruction
  jq -nc --arg reason "$1" '{decision: "block", reason: $reason}' 2>/dev/null \
    || printf '{"decision":"block","reason":"%s"}' "$1"
  exit 0
}

if ! command -v jq >/dev/null 2>&1; then
  echo "[orchestrator-hooks] BLOCKED: jq is not installed, so the findings guard cannot verify this run. Install jq — without it every checker/reviewer/tester result is unverifiable and must not be trusted." >&2
  exit 2
fi

AGENT=$(echo "$INPUT" | jq -r '.agent_type // empty' 2>/dev/null)
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // empty' 2>/dev/null)
LAST_MSG=$(echo "$INPUT" | jq -r '.last_assistant_message // empty' 2>/dev/null)

# Derive the expected filename and check KIND from the agent that is stopping, so each
# agent is held to its own file rather than sharing one hardcoded path. checker, reviewer,
# and tester write substantiated findings (checks[] with real exit codes); reader, writer,
# thinker, and researcher write reports (presence and freshness only — see file header).
case "$AGENT" in
  *checker) SOURCE="checker"; KIND="findings" ;;
  *reviewer) SOURCE="reviewer"; KIND="findings" ;;
  *tester) SOURCE="tester"; KIND="findings" ;;
  *reader) SOURCE="reader"; KIND="report" ;;
  *writer) SOURCE="writer"; KIND="report" ;;
  *thinker) SOURCE="thinker"; KIND="report" ;;
  *researcher) SOURCE="researcher"; KIND="report" ;;
  *) exit 0 ;;
esac

if [ "$KIND" = "findings" ]; then
  FILE_SUFFIX="findings"
else
  FILE_SUFFIX="report"
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
PIPELINE_ROOT="$PROJECT_DIR/.claude/pipeline"
STAMP_FILE="$PIPELINE_ROOT/.starts/${AGENT_ID}"

# Anything written before this agent started belongs to an earlier round or another
# track. With no stamp (SubagentStart missed), fall back to the file's own recency.
START_TS=0
if [ -f "$STAMP_FILE" ]; then
  START_TS=$(cat "$STAMP_FILE" 2>/dev/null || echo 0)
fi
case "$START_TS" in
  ''|*[!0-9]*) START_TS=0 ;;
esac
if [ "$START_TS" -eq 0 ]; then
  START_TS=$(( $(date -u +%s) - 900 ))
fi

# Collect every candidate for this source across the default dir and all track subdirs,
# then keep only those this agent could plausibly have written.
FRESH_FILE=""
BEST_TS=0
while IFS= read -r candidate; do
  [ -f "$candidate" ] || continue
  WRITTEN_AT=$(jq -r '.written_at // 0' "$candidate" 2>/dev/null || echo 0)
  case "$WRITTEN_AT" in
    ''|*[!0-9]*) WRITTEN_AT=0 ;;
  esac
  # Older findings files predate the written_at field; fall back to mtime for those.
  if [ "$WRITTEN_AT" -eq 0 ]; then
    WRITTEN_AT=$(stat -c %Y "$candidate" 2>/dev/null || echo 0)
  fi
  if [ "$WRITTEN_AT" -ge "$START_TS" ] && [ "$WRITTEN_AT" -ge "$BEST_TS" ]; then
    FRESH_FILE="$candidate"
    BEST_TS="$WRITTEN_AT"
  fi
done <<EOF
$(find "$PIPELINE_ROOT" -name "${SOURCE}-*-${FILE_SUFFIX}.json" 2>/dev/null)
EOF

if [ -z "$FRESH_FILE" ]; then
  # Distinguish "never wrote one" from "wrote one, but before this run" — and do not
  # assert the cause. A stopped agent with nothing written may equally have hit its turn
  # limit or been aborted; SubagentStop carries no terminal_reason or aborted field to
  # tell these apart, so the message reports the observation and quotes the agent.
  DETAIL="No ${SOURCE}-${FILE_SUFFIX}.json written during this run"
  if find "$PIPELINE_ROOT" -name "${SOURCE}-*-${FILE_SUFFIX}.json" 2>/dev/null | read -r _; then
    DETAIL="A ${SOURCE}-${FILE_SUFFIX}.json exists but predates this run (stale — from an earlier round or another track)"
  fi
  SUMMARY=""
  [ -n "$LAST_MSG" ] && SUMMARY=" Your final message was: \"$(echo "$LAST_MSG" | head -c 300)\"."
  if [ "$KIND" = "findings" ]; then
    block "[orchestrator] ${DETAIL}. Call write_findings now with source=\"${SOURCE}\", one checks[] entry per check or suite you actually ran, and the real process exit_code for each. If a check could not execute, report status=\"ERROR\" with exit_code=null and say why — never omit it and never report PASS for something that did not run. If you stopped because you ran out of turns or were interrupted, say so explicitly instead of reporting a result.${SUMMARY}"
  else
    block "[orchestrator] ${DETAIL}. Call write_report now with source=\"${SOURCE}\" and the fields for your report type before stopping. If you stopped because you ran out of turns or were interrupted, say so explicitly instead of reporting a result. If you cannot proceed without more context, use context_request rather than stopping silently.${SUMMARY}"
  fi
fi

if [ "$KIND" = "findings" ]; then
  REASON=$(jq -r '
    if (.checks | type) != "array" or (.checks | length) == 0 then
      "the findings record no checks[] at all, so nothing proves any check ran"
    elif ([.checks[] | select(.status == "PASS" and (.exit_code == null or .exit_code == ""))] | length) > 0 then
      # An absent exit_code key compares equal to null in jq, covering both the
      # "reported null" and "omitted the field" cases.
      "a checks[] entry claims PASS with no real exit_code"
    else
      ""
    end' "$FRESH_FILE" 2>/dev/null || echo "the findings file is not readable as JSON")

  if [ -n "$REASON" ]; then
    block "[orchestrator] Your ${SOURCE} findings are unproven: ${REASON}. Re-run the checks and call write_findings again with the real exit code for every entry. A check that could not execute must be status=\"ERROR\" with exit_code=null, never PASS."
  fi

  STATUS=$(jq -r '.status // "UNKNOWN"' "$FRESH_FILE" 2>/dev/null || echo "UNKNOWN")
  jq -nc \
    --arg status "$STATUS" \
    --arg file "$FRESH_FILE" \
    --arg src "$SOURCE" \
    '{hookSpecificOutput: {hookEventName: "SubagentStop", additionalContext: ("[\($src)] stopped — status=\($status), findings at \($file)")}}'
else
  # Reports carry no status/checks[] — presence and freshness is the whole check.
  jq -e . "$FRESH_FILE" >/dev/null 2>&1 || block "[orchestrator] Your ${SOURCE} report at ${FRESH_FILE} is not readable as JSON. Call write_report again with source=\"${SOURCE}\"."
  jq -nc \
    --arg file "$FRESH_FILE" \
    --arg src "$SOURCE" \
    '{hookSpecificOutput: {hookEventName: "SubagentStop", additionalContext: ("[\($src)] stopped — report at \($file)")}}'
fi
