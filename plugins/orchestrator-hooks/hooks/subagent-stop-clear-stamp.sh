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
set -euo pipefail

command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat)
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // empty' 2>/dev/null)
[ -z "$AGENT_ID" ] && exit 0

# Guard against a crafted agent_id escaping the stamp directory.
case "$AGENT_ID" in
  */*|..*) exit 0 ;;
esac

STAMP_DIR="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/pipeline/.starts"
rm -f "$STAMP_DIR/${AGENT_ID}" 2>/dev/null || true

exit 0
