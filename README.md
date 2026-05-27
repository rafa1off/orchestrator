# Orchestrator Plugins

A private plugin marketplace for the orchestrator multi-agent development ecosystem, fully supporting both **Claude Code** and **Google Antigravity CLI** (using native Google Gemini models).

## Plugins

| Plugin | Description | Requires |
|---|---|---|
| [`orchestrator-core`](#orchestrator-core) | 8 agents, 4 skills, stack-agnostic dev-tools MCP with timeout protection, full hook suite (SessionStart, SubagentStop JSON-validated blocking, PostToolUse auto-context, PreCompact snapshot with progress.md, TeammateIdle gate, SessionEnd audit) | `uv` |
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

### Installation (Google Antigravity CLI)

1. Import the plugins directly into your global store:
```bash
# Core orchestrator (required)
agy plugin import /path/to/orchestrator/plugins/orchestrator-core

# Python LSP — install for Python projects
agy plugin import /path/to/orchestrator/plugins/ty-lsp

# TypeScript/JavaScript LSP — install for TS/JS projects
agy plugin import /path/to/orchestrator/plugins/vtsls-lsp
```

2. Copy the auxiliary scripts and configurations to your global plugin directories (to bridge import copy limitations):
```bash
mkdir -p ~/.gemini/config/plugins/orchestrator-core/hooks ~/.gemini/config/plugins/orchestrator-core/mcp-server-py
cp plugins/orchestrator-core/hooks/*.sh ~/.gemini/config/plugins/orchestrator-core/hooks/
cp plugins/orchestrator-core/mcp-server-py/*.py ~/.gemini/config/plugins/orchestrator-core/mcp-server-py/
cp plugins/ty-lsp/.lsp.json ~/.gemini/config/plugins/ty-lsp/.lsp.json
cp plugins/vtsls-lsp/.lsp.json ~/.gemini/config/plugins/vtsls-lsp/.lsp.json
```

3. Run `agy plugin list` to verify they are enabled. No other setup is required.

---

### Installation (Claude Code)

#### 1. Add this marketplace to Claude Code

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

#### 2. Install plugins

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

#### 3. Activate in your project

Add one line to your project's `CLAUDE.md`:

```markdown
Skill("/orchestrator-core:orchestrator")
```

That's it. No other setup required.

---

## orchestrator-core

A complete multi-agent development harness for Claude Code and Google Antigravity CLI. The main session acts as a coordinator, calling specialized subagents on demand.

### Agents

| Agent | Claude Model | Gemini Model | Permission | Role |
|---|---|---|---|---|
| `reader` | haiku | `gemini-3.5-flash` | `plan` | Maps code paths, returns structured context snapshots |
| `researcher` | sonnet | `gemini-3.1-pro` | `plan` | Finds external patterns, library APIs, prior project decisions; persists findings to project memory |
| `writer` | sonnet | `gemini-3.1-pro` | session | Produces minimal, focused code changes from a context block |
| `thinker` | sonnet | `gemini-3.1-pro` | `plan` | Deep reasoning, tradeoff analysis, architectural decisions; persists decisions to project memory |
| `checker` | haiku | `gemini-3.5-flash` | `plan` | Runs lint + typecheck, writes structured findings; dispatched as background task |
| `reviewer` | sonnet | `gemini-3.1-pro` | `plan` | Reviews diffs against conventions, writes structured findings |
| `tester` | sonnet | `gemini-3.1-pro` | session | Identifies missing tests, writes them, runs the suite |
| `documenter` | sonnet | `gemini-3.1-pro` | session | Updates `docs/` and `CLAUDE.md` when public surfaces change |

`plan` = read-only at harness level regardless of session mode. `session` = inherits the active session's permission mode.

### Skills

| Skill | When to use |
|---|---|
| `/orchestrator-core:orchestrator` | Load at every session start — the agent routing guide; includes session registry pattern for warm agent reuse |
| `/orchestrator-core:orchestrator-plan` | Before any multi-step task — writes a plan to `.claude/plans/` with agent assignments, `*(reuse: true)*` stage annotations, and auto-detected execution mode (`execute` or `team`) |
| `/orchestrator-core:orchestrator-execute` | After plan approval — dispatches agents, maintains a session registry to reuse warm agent sessions across stages, and routes to `orchestrator-team` when `mode: team` |
| `/orchestrator-core:orchestrator-team` | For tasks with 3+ independent write tracks — fans out to agent teammates running in parallel with per-track `(agent_type, track_id)` session registry to isolate context; requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` |

### Hooks

| Event | Trigger | Behavior |
|---|---|---|
| `SessionStart` | Session begins or resumes | Clears stale findings and snapshot from `.claude/pipeline/` |
| `SubagentStop` (checker/reviewer) | Agent finishes | **Blocks** (exit 2) if the agent stopped without a valid findings JSON file — validates with `jq` when available; forces re-invocation of `write_findings` |
| `PostToolUse` (`write_findings`) | Findings file written | Reads the file and injects its content as `additionalContext` — orchestrator receives results automatically |
| `PreCompact` | Context compaction begins | Snapshots findings files and `progress.md` to `.claude/pipeline/pre-compact-snapshot.md` so state survives compaction |
| `TeammateIdle` | Agent team teammate goes idle | **Blocks** if unread findings files are present — enforces that the lead reads all findings before the teammate closes |
| `SessionEnd` | Session terminates | Appends an entry to `.claude/pipeline/session-log.txt` and removes stale findings |

Checker and reviewer also carry **frontmatter `PreToolUse` hooks** (active only while that agent runs) that block write and destructive Bash operations (`rm`, `mv`, shell redirects, `git commit/push`, package installs) as a second layer of read-only enforcement beyond `permissionMode: plan`.

### Dev-tools MCP server

Stack-agnostic tools available to checker, reviewer, and tester. Each command runs with a 120-second timeout:

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
