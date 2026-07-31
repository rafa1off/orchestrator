#!/usr/bin/env bash
# SubagentStart hook: record when a verify/tester agent began, keyed by agent_id.
#
# This is the other half of the freshness check in subagent-stop-findings-guard.sh.
# Without a start time there is no way to tell a findings file this agent just wrote
# from one left behind by an earlier round or a sibling track — and "stale file that
# happens to say PASS" was the exact route by which the proof-of-execution chain
# reported green while verifying nothing.
set -euo pipefail

command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat)
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // empty' 2>/dev/null)
AGENT=$(echo "$INPUT" | jq -r '.agent_type // empty' 2>/dev/null)
[ -z "$AGENT_ID" ] && exit 0
[ -z "$AGENT" ] && exit 0

STAMP_DIR="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/pipeline/.starts"
mkdir -p "$STAMP_DIR" 2>/dev/null || exit 0
date -u +%s > "$STAMP_DIR/${AGENT_ID}" 2>/dev/null || true

exit 0
