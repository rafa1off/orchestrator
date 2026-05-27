import os
import json
import subprocess
from pathlib import Path
import pytest

HOOKS_DIR = Path(__file__).parent.parent / "hooks"
GUARD_SCRIPT = HOOKS_DIR / "guard-bash-readonly.sh"
POST_SCRIPT = HOOKS_DIR / "post-tool-findings.sh"

def test_guard_bash_safe():
    input_json = {
        "tool_input": {
            "command": "ls -la"
        }
    }
    proc = subprocess.run(
        ["bash", str(GUARD_SCRIPT)],
        input=json.dumps(input_json),
        text=True,
        capture_output=True
    )
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert proc.stderr == ""

def test_guard_bash_no_cmd():
    # Test case where command is empty or not in tool_input
    input_json = {
        "tool_input": {}
    }
    proc = subprocess.run(
        ["bash", str(GUARD_SCRIPT)],
        input=json.dumps(input_json),
        text=True,
        capture_output=True
    )
    assert proc.returncode == 0

def test_guard_bash_destructive_rm():
    input_json = {
        "tool_input": {
            "command": "rm -rf important_file"
        }
    }
    proc = subprocess.run(
        ["bash", str(GUARD_SCRIPT)],
        input=json.dumps(input_json),
        text=True,
        capture_output=True
    )
    assert proc.returncode == 2
    assert "Blocked: write or destructive Bash command not permitted" in proc.stderr

def test_guard_bash_destructive_git_push():
    input_json = {
        "tool_input": {
            "command": "git push origin main"
        }
    }
    proc = subprocess.run(
        ["bash", str(GUARD_SCRIPT)],
        input=json.dumps(input_json),
        text=True,
        capture_output=True
    )
    assert proc.returncode == 2
    assert "Blocked: write or destructive Bash command not permitted" in proc.stderr

def test_guard_bash_destructive_npm_install():
    input_json = {
        "tool_input": {
            "command": "npm install dotenv"
        }
    }
    proc = subprocess.run(
        ["bash", str(GUARD_SCRIPT)],
        input=json.dumps(input_json),
        text=True,
        capture_output=True
    )
    assert proc.returncode == 2
    assert "Blocked: write or destructive Bash command not permitted" in proc.stderr

def test_post_tool_findings_nonexistent(tmp_path):
    input_json = {
        "tool_input": {
            "source": "checker"
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
    findings_file = pipeline_dir / "checker-findings.json"
    
    findings_data = {
        "source": "checker",
        "status": "PASS",
        "errors": None
    }
    findings_file.write_text(json.dumps(findings_data))
    
    input_json = {
        "tool_input": {
            "source": "checker"
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
    assert "checker findings ready (status: PASS)" in additional_context
    assert '"status": "PASS"' in additional_context
