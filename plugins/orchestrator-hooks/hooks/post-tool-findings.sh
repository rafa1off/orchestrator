#!/usr/bin/env bash
# PostToolUse hook: after write_findings succeeds, inject findings content as additionalContext
# so the orchestrator receives results automatically without a manual cat step.
set -euo pipefail

command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat)
SOURCE=$(echo "$INPUT" | jq -r '.tool_input.source // empty' 2>/dev/null)
[ -z "$SOURCE" ] && exit 0

# Multi-track runs pass a pipeline override (e.g. .claude/pipeline/track-a); reading
# only the default path here skipped the proof-of-execution guard below for every
# parallel track.
PIPELINE=$(echo "$INPUT" | jq -r '.tool_input.pipeline // empty' 2>/dev/null)
FILE="${CLAUDE_PROJECT_DIR}/${PIPELINE:-.claude/pipeline}/${SOURCE}-findings.json"
[ -f "$FILE" ] || exit 0

STATUS=$(jq -r '.status // "unknown"' "$FILE" 2>/dev/null || echo "unknown")
CONTENT=$(cat "$FILE")

# Proof-of-execution guard: block checker/reviewer/tester findings that do not
# substantiate their own claim. Backgrounded checker, reviewer, and tester agents can
# have Bash auto-denied (lint/typecheck or the test suite); this catches a silent skip
# reported as a false PASS.
#
# The guard asserts positive evidence, not just well-formed failure reporting. Checking
# only `.checks[]?` let `{"source":"checker","status":"PASS"}` — no checks at all — through
# as a green result, because an empty iteration satisfies every "no bad entry" test. An
# absent or empty `checks` list is now the first thing rejected.
#
# ERROR is NOT blocked, and that is deliberate. Blocking it made honest failure
# unreportable: an agent that cannot write "this check could not run" is left with only
# PASS and FAIL, both of which are false, so the guard was pushing toward the exact lie it
# exists to catch. An ERROR is not an unproven claim — it is the claim being withdrawn.
# It passes through, loudly flagged, and the orchestrator decides.
#
# What still blocks is an unproven *green*: no checks at all, a PASS entry with no real
# exit code, or an overall PASS sitting on top of a check that errored.
if [ "$SOURCE" = "checker" ] || [ "$SOURCE" = "reviewer" ] || [ "$SOURCE" = "tester" ]; then
  REASON=$(jq -r '
    if (.checks | type) != "array" or (.checks | length) == 0 then
      "no checks[] recorded — nothing proves any check ran"
    elif (.status == "PASS" and ([.checks[] | select(.status == "ERROR")] | length) > 0) then
      "overall status is PASS but a checks[] entry is ERROR — a check that did not run cannot be part of a pass"
    elif ([.checks[] | select(.status == "PASS" and (.exit_code == null or .exit_code == ""))] | length) > 0 then
      # An absent exit_code key compares equal to null in jq, so this covers both
      # "reported null" and "omitted the field entirely".
      "a checks[] entry claims PASS with no real exit_code"
    else
      ""
    end' "$FILE" 2>/dev/null || echo "findings file is not readable as JSON")

  if [ -n "$REASON" ]; then
    echo "[orchestrator] BLOCKED: ${SOURCE} findings are unproven — ${REASON}. A ${SOURCE} result is only trustworthy when every checks[] entry carries the real process exit_code. Likely cause: a Bash command was auto-denied (check the README Bash allow-rules), the agent ran out of turns, or it reported without running anything. Re-run ${SOURCE} and report the actual exit codes. If a check genuinely could not execute, report it as status=\"ERROR\" — that is accepted." >&2
    exit 2
  fi

  # Not blocked, but an errored check must not slide past as ordinary output.
  ERRORED=$(jq -r '[.checks[]? | select(.status == "ERROR") | .name] | join(", ")' "$FILE" 2>/dev/null || echo "")
  if [ -n "$ERRORED" ]; then
    STATUS="${STATUS} — ERRORED CHECKS: ${ERRORED} (did not run; not covered by this result)"
  fi
fi

jq -nc \
  --arg src "$SOURCE" \
  --arg status "$STATUS" \
  --arg content "$CONTENT" \
  '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: ("[orchestrator] \($src) findings ready (status: \($status)):\n\($content)")}}'
