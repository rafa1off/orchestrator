# Orchestrator Plugins

A private Claude Code plugin marketplace for the orchestrator multi-agent development ecosystem.

## Plugins

| Plugin | Description | Requires |
|---|---|---|
| [`orchestrator-core`](#orchestrator-core) | 8 agents, 2 skills, dev-tools MCP server (`write_findings` pipeline contract), full hook suite (SessionStart, SubagentStop JSON-validated blocking, PostToolUse auto-context, PreCompact snapshot, SessionEnd audit) | `uv` |
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

| Agent | Model | Type | Role |
|---|---|---|---|
| `orchestrator-core:reader` | haiku | readonly | Maps code paths, returns structured context snapshots |
| `orchestrator-core:researcher` | sonnet | readonly | Finds external patterns, library APIs, prior project decisions |
| `orchestrator-core:thinker` | sonnet | readonly | Deep reasoning, tradeoff analysis, brainstorming; isolates verbose analysis from main context |
| `orchestrator-core:writer` | sonnet | read+write | Produces minimal, focused code changes from a context block |
| `orchestrator-core:checker` | haiku | readonly | Lint + typecheck + build only — no diff review; ad-hoc quality gate, call any time |
| `orchestrator-core:reviewer` | sonnet | readonly | Diff review only — no lint/typecheck; for PR reviews or reviewing a change set after checker passes |
| `orchestrator-core:verify` | sonnet | readonly | Lint + typecheck + diff review in one pass; post-write loop only; writes `verify-findings.json`; `background: true` |
| `orchestrator-core:tester` | sonnet | read+write | Identifies missing tests, writes them, runs the suite |

### Skills

| Skill | When to use |
|---|---|
| `/orchestrator-core:orchestrator` | Load at every session start — the agent routing guide; L1/L2/L3 dispatch levels, 3 invariants, verify loop |
| `/orchestrator-core:orchestrator-plan` | Before any multi-step task — writes a plan to `.claude/plans/`, then dispatches directly after approval |

### Hooks

| Event | Trigger | Behavior |
|---|---|---|
| `SessionStart` | Session begins or resumes | Clears stale `verify-findings.json` and snapshot from `.claude/pipeline/` |
| `SubagentStop` (verify) | verify agent finishes | **Blocks** (exit 2) if the agent stopped without a valid `verify-findings.json` — validates with `jq` when available; forces re-invocation of `write_findings` |
| `PostToolUse` (`write_findings`) | Findings file written | Reads the file and injects its content as `additionalContext` — orchestrator receives results automatically |
| `PreCompact` | Context compaction begins | Snapshots `verify-findings.json` and `progress.md` to `.claude/pipeline/pre-compact-snapshot.md` so state survives compaction |
| `SessionEnd` | Session terminates | Appends an entry to `.claude/pipeline/session-log.txt` and removes stale findings |

### Dev-tools MCP server

Exposes a single tool used by verify to write structured findings to the pipeline:

| Tool | Description |
|---|---|
| `write_findings(source, status, pipeline?, errors?, issues?)` | Writes `verify-findings.json` to `.claude/pipeline/` (or a per-track subdirectory for parallel runs) |

Verify runs lint, typecheck, and diff review directly via `Bash`, reading the project's commands from `CLAUDE.md` first and falling back to marker-file detection (`uv.lock` → ruff/mypy, `package.json` → eslint/tsc, etc.).

### The 3 Invariants

The orchestrator enforces these rules regardless of task or scale:

1. **Read before write** — invoke reader (or read files directly for trivial changes) before calling writer
2. **Verify after write, max 2 rounds** — run verify + tester after a write phase, always together in the same message turn; escalate after 2 rounds with remaining findings. Use checker/reviewer for ad-hoc checks outside the write loop.
3. **One writer per overlapping file set** — serialize writers sharing files; disjoint sets may run in parallel

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
