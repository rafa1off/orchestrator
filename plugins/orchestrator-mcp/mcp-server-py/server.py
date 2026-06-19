#!/usr/bin/env python3
# /// script
# dependencies = ["fastmcp>=2.0.0"]
# ///
"""MCP dev-tools server — pipeline findings writer."""

from fastmcp import FastMCP
import json
import os
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
DEFAULT_PIPELINE = ".claude/pipeline"

mcp = FastMCP("dev-tools")


@mcp.tool()
def write_findings(
    source: str,
    status: str,
    pipeline: str | None = None,
    checks: list[dict] | None = None,
    issues: list[str] | None = None,
) -> str:
    """
    Write findings to .claude/pipeline/<source>-findings.json.
    Always call — even on PASS/APPROVED.
    source: 'verify' | 'checker' | 'reviewer'
    status: 'PASS'|'FAIL'|'ERROR' (verify/checker) or 'APPROVED'|'ISSUES' (reviewer)
    pipeline: optional override for multi-track runs, e.g. '.claude/pipeline/track-a'
    checks: list of {name, status, exit_code, output} dicts (used by verify)
    issues: list of issue strings (used by reviewer)
    """
    pipeline_dir = PROJECT_DIR / (pipeline or DEFAULT_PIPELINE)
    pipeline_dir.mkdir(parents=True, exist_ok=True)

    findings: dict = {"source": source, "status": status}
    if checks:
        findings["checks"] = checks
    if issues:
        findings["issues"] = issues

    out_path = pipeline_dir / f"{source}-findings.json"
    out_path.write_text(json.dumps(findings, indent=2))
    return f"wrote {pipeline or DEFAULT_PIPELINE}/{source}-findings.json"


if __name__ == "__main__":
    mcp.run(transport="stdio")
