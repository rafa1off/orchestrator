"""Unit tests for cross-platform Python hooks."""

from __future__ import annotations

from pathlib import Path

from orchestrator_hooks.post_tool_use import check_proof_of_execution
from orchestrator_hooks.pre_tool_use import check_command
from orchestrator_hooks.session_start import clean_pipeline_dir
from orchestrator_hooks.session_stop import record_session_end


def test_pre_tool_use_command_blocking():
    # Blocked commands
    blocked_commands = [
        "git push",
        "git push origin main",
        "git -C /some/path push",
        "git --no-pager push origin HEAD",
        "env git push",
        "git push --force",
        "gh pr create --title 'feat'",
        "gh pr merge 123",
        "gh pr edit 456 --title 'new'",
    ]
    for cmd in blocked_commands:
        is_blocked, reason = check_command(cmd)
        assert is_blocked is True, f"Expected '{cmd}' to be blocked"
        assert "BLOCKED" in reason

    # Allowed commands
    allowed_commands = [
        "git status",
        "git diff HEAD~1",
        "git commit -m 'feat: something'",
        "git log -n 5",
        "git log --grep push",
        "uv run pytest",
        "uv run ruff check .",
        "npx tsc --noEmit",
    ]
    for cmd in allowed_commands:
        is_blocked, _ = check_command(cmd)
        assert is_blocked is False, f"Expected '{cmd}' to be allowed"


def test_session_start_clean_pipeline(tmp_path: Path):
    pipeline_dir = tmp_path / ".gemini" / "pipeline"
    pipeline_dir.mkdir(parents=True)

    # Create dummy transient files
    (pipeline_dir / "checker-test-findings.json").write_text("{}")
    (pipeline_dir / "reader-test-report.json").write_text("{}")
    (pipeline_dir / "pre-compact-snapshot.md").write_text("# snapshot")
    (pipeline_dir / "write-log.tsv").write_text("log")

    # Create track subdir with transient files
    track_dir = pipeline_dir / "track-a"
    track_dir.mkdir()
    (track_dir / "checker-t-findings.json").write_text("{}")

    # Starts dir
    starts_dir = pipeline_dir / ".starts"
    starts_dir.mkdir()
    (starts_dir / "writer-1").write_text("timestamp")

    clean_pipeline_dir(pipeline_dir)

    assert not (pipeline_dir / "checker-test-findings.json").exists()
    assert not (pipeline_dir / "reader-test-report.json").exists()
    assert not (pipeline_dir / "pre-compact-snapshot.md").exists()
    assert not (pipeline_dir / "write-log.tsv").exists()
    assert not (track_dir / "checker-t-findings.json").exists()
    assert not starts_dir.exists()


def test_post_tool_use_proof_of_execution():
    # Checker PASS without checks
    empty_checks = {"source": "checker", "status": "PASS", "checks": []}
    valid, reason = check_proof_of_execution(empty_checks)
    assert valid is False
    assert "without checks[]" in reason

    # Checker PASS with ERROR check
    error_checks = {
        "source": "checker",
        "status": "PASS",
        "checks": [{"name": "lint", "status": "ERROR", "exit_code": None}],
    }
    valid, reason = check_proof_of_execution(error_checks)
    assert valid is False
    assert "ERROR check" in reason

    # Checker PASS with null exit_code
    null_exit = {
        "source": "checker",
        "status": "PASS",
        "checks": [{"name": "lint", "status": "PASS", "exit_code": None}],
    }
    valid, reason = check_proof_of_execution(null_exit)
    assert valid is False
    assert "null exit_code" in reason

    # Checker valid PASS
    good_checks = {
        "source": "checker",
        "status": "PASS",
        "checks": [{"name": "lint", "status": "PASS", "exit_code": 0}],
    }
    valid, _ = check_proof_of_execution(good_checks)
    assert valid is True


def test_session_stop_records_log(tmp_path: Path):
    pipeline_dir = tmp_path / ".gemini" / "pipeline"
    pipeline_dir.mkdir(parents=True)

    record_session_end(pipeline_dir)
    log_file = pipeline_dir / "session-log.txt"
    assert log_file.exists()
    assert "session-end" in log_file.read_text(encoding="utf-8")
