"""PreToolUse hook: Prevents remote-facing commands (git push, gh pr)."""

from __future__ import annotations

import re
from typing import Any

from orchestrator_hooks.common import emit_decision, read_hook_input

# Matches git push and gh pr create/merge/edit with arbitrary flags or prefix commands
# E.g.: git push, git -C /path push, env git push, gh pr create
_GIT_PUSH_PATTERN = re.compile(
    r"(?:^|[;&|`\n]|\$\()\s*(?:env\s+)?git(?:\s+-[^\s]+(?:\s+[^-][^\s]*)?)*\s+push\b",
    re.IGNORECASE,
)
_GH_PR_PATTERN = re.compile(
    r"(?:^|[;&|`\n]|\$\()\s*gh\s+pr\s+(?:create|merge|edit)\b",
    re.IGNORECASE,
)


def check_command(cmd: str) -> tuple[bool, str]:
    """Check if command is blocked. Returns (is_blocked, reason)."""
    if not cmd:
        return False, ""

    if _GIT_PUSH_PATTERN.search(cmd):
        return (
            True,
            (
                f"BLOCKED: Remote-facing operation ({cmd.strip()[:60]}...). "
                "Subagents may not push to remote repositories. Return results to orchestrator instead."
            ),
        )

    if _GH_PR_PATTERN.search(cmd):
        return (
            True,
            (
                f"BLOCKED: Pull Request operation ({cmd.strip()[:60]}...). "
                "Subagents may not create, merge, or edit PRs."
            ),
        )

    return False, ""


def main() -> None:
    data = read_hook_input()
    tool_call: dict[str, Any] = data.get("toolCall") or data.get("tool_call") or {}
    args = tool_call.get("args") or data.get("tool_input", {})

    cmd = args.get("CommandLine") or args.get("command") or args.get("cmd") or ""

    is_blocked, reason = check_command(cmd)
    if is_blocked:
        emit_decision("deny", reason)

    emit_decision("allow")


if __name__ == "__main__":
    main()
