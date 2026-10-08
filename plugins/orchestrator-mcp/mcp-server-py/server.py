#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = ["fastmcp>=2.0.0"]
#
# [tool.ty.environment]
# root = ["."]
# ///
"""Launcher for the dev-tools MCP server.

The plugin starts the server with `uv run server.py`, which installs the dependencies
declared in the inline script metadata above. The implementation lives in dev_tools.py, a
plain module, so tests and language servers can import it directly. Keep `dependencies` in
sync with the repo-root pyproject.toml — test_server.py checks it.
"""

from dev_tools import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
