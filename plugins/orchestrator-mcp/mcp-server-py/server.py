#!/usr/bin/env python3
# /// script
# dependencies = ["fastmcp>=2.0.0"]
# ///
"""MCP dev-tools server — pipeline findings writer."""

import json
import os
import time
from pathlib import Path

from fastmcp import FastMCP

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
DEFAULT_PIPELINE = ".claude/pipeline"

# Sources whose findings are a verification claim: an empty or absent `checks` list
# means "nothing ran", which must be distinguishable on disk from "checks ran and
# passed". Recording the key verbatim lets the PostToolUse guard reject the former.
PROOF_REQUIRED_SOURCES = frozenset({"checker", "reviewer", "tester"})

mcp = FastMCP("dev-tools")


@mcp.tool()
def write_findings(
    source: str,
    status: str,
    pipeline: str | None = None,
    checks: list[dict] | None = None,
    issues: list[str] | None = None,
    failures: list[dict] | None = None,
) -> str:
    """
    Write findings to .claude/pipeline/<source>-findings.json.
    Always call — even on PASS/APPROVED.
    source: 'checker' | 'reviewer' | 'tester'. checker reports lint/typecheck/build
            checks, reviewer reports diff-review issues[], and tester reports suite
            checks[] plus classified failures[].
    status: 'PASS'|'FAIL'|'ERROR'
    pipeline: optional override for multi-track runs, e.g. '.claude/pipeline/track-a'
    checks: list of {name, status, exit_code, output} dicts — REQUIRED and non-empty
            for checker, reviewer, and tester. One entry per check/suite actually
            executed, each carrying the real process exit_code. A PostToolUse guard
            rejects a checker/reviewer/tester payload with no checks: an
            unsubstantiated PASS is indistinguishable from a run that never happened.
    issues: list of issue strings (reviewer's diff-review findings)
    failures: list of {test, classification, evidence, recommendation} dicts (used by
              tester); classification is REGRESSION|STALE_TEST|FLAKY|UNCLEAR
    `checks`, `issues`, and `failures` are recorded verbatim when supplied — an empty
    list is written as an empty list, never dropped, so "nothing ran" stays visible.
    """
    if source in PROOF_REQUIRED_SOURCES and not checks:
        raise ValueError(
            f"{source} findings require a non-empty `checks` list: one entry per check "
            "or suite actually executed, each with the real process exit_code. A claim "
            "with no checks cannot be told apart from a run that never happened. If no "
            'check could execute, report status="ERROR" with a checks entry describing '
            "why (exit_code=null)."
        )

    pipeline_dir = PROJECT_DIR / (pipeline or DEFAULT_PIPELINE)
    pipeline_dir.mkdir(parents=True, exist_ok=True)

    findings: dict = {
        "source": source,
        "status": status,
        "written_at": int(time.time()),
    }
    if checks is not None:
        findings["checks"] = checks
    if issues is not None:
        findings["issues"] = issues
    if failures is not None:
        findings["failures"] = failures

    out_path = pipeline_dir / f"{source}-findings.json"
    out_path.write_text(json.dumps(findings, indent=2))
    return f"wrote {pipeline or DEFAULT_PIPELINE}/{source}-findings.json"


if __name__ == "__main__":
    mcp.run(transport="stdio")
