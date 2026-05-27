import os
import sys
import json
from pathlib import Path
import pytest

# Add mcp-server-py to path so we can import server
sys.path.insert(0, str(Path(__file__).parent.parent / "mcp-server-py"))

from server import write_findings, PROJECT_DIR

def test_write_findings(tmp_path, monkeypatch):
    # Mock PROJECT_DIR inside server to point to tmp_path
    monkeypatch.setattr("server.PROJECT_DIR", tmp_path)

    result = write_findings(
        source="checker",
        status="FAIL",
        errors={"compile": "error on line 5"},
        issues=["issue 1"]
    )

    expected_file = tmp_path / ".claude" / "pipeline" / "checker-findings.json"
    assert expected_file.exists()

    data = json.loads(expected_file.read_text())
    assert data["source"] == "checker"
    assert data["status"] == "FAIL"
    assert data["errors"] == {"compile": "error on line 5"}
    # checker does not write issues, reviewer does
    assert "issues" not in data

def test_write_findings_reviewer(tmp_path, monkeypatch):
    monkeypatch.setattr("server.PROJECT_DIR", tmp_path)

    result = write_findings(
        source="reviewer",
        status="APPROVED",
        issues=["no issues found"]
    )

    expected_file = tmp_path / ".claude" / "pipeline" / "reviewer-findings.json"
    assert expected_file.exists()

    data = json.loads(expected_file.read_text())
    assert data["source"] == "reviewer"
    assert data["status"] == "APPROVED"
    assert data["issues"] == ["no issues found"]
