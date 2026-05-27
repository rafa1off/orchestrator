# Orchestrator Plugins

A private Claude Code plugin marketplace for the orchestrator multi-agent development ecosystem.

## Plugins

| Plugin | Description | Requires |
|---|---|---|
| [`orchestrator-core`](#orchestrator-core) | 8 agents, 5 skills, dev-tools MCP server (`write_findings` pipeline contract), full hook suite (SessionStart, SubagentStop JSON-validated blocking, PostToolUse auto-context, PreCompact snapshot with progress.md, TeammateIdle gate, SessionEnd audit) | `uv` |
| [`ty-lsp`](#ty-lsp) | Python LSP via Astral ty | `uv tool install ty` |
| [`vtsls-lsp`](#vtsls-lsp) | TypeScript/JavaScript LSP via vtsls | `npm install -g @vtsls/language-server` |

---

## Requirements

### MCP dev-tools server (`orchestrator-core`)

The dev-tools MCP server is a Python process launched automatically when the plugin is active. Requires either:

| Runtime | Notes |
|---|---|
| [`uv`](https://github.com/astral-sh/uv) | Preferred — dependencies resolved automatically |
| Python 3.11+ | Fallback — install manually: `pip install fastmcp` |

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

| Agent | Model | Permission | Role |
|---|---|---|---|
| `reader` | haiku | `plan` | Maps code paths, returns structured context snapshots |
| `researcher` | sonnet | `plan` | Finds external patterns, library APIs, prior project decisions; persists findings to project memory |
| `writer` | sonnet | session | Produces minimal, focused code changes from a context block |
| `thinker` | sonnet | `plan` | Deep reasoning, tradeoff analysis, architectural decisions; persists decisions to project memory |
| `checker` | haiku | `plan` | Runs lint + typecheck, writes structured findings; dispatched as background task |
| `reviewer` | sonnet | `plan` | Reviews diffs against conventions, writes structured findings |
| `tester` | sonnet | session | Identifies missing tests, writes them, runs the suite |
| `documenter` | sonnet | session | Updates `docs/` and `CLAUDE.md` when public surfaces change |

`plan` = read-only at harness level regardless of session mode. `session` = inherits the active session's permission mode.

### Skills

| Skill | When to use |
|---|---|
| `/orchestrator-core:orchestrator` | Load at every session start — the agent routing guide; includes session registry pattern for warm agent reuse |
| `/orchestrator-core:orchestrator-plan` | Before any multi-step task — writes a plan to `.claude/plans/` with agent assignments and auto-detected execution mode (`execute` or `team`) |
| `/orchestrator-core:orchestrator-execute` | After plan approval — routes to `orchestrator-subagent` or `orchestrator-team` based on plan `mode:` field |
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

Exposes a single tool used by checker and reviewer to write structured findings to the pipeline:

| Tool | Description |
|---|---|
| `write_findings(source, status, pipeline?, errors?, issues?)` | Writes `<source>-findings.json` to `.claude/pipeline/` (or a per-track subdirectory for parallel runs) |

Checker and tester run lint, typecheck, and tests directly via `Bash`, reading the project's commands from `CLAUDE.md` first and falling back to marker-file detection (`uv.lock` → ruff/mypy/pytest, `package.json` → eslint/tsc/jest, etc.).

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
