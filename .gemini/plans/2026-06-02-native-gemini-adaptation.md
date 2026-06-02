# Native Gemini & Antigravity Transition Plan — Orchestrator Plan

> **For execution:** Use `orchestrator-execute` to run this plan.

**Goal:** Permanently adapt the orchestrator ecosystem to a native Google Gemini / Antigravity integration by removing all Claude mentions, transitioning config folders from `.claude` to `.gemini`, renaming `CLAUDE.md` to `GEMINI.md`, and implementing an automated Git-sync hook for seamless plugin deployments.
**Date:** 2026-06-02

---

## Explanation

Through deep reverse-engineering of the Google Antigravity CLI (`agy`) binary and its configuration schemas, we discovered that:
1. **Remote-Backed Marketplaces**: The `agy plugin link` and `install` commands are backed by a Google internal gRPC service (`ListRemoteRepositories`, `GetSkillMarketplaceLink`). It validates marketplaces against an official remote registry, which is why custom third-party marketplaces return `unknown marketplace`.
2. **Direct Local Installations**: `agy plugin install <local-path>` is fully supported natively! It reads the root-level `plugin.json` and perfectly processes skills, agents, MCP servers, and hooks.
3. **Automated Git Sync**: We can achieve a 100% native, copy-free, symlink-free sync by deploying a **Git `post-merge` hook** in the local workspace. Every time a `git pull` or branch update occurs, the hook automatically runs the native `agy plugin install` command, keeping the active plugins perfectly in sync with the checked-out branch.

This plan transitions the entire ecosystem to a first-class Gemini experience.

---

## Files

| Action | Path | Purpose |
|--------|------|---------|
| Rename | `.claude-plugin/` &rarr; `.gemini-plugin/` | Rename the marketplace metadata directory. |
| Modify | `.gemini-plugin/marketplace.json` | Update plugin versions, descriptions, and schemas to native Gemini. |
| Create | `GEMINI.md` | Create the native Gemini project coordination manual (replaces `CLAUDE.md`). |
| Delete | `CLAUDE.md` | Remove the old Claude coordination manual. |
| Modify | `README.md` | Completely remove Claude instructions, focusing entirely on native Antigravity installation and Git-sync hook. |
| Modify | `plugins/orchestrator-core/agents/*.md` | Update all 6 agents (reader, researcher, tester, thinker, verify, writer) to reference `GEMINI.md` and `.gemini/` directories. |
| Modify | `plugins/orchestrator-core/skills/*.md` | Update orchestrator and orchestrator-plan skills to reference `GEMINI.md` and `.gemini/`. |
| Modify | `plugins/orchestrator-core/hooks.json` | Re-align all hooks to clean and validate `.gemini/pipeline/verify-findings.json`. |
| Modify | `plugins/orchestrator-core/hooks/hooks.json` | Re-align hooks in subdirectory to `.gemini/pipeline/verify-findings.json`. |
| Modify | `plugins/orchestrator-core/hooks/post-tool-findings.sh` | Update pipeline findings path to `.gemini/pipeline/`. |
| Modify | `plugins/orchestrator-core/mcp-server-py/server.py` | Rename environment variables and default directory to `.gemini/pipeline/`. |
| Modify | `plugins/orchestrator-core/mcp_config.json` | Rename environment variables passed to the MCP server. |
| Modify | `plugins/orchestrator-core/plugin.json` | Update metadata description to remove Claude mentions. |
| Modify | `plugins/orchestrator-core/tests/test_server.py` | Re-align mock findings directories and paths to `.gemini/`. |
| Modify | `plugins/orchestrator-core/tests/test_hooks.py` | Re-align mock findings directories and paths to `.gemini/`. |
| Create | `.git/hooks/post-merge` | Add the Git post-merge hook to automate `agy plugin install` on updates. |

---

## Tasks

1. **Perform Directory Renamings & Deletions** — Rename `.claude-plugin/` to `.gemini-plugin/` and prepare for folder structure conversion.
2. **Transition project orchestration** — Rename and rewrite `CLAUDE.md` to `GEMINI.md`.
3. **Re-align Agents and Skills** — Globally replace `CLAUDE.md` with `GEMINI.md` and `.claude/` with `.gemini/` in all agent and skill markdown files.
4. **Update Hook Configurations & Script** — Modify `hooks.json` and `post-tool-findings.sh` to target `.gemini/pipeline/verify-findings.json`.
5. **Update MCP Server & Config** — Refactor `server.py` and `mcp_config.json` to use `GEMINI_PROJECT_DIR` and `.gemini/pipeline/`.
6. **Re-align Test Suite Paths** — Update `test_server.py` and `test_hooks.py` to assert `.gemini/` pathing, and verify `pytest` passes.
7. **Deploy Git Sync Hook** — Install the Git `post-merge` hook in the repository to automate live plugin synchronization.
