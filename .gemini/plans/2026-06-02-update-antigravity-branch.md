# Update Antigravity Branch to Orchestrator V2 — Orchestrator Plan

> **For execution:** Use `orchestrator-execute` to run this plan.

**Goal:** Reconcile and merge the main branch's V2 redesign into the antigravity branch, adapting the new verify agent and other updated configurations to Google Gemini models, optimizing MCP server robustness, and updating the unit test suite.
**Date:** 2026-06-02

---

## Explanation

The `main` branch has been upgraded to Orchestrator V2, which introduces a consolidated multi-agent catalog (6 agents instead of 8), simplified skills (retaining only `orchestrator` and `orchestrator-plan`), L1/L2/L3 dispatch levels, and an integrated `verify` agent.

This plan details the steps required to safely bring the `antigravity` branch up to date with these V2 updates while preserving its core integrations:
1. **Model & LSP Preservation**: Retain all custom LSP plugins (`go-lsp`, `lua-lsp`, `rust-lsp` in addition to `ty-lsp`, `vtsls-lsp`) and map the new `verify` agent to Gemini models (`gemini-3.1-pro`).
2. **Configuration Alignment**: Re-synchronize the root-level hook files and MCP configurations specifically used by the Google Antigravity CLI.
3. **MCP Server Robustness**: Fix an outstanding design gap in the Python MCP server's `write_findings` tool by extending it to accept `lint`, `typecheck`, and `review` parameters as defined in the V2 verify agent description, and write all findings seamlessly to `verify-findings.json`.
4. **Test Reconcile**: Remove obsolete hook tests (as `guard-bash-readonly.sh` is dropped in V2) and add new test cases covering the `verify` flow.

---

## Files

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `.gemini-plugin/marketplace.json` | Restore custom LSP plugins and update versions to match v2.0.1. |
| Modify | `README.md` | Reconcile v2 design changes with Antigravity native CLI installation instructions and Gemini mappings. |
| Modify | `plugins/orchestrator-core/agents/verify.md` | Port the verify agent to use `gemini-3.1-pro` model. |
| Modify | `plugins/orchestrator-core/agents/reader.md` | Ensure it uses `gemini-3.5-flash`. |
| Modify | `plugins/orchestrator-core/agents/researcher.md` | Ensure it uses `gemini-3.1-pro`. |
| Modify | `plugins/orchestrator-core/agents/tester.md` | Ensure it uses `gemini-3.1-pro`. |
| Modify | `plugins/orchestrator-core/agents/thinker.md` | Ensure it uses `gemini-3.1-pro`. |
| Modify | `plugins/orchestrator-core/agents/writer.md` | Ensure it uses `gemini-3.1-pro`. |
| Modify | `plugins/orchestrator-core/hooks.json` | Re-sync root-level hooks with V2 hook definitions. |
| Modify | `plugins/orchestrator-core/mcp-server-py/server.py` | Add `lint`, `typecheck`, and `review` arguments to `write_findings` for robust handling of the `verify` agent. |
| Modify | `plugins/orchestrator-core/tests/test_server.py` | Add unit tests for `verify` source findings writing. |
| Modify | `plugins/orchestrator-core/tests/test_hooks.py` | Clean up obsolete guard tests and add verification tests. |
| Delete | `plugins/orchestrator-core/agents/checker.md` | Clean up obsolete agent file. |
| Delete | `plugins/orchestrator-core/agents/reviewer.md` | Clean up obsolete agent file. |
| Delete | `plugins/orchestrator-core/agents/documenter.md` | Clean up obsolete agent file. |

---

## Tasks

1. **Merge `main` branch into `antigravity`** — Run `git merge main`, resolve conflicts in `.gemini-plugin/marketplace.json` and `README.md`, and reconcile agent deletions (`checker.md`, `reviewer.md`, `documenter.md`).
2. **Migrate V2 Verify Agent to Gemini** — Update `plugins/orchestrator-core/agents/verify.md` to use `gemini-3.1-pro`.
3. **Validate Other Agents' Model Mappings** — Confirm `reader.md` uses `gemini-3.5-flash` and others use `gemini-3.1-pro`.
4. **Re-sync Root-Level Hook Files** — Synchronize `plugins/orchestrator-core/hooks.json` and `plugins/orchestrator-core/hooks/hooks.json` to V2 specifications.
5. **Improve MCP Server Findings Tool** — Refactor `plugins/orchestrator-core/mcp-server-py/server.py` to robustly support `verify` and its optional metadata parameters.
6. **Update Hook & Server Test Suites** — Update `test_server.py` and `test_hooks.py` to match V2 agent/hook specifications.
7. **Verify Suite Passing** — Run unit tests (`pytest`) in the workspace and confirm success.
