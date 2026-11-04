# Superpowers Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Superpowers skills dispatch the orchestrator agents through an opt-in bridge skill,
the agents get cheaper, `orchestrator-plan` is retired, and an evaluation kit exists to
compare cost with and without the bridge.

**Architecture:** Everything lives in our plugins; the superpowers plugin is never edited. A
new skill `orchestrator-skills:superpowers-bridge` holds per-skill overrides on top of the
existing `orchestrator` skill, which keeps its dispatch rules, verification and Plan Event
Log. One contract change: the tester findings classification `EXPECTED_RED`, so TDD's red
step is attested by findings.

**Tech Stack:** Claude Code plugin Markdown (skills, agent frontmatter), Python 3.14
(`dev_tools.py`, pydantic, fastmcp), pytest, ruff, ty, `claude plugin validate`.

**Spec:** `docs/superpowers/specs/2026-11-04-superpowers-bridge-design.md`

## Global Constraints

- Never edit anything under `~/.claude/plugins/cache/` (superpowers).
- Do not loosen any hook, guard or findings contract. The `writer` agent gets no Bash.
- Minimum Claude Code version: 2.1.317.
- The bridge is opt-in. It is not added to this repo's committed `CLAUDE.md`, nor to the
  README's default activation line.
- Repo commands: `uv run pytest`, `uv run ruff check`, `uv run ty check`.
- Semver per plugin: `orchestrator-skills` 1.31.0 → **2.0.0**, `orchestrator-agents` 1.27.0 →
  **1.28.0**, `orchestrator-mcp` 1.11.0 → **1.12.0**. Each is bumped in its own `plugin.json`
  and in `.claude-plugin/marketplace.json`.
- Commit messages follow the repo style:
  `<plugin> <version>[ / <plugin> <version>]: <summary>`.
- Docs and skill text are in English.

## Review Focus

1. **A superpowers skill text that still says `general-purpose`.** Every subagent-dispatching
   superpowers skill listed in the spec's mapping table needs an explicit override in the
   bridge. Task 3 Step 3 checks this.
2. **A tester red run on a test that fails for the wrong reason** (an import error, a typo in
   the test). That is not an expected red. `EXPECTED_RED` applies only when the failure
   matches the reason the task predicts; otherwise it is REGRESSION or UNCLEAR. Task 1's
   tester text and Task 3's TDD section both state this.
3. **Resuming a bridged plan after compaction.** The `orchestrator` skill's Resuming section
   only finds plans with `.claude/plans/<stem>.md`, so the bridge must copy the plan before
   `plan_archived`. Task 3 Step 3 checks this.
4. **The hybrid rule with nothing to rule from.** A REGRESSION/STALE_TEST diagnosis that
   neither the plan nor the spec settles must stop and ask, never become a ruling. Task 3
   states this.
5. **Dangling references to `orchestrator-plan` or `plan-format.md`** after the retirement.
   Task 4 Step 2 checks this with `rg`.

---

### Task 1: `EXPECTED_RED` tester classification

**Files:**
- Modify: `plugins/orchestrator-mcp/mcp-server-py/dev_tools.py:75-79` (`Failure`)
- Test: `plugins/orchestrator-mcp/mcp-server-py/test_server.py` (append)
- Modify: `plugins/orchestrator-agents/agents/tester.md` (the classification table near line
  79 and the rules near line 83)
- Modify: `plugins/orchestrator-skills/skills/orchestrator/verification.md` (Step 5,
  "Branch on result", and the tester-diagnosis paragraph near line 201)

**Interfaces:**
- Produces:
  `Failure.classification: Literal["REGRESSION", "STALE_TEST", "FLAKY", "UNCLEAR", "EXPECTED_RED"]`.
  Task 3 refers to `EXPECTED_RED` by this exact name.

- [ ] **Step 1: Write the failing tests**

