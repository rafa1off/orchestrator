#!/usr/bin/env python3
# /// script
# dependencies = ["fastmcp>=2.0.0"]
# ///
"""MCP dev-tools server — stack-agnostic, detects project toolchain at startup."""

from fastmcp import FastMCP
import subprocess
import json
import os
from pathlib import Path
from dataclasses import dataclass

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
DEFAULT_PIPELINE = ".claude/pipeline"

mcp = FastMCP("dev-tools")


@dataclass
class StackConfig:
    name: str
    lint: list[str]
    typecheck: list[str] | None
    test: list[str]
    scoped_lint: bool = (
        True  # False for stacks where file args are unsupported (Go, Rust, Java)
    )


def _detect_stack(project_dir: Path) -> StackConfig:
    """Probe marker files to select toolchain commands. .claude/dev-tools.json overrides any key."""
    config_path = project_dir / ".claude" / "dev-tools.json"
    overrides: dict[str, list[str]] = {}

    if config_path.exists():
        overrides = json.loads(config_path.read_text())
        if all(k in overrides for k in ("lint", "typecheck", "test")):
            return StackConfig(
                name="custom",
                lint=overrides["lint"],
                typecheck=overrides.get("typecheck"),
                test=overrides["test"],
            )

    # Python
    if any(
        (project_dir / m).exists()
        for m in (
            "uv.lock",
            "pyproject.toml",
            "setup.py",
            "requirements.txt",
            "Pipfile",
        )
    ):
        prefix = (
            ["uv", "run"] if (project_dir / "uv.lock").exists() else ["python", "-m"]
        )
        stack = StackConfig(
            name="python",
            lint=[*prefix, "ruff", "check"],
            typecheck=[*prefix, "mypy", "."],
            test=[*prefix, "pytest", "-x"],
        )
    # TypeScript
    elif (project_dir / "tsconfig.json").exists() and (
        project_dir / "package.json"
    ).exists():
        stack = StackConfig(
            name="typescript",
            lint=["npx", "eslint", "--ext", ".ts,.tsx", "src/"],
            typecheck=["npx", "tsc", "--noEmit"],
            test=["npx", "jest", "--testPathPattern"],
        )
    # JavaScript
    elif (project_dir / "package.json").exists():
        stack = StackConfig(
            name="javascript",
            lint=["npx", "eslint", "src/"],
            typecheck=None,
            test=["npx", "jest", "--testPathPattern"],
        )
    # Go
    elif (project_dir / "go.mod").exists():
        stack = StackConfig(
            name="go",
            lint=["go", "vet", "./..."],
            typecheck=["go", "build", "./..."],
            test=["go", "test", "./..."],
            scoped_lint=False,
        )
    # Rust
    elif (project_dir / "Cargo.toml").exists():
        stack = StackConfig(
            name="rust",
            lint=["cargo", "clippy", "--", "-D", "warnings"],
            typecheck=["cargo", "check"],
            test=["cargo", "test"],
            scoped_lint=False,
        )
    # Ruby
    elif (project_dir / "Gemfile").exists():
        stack = StackConfig(
            name="ruby",
            lint=["bundle", "exec", "rubocop"],
            typecheck=None,
            test=["bundle", "exec", "rspec"],
        )
    # Java/Kotlin — Gradle
    elif any((project_dir / m).exists() for m in ("build.gradle", "build.gradle.kts")):
        stack = StackConfig(
            name="java-gradle",
            lint=["./gradlew", "checkstyleMain"],
            typecheck=["./gradlew", "compileJava"],
            test=["./gradlew", "test"],
            scoped_lint=False,
        )
    # Java/Kotlin — Maven
    elif (project_dir / "pom.xml").exists():
        stack = StackConfig(
            name="java-maven",
            lint=["mvn", "checkstyle:check", "-q"],
            typecheck=["mvn", "compile", "-q"],
            test=["mvn", "test", "-q"],
            scoped_lint=False,
        )
    else:
        return StackConfig(name="unknown", lint=[], typecheck=None, test=[])

    if overrides.get("lint"):
        stack.lint = overrides["lint"]
    if overrides.get("typecheck"):
        stack.typecheck = overrides["typecheck"]
    if overrides.get("test"):
        stack.test = overrides["test"]

    return stack


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, cwd=PROJECT_DIR, capture_output=True, text=True)
    return (result.stdout + result.stderr).strip()


STACK = _detect_stack(PROJECT_DIR)


@mcp.tool()
def lint(files: list[str]) -> str:
    """Run linter scoped to files. Stacks without file-scoped support (Go, Rust, Java) run full-project."""
    if not STACK.lint:
        return f"Stack '{STACK.name}' not detected — lint skipped."
    if STACK.scoped_lint and files:
        cmd = [*STACK.lint, *files]
        note = ""
    else:
        cmd = STACK.lint
        note = (
            f"Note: {STACK.name} linter runs full-project (file-scoped runs unsupported).\n"
            if files
            else ""
        )
    return note + (_run(cmd) or "No lint errors.")


@mcp.tool()
def typecheck() -> str:
    """Run full-project typecheck."""
    if not STACK.typecheck:
        return f"Stack '{STACK.name}' has no typecheck command — skipped."
    return _run(STACK.typecheck) or "No type errors."


@mcp.tool()
def test(pattern: str) -> str:
    """Run tests matching pattern. Appended as a path/package filter to the stack's test command."""
    if not STACK.test:
        return f"Stack '{STACK.name}' not detected — test skipped."
    return _run([*STACK.test, pattern])


@mcp.tool()
def write_findings(
    source: str,
    status: str,
    pipeline: str | None = None,
    errors: dict | None = None,
    issues: list[str] | None = None,
) -> str:
    """
    Write checker or reviewer findings to .claude/pipeline/<source>-findings.json.
    Always call — even on PASS/APPROVED.
    source: 'checker' | 'reviewer'
    status: 'PASS'|'FAIL' (checker) or 'APPROVED'|'ISSUES' (reviewer)
    pipeline: optional override for multi-task runs, e.g. '.claude/pipeline/task-1'
    """
    pipeline_dir = PROJECT_DIR / (pipeline or DEFAULT_PIPELINE)
    pipeline_dir.mkdir(parents=True, exist_ok=True)

    findings: dict = {"source": source, "status": status}
    if source == "checker" and errors:
        findings["errors"] = errors
    if source == "reviewer" and issues:
        findings["issues"] = issues

    out_path = pipeline_dir / f"{source}-findings.json"
    out_path.write_text(json.dumps(findings, indent=2))
    return f"wrote {pipeline or DEFAULT_PIPELINE}/{source}-findings.json"


if __name__ == "__main__":
    mcp.run(transport="stdio")
