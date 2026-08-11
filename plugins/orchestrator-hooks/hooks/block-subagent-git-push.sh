#!/usr/bin/env bash
# PreToolUse hook: block writer/verify/tester from running git push or opening/merging/editing PRs.
# Reason: Claude Code v2.1.198+ makes background agents auto-commit/push/open draft PRs on completion.
# writer/verify/tester run background:true routinely in this ecosystem, and there's no user in the
# loop to confirm a push from inside a subagent — so it's blocked outright, not just asked for.
set -euo pipefail

command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat)
AGENT=$(echo "$INPUT" | jq -r '.agent_type // empty' 2>/dev/null)
# `agent_type` is the definition type when dispatched as a subagent, but the teammate's
# NAME in team mode. Resolve both to the definition type so this guard covers either
# dispatch path — matching the raw value silently no-ops on every teammate.
# shellcheck source=lib-resolve-agent-identity.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib-resolve-agent-identity.sh"
AGENT=$(resolve_agent_identity "$AGENT" "$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)")
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

[ -z "$AGENT" ] && exit 0
[ -z "$CMD" ] && exit 0

case "$AGENT" in
  orchestrator-agents:writer|orchestrator-agents:verify|orchestrator-agents:tester) ;;
  *) exit 0 ;;
esac

# Separators include newlines, subshells, and command substitution — not just && ; | —
# and `git` accepts global options before its subcommand, so matching a literal
# "git push" let `git -C /path push`, `git --no-pager -C /r push`, `env git push`,
# `$(git push)` and any newline-separated line all through. Newlines are normalised to
# `;` so a multi-line script is scanned per command; the option group also consumes a
# flag's argument (`-C /repo`) so `push` is still recognised as the subcommand.
# Verified not to fire on git status/commit/log/remote, including `git log --grep push`.
if echo "$CMD" | tr '\n' ';' | grep -qE '(^|&&|;|\||\(|`)[[:space:]]*(env[[:space:]]+)?git([[:space:]]+-[^[:space:]]+([[:space:]]+[^-[:space:]][^[:space:]]*)?)*[[:space:]]+push|(^|&&|;|\||\(|`)[[:space:]]*gh[[:space:]]+pr[[:space:]]+(create|merge|edit)'; then
  echo "[orchestrator-hooks] BLOCKED: $AGENT attempted a remote-facing operation ($CMD). Subagents may not push, open, or merge PRs — return the result to the orchestrator instead." >&2
  exit 2
fi

exit 0