```python
def test_failure_accepts_expected_red():
    f = server.Failure(test="t", classification="EXPECTED_RED", evidence="e", recommendation="r")
    assert f.classification == "EXPECTED_RED"


def test_write_findings_tester_expected_red_round_trips(tmp_path, monkeypatch):
    # same setup as the existing write_findings tests (pipeline dir under tmp_path)
    findings = server.TesterFindings(
        source="tester", status="FAIL",
        checks=[server.Check(name="pytest", status="FAIL", exit_code=1, output="1 failed")],
        failures=[server.Failure(test="t", classification="EXPECTED_RED", evidence="e", recommendation="r")],
    )
    # call write_findings(findings, label="red-step"); read the written JSON back
    assert written["failures"][0]["classification"] == "EXPECTED_RED"
```

Mirror the fixture and call style of the existing `write_findings` tests in the same file.

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `uv run pytest plugins/orchestrator-mcp/mcp-server-py/test_server.py -k expected_red -v`
Expected: FAIL with a pydantic `literal_error` on `classification`.

- [ ] **Step 3: Add `"EXPECTED_RED"` to the `Literal` in `Failure.classification`**

- [ ] **Step 4: Update `tester.md`**

Add a table row:

> **EXPECTED_RED** — the intended behavior change says this test was written before its
> implementation and must fail now. Evidence: the failure is the predicted one (for example,
> the missing name or the asserted value from the task), not a collection, import or syntax
> error. Recommendation: proceed to implementation.

Add a rule: a failure that does not match the predicted reason is never `EXPECTED_RED`.

- [ ] **Step 5: Update `verification.md` Step 5**

`EXPECTED_RED` failures are not diagnoses to surface. They clear the red step of a TDD task.
Every other classification keeps the existing handling.

- [ ] **Step 6: Run the full verification**

Run: `uv run pytest && uv run ruff check && uv run ty check`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add plugins/orchestrator-mcp/mcp-server-py/dev_tools.py plugins/orchestrator-mcp/mcp-server-py/test_server.py plugins/orchestrator-agents/agents/tester.md plugins/orchestrator-skills/skills/orchestrator/verification.md
git commit -m "orchestrator-mcp: EXPECTED_RED tester classification for TDD red steps"
```

---

### Task 2: Cheaper agents

**Files:**
- Modify the frontmatter of `plugins/orchestrator-agents/agents/{researcher,thinker,tester,reviewer}.md`
- Modify the body of `plugins/orchestrator-agents/agents/thinker.md`: one line
- Modify `plugins/orchestrator-skills/skills/orchestrator/SKILL.md`: the tester row of the
  Agent Catalog (Effort column)

**Interfaces:** none consumed or produced.

- [ ] **Step 1: Confirm the key format**

Read `https://code.claude.com/docs/en/sub-agents`, using the `claude-code-guide` agent if
needed. Confirm the frontmatter spelling and value type of `omitClaudeMd` (boolean) and
`autoCompactWindow` (token count). If either differs from what is written below, use the
documented form and note it in the commit body.

- [ ] **Step 2: Apply these exact settings**

| Agent | Change |
|---|---|
| researcher | `omitClaudeMd: true` |
| thinker | `omitClaudeMd: true`; add to the body: "If the question depends on project conventions, `Read` the project `CLAUDE.md` first." |
| tester | `effort: high` → `effort: medium`; `autoCompactWindow: 200000` |
| reviewer | `autoCompactWindow: 200000` |

Leave `reader`, `writer` and `checker` unchanged. `reader` and `writer` need the conventions,
and `checker` needs the Commands section and the user's global rtk instructions.

- [ ] **Step 3: Update the tester's Effort cell in the `orchestrator` SKILL.md catalog to `medium`**

- [ ] **Step 4: Validate**

Run: `claude plugin validate plugins/orchestrator-agents`
Expected: no errors. An unknown-key warning on the new keys means Step 1 got the spelling
wrong: fix it.

- [ ] **Step 5: Commit**

```bash
git add plugins/orchestrator-agents/agents plugins/orchestrator-skills/skills/orchestrator/SKILL.md
git commit -m "orchestrator-agents: omitClaudeMd, autoCompactWindow and tester effort for cheaper runs"
```

---

### Task 3: The `superpowers-bridge` skill

**Files:**
- Create: `plugins/orchestrator-skills/skills/superpowers-bridge/SKILL.md`
- Create: `plugins/orchestrator-skills/skills/superpowers-bridge/planning.md` (lazy-loaded;
  holds the content migrated from `orchestrator-plan` Steps 2, 3 and 6)

