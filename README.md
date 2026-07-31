# Orchestrator Plugins

A private Claude Code plugin marketplace for the orchestrator multi-agent development ecosystem.

## Plugins

| Plugin | Description | Requires |
|---|---|---|
| [`orchestrator-skills`](#orchestrator-skills) | 2 workflow skills — auto-installs `orchestrator-agents` + `orchestrator-hooks` | — |
| [`orchestrator-agents`](#orchestrator-agents) | 8-agent catalog — auto-installs `orchestrator-mcp` | `uv` |
| [`orchestrator-hooks`](#orchestrator-hooks) | Full hook suite (SessionStart/End, SubagentStart/Stop findings guards, PreToolUse guardrails, PostToolUse findings + writer-overlap, PreCompact) | `jq` |
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

### `jq` (required by `orchestrator-hooks`)

Every guard script parses its hook payload with [`jq`](https://jqlang.github.io/jq/). It is a
**hard requirement, not a soft dependency**: without it the verify/tester findings guard cannot
confirm that any check actually ran, so it **blocks** rather than allowing an unverifiable
result through. A blocked verify complaining that `jq` is missing means exactly that — install
it, don't work around it.

```bash
sudo apt install jq      # Debian/Ubuntu
brew install jq          # macOS
sudo dnf install jq      # Fedora/RHEL
```

Precisely which hooks do what without `jq`:

| Hook | No `jq` | Why |
|---|---|---|
| `SubagentStop` findings guard | **blocks** | It is the last gate before a result is trusted. A guard that cannot check must not approve |
| `PreToolUse` guardrails, `PostToolUse` injection, start-stamp, overlap tracker | `exit 0` | None of them is the final gate on a correctness claim, and the `SubagentStop` block above means no verify or tester run can complete without `jq` anyway |

See [Fail-closed principle](#fail-closed-principle).

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

> **Install `jq` first** if it is not already present (`jq --version`). `orchestrator-hooks`
> requires it — see [Requirements](#jq-required-by-orchestrator-hooks).

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

### 4. Required settings & permissions

Add the following to your project's `.claude/settings.json` (or user settings at `~/.claude/settings.json`).

#### Agent teams flag

The L3b TeamCreate dispatch level and SendMessage warm-agent reuse require the experimental teams feature. Add it to the `env` block:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

> **Note:** This flag enables an experimental Claude Code feature. Behaviour may change across releases.

#### Permissions allow-rules

Background subagents (verify, tester, reader, researcher) auto-deny any tool that would prompt for permission — without allow-rules they silently skip lint, typecheck, and test runs. Add these entries to the `permissions.allow` block so backgrounded agents can execute their checks:

```json
{
  "permissions": {
    "allow": [
      "Bash(uv *)",
      "Bash(pytest *)",
      "Bash(ruff *)",
      "Bash(mypy *)",
      "Bash(npx *)",
      "mcp__plugin_orchestrator-mcp_dev-tools__write_findings"
    ]
  }
}
```

Adjust the `Bash(...)` patterns to match your project's actual toolchain. The `mcp__plugin_orchestrator-mcp_dev-tools__write_findings` entry allows the verify and tester agents to write structured findings to the pipeline without prompting.

If a check is denied anyway, the run now **fails loudly instead of silently**: an agent whose
lint or test command could not execute cannot report `PASS` for it, and the guards refuse the
findings with the reason. A blocked verify pointing at a missing allow-rule is the expected
symptom of an incomplete list above — not a reason to bypass the guard.

#### Cache configuration

To avoid cold-starting the prompt cache mid-session:

- Fix the model and effort level at session start — switching models resets the cache.
- Keep the MCP server connected for the entire session; disconnecting and reconnecting can invalidate cached context.
- API-key users: set `ENABLE_PROMPT_CACHING_1H=1` in `env` for a 1-hour TTL. Subscription users get extended TTL automatically.

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
    "ENABLE_PROMPT_CACHING_1H": "1"
  }
}
```

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

| Agent | Model | Type | Role |
|---|---|---|---|
| `orchestrator-agents:reader` | haiku | readonly | Maps code paths, returns structured context snapshots |
| `orchestrator-agents:researcher` | sonnet | readonly | Finds external patterns, library APIs, prior project decisions |
| `orchestrator-agents:thinker` | sonnet | readonly | Deep reasoning, tradeoff analysis, brainstorming; isolates verbose analysis from main context |
| `orchestrator-agents:writer` | sonnet | read+write | Produces minimal, focused code changes from a context block |
| `orchestrator-agents:checker` | haiku | readonly | Lint + typecheck + build only — no diff review; ad-hoc quality gate, call any time |
| `orchestrator-agents:reviewer` | sonnet | readonly | Diff review only — no lint/typecheck; for PR reviews or reviewing a change set after checker passes |
| `orchestrator-agents:verify` | sonnet | readonly | Lint + typecheck + diff review in one pass; post-write loop only; writes `verify-findings.json` |
| `orchestrator-agents:tester` | sonnet | readonly | Runs the suite and classifies each failure (REGRESSION / STALE TEST / FLAKY / UNCLEAR) with evidence — never writes or fixes tests |

All agents accept `taskId` (single task) or `tasks: [{taskId, description}, ...]` (multiple sequential tasks) in the invocation prompt and self-manage `in_progress`/`completed` status transitions.

**Dispatch mode:** no agent definition sets `background`. Dispatch with
`run_in_background: false` whenever an agent needs `LSP`, `TaskGet`, or `TaskUpdate` —
Claude Code strips those from *background* subagents even when they are listed in `tools:`.
Background subagents keep all MCP tools but only a fixed built-in set (`Read`, `Grep`,
`Glob`, `Bash`, `Edit`, `Write`, …). That affects every agent except checker.

**Trust asymmetry:** only `verify` and `tester` write findings via `write_findings`, and only
they are covered by the proof-of-execution and `SubagentStop` guards. `checker` and
`reviewer` return prose — a PASS from either is an unverified claim and never substitutes
for the invariant-2 verify + tester pass.

**Readonly agents that hold `Write`:** `thinker` and `researcher` declare `memory: project`,
which auto-grants `Read`/`Write`/`Edit` so they can maintain their memory directory. The
grant is not path-scoped and cannot be narrowed in frontmatter, so a `PreToolUse` hook
(`block-readonly-agent-writes.sh`) confines their writes to `.claude/agent-memory/`.

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
| `SessionStart` | Session begins or resumes | Clears stale findings, start-stamps, and the write log from `.claude/pipeline/` (including `track-*/` subdirs) |
| `SubagentStart` (verify, tester) | Agent spawns | Records the start time keyed by `agent_id` — the reference point the freshness check below compares against |
| `SubagentStop` (verify, tester) | Agent finishes | **Blocks** unless findings were written *during this run* and every `checks[]` entry carries a real `exit_code`. Blocks via `decision: "block"` with a reason, so the agent gets a retry instruction rather than a dead end |
| `PreToolUse` (`Bash`) | writer/verify/tester run a command | **Blocks** `git push` and `gh pr create/merge/edit`, including `git -C <path> push` and newline-separated forms |
| `PreToolUse` (`Agent`) | Any subagent spawns a subagent | Allowlist — only reader/researcher/thinker/reviewer may be nested targets |
| `PreToolUse` (`Write`/`Edit`) | thinker/researcher write | **Blocks** any path outside `.claude/agent-memory/` |
| `PostToolUse` (`write_findings`) | Findings file written | Proof-of-execution guard, then injects the file's content as `additionalContext` |
| `PostToolUse` (`Write`/`Edit`) | writer edits a file | Logs `agent_id`→path to `.claude/pipeline/write-log.tsv` and flags the file when a *different* writer already touched it (invariant 3) |
| `PreCompact` | Context compaction begins | Snapshots findings and `progress.md` to `.claude/pipeline/pre-compact-snapshot.md` |
| `SessionEnd` | Session terminates | Appends to `.claude/pipeline/session-log.txt` (capped at 500 lines) and clears findings, stamps, and the write log |

### Fail-closed principle

Every guard here asserts **positive evidence**, not merely well-formed failure reporting.
A verify or tester result is trusted only when it carries one `checks[]` entry per check
actually executed, each with the real process exit code; absent, empty, or null-exit-code
checks are refused at three layers (the MCP tool itself, `PostToolUse`, and `SubagentStop`).
A missing `jq` blocks rather than silently disabling the guard. The guards' *presence* is
what makes a green result meaningful, so failing open is worse than having no guard at all.

---

## orchestrator-mcp

Exposes a single tool used by the verify and tester agents to write structured findings to the pipeline:

| Tool | Description |
|---|---|
| `write_findings(source, status, pipeline?, checks?, issues?, failures?)` | Writes `<source>-findings.json` to `.claude/pipeline/` (or a per-track subdirectory for parallel runs), stamped with `written_at` |

`source` is `verify` or `tester` — the only two agents holding the tool. `checks` is required
and non-empty for both: the call is **rejected** without it, because a result with no checks
cannot be distinguished from a run that never happened. Empty `issues`/`failures` lists are
recorded verbatim rather than dropped, so "reported nothing" stays distinct from "never
populated the field".

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
