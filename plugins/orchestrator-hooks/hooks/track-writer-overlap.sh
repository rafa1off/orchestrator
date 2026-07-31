#!/usr/bin/env bash
# PostToolUse hook: record which writer agent touched which file, and flag it when two
# different writers touch the same one.
#
# "One writer per overlapping file set" is a core invariant with, until now, no
# enforcement at all — it was prose in the skill, and the only mitigation was an
# instruction to escalate AFTER the conflict had already happened. It is also the
# invariant whose violation actually corrupts work: two parallel writers editing one
# file silently lose edits.
#
# Detection, not blocking: a writer legitimately revisits its own files across verify
# rounds, and a serialized second writer on the same file is a valid L1 pattern. Only
# concurrent DIFFERENT writers are the bug, and the hook cannot know the orchestrator's
# intent — so it reports rather than refuses. The log is left at
# .claude/pipeline/write-log.tsv for the orchestrator to inspect.
set -euo pipefail

command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat)
AGENT=$(echo "$INPUT" | jq -r '.agent_type // empty' 2>/dev/null)
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // empty' 2>/dev/null)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty' 2>/dev/null)

[ -z "$AGENT" ] && exit 0
[ -z "$FILE" ] && exit 0

case "$AGENT" in
  *writer) ;;
  *) exit 0 ;;
esac

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
REL="${FILE#"$PROJECT_DIR"/}"
LOG="$PROJECT_DIR/.claude/pipeline/write-log.tsv"
mkdir -p "$(dirname "$LOG")" 2>/dev/null || exit 0

AGENT_ID="${AGENT_ID:-unknown}"

# Any prior writer on this path that is not this agent.
OTHER=""
if [ -f "$LOG" ]; then
  OTHER=$(awk -F'\t' -v path="$REL" -v self="$AGENT_ID" \
    '$2 == path && $1 != self { print $1; exit }' "$LOG" 2>/dev/null || true)
fi

printf '%s\t%s\t%s\n' "$AGENT_ID" "$REL" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG" 2>/dev/null || true

if [ -n "$OTHER" ]; then
  jq -nc --arg path "$REL" --arg other "$OTHER" --arg log "$LOG" \
    '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: ("[orchestrator] WRITER OVERLAP: \($path) was already modified by a different writer agent (\($other)) this session. If both writers are running in parallel, the disjoint-file invariant was violated and one set of edits may be lost — report this path and both agents to the orchestrator instead of continuing silently. Write log: \($log)")}}'
fi

exit 0
