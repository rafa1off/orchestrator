"""PostToolUse hook: Proof-of-execution guard and additionalContext injector."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from orchestrator_hooks.common import (
    emit_context,
    read_hook_input,
    resolve_pipeline_dir,
    resolve_project_dir,
)


def check_proof_of_execution(findings: dict[str, Any]) -> tuple[bool, str]:
    """Validate findings proof of execution for checker/reviewer/tester."""
    source = findings.get("source")
    if source not in ("checker", "reviewer", "tester"):
        return True, ""

    checks = findings.get("checks")
    if not isinstance(checks, list) or len(checks) == 0:
        return False, f"Proof-of-execution violation: {source} reported without checks[]"

    status = findings.get("status")
    if status == "PASS":
        if any(c.get("status") == "ERROR" for c in checks if isinstance(c, dict)):
            return False, f"Proof-of-execution violation: {source} reported PASS over an ERROR check"
        if any(c.get("status") == "PASS" and c.get("exit_code") is None for c in checks if isinstance(c, dict)):
            return False, f"Proof-of-execution violation: {source} reported PASS with null exit_code"

    return True, ""


def find_latest_file(pipeline_dir: Path, source: str, suffix: str) -> Path | None:
    if not pipeline_dir.is_dir():
        return None
    matches = list(pipeline_dir.glob(f"{source}-*-{suffix}.json"))
    if not matches:
        return None
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0]


def main() -> None:
    data = read_hook_input()
    tool_call: dict[str, Any] = data.get("toolCall") or data.get("tool_call") or {}
    args = tool_call.get("args") or data.get("tool_input", {})

    findings_arg = args.get("findings")
    report_arg = args.get("report")

    if not findings_arg and not report_arg:
        sys.exit(0)

    is_report = report_arg is not None
    payload = report_arg if is_report else findings_arg
    source = payload.get("source") if isinstance(payload, dict) else ""
    suffix = "report" if is_report else "findings"

    project_dir = resolve_project_dir(data)
    pipeline_override = args.get("pipeline")
    pipeline_dir = resolve_pipeline_dir(project_dir, pipeline_override)

    latest_file = find_latest_file(pipeline_dir, source, suffix)
    if not latest_file:
        sys.exit(0)

    try:
        content_text = latest_file.read_text(encoding="utf-8")
        file_json = json.loads(content_text)
    except (json.JSONDecodeError, OSError):
        sys.exit(0)

    if not is_report:
        valid, reason = check_proof_of_execution(file_json)
        if not valid:
            emit_context(f"[ORCHESTRATOR-HOOK ALERT]: {reason}\nFile: {latest_file.name}")

    # Inject context so orchestrator receives the structured result automatically
    emit_context(f"[Pipeline Artifact: {latest_file.name}]\n{content_text}")


if __name__ == "__main__":
    main()
