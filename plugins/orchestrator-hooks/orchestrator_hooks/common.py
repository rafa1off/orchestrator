"""Common helpers for orchestrator python hooks."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def read_hook_input() -> dict[str, Any]:
    """Read JSON input from sys.stdin safely."""
    try:
        content = sys.stdin.read().strip()
        if not content:
            return {}
        return json.loads(content)
    except (json.JSONDecodeError, OSError, ValueError):
        return {}


def resolve_project_dir(hook_input: dict[str, Any] | None = None) -> Path:
    """Resolve the active workspace/project directory."""
    data = hook_input or {}
    workspaces = data.get("workspacePaths") or []
    if workspaces and isinstance(workspaces, list) and workspaces[0]:
        return Path(workspaces[0])

    env_dir = (
        os.environ.get("ORCHESTRATOR_PROJECT_DIR")
        or os.environ.get("GEMINI_PROJECT_DIR")
        or os.environ.get("CLAUDE_PROJECT_DIR")
    )
    if env_dir:
        return Path(env_dir)

    return Path.cwd()


def resolve_pipeline_dir(project_dir: Path, pipeline_override: str | None = None) -> Path:
    """Resolve the pipeline directory, supporting custom pipeline tracks and .gemini/.claude."""
    if pipeline_override:
        return project_dir / pipeline_override

    if env_pipe := os.environ.get("ORCHESTRATOR_PIPELINE_DIR"):
        return project_dir / env_pipe

    for candidate in [".gemini", ".orchestrator", ".claude"]:
        if (project_dir / candidate).is_dir():
            return project_dir / candidate / "pipeline"

    return project_dir / ".gemini" / "pipeline"


def emit_decision(decision: str, reason: str = "", **extra: Any) -> None:
    """Emit a hook decision JSON to stdout and exit 0."""
    payload = {"decision": decision, **extra}
    if reason:
        payload["reason"] = reason
    print(json.dumps(payload))
    sys.exit(0)


def emit_context(context_text: str, **extra: Any) -> None:
    """Emit additional context JSON to stdout and exit 0."""
    payload = {"additionalContext": context_text, **extra}
    print(json.dumps(payload))
    sys.exit(0)