**Interfaces:**
- Consumes: `EXPECTED_RED` (Task 1); the `orchestrator` skill and its `verification.md`,
  `dispatch-levels.md` and `agent-contracts.md`, unchanged and referenced rather than copied.
- Produces: the skill `orchestrator-skills:superpowers-bridge`, used by Task 5's Run B
  kickoff.

- [ ] **Step 1: Write `SKILL.md`**

Frontmatter: `name: superpowers-bridge`. The `description` and `when_to_use` must say it is
opt-in, loaded explicitly, and loaded together with `orchestrator-skills:orchestrator`. The
body states, in this order:

1. **Precedence.** This skill is a user instruction. Where it and a superpowers skill
   disagree, this skill wins. Superpowers decides what happens and when; the orchestrator
   decides who does it and how it is proven.
2. **Override table.** One row per superpowers skill, exactly as in the spec's "How
   superpowers skills map under the bridge" table, each naming the `orchestrator-agents:*`
   type that replaces `general-purpose`.
3. **SDD under the bridge.**
   - Setup: skip `scripts/sdd-workspace` and `progress.md`; the Plan Event Log is the ledger.
     Run Start comes from the `orchestrator` skill, once.
   - Per task: `writer_dispatched` → `writer` → `checker` + `tester` + `reviewer` (the task
     review) → the Commit Recipe → `task_complete`.
   - Fix rounds 1–3 resume the same `writer` via `SendMessage`. Rounds 4–5 dispatch a fresh
     `writer` with `model` set one tier up.
   - Final review: the `orchestrator` skill's Final Full-Branch Review, then
     `superpowers:finishing-a-development-branch`.
4. **TDD under the bridge.**
   - Red: the `writer` writes only the test. The `tester` runs it with
     "Intended behavior change: <test> is written ahead of <feature> and must fail because
     <predicted reason>" and must return `EXPECTED_RED`.
   - Green: the `writer` implements, then the `tester` runs again and must PASS.
   - An unexpected red (any classification other than `EXPECTED_RED`) is handled like any
     other tester diagnosis.
5. **The hybrid rule.** A REGRESSION/STALE_TEST diagnosis is ruled on, with
   `write_plan_event(Ruling(kind="ruling", task=N, seq=…, text="<decision> — <why> — <cost if wrong>"))`,
   only when the plan or spec text settles it; quote that text in the ruling. Otherwise stop
   and ask the user (orchestrator invariant 3). A superpowers ruling on anything else also
   becomes a `ruling` event.
6. **Model.** Omit `model` on every dispatch, except the round 4–5 escalation and where
   superpowers asks for the most capable model.
7. **Planning.** For `writing-plans`, read `planning.md`.

- [ ] **Step 2: Write `planning.md`**

Move these from `orchestrator-plan/SKILL.md`:

- Step 2's dispatch table and its two non-negotiable demands, adapted. Plan mode is not used.
- Step 3's blast-radius categories, as a list folded into the text. Do not reference
  `plan-format.md`, which Task 4 deletes.
- Step 6's archive procedure, adapted:
  1. Copy the approved superpowers plan to `.claude/plans/<stem>.md`, where `<stem>` is the
     plan file's basename. It already matches `YYYY-MM-DD-<slug>`.
  2. Write `plan_archived{archive: "<original plan path>"}`.
  3. Write one `task_created` per `### Task N`; `files` comes from that task's `**Files:**`
     list.
  4. Write one `decision{who: "user"}` per user decision in the spec's decisions table.

  Keep the `supersedes` / `plan_abandoned` handling.

- [ ] **Step 3: Check coverage**

Run:
`rg -l "general-purpose|Subagent \(" ~/.claude/plugins/cache/claude-plugins-official/superpowers/*/skills`

Expected: every skill directory listed has a row in the override table. Also confirm that
`planning.md` copies the plan to `.claude/plans/` before the first `write_plan_event` call.

- [ ] **Step 4: Validate**

