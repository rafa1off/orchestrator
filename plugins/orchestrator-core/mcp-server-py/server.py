#!/usr/bin/env python3
# /// script
# dependencies = ["fastmcp>=2.0.0"]
# ///
"""MCP dev-tools server — pipeline findings writer."""

from fastmcp import FastMCP
import json
import os
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("GEMINI_PROJECT_DIR", os.getcwd()))
DEFAULT_PIPELINE = ".gemini/pipeline"

mcp = FastMCP("dev-tools")


@mcp.tool()
def write_findings(
    source: str,
    status: str,
    pipeline: str | None = None,
    errors: dict | None = None,
    issues: list[str] | None = None,
    lint: dict | None = None,
    typecheck: dict | None = None,
    review: dict | None = None,
) -> str:
    """
    Write checker, reviewer, or verify findings to .gemini/pipeline/<source>-findings.json.
    Always call — even on PASS.
    source: 'checker' | 'reviewer' | 'verify'
    status: 'PASS'|'FAIL' (checker/verify) or 'APPROVED'|'ISSUES' (reviewer)
    pipeline: optional override for multi-track runs, e.g. '.gemini/pipeline/track-a'
    """
    pipeline_dir = PROJECT_DIR / (pipeline or DEFAULT_PIPELINE)
    pipeline_dir.mkdir(parents=True, exist_ok=True)

    findings: dict = {"source": source, "status": status}
    if source == "checker" and errors:
        findings["errors"] = errors
    if source == "reviewer" and issues:
        findings["issues"] = issues

    # Support for verify findings format and metadata parameters
    if source == "verify":
        if errors:
            findings["errors"] = errors
        if issues:
            findings["issues"] = issues
        if lint:
            findings["lint"] = lint
        if typecheck:
            findings["typecheck"] = typecheck
        if review:
            findings["review"] = review

    out_path = pipeline_dir / f"{source}-findings.json"
    out_path.write_text(json.dumps(findings, indent=2))
    return f"wrote {pipeline or DEFAULT_PIPELINE}/{source}-findings.json"


if __name__ == "__main__":
    mcp.run(transport="stdio")
