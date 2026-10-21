# orchestrator (Antigravity & Gemini Ecosystem)

Multi-agent orchestrator development ecosystem for Google Antigravity (AGY CLI) and Claude Code.
Features 7 specialized subagents, FastMCP dev-tools server with Plan Event Log, and cross-platform Python lifecycle hooks.

## Subagent Model Tiers

- `thinker` & `reviewer`: **Gemini 4 Argon** (`gemini-4-argon`, thinking: high/medium)
- `writer`: **Gemini 3.8 Flash** (routine) / **Gemini 4 Argon** (complex architectural tasks)
- `tester`, `reader`, `researcher`: **Gemini 3.8 Flash**
- `checker`: **Gemini 3.8 Flash** (thinking: low/off)

## Commands (repo root)

- Setup: `uv sync --all-groups`
- Test: `uv run pytest`
- Lint: `uv run ruff check`
- Typecheck: `uv run ty check`

## Antigravity Plugins Installation

Install plugins globally in Antigravity:

```bash
rtk agy plugin install plugins/orchestrator-skills
rtk agy plugin install plugins/orchestrator-gemini-agents
rtk agy plugin install plugins/orchestrator-hooks
rtk agy plugin install plugins/orchestrator-mcp
```

Always use `rtk` prefix for terminal commands on Windows (`rtk uv run pytest`, `rtk git status`).
