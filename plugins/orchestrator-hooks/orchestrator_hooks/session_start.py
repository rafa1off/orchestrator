"""SessionStart hook: Cleans transient findings, reports, and logs."""

from __future__ import annotations

import shutil
import sys

from orchestrator_hooks.common import (
    read_hook_input,
    resolve_project_dir,
)


def clean_pipeline_dir(pipeline_dir) -> None:
    if not pipeline_dir.is_dir():
        return

    transient_patterns = [
        "*-findings.json",
        "*-report.json",
        "pre-compact-snapshot.md",
        "write-log.tsv",
        "identity-audit.jsonl",
    ]

    for pat in transient_patterns:
        for f in pipeline_dir.glob(pat):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
        # Also clean track subdirectories (e.g. track-a/*-findings.json)
        for f in pipeline_dir.glob(f"*/{pat}"):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass

    starts_dir = pipeline_dir / ".starts"
    if starts_dir.is_dir():
        try:
            shutil.rmtree(starts_dir, ignore_errors=True)
        except OSError:
            pass


def main() -> None:
    data = read_hook_input()
    project_dir = resolve_project_dir(data)
    # Check both .gemini/pipeline and .claude/pipeline if they exist
    for candidate in [".gemini", ".claude", ".orchestrator"]:
        pipe_dir = project_dir / candidate / "pipeline"
        clean_pipeline_dir(pipe_dir)
    sys.exit(0)


if __name__ == "__main__":
    main()
