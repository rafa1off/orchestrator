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


def record_active_workspace(project_dir: Path) -> None:
    """Record active project directory for tools and MCP servers to locate workspace."""
    try:
        marker = Path.home() / ".gemini" / "active_workspace.txt"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(project_dir.resolve()), encoding="utf-8")
    except OSError:
        pass


def resolve_project_dir(hook_input: dict[str, Any] | None = None) -> Path:
    """Resolve the active workspace/project directory."""
    data = hook_input or {}
    workspaces = data.get("workspacePaths") or []
    if workspaces and isinstance(workspaces, list) and workspaces[0]:
        resolved = Path(workspaces[0])
        record_active_workspace(resolved)
        return resolved

    env_dir = (
        os.environ.get("ORCHESTRATOR_PROJECT_DIR")
        or os.environ.get("GEMINI_PROJECT_DIR")
        or os.environ.get("CLAUDE_PROJECT_DIR")
    )
    if env_dir and env_dir != ".":
        resolved = Path(env_dir)
        record_active_workspace(resolved)
        return resolved

    marker = Path.home() / ".gemini" / "active_workspace.txt"
    if marker.is_file():
        try:
            recorded = marker.read_text(encoding="utf-8").strip()
            if recorded and Path(recorded).is_dir():
                return Path(recorded)
        except OSError:
            pass

    resolved = Path.cwd()
    record_active_workspace(resolved)
    return resolved


def resolve_pipeline_dir(project_dir: Path, pipeline_override: str | None = None) -> Path:
    """Resolve the pipeline directory, supporting custom pipeline tracks and .gemini/.claude."""
    if pipeline_override:
        p = Path(pipeline_override)
        return p if p.is_absolute() else project_dir / pipeline_override

    if env_pipe := os.environ.get("ORCHESTRATOR_PIPELINE_DIR"):
        return project_dir / env_pipe

    if (project_dir / ".gemini").is_dir():
        return project_dir / ".gemini" / "pipeline"

    if (project_dir / ".orchestrator").is_dir():
        return project_dir / ".orchestrator" / "pipeline"

    if (project_dir / ".claude").is_dir():
        return project_dir / ".claude" / "pipeline"

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
