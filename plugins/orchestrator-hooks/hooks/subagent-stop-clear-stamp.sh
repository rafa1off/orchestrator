#!/usr/bin/env bash
# SubagentStop hook: clear a writer's start stamp so the file is a liveness signal.
#
# track-writer-overlap.sh needs to tell "another writer is editing this file right now"
# (the invariant-3 violation, which silently loses edits) from "another writer edited it
# and finished an hour ago" (serialization — exactly what the invariant asks for). Without
# a stop signal it could only see "a different agent id appears in the log", so every
# sequential second writer was reported as an overlap. False positives train the reader to
# ignore the warning, which costs more than the warning was ever worth.
#
# Stamp present = that agent is still running. Removed = it finished.
#
# While the stamp is in hand, this is also the only point that ever knows both when an
# agent started and when it stopped. Logging the difference to
# .claude/metrics/agent-timings.tsv turns "this agent is slow" from a hunch into a number
# someone can query — without it there is no record to falsify the claim against.
set -euo pipefail

command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat)
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // empty' 2>/dev/null)
AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // empty' 2>/dev/null)
[ -z "$AGENT_ID" ] && exit 0

# Guard against a crafted agent_id escaping the stamp directory.
case "$AGENT_ID" in
  */*|..*) exit 0 ;;
esac

STAMP_DIR="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/pipeline/.starts"
STAMP_FILE="$STAMP_DIR/${AGENT_ID}"

# Log elapsed duration before the stamp is removed. Every failure path here falls through
# to the rm -f below rather than exiting — a stale stamp would make
# track-writer-overlap.sh report a finished writer as an active overlap, which is exactly
# the false positive this file's header exists to prevent, so logging must never skip it.
if [ -f "$STAMP_FILE" ]; then
  START_EPOCH=$(cat "$STAMP_FILE" 2>/dev/null || echo "")
  case "$START_EPOCH" in
    ''|*[!0-9]*) START_EPOCH="" ;;
  esac
  if [ -n "$START_EPOCH" ]; then
    NOW_EPOCH=$(date -u +%s 2>/dev/null || echo "")
    if [ -n "$NOW_EPOCH" ]; then
      ELAPSED=$((NOW_EPOCH - START_EPOCH))
      LOG="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/metrics/agent-timings.tsv"
      if mkdir -p "$(dirname "$LOG")" 2>/dev/null; then
        printf '%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$AGENT_TYPE" "$ELAPSED" >> "$LOG" 2>/dev/null || true

        # Bounded, mirroring agent-identity-audit.sh: this fires on every guarded stop, so
        # an unbounded log would grow without limit across a long session.
        LINES=$(wc -l < "$LOG" 2>/dev/null || echo 0)
        case "$LINES" in ''|*[!0-9]*) LINES=0 ;; esac
        if [ "$LINES" -gt 2000 ]; then
          tail -n 1000 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG" 2>/dev/null || true
        fi
      fi
    fi
  fi
fi

rm -f "$STAMP_FILE" 2>/dev/null || true

exit 0
