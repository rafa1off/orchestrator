# Orchestrator Plugins

A private Claude Code plugin marketplace for the orchestrator multi-agent development ecosystem.

## Plugins

| Plugin | Description | Requires |
|---|---|---|
| [`orchestrator-core`](#orchestrator-core) | 8 agents, 3 skills, stack-agnostic dev-tools MCP, SessionStart hook | `uv` |
| [`ty-lsp`](#ty-lsp) | Python LSP via Astral ty | `uv tool install ty` |
| [`vtsls-lsp`](#vtsls-lsp) | TypeScript/JavaScript LSP via vtsls | `npm install -g @vtsls/language-server` |

---

## Requirements

### MCP dev-tools server (`orchestrator-core`)

The dev-tools MCP server is a Python process launched automatically when the plugin is active. It requires either:

| Runtime | Minimum version | Notes |
|---|---|---|
| [`uv`](https://github.com/astral-sh/uv) | any recent | Preferred — server runs via `uv run`; dependencies resolved automatically from the bundled `pyproject.toml` |
| Python | 3.11+ | Fallback — server runs via `python`; install dependencies manually: `pip install fastmcp` |

If `uv` is present it is used automatically. If only `python` is available, the server falls back to the plain-Python command set — no extra configuration needed.

---

## Installation

### 1. Add this marketplace to Claude Code

```bash
/plugin marketplace add rafa1off/orchestrator
```

Or manually in your project's `.claude/settings.json` or user settings (`~/.claude/settings.json`):

```json
{
  "extraKnownMarketplaces": {
    "orchestrator": {
      "source": {
        "source": "github",
        "repo": "rafa1off/orchestrator"
      }
    }
  }
}
```

### 2. Install plugins

```bash
# Core orchestrator (required)
claude plugin install orchestrator-core@orchestrator

# Python LSP — install for Python projects
claude plugin install ty-lsp@orchestrator

# TypeScript/JavaScript LSP — install for TS/JS projects
claude plugin install vtsls-lsp@orchestrator
```

#### Other language servers

For Go, Rust, Java, and other languages, check the official Claude Code plugin marketplace:

```bash
/plugin marketplace browse
```

Official LSP plugins (gopls, rust-analyzer, etc.) are maintained there and install without any additional configuration.

### 3. Activate in your project

Add one line to your project's `CLAUDE.md`:

```markdown
Skill("/orchestrator-core:orchestrator")
```

That's it. No other setup required.

---

## orchestrator-core

A complete multi-agent development harness for Claude Code. The orchestrator session acts as a coordinator, calling specialized subagents on demand.

### Agents

| Agent | Model | Role |
|---|---|---|
| `reader` | haiku | Maps code paths, returns structured context snapshots |
| `researcher` | sonnet | Finds external patterns, library APIs, prior project decisions |
| `writer` | sonnet | Produces minimal, focused code changes from a context block |
| `thinker` | sonnet | Deep reasoning, tradeoff analysis, architectural decisions |
| `checker` | haiku | Runs lint + typecheck, writes structured findings |
| `reviewer` | sonnet | Reviews diffs against conventions, writes structured findings |
| `tester` | sonnet | Identifies missing tests, writes them, runs the suite |
| `documenter` | sonnet | Updates `docs/` and `CLAUDE.md` when public surfaces change |

### Skills

| Skill | When to use |
|---|---|
| `/orchestrator-core:orchestrator` | Load at every session start — the agent routing guide |
| `/orchestrator-core:orchestrator-plan` | Before any multi-step task — writes a plan to `.claude/plans/` |
| `/orchestrator-core:orchestrator-execute` | After plan approval — dispatches agents and enforces the 5 invariants |

### Dev-tools MCP server

Stack-agnostic tools available to checker, reviewer, and tester:

| Tool | Description |
|---|---|
| `lint(files)` | Scoped linter run |
| `typecheck()` | Full-project type check |
| `test(pattern)` | Scoped test run |
| `write_findings(...)` | Writes structured JSON to `.claude/pipeline/` for the orchestrator to read |

Stack is auto-detected at server startup from marker files:

| Stack | Detection | Commands |
|---|---|---|
| Python (uv) | `uv.lock` | `uv run ruff check` / `uv run mypy .` / `uv run pytest -x` |
| Python | `pyproject.toml`, `requirements.txt` | `python -m ruff check` / `python -m mypy .` / `python -m pytest -x` |
| TypeScript | `tsconfig.json` + `package.json` | `npx eslint` / `npx tsc --noEmit` / `npx jest` |
| JavaScript | `package.json` | `npx eslint` / — / `npx jest` |
| Go | `go.mod` | `go vet ./...` / `go build ./...` / `go test ./...` |
| Rust | `Cargo.toml` | `cargo clippy` / `cargo check` / `cargo test` |
| Ruby | `Gemfile` | `bundle exec rubocop` / — / `bundle exec rspec` |
| Java (Gradle) | `build.gradle` | `./gradlew checkstyleMain` / `./gradlew compileJava` / `./gradlew test` |
| Java (Maven) | `pom.xml` | `mvn checkstyle:check` / `mvn compile` / `mvn test` |

**Override any command** by creating `.claude/dev-tools.json` in your project:

```json
{
  "lint": ["./scripts/lint.sh"],
  "test": ["npx", "vitest", "run"]
}
```

Any key present overrides only that command. All three keys present skips detection entirely.

### The 5 Invariants

The orchestrator enforces these rules regardless of task or mode:

1. **Read before write** — reader runs before writer on any file set
2. **Verify at checkpoints** — checker + reviewer run together after every write phase
3. **One writer per overlapping file set** — writers sharing files are serialized
4. **Max 2 verify rounds** — unresolved findings after 2 cycles escalate to the user
5. **Plan mode blocks writes** — only reader, researcher, thinker run until plan is approved

---

## ty-lsp

Python LSP via [Astral ty](https://github.com/astral-sh/ty). Provides go-to-definition, find-references, hover, and document-symbol on `.py` files.

**Prerequisite:** `uv tool install ty`

---

## vtsls-lsp

TypeScript and JavaScript LSP via [vtsls](https://github.com/yioneko/vtsls). Provides go-to-definition, find-references, hover, and document-symbol on `.ts`, `.tsx`, `.js`, and `.jsx` files.

**Prerequisite:** `npm install -g @vtsls/language-server`

---

## Contributing

Each plugin lives in `plugins/<name>/`. The marketplace manifest is at `.claude-plugin/marketplace.json`.

To add a new plugin:
1. Create `plugins/<name>/` with a `.claude-plugin/plugin.json` manifest
2. Add the entry to `.claude-plugin/marketplace.json`
3. Bump the version in both files

Versioning follows semver. `MAJOR` for breaking protocol changes, `MINOR` for new agents/skills/tools, `PATCH` for fixes and instruction improvements.

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
