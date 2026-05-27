import os
import sys
import json
from pathlib import Path
import pytest

# Add mcp-server-py to path so we can import server
sys.path.insert(0, str(Path(__file__).parent.parent / "mcp-server-py"))

from server import _detect_stack, StackConfig, write_findings, STACK, PROJECT_DIR

def test_detect_stack_unknown(tmp_path):
    # Empty directory should return unknown
    stack = _detect_stack(tmp_path)
    assert stack.name == "unknown"
    assert stack.lint == []
    assert stack.typecheck is None
    assert stack.test == []

def test_detect_stack_python_uv(tmp_path):
    # uv.lock present
    (tmp_path / "uv.lock").touch()
    stack = _detect_stack(tmp_path)
    assert stack.name == "python"
    assert "uv" in stack.lint
    assert "pytest" in stack.test

def test_detect_stack_python_pip(tmp_path):
    # requirements.txt present
    (tmp_path / "requirements.txt").touch()
    stack = _detect_stack(tmp_path)
    assert stack.name == "python"
    assert "python" in stack.lint
    assert "pytest" in stack.test

def test_detect_stack_typescript(tmp_path):
    (tmp_path / "package.json").touch()
    (tmp_path / "tsconfig.json").touch()
    stack = _detect_stack(tmp_path)
    assert stack.name == "typescript"
    assert "eslint" in stack.lint
    assert "tsc" in stack.typecheck
    assert "jest" in stack.test

def test_detect_stack_javascript(tmp_path):
    (tmp_path / "package.json").touch()
    stack = _detect_stack(tmp_path)
    assert stack.name == "javascript"
    assert "eslint" in stack.lint
    assert stack.typecheck is None
    assert "jest" in stack.test

def test_detect_stack_go(tmp_path):
    (tmp_path / "go.mod").touch()
    stack = _detect_stack(tmp_path)
    assert stack.name == "go"
    assert "go" in stack.lint
    assert "go" in stack.test
    assert not stack.scoped_lint

def test_detect_stack_rust(tmp_path):
    (tmp_path / "Cargo.toml").touch()
    stack = _detect_stack(tmp_path)
    assert stack.name == "rust"
    assert "cargo" in stack.lint
    assert "cargo" in stack.test
    assert not stack.scoped_lint

def test_detect_stack_ruby(tmp_path):
    (tmp_path / "Gemfile").touch()
    stack = _detect_stack(tmp_path)
    assert stack.name == "ruby"
    assert "rubocop" in stack.lint
    assert "rspec" in stack.test

def test_detect_stack_java_gradle(tmp_path):
    (tmp_path / "build.gradle").touch()
    stack = _detect_stack(tmp_path)
    assert stack.name == "java-gradle"
    assert "./gradlew" in stack.lint
    assert "./gradlew" in stack.test

def test_detect_stack_java_maven(tmp_path):
    (tmp_path / "pom.xml").touch()
    stack = _detect_stack(tmp_path)
    assert stack.name == "java-maven"
    assert "mvn" in stack.lint
    assert "mvn" in stack.test

def test_detect_stack_custom_full_override(tmp_path):
    # Setup .claude/dev-tools.json with full override
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    config_file = claude_dir / "dev-tools.json"
    config_data = {
        "lint": ["custom-lint"],
        "typecheck": ["custom-typecheck"],
        "test": ["custom-test"]
    }
    config_file.write_text(json.dumps(config_data))

    stack = _detect_stack(tmp_path)
    assert stack.name == "custom"
    assert stack.lint == ["custom-lint"]
    assert stack.typecheck == ["custom-typecheck"]
    assert stack.test == ["custom-test"]

def test_detect_stack_partial_override(tmp_path):
    # Setup .claude/dev-tools.json with partial override on top of Python
    (tmp_path / "uv.lock").touch()
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    config_file = claude_dir / "dev-tools.json"
    config_data = {
        "test": ["custom-test"]
    }
    config_file.write_text(json.dumps(config_data))

    stack = _detect_stack(tmp_path)
    assert stack.name == "python"
    assert "ruff" in stack.lint
    assert stack.test == ["custom-test"]

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
