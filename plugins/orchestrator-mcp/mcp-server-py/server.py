#!/usr/bin/env python3
# /// script
# dependencies = ["fastmcp>=2.0.0"]
# ///
"""MCP dev-tools server — pipeline findings and report writer."""

import json
import os
import time
from pathlib import Path
from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
DEFAULT_PIPELINE = ".claude/pipeline"


class _Strict(BaseModel):
    # extra="forbid" is load-bearing, not decorative: the default extra="ignore"
    # silently drops unknown fields, so a schema guarantee (e.g. CheckerFindings
    # has no `issues`) degrades back into a mere convention. It also protects
    # against typos — a misspelled optional field would otherwise validate
    # silently with its declared default, instead of failing loudly.
    model_config = ConfigDict(extra="forbid")


# --- Findings models -------------------------------------------------------
# A findings payload is a verification claim: it asserts that checks actually ran.
# `checks: list[...] = Field(min_length=1)` on every findings model below rejects an
# empty-checks payload at the schema layer, before the tool body ever runs — see the
# note at the bottom of the module on why the old runtime check is now redundant.


class Check(_Strict):
    name: str
    status: Literal["PASS", "FAIL", "ERROR"]
    exit_code: int | None  # null ONLY when status == "ERROR"
    output: str


class Issue(_Strict):
    file: str
    line: int | None = None  # None when the issue is file-level, not line-level
    description: str


class Failure(_Strict):
    test: str
    classification: Literal["REGRESSION", "STALE_TEST", "FLAKY", "UNCLEAR"]
    evidence: str
    recommendation: str


class CheckerFindings(_Strict):
    source: Literal["checker"]
    status: Literal["PASS", "FAIL", "ERROR"]
    checks: list[Check] = Field(min_length=1)
    # NO `issues` field. checker performs no diff review, so reporting one is
    # unrepresentable rather than merely discouraged.


class ReviewerFindings(_Strict):
    source: Literal["reviewer"]
    status: Literal["PASS", "FAIL", "ERROR"]
    checks: list[Check] = Field(min_length=1)
    issues: list[Issue] = []


class TesterFindings(_Strict):
    source: Literal["tester"]
    status: Literal["PASS", "FAIL", "ERROR"]
    checks: list[Check] = Field(min_length=1)
    failures: list[Failure] = []


Findings = Annotated[
    CheckerFindings | ReviewerFindings | TesterFindings,
    Field(discriminator="source"),
]


# --- Report models -----------------------------------------------------------
# Reports are not proof-of-execution: reader, writer, thinker, and researcher run no
# commands, so there is no `checks[]` and no exit code here. The `SubagentStop` guard
# demands presence and freshness for reports, never exit codes.


class ContextRequest(_Strict):
    needs: list[str]  # what is missing, specifically
    why: str  # why the agent cannot proceed without it


class FileEntry(_Strict):
    path: str
    role: str  # what the file IS, not what was done to it


class Interface(_Strict):
    location: str  # "file:line"
    signature: str  # signature only, no body


class Convention(_Strict):
    rule: str
    precedent: str  # "file:line" — REQUIRED. No citation, no convention.
    split: str | None = None  # set when the rule holds in some files and not others


class ReaderReport(_Strict):
    source: Literal["reader"]
    relevant_files: list[FileEntry]
    interfaces: list[Interface] = []
    conventions: list[Convention] = []
    entry_points: list[str] = []
    test_files: list[str] = []
    context_request: ContextRequest | None = None


class ModifiedFile(_Strict):
    path: str
    change: str  # one line: what changed
    in_scope: bool = True  # False = was not in `## Files to modify`
    note: str | None = None  # why, when in_scope is False


class WriterReport(_Strict):
    source: Literal["writer"]
    modified: list[ModifiedFile]
    context_request: ContextRequest | None = None


class Option(_Strict):
    name: str
    summary: str
    tradeoffs: str


class ThinkerReport(_Strict):
    source: Literal["thinker"]
    mode: Literal["analysis", "brainstorming", "qa"]
    findings: str | None = None  # analysis mode
    assessment: str | None = None  # analysis mode
    options: list[Option] = []  # brainstorming mode
    answer: str | None = None  # qa mode
    evidence: str | None = None  # qa mode
    recommendation: str  # REQUIRED in every mode
    caveats: list[str] = []
    context_request: ContextRequest | None = None


class Reference(_Strict):
    claim: str
    source: str  # URL or doc path — REQUIRED
    checked: str | None = None  # date or version the claim was true for


class ResearcherReport(_Strict):
    source: Literal["researcher"]
    prior_decisions: list[Reference] = []
    api_reference: list[Reference] = []
    recommended_approach: str
    caveats: list[str] = []
    context_request: ContextRequest | None = None


Report = Annotated[
    ReaderReport | WriterReport | ThinkerReport | ResearcherReport,
    Field(discriminator="source"),
]


mcp = FastMCP("dev-tools")


def _pipeline_dir(pipeline: str | None) -> Path:
    pipeline_dir = PROJECT_DIR / (pipeline or DEFAULT_PIPELINE)
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    return pipeline_dir


@mcp.tool()
def write_findings(findings: Findings, pipeline: str | None = None) -> str:
    """
    Write findings to .claude/pipeline/<source>-findings.json. Always call — even on
    PASS. `exit_code` is null only when a check's own `status` is "ERROR"; a check that
    could not execute at all must still be reported as a checks[] entry with
    status="ERROR" (exit_code=null), never omitted — omission is indistinguishable from
    a run that never happened.
    pipeline: optional override for multi-track runs, e.g. '.claude/pipeline/track-a'
    """
    pipeline_dir = _pipeline_dir(pipeline)

    payload = findings.model_dump(mode="json")
    payload.pop("source", None)
    payload.pop("status", None)
    out = {
        "source": findings.source,
        "status": findings.status,
        "written_at": int(time.time()),
        **payload,
    }

    out_path = pipeline_dir / f"{findings.source}-findings.json"
    out_path.write_text(json.dumps(out, indent=2))
    return f"wrote {pipeline or DEFAULT_PIPELINE}/{findings.source}-findings.json"


@mcp.tool()
def write_report(report: Report, pipeline: str | None = None) -> str:
    """
    Write a report to .claude/pipeline/<source>-report.json. Always call, even when
    there is nothing noteworthy to say. `context_request` is how an agent signals it
    cannot proceed — set it instead of writing a "## Context Request" heading in prose;
    the orchestrator branches on `report.context_request is not None`. A report is not
    proof-of-execution: it carries no checks[] or exit codes.
    pipeline: optional override for multi-track runs, e.g. '.claude/pipeline/track-a'
    """
    pipeline_dir = _pipeline_dir(pipeline)

    payload = report.model_dump(mode="json")
    payload.pop("source", None)
    out = {
        "source": report.source,
        "written_at": int(time.time()),
        **payload,
    }

    out_path = pipeline_dir / f"{report.source}-report.json"
    out_path.write_text(json.dumps(out, indent=2))
    return f"wrote {pipeline or DEFAULT_PIPELINE}/{report.source}-report.json"


if __name__ == "__main__":
    mcp.run(transport="stdio")
