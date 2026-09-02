# Orchestrator Plugins

A private Claude Code plugin marketplace for the orchestrator multi-agent development ecosystem.

## Plugins

| Plugin | Description | Requires |
|---|---|---|
| [`orchestrator-skills`](#orchestrator-skills) | 2 workflow skills — auto-installs `orchestrator-agents` + `orchestrator-hooks` | — |
| [`orchestrator-agents`](#orchestrator-agents) | 7-agent catalog — auto-installs `orchestrator-mcp` | `uv` |
| [`orchestrator-hooks`](#orchestrator-hooks) | Full hook suite (SessionStart/End, SubagentStart/Stop findings guards, PreToolUse guardrails, PostToolUse findings + writer-overlap, PreCompact) | `jq` |
| [`orchestrator-mcp`](#orchestrator-mcp) | Dev-tools MCP server (`write_findings` pipeline contract) | `uv` |
| [`ty-lsp`](#ty-lsp) | Python LSP via Astral ty | `uv tool install ty` |
| [`tsgo-lsp`](#tsgo-lsp) | TypeScript/JavaScript LSP via tsgo | `tsc --lsp --stdio` |

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
**hard requirement, not a soft dependency**: without it the checker/reviewer/tester findings
guard cannot confirm that any check actually ran, so it **blocks** rather than allowing an
unverifiable result through. A blocked checker, reviewer, or tester run complaining that `jq`
is missing means exactly that — install it, don't work around it.

```bash
sudo apt install jq      # Debian/Ubuntu
brew install jq          # macOS
sudo dnf install jq      # Fedora/RHEL
```

Precisely which hooks do what without `jq`:

| Hook | No `jq` | Why |
|---|---|---|
| `SubagentStop` findings guard | **blocks** | It is the last gate before a result is trusted. A guard that cannot check must not approve |
| `PreToolUse` guardrails, `PostToolUse` injection, start-stamp, overlap tracker | `exit 0` | None of them is the final gate on a correctness claim, and the `SubagentStop` block above means no checker, reviewer, or tester run can complete without `jq` anyway |

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
claude plugin install tsgo-lsp@orchestrator
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

#### Permissions allow-rules

Background subagents (checker, reviewer, tester, reader, researcher) auto-deny any tool that would prompt for permission — without allow-rules they silently skip lint, typecheck, and test runs. Add these entries to the `permissions.allow` block so backgrounded agents can execute their checks:

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

Adjust the `Bash(...)` patterns to match your project's actual toolchain. The `mcp__plugin_orchestrator-mcp_dev-tools__write_findings` entry allows the checker, reviewer, and tester agents to write structured findings to the pipeline without prompting.

If a check is denied anyway, the run now **fails loudly instead of silently**: an agent whose
lint or test command could not execute cannot report `PASS` for it, and the guards refuse the
findings with the reason. A blocked checker or reviewer pointing at a missing allow-rule is the
expected symptom of an incomplete list above — not a reason to bypass the guard.

#### Cache configuration

To avoid cold-starting the prompt cache mid-session:

- Fix the model and effort level at session start — switching models resets the cache.
- Keep the MCP server connected for the entire session; disconnecting and reconnecting can invalidate cached context.
- API-key users: set `ENABLE_PROMPT_CACHING_1H=1` in `env` for a 1-hour TTL. Subscription users get extended TTL automatically.

```json
{
  "env": {
    "ENABLE_PROMPT_CACHING_1H": "1"
  }
}
```

---

## orchestrator-skills

Two workflow skills for the orchestrator session:

| Skill | When to use |
|---|---|
| `/orchestrator-skills:orchestrator` | Load at every session start — the agent routing guide: 7-agent catalog, 3 core invariants, L1/L2/L3 dispatch levels (L3 via `Workflow`), dispatch mode rules, routing special cases. Lazy-loads `dispatch-levels.md`, `verification.md`, and `agent-contracts.md` on demand. |
| `/orchestrator-skills:orchestrator-plan` | Before any multi-step task — enters plan mode, runs reader/researcher in parallel, writes a plan to `.claude/plans/`, creates the `.claude/plans/progress.md` ledger, then dispatches after approval following L1/L2/L3. |

**Dependencies:** `orchestrator-agents`, `orchestrator-hooks`

---

## orchestrator-agents

7-agent catalog. The orchestrator session acts as coordinator, calling specialized subagents on demand.

| Agent | Model | Effort | Type | Role |
|---|---|---|---|---|
| `orchestrator-agents:reader` | haiku | *(absent — inert on haiku)* | readonly | Maps code paths, writes `reader-report.json` with structured context snapshots |
| `orchestrator-agents:researcher` | sonnet | low | readonly | Finds external patterns, library APIs, prior project decisions; writes `researcher-report.json` |
| `orchestrator-agents:thinker` | opus | medium | readonly | Deep reasoning, tradeoff analysis, brainstorming; isolates verbose analysis from main context; writes `thinker-report.json` |
| `orchestrator-agents:writer` | sonnet | low | read+write | Produces minimal, focused code changes from a context block; writes `writer-report.json` listing modified files |
| `orchestrator-agents:checker` | haiku | *(absent — inert on haiku)* | readonly | Lint + typecheck + build only — no diff review; call any time, writes `checker-findings.json` |
| `orchestrator-agents:reviewer` | opus | medium | readonly | Diff review only — no lint/typecheck; always spawned fresh, writes `reviewer-findings.json` |
| `orchestrator-agents:tester` | sonnet | low | readonly | Runs the suite and classifies each failure (REGRESSION / STALE TEST / FLAKY / UNCLEAR) with evidence — never writes or fixes tests |

**Dispatch mode:** agents always run as background subagents — fork mode is on by default in
interactive sessions and Claude cannot request the foreground. Background subagents keep all
MCP tools but only a fixed built-in set (`Read`, `Grep`, `Glob`, `Bash`, `Edit`, `Write`,
`Skill`, …), which excludes `LSP` and the Task tools (`TaskGet`/`TaskUpdate`/…). No agent
definition instructs either, so this never blocks a dispatch.

**Guarded findings:** `checker`, `reviewer`, and `tester` all write findings via
`write_findings` and are covered by the proof-of-execution and `SubagentStop` guards — a PASS
from any of them is substantiated, not a claim. Verification itself is discretionary: there is
no mandatory post-write pass, and the orchestrator decides when to dispatch checker, reviewer,
and tester based on the plan or the current task.

**Readonly agents that hold `Write`:** `thinker` and `researcher` declare `memory: project`,
which auto-grants `Read`/`Write`/`Edit` so they can maintain their memory directory. The
grant is not path-scoped and cannot be narrowed in frontmatter, so a `PreToolUse` hook
(`block-readonly-agent-writes.sh`) confines their writes to `.claude/agent-memory/`.

**Dependency:** `orchestrator-mcp`

### The 3 Invariants

1. **Read before write** — invoke reader before calling writer; the orchestrator may read files directly when the scope is narrow enough to not warrant a reader agent
2. **One writer per overlapping file set** — serialize writers sharing files; disjoint sets may run in parallel
3. **Never auto-fix a tester diagnosis** — REGRESSION and STALE_TEST have opposite fixes, so tester failures are surfaced to the user for a decision and a writer is dispatched only once the user has chosen

Verification (checker, reviewer, tester) is discretionary, not mandatory — see `verification.md`.

---

## orchestrator-hooks

Hook suite that automates the orchestrator's pipeline contracts:

| Event | Trigger | Behavior |
|---|---|---|
| `SessionStart` | Session begins or resumes | Clears stale findings, reports, start-stamps, and the write log from `.claude/pipeline/` (including `track-*/` subdirs); `.claude/plans/progress.md` and `.claude/metrics/` are untouched — both are persistent |
| `SubagentStart` (all 7 agents) | Agent spawns | Records the start time keyed by `agent_id` — the reference point the freshness check below compares against |
| `SubagentStop` (all 7 agents) | Agent finishes | For checker/reviewer/tester: **blocks** unless findings were written *during this run* and every `checks[]` entry carries a real `exit_code`. For reader/writer/thinker/researcher: **blocks** unless a report was written during this run and is fresh — no exit codes to check, since none of them runs commands. Blocks via `decision: "block"` with a reason, so the agent gets a retry instruction rather than a dead end |
| `SubagentStop` (writer, checker, reviewer, tester) | Agent finishes | Appends `<iso8601>\t<agent_type>\t<elapsed_seconds>` to `.claude/metrics/agent-timings.tsv`, capped at 1000 rows past 2000; every failure path (missing stamp, unwritable dir, absent `jq`) still exits 0 and clears the stamp |
| `PreToolUse` (`Bash`) | writer/checker/reviewer/tester run a command | **Blocks** `git push` and `gh pr create/merge/edit`, including `git -C <path> push` and newline-separated forms |
| `PreToolUse` (`Agent`) | Any subagent spawns a subagent | Allowlist — only reader/researcher/thinker/reviewer may be nested targets |
| `PreToolUse` (`Write`/`Edit`) | thinker/researcher write | **Blocks** any path outside `.claude/agent-memory/` |
| `PostToolUse` (`write_findings`\|`write_report`) | Findings or report file written | Proof-of-execution guard for findings, presence-and-freshness guard for reports, then injects the file's content as `additionalContext` |
| `PostToolUse` (`Write`/`Edit`) | writer edits a file | Logs `agent_id`→path to `.claude/pipeline/write-log.tsv` and flags the file when a *different* writer already touched it (invariant 2) |
| `PreCompact` | Context compaction begins | Snapshots the findings files (`checker-findings.json`, `reviewer-findings.json`, `tester-findings.json`) and the report files (`reader-report.json`, `writer-report.json`, `thinker-report.json`, `researcher-report.json`) to `.claude/pipeline/pre-compact-snapshot.md`; `progress.md` is not read here — it is durable at a fixed path and needs no snapshot |
| `SessionEnd` | Session terminates | Appends to `.claude/pipeline/session-log.txt` (capped at 500 lines) and clears findings, reports, stamps, and the write log; `.claude/plans/progress.md` and `.claude/metrics/` are untouched — both are persistent |

### Fail-closed principle

Every guard here asserts **positive evidence**, not merely well-formed failure reporting.
A checker, reviewer, or tester result is trusted only when it carries one `checks[]` entry per
check actually executed, each with the real process exit code; absent, empty, or
null-exit-code checks are refused at three layers (the MCP tool itself, `PostToolUse`, and
`SubagentStop`). A missing `jq` blocks rather than silently disabling the guard. The guards'
*presence* is what makes a green result meaningful, so failing open is worse than having no
guard at all.

---

## orchestrator-mcp

Exposes two tools, so every one of the 7 agents returns through a schema-validated call
rather than a markdown final message:

| Tool | Description |
|---|---|
| `write_findings(findings, pipeline?)` | Writes `<source>-findings.json` to `.claude/pipeline/` (or a per-track subdirectory for parallel runs), stamped with `written_at` |
| `write_report(report, pipeline?)` | Writes `<source>-report.json` to `.claude/pipeline/` (or a per-track subdirectory), stamped with `written_at` |

`write_findings`'s `source` is `checker`, `reviewer`, or `tester` — the only three agents
running commands and holding the tool. `checks` is required and non-empty for all three: the
call is **rejected** without it, because a result with no checks cannot be distinguished from
a run that never happened. Empty `issues`/`failures` lists are recorded verbatim rather than
dropped, so "reported nothing" stays distinct from "never populated the field".

`write_report`'s `source` is `reader`, `writer`, `thinker`, or `researcher` — agents that run
no commands and so have no `checks[]` to report. Every report type carries a `context_request`
field (`needs`, `why`) in place of a `## Context Request` markdown heading, and a handful of
fields are required outright to enforce a quality bar: `Convention.precedent`,
`Reference.source`, and `ThinkerReport.recommendation`.

Checker runs lint, typecheck, and build directly via `Bash`, reading the project's commands
from `CLAUDE.md` first and falling back to marker-file detection (`uv.lock` → ruff/mypy,
`package.json` → eslint/tsc, etc.). Reviewer runs the diff-review pass and reports issues at
`file:line`.

---

## ty-lsp

Python LSP via [Astral ty](https://github.com/astral-sh/ty). Provides go-to-definition, find-references, hover, and document-symbol on `.py` files.

**Prerequisite:** `uv tool install ty`

---

## tsgo-lsp

TypeScript and JavaScript LSP via tsgo. Provides go-to-definition, find-references, hover, and document-symbol on `.ts`, `.tsx`, `.js`, and `.jsx` files.

**Prerequisite:** `tsc --lsp --stdio` must be available on `PATH`.

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
