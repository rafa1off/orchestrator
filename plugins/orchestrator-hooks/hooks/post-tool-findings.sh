#!/usr/bin/env bash
# PostToolUse hook: after write_findings or write_report succeeds, inject the file's
# content as additionalContext so the orchestrator receives results automatically without
# a manual cat step. Generalised (rather than split into a sibling) because both tools
# share the same "read tool_input, locate the file, inject additionalContext" shape and
# differ only in whether proof-of-execution applies — one `if` branch expresses that
# difference more clearly than duplicating the whole script. The name now undersells the
# report half of its job; left as-is since renaming is a deliberate hooks.json + test
# change, not this task's call to make.
#
# The proof-of-execution check below applies ONLY to findings (checker/reviewer/tester).
# Reports (reader/writer/thinker/researcher) are not proof-of-execution — reader runs no
# commands, so a report has no checks[] and no exit codes (cs3-schema.md Part 2,
# "Deliberate non-goals") — and must never be run through this check.
set -euo pipefail

command -v jq >/dev/null 2>&1 || exit 0

# write_findings and write_report each take a single nested model argument now
# (`findings`/`report`), not flat top-level fields, so `.tool_input.source` no longer
# resolves under either tool and must not be read directly. The key that is present
# (`findings` or `report`) tells us both the source and which kind of payload this is.
INPUT=$(cat)
SOURCE=$(echo "$INPUT" | jq -r '.tool_input.findings.source // .tool_input.report.source // empty' 2>/dev/null)
[ -z "$SOURCE" ] && exit 0

if echo "$INPUT" | jq -e '.tool_input.report // empty' >/dev/null 2>&1; then
  SUFFIX="report"
else
  SUFFIX="findings"
fi

# Multi-track runs pass a pipeline override (e.g. .claude/pipeline/track-a); reading
# only the default path here skipped the proof-of-execution guard below for every
# parallel track.
PIPELINE=$(echo "$INPUT" | jq -r '.tool_input.pipeline // empty' 2>/dev/null)
FILE="${CLAUDE_PROJECT_DIR}/${PIPELINE:-.claude/pipeline}/${SOURCE}-${SUFFIX}.json"
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

if [ "$SUFFIX" = "report" ]; then
  jq -nc \
    --arg src "$SOURCE" \
    --arg content "$CONTENT" \
    '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: ("[orchestrator] \($src) report ready:\n\($content)")}}'
else
  jq -nc \
    --arg src "$SOURCE" \
    --arg status "$STATUS" \
    --arg content "$CONTENT" \
    '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: ("[orchestrator] \($src) findings ready (status: \($status)):\n\($content)")}}'
fi
