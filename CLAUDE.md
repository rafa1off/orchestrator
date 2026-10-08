# orchestrator

Claude Code plugins (agents, skills, hooks, an MCP server, LSP configs). The only Python is the
dev-tools MCP server in `plugins/orchestrator-mcp/mcp-server-py/`; the repo-root `pyproject.toml`
is its dev-only project (the plugin itself launches `server.py` from its inline script metadata).

## Commands (repo root)

- Setup: `uv sync --all-groups`
- Test: `uv run pytest`
- Lint: `uv run ruff check`
- Typecheck: `uv run ty check`

`uv run` syncs the root `.venv` to `uv.lock` first; add tools to the `dev` group, not by hand.
