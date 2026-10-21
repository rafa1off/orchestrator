"""Stop / SessionEnd hook: Cleans transient findings and writes session-log."""

from __future__ import annotations

import sys
from datetime import UTC, datetime

from orchestrator_hooks.common import read_hook_input, resolve_project_dir
from orchestrator_hooks.session_start import clean_pipeline_dir


def record_session_end(pipeline_dir) -> None:
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    log_file = pipeline_dir / "session-log.txt"

    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = []
    if log_file.is_file():
        try:
            lines = log_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            pass

    lines.append(f"{now_iso} session-end")
    if len(lines) > 500:
        lines = lines[-500:]

    try:
        log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


def main() -> None:
    data = read_hook_input()
    project_dir = resolve_project_dir(data)
    for candidate in [".gemini", ".claude", ".orchestrator"]:
        pipe_dir = project_dir / candidate / "pipeline"
        if pipe_dir.parent.is_dir():
            record_session_end(pipe_dir)
            clean_pipeline_dir(pipe_dir)
    sys.exit(0)


if __name__ == "__main__":
    main()