Run: `claude plugin validate plugins/orchestrator-skills`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add plugins/orchestrator-skills/skills/superpowers-bridge
git commit -m "orchestrator-skills: superpowers-bridge skill"
```

---

### Task 4: Retire `orchestrator-plan`; versions and README

**Files:**
- Delete: `plugins/orchestrator-skills/skills/orchestrator-plan/` (`SKILL.md`, `plan-format.md`)
- Modify: `plugins/orchestrator-skills/skills/orchestrator/verification.md:306`: point at
  `superpowers-bridge/planning.md`
- Modify: `README.md`, in these sections:
  - `## orchestrator-skills`: drop the `orchestrator-plan` row, add a `superpowers-bridge` row
    (opt-in, how to activate);
  - `## Plugins`: change the skill count;
  - `#### Cache configuration`: add `CLAUDE_CODE_SUBAGENT_EFFORT` as a safety net;
  - `## Requirements`: add the Claude Code ≥ 2.1.317 line;
  - `## orchestrator-agents`: update the tester's Effort cell.
- Modify: `plugins/{orchestrator-skills,orchestrator-agents,orchestrator-mcp}/.claude-plugin/plugin.json`
  and `.claude-plugin/marketplace.json`, with the versions from Global Constraints.

**Interfaces:** none.

- [ ] **Step 1: Delete the directory and edit the files above**

- [ ] **Step 2: Check for dangling references**

Run: `rg -n "orchestrator-plan|plan-format" --glob '!docs/**' .`
Expected: only the two example strings in `dev_tools.py` (lines 31 and 1061).

- [ ] **Step 3: Validate the marketplace and the plugins**

Run:
`claude plugin validate . && uv run pytest && uv run ruff check && uv run ty check`

Expected: all pass. The versions in each `plugin.json` match `marketplace.json`.

- [ ] **Step 4: Commit**

```bash
git add -A plugins/orchestrator-skills README.md .claude-plugin/marketplace.json plugins/*/.claude-plugin/plugin.json
git commit -m "orchestrator-skills 2.0.0 / orchestrator-agents 1.28.0 / orchestrator-mcp 1.12.0: superpowers bridge, retire orchestrator-plan"
```

---

### Task 5: Evaluation kit

**Files:**
- Create: `docs/benchmarks/2026-11-superpowers-bridge/kickoff-a.md`
- Create: `docs/benchmarks/2026-11-superpowers-bridge/kickoff-b.md`
- Create: `docs/benchmarks/2026-11-superpowers-bridge/comparison.md`

**Interfaces:**
- Consumes: the benchmark plan path, `docs/superpowers/plans/2026-11-04-hook-test-suite.md`.
  That plan is written after this plan completes and is out of scope here; the kickoffs
  reference it by this exact path.

- [ ] **Step 1: Write `kickoff-a.md`**

A prompt to paste into the Run A session. It contains:

- `cd` into worktree A (`git worktree add ../orchestrator-run-a <base>`);
- the instruction to execute the benchmark plan with `superpowers:subagent-driven-development`;
- a pre-answer: commit per task, and bugs found in hooks are recorded with `xfail(strict=True)`,
  never fixed.

It must not mention the bridge.

- [ ] **Step 2: Write `kickoff-b.md`**

The same as `kickoff-a.md`, except:

- worktree B;
- before anything else, load `orchestrator-skills:orchestrator` and then
  `orchestrator-skills:superpowers-bridge`;
- a precondition line for the user. The two sessions already exist, so `--plugin-dir` is not
  available. Push the plugins, run `/plugin update` for the orchestrator plugins (≥ 2.0.0) and
  `/reload-plugins` in both sessions before Run A. Run A then sees the same installed plugins
  as today's setup and simply never loads the bridge;
- pre-answer the Run Start auto-commit confirmation with "confirmed".

- [ ] **Step 3: Write `comparison.md`**

A table with one column per run and a row for each metric in the spec's Evaluation section,
with empty values. Add a "how measured" line per row, naming the source:

- `/usage` (user);
- transcripts under `~/.claude/projects/` (Claude);
- the plan event log (B) or git log (A) for fix rounds.

- [ ] **Step 4: Commit**

```bash
git add docs/benchmarks/2026-11-superpowers-bridge
git commit -m "docs: superpowers bridge evaluation kit"
```
