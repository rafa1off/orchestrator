import os
import json
import subprocess
from pathlib import Path
import pytest

HOOKS_DIR = Path(__file__).parent.parent / "hooks"
POST_SCRIPT = HOOKS_DIR / "post-tool-findings.sh"

def test_post_tool_findings_nonexistent(tmp_path):
    input_json = {
        "tool_input": {
            "source": "verify"
        }
    }
    
    # Run hook when findings file doesn't exist; should exit 0 and produce no output
    proc = subprocess.run(
        ["bash", str(POST_SCRIPT)],
        input=json.dumps(input_json),
        text=True,
        capture_output=True,
        env={"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": os.environ["PATH"]}
    )
    
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""

def test_post_tool_findings_success(tmp_path):
    # Setup mock findings
    pipeline_dir = tmp_path / ".claude" / "pipeline"
    pipeline_dir.mkdir(parents=True)
    findings_file = pipeline_dir / "verify-findings.json"
    
    findings_data = {
        "source": "verify",
        "status": "FAIL",
        "lint": {"status": "FAIL", "output": "ruff error"},
        "typecheck": {"status": "PASS", "output": ""},
        "review": {"status": "APPROVED", "issues": []}
    }
    findings_file.write_text(json.dumps(findings_data))
    
    input_json = {
        "tool_input": {
            "source": "verify"
        }
    }
    
    proc = subprocess.run(
        ["bash", str(POST_SCRIPT)],
        input=json.dumps(input_json),
        text=True,
        capture_output=True,
        env={"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": os.environ["PATH"]}
    )
    
    assert proc.returncode == 0
    output_data = json.loads(proc.stdout)
    assert "hookSpecificOutput" in output_data
    assert "additionalContext" in output_data["hookSpecificOutput"]
    
    additional_context = output_data["hookSpecificOutput"]["additionalContext"]
    assert "verify findings ready (status: FAIL)" in additional_context
    assert '"status": "FAIL"' in additional_context
