# Orchestrator Plugins

A private Claude Code plugin marketplace for the orchestrator multi-agent development ecosystem.

## Plugins

| Plugin | Description | Requires |
|---|---|---|
| [`orchestrator-skills`](#orchestrator-skills) | 2 workflow skills — auto-installs `orchestrator-agents` + `orchestrator-hooks` | — |
| [`orchestrator-agents`](#orchestrator-agents) | 8-agent catalog — auto-installs `orchestrator-mcp` | `uv` |
| [`orchestrator-hooks`](#orchestrator-hooks) | Full hook suite (SessionStart, SubagentStop, PostToolUse, PreCompact, SessionEnd, FileChanged) | — |
| [`orchestrator-mcp`](#orchestrator-mcp) | Dev-tools MCP server (`write_findings` pipeline contract) | `uv` |
| [`ty-lsp`](#ty-lsp) | Python LSP via Astral ty | `uv tool install ty` |
| [`vtsls-lsp`](#vtsls-lsp) | TypeScript/JavaScript LSP via vtsls | `npm install -g @vtsls/language-server` |

**Dependency chain:** installing `orchestrator-skills` pulls in the full stack automatically.

```
orchestrator-skills
├── orchestrator-agents
│   └── orchestrator-mcp
└── orchestrator-hooks
```

---

## Requirements

### MCP dev-tools server (`orchestrator-mcp`)

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
# Full orchestrator stack (recommended — installs all dependencies)
claude plugin install orchestrator-skills@orchestrator

# Python LSP — install for Python projects
claude plugin install ty-lsp@orchestrator

# TypeScript/JavaScript LSP — install for TS/JS projects
claude plugin install vtsls-lsp@orchestrator
```

To install components individually:

```bash
claude plugin install orchestrator-mcp@orchestrator
claude plugin install orchestrator-hooks@orchestrator
claude plugin install orchestrator-agents@orchestrator
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
Skill("/orchestrator-skills:orchestrator")
```

That's it. No other setup required.

---

## orchestrator-skills

Two workflow skills for the orchestrator session:

| Skill | When to use |
|---|---|
| `/orchestrator-skills:orchestrator` | Load at every session start — the agent routing guide: 8-agent catalog, 3 core invariants, L1/L2/L3 dispatch levels (L3 splits into Workflow default + TeamCreate for coordination-heavy tasks), dispatch mode rules, routing special cases. Lazy-loads `dispatch-levels.md`, `verify-loop.md`, and `agent-contracts.md` on demand. |
| `/orchestrator-skills:orchestrator-plan` | Before any multi-step task — enters plan mode, runs reader/researcher in parallel, writes a plan to `.claude/plans/`, creates tasks via `TaskCreate`, then dispatches after approval following L1/L2/L3. |

**Dependencies:** `orchestrator-agents`, `orchestrator-hooks`

---

## orchestrator-agents

8-agent catalog. The orchestrator session acts as coordinator, calling specialized subagents on demand.

| Agent | Model | Type | Dispatch | Role |
|---|---|---|---|---|
| `orchestrator-agents:reader` | haiku | readonly | `background: true` | Maps code paths, returns structured context snapshots |
| `orchestrator-agents:researcher` | sonnet | readonly | `background: true` | Finds external patterns, library APIs, prior project decisions |
| `orchestrator-agents:thinker` | sonnet | readonly | `background: true` | Deep reasoning, tradeoff analysis, brainstorming; isolates verbose analysis from main context |
| `orchestrator-agents:writer` | sonnet | read+write | orchestrator's choice | Produces minimal, focused code changes from a context block |
| `orchestrator-agents:checker` | haiku | readonly | in-session | Lint + typecheck + build only — no diff review; ad-hoc quality gate, call any time |
| `orchestrator-agents:reviewer` | sonnet | readonly | in-session | Diff review only — no lint/typecheck; for PR reviews or reviewing a change set after checker passes |
| `orchestrator-agents:verify` | sonnet | readonly | `background: true` | Lint + typecheck + diff review in one pass; post-write loop only; writes `verify-findings.json` |
| `orchestrator-agents:tester` | sonnet | read+write | `background: true` | Identifies missing tests, writes them, runs the suite |

All agents accept `taskId` (single task) or `tasks: [{taskId, description}, ...]` (multiple sequential tasks) in the invocation prompt and self-manage `in_progress`/`completed` status transitions.

**Dependency:** `orchestrator-mcp`

### The 3 Invariants

1. **Read before write** — invoke reader before calling writer; the orchestrator may read files directly when the scope is narrow enough to not warrant a reader agent
2. **Verify after write, max 2 rounds** — run verify + tester after a write phase, always together in the same message turn; escalate after 2 rounds with remaining findings
3. **One writer per overlapping file set** — serialize writers sharing files; disjoint sets may run in parallel

---

## orchestrator-hooks

Hook suite that automates the orchestrator's pipeline contracts:

| Event | Trigger | Behavior |
|---|---|---|
| `SessionStart` | Session begins or resumes | Clears stale `verify-findings.json` and snapshot from `.claude/pipeline/` |
| `SubagentStop` (verify) | verify agent finishes | **Blocks** (exit 2) if the agent stopped without a valid `verify-findings.json`; on success injects `additionalContext` with status + findings path |
| `PostToolUse` (`write_findings`) | Findings file written | Reads the file and injects its content as `additionalContext` — orchestrator receives results automatically |
| `FileChanged` (`verify-findings.json`) | Background verify writes findings | Injects findings status and pipeline path as `additionalContext` — eliminates the manual `cat` step |
| `PreCompact` | Context compaction begins | Snapshots `verify-findings.json` and `progress.md` to `.claude/pipeline/pre-compact-snapshot.md` |
| `SessionEnd` | Session terminates | Appends an entry to `.claude/pipeline/session-log.txt` and removes stale findings |

---

## orchestrator-mcp

Exposes a single tool used by the verify agent to write structured findings to the pipeline:

| Tool | Description |
|---|---|
| `write_findings(source, status, pipeline?, errors?, issues?)` | Writes `verify-findings.json` to `.claude/pipeline/` (or a per-track subdirectory for parallel runs) |

Verify runs lint, typecheck, and diff review directly via `Bash`, reading the project's commands from `CLAUDE.md` first and falling back to marker-file detection (`uv.lock` → ruff/mypy, `package.json` → eslint/tsc, etc.).

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
3. Declare dependencies in `plugin.json` if the plugin requires others

Versioning follows semver. `MAJOR` for breaking protocol changes, `MINOR` for new agents/skills/tools, `PATCH` for fixes and instruction improvements. Each plugin versions independently.

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
