# Verification — Reference

Read this file when deciding whether, and how, to verify a write.

---

## When to verify

Verification is discretionary, not mandatory — the orchestrator or operator decides based
on the plan or the current task. Weigh:

- the plan's acceptance criteria — does it call for a check before the task is considered done?
- the blast radius of the change — a one-line fix in an isolated module needs less scrutiny than a shared interface or a hot path;
- whether anything executable changed — pure documentation or comment edits rarely warrant a full pass.

There is a round cap of 5 (see the Adjudication Protocol below) and no requirement to
dispatch checker, reviewer, and tester together. Call whichever of the three the task needs,
whenever it's warranted.

---

## Run Start

A single, unambiguous trigger, defined in terms of an **epoch** rather than a session — the
two are not the same thing: an epoch begins at session start and begins again at every
compaction-resume, so one session ordinarily contains multiple epochs (one per compaction).
Run Start's trigger is: **at most once per epoch, the first time in that epoch a writer is
about to be dispatched for a plan-backed run.** It fires again after a compaction specifically
because a compaction starts a new epoch — the WIP snapshot's re-capture and the in-flight
exclusion (step 3, below) both depend on Run Start re-firing post-compaction, within the same
session. This is not tied to `orchestrator/SKILL.md`'s `## Resuming` trigger (session start /
after compaction), which fires at a different frequency and would, folded into it, either
never run in the common archive-then-execute-same-turn path (Resuming never fires there) or
over-fire on a session that never touches this plan.

**This entire mechanism (the round cap's persisted count, this section, and the full-branch
review below) is conditional on a plan-backed run** — one with `.claude/plans/progress.md`
for the work in question. Plan-less, single-request verification (above) is unaffected: no
confirmation is asked, no commit is made, and the round cap is counted in-session only, with
nothing persisted. The commit ledger itself lives at `.claude/plans/<same stem as
`progress.md`'s `**Plan:**` value>.jsonl` — one file per plan, created on its first
`write_ledger_entry` call and never overwritten across different plans (unlike `progress.md`,
which is overwritten each time a new plan archives). "The ledger" below always means this
per-plan file, derived the same way every time.

Run Start runs its checks in this order, each one keyed on the field's literal value (its
first whitespace-delimited token — the stored value carries a trailing date), never on its
mere presence:

1. **Read `**Auto-commit:**` from `progress.md`'s header.** A `progress.md` written before
   this mechanism existed has no such line at all — treat an absent line identically to "not
   yet confirmed", never as `declined` or `confirmed`.
   - **Token is `declined`:** stop here. Do not capture Base, do not snapshot WIP, do not ask
     again. This plan runs in the pre-this-mechanism mode for the rest of its execution: no
     per-task commits, no ledger lines, `progress.md` checkboxes set directly by the
     orchestrator from each task's verification outcome, and the full-branch review never runs
     (skipped silently — the user was already told once, at the moment they declined, why).
   - **Token is `confirmed`:** proceed to step 2.
   - **Line is absent, or its token is neither (the "not yet confirmed" placeholder value):**
     state in one line that this run will commit each accepted task individually as it is
     approved, and ask the user to confirm — the natural point to discover whether Bash is
     available for this run at all (see the degraded path in the Commit Recipe, below). Then:
     - **Confirms:** write `**Auto-commit:** confirmed YYYY-MM-DD` into the header, replacing
       "not yet confirmed" (or adding the line, if it was absent). Proceed to step 2.
     - **Declines:** state in one line that this run will proceed without per-task commits or
       a full-branch review (so the "skipped silently" in the `declined` branch above means
       silent on later runs, not this one), then write `**Auto-commit:** declined YYYY-MM-DD`.
       Stop here, per the `declined` branch above.
2. **Record `**Base:** <sha of current HEAD>` into `progress.md`'s header — keyed on the
   header's literal value, the same way:** value `not yet captured` (or the line entirely
   absent, for a pre-this-mechanism `progress.md`) → obtain the current HEAD sha (`git
   rev-parse HEAD`) and write it now, this is a fresh start. Any other value (an actual sha is
   already recorded) → never silently overwritten by this step — specifically not "no
   validated line exists in the ledger", which would reopen the gate incorrectly after
   a rebase (a plan resumed after a history rewrite can have committed tasks whose lines all
   fail `--is-ancestor` validation while still being a mid-execution resume, not a fresh
   start). The one exception to "never overwritten" is the explicit user instruction
   described immediately below — never an automatic recapture.
   - **If the header already holds a sha but that sha itself fails `--is-ancestor <Base-sha>
     HEAD`** (the branch was rebased out from under a Base that was already recorded): Run
     Start halts here — it does not proceed to step 3, and no writer is dispatched this turn.
     Surface this to the user explicitly: the branch's history has been rewritten since this
     plan started, the eventual full-branch review has no valid starting point, and the user
     must choose one of two explicit instructions before Run Start can proceed — (a) "accept a
     fresh Base:" the orchestrator overwrites `**Base:**` with the current HEAD sha (the one
     narrow, explicit exception to "never overwritten" above), accepting that earlier
     committed tasks may fall outside the new diff, and Run Start then proceeds to step 3; or
     (b) "investigate first:" Run Start halts for this turn, nothing is written, and the user
     resolves the history question before the next Run Start.
   - **If Bash is unavailable when this step needs to run `git rev-parse HEAD` or
     `--is-ancestor`:** leave the header exactly as it was — never write a partial or
     placeholder value — and surface this to the user. Run Start halts here (as in the rebase
     case): no writer is dispatched this turn, and the same check is retried the next time Run
     Start runs for this plan.
3. **Snapshot `git status --porcelain`** — always re-captured, every time this step runs,
   resumed or not. This is the one Run Start artifact with no persisted memory across runs,
   and deliberately so for committed work — unlike Base, there is no already-committed work
   for a fresh WIP snapshot to lose track of. But it must exclude one thing to stay correct:
   the file set of any task that is currently in-flight — defined as: a task with a `Task N:
   writer dispatched.` or `Task N: forced fix applied.` line in `progress.md`'s `## Verify
   Rounds` section (see the Adjudication Protocol, below) whose last ledger line, if
   any, is not a **terminal** status. Terminal statuses are `complete` and
   `complete-with-parked` only — `reverted` and the degraded status-omitted line are not
   terminal for this purpose. This is the single test; nothing else defines "in-flight" for
   this step. It is precisely what makes the common case — a compaction landing between a
   writer returning and its first verify dispatch — coverable at all: the `Task N: writer
   dispatched.` marker is appended the moment the writer is dispatched, before any round is
   recorded, so the task already has a `## Verify Rounds` entry in that window. Excluding a
   task once its writer is dispatched and until it reaches a terminal ledger line means a task
   abandoned mid-loop in an *earlier*, separate effort cannot match — that task's `## Verify
   Rounds` entry belongs to a different, already-archived plan's `progress.md`.
   - **If Bash is unavailable for this snapshot:** proceed without a WIP guard for this Run
     Start — surface one line to the user noting the guard could not run this time, rather
     than halting the whole run over a snapshot.

---

## Steps

**1 — Clear stale findings:**
```bash
rm -f .claude/pipeline/checker-findings.json .claude/pipeline/reviewer-findings.json .claude/pipeline/tester-findings.json
# or for multi-track:
rm -f .claude/pipeline/<track>/checker-findings.json .claude/pipeline/<track>/reviewer-findings.json .claude/pipeline/<track>/tester-findings.json
```

**Note:** reviewer is always spawned fresh (never reused) — a deliberate correctness-over-cache
choice. A clean diff baseline each time is worth paying a cold cache; do not optimize it into
warm reuse.

**2 — Dispatch what the task calls for:**
```
Agent({ description: "Checker: lint + typecheck + build",  subagent_type: "orchestrator-agents:checker",  prompt: "Files: [list]. Pipeline: .claude/pipeline/[track if multi]." })
Agent({ description: "Reviewer: diff review",              subagent_type: "orchestrator-agents:reviewer", prompt: "Task: [desc]. Modified files: [list]. Diff base: [sha, or omit for the default per-task HEAD diff]. Pipeline: .claude/pipeline/[track if multi]." })
Agent({ description: "Tester: run and diagnose tests",     subagent_type: "orchestrator-agents:tester",   prompt: "Task: [desc]. Intended behavior change: [what the change was meant to alter]. Changed files: [list]. Test: [what]." })
```
Any subset, in any combination, is valid — there is no requirement to run all three, or to
run them in the same turn. `Diff base` is used only by the `## Final Full-Branch Review` step
below — every ordinary per-task reviewer dispatch omits it.

**3 — Read findings after dispatched agents complete:**

Each writes structured findings via `write_findings`; a `PostToolUse` hook auto-injects each
file's contents into your context as it lands, so you usually receive them without a manual
read. This mirrors the auto-injection for reports written by `write_report`, though reports
are not this file's concern — findings are the proof-of-execution signal verification acts
on. To read explicitly:
```bash
cat .claude/pipeline/checker-findings.json .claude/pipeline/reviewer-findings.json .claude/pipeline/tester-findings.json
```
`checker-findings.json` carries `checks[]` only (no `issues[]`). `reviewer-findings.json`
carries `issues[]` at `file:line` plus a `checks[]` entry for the review pass.
`tester-findings.json` carries the per-suite `checks` table plus a `failures` list, each
`{ test, classification, evidence, recommendation }`.

**4 — Branch on result. The two signals are handled differently:**

*Checker / reviewer findings (lint / typecheck / diff review)* — translate directly into an
ordinary writer dispatch:
- `status: PASS` + `review: APPROVED` → that side is clear
- `FAIL` or open `issues[]` → read the findings file(s) and dispatch a writer with its single
  input contract:
  - `## Context` — the findings from `checker-findings.json` / `reviewer-findings.json`
  - `## Task` — the required fix, lint and typecheck failures addressed before diff-review issues
  - `## Files to modify` — the affected files

*Tester diagnoses (test failures)* — **do NOT auto-fix.** Tester is readonly and classifies
each failure as REGRESSION / STALE_TEST / FLAKY / UNCLEAR. Because REGRESSION (fix the code)
and STALE_TEST (update the test) have opposite fixes, the orchestrator **presents the
diagnoses to the user and asks them to decide** what to do. Only after the user decides do you
dispatch a writer — with the decision folded into its `## Task` — to act on it. Never guess
which side a failure falls on, and never dispatch a test-authoring or test-fixing writer
without a user decision.

---

## Commit Recipe

For a plan-backed run with `**Auto-commit:** confirmed` (see `## Run Start`, above): once
checker/reviewer approve a task (step 4, above), the orchestrator —
never the writer, whose tool list has no `Bash` — commits that task's file set:

```bash
git add -- <paths>
git commit -m 'task <N>: <deliverable phrase>' -- <paths>
```

- `<paths>` is sourced from the writer's `write_report` `modified[]` entries with
  `in_scope: true`, intersected with the task's file set from the plan. Entries with
  `in_scope: false` are surfaced to the user, never committed as part of this task.
- **This source does not survive every boundary the commit can be attempted across** —
  `writer-*-report.json` is deleted on session start (along with the pre-compact snapshot),
  and a compaction's snapshot never covers a per-track report either. When this happens, do
  not improvise `<paths>` from the plan's §7 file set (the plan's file set is not necessarily
  the writer's actual committed set, and this is exactly the task the WIP guard already
  excludes as in-flight — so nothing would catch foreign dirt swept in on those paths).
  Instead: re-dispatch the writer for this task and commit from its fresh report. If the
  fresh report's `modified[]` is empty (the prior edits are still in the working tree — only
  the report was lost), do not commit from it either — ask the user how to proceed.
- `git add` is required before the pathspec commit for any newly-created file (a bare
  pathspec commit does not pick up untracked files).
- The commit message is always `-m`, never an editor invocation — `git commit -- <paths>`
  with no `-m` would open `$EDITOR` and hang the agent. `<deliverable phrase>` is derived from
  the task's numbered §7 line only (never its Consumes/Produces sub-lines): take the text
  before the task's first `—`, strip the leading numeric prefix and its trailing `.` and
  whitespace, strip any backticks, strip (not escape) any single-quote characters, and pass
  the result single-quoted, never double-quoted (§7 lines routinely contain backticked file
  names, and backticks inside a double-quoted `-m` string are shell command substitution).
- Never `-a`. Current branch only — never creates a branch, never pushes. Two reasons: (1)
  the writer has no `Bash` tool — only the orchestrator can commit; (2) under L2/L3 a sibling
  track may have uncommitted edits in the same working tree at the same moment — pathspec-only
  commits are what keep one task's commit from sweeping in another track's in-flight work.

**WIP guard:** the `git status --porcelain` snapshot taken at Run Start (re-captured every
epoch, excluding any in-flight task's own file set) is checked against each task's file set
before that task's commit. If any path was already dirty at the snapshot moment, surface it
to the user before committing rather than silently including their pre-existing uncommitted
work. If no snapshot exists for the current epoch (Run Start never fired because no writer
was dispatched that epoch — e.g. a re-verify-only epoch after a compaction): skip the WIP
guard for this commit and surface one line to the user stating it was skipped, never commit
silently as if a stale snapshot still applied.

**Ledger writes go through `mcp__plugin_orchestrator-mcp_dev-tools__write_ledger_entry`, on
every write, not only the degraded path below** — never a hand-rolled `Read`/`Write` append.
The tool takes `entry` (the fields below) and `plan` (the archive stem — see above); it
appends and creates the file on first use, so nothing needs to pre-create it. This is schema
validation, not subagent-boundary attestation (the orchestrator itself is both the actor that
ran the commit and the caller of this tool, so there is no proof-of-execution gap to bridge)
— what it buys is a malformed call being rejected and retried instead of silently corrupting
a line every later Resuming/Run Start/Adjudication Protocol read depends on parsing
correctly. `Bash` is needed only for the actual `git add` / `git commit` / `git revert`
operations, never for recording their result in the ledger.

**Degraded path — a specific commit cannot be made (Bash denied or unavailable for this
commit, distinct from `**Auto-commit:** declined`, which stops per-task commits for the whole
run before any commit is attempted):** call `write_ledger_entry` with `sha: null` and
`status`/`files` omitted, and surface this to the user immediately. On any later resume, a
`sha: null` line always renders `[!]`.

**Failure path:**
- Task already committed, needs undoing → `git revert <sha>` (a new commit, never a history
  rewrite) → `write_ledger_entry({task: N, sha: "<revert-sha>", status: "reverted", reverts:
  "<original-sha>"}, plan: "<stem>")`.
- Task not yet committed → discard the writer's edits; no ledger line is written.

**Ledger schema** — append-only, one line per ledger event (each line the JSON body of one
`write_ledger_entry` call), e.g.:
```json
{"task": 3, "sha": "a1b2c3d", "files": ["path/a.ts", "path/b.ts"], "status": "complete"}
{"task": 4, "sha": "b2c3d4e", "files": ["path/c.ts"], "status": "complete-with-parked", "ruling": "trailing whitespace flagged by reviewer, cosmetic, parked at round cap"}
{"task": 3, "sha": "c3d4e5f", "status": "reverted", "reverts": "a1b2c3d"}
```
Fields: `task` (int, required), `sha` (string, or `null` on the degraded path), `files`
(array — holding exactly the `<paths>` from that commit — present when `status` is
`complete`/`complete-with-parked`, absent on `reverted` and on the degraded line), `status`
(optional — one of `complete` | `complete-with-parked` | `reverted`; absent specifically and
only on the degraded path, where `sha: null` is itself what marks the line), `ruling`
(present only when status is `complete-with-parked`), `reverts` (present only when status is
`reverted`, naming the sha it undoes). A task may have more than one line — the reader takes
the **last line for each task number**, independently, as that task's current status; there
is no "trusted prefix" and no task-number-gap rule, since under L2/L3 parallel tracks finish
out of order.

---

## Final Full-Branch Review

A step after the last task's commit (and, for L2/L3, after the existing integration pass in
`dispatch-levels.md`) — applies to multi-task L1 work too, which is why the pointer to this
section lives in `orchestrator/SKILL.md` rather than the whole mechanism living in
`dispatch-levels.md` (scoped to L2/L3 only, an L1 orchestrator never opens it). Per-task
review (the checker/reviewer/tester dispatch above) always runs *before* that task's commit,
so it always sees uncommitted working-tree content — nothing about per-task review changes.

**This step only runs once every *file-authoring* task's last ledger line is `complete` or
`complete-with-parked`.** If any file-authoring task's last line is `reverted` or the degraded
`sha: null`, that task is not actually done — this review does not run; surface the
outstanding task(s) to the user instead (a revert needs a new writer dispatch to redo the
work; a degraded line needs Bash restored or a manual commit). A verification-only task (no
file set) never participates in this precondition or in `<files>` below.

Dispatch a fresh `reviewer` scoped to the whole branch, diffing against the `Base` sha
recorded in `progress.md`'s header — not `git merge-base <base-branch> HEAD`, which is
undefined when working directly on `main` or when there is no clear base branch. `<files>` is
the union of every file-authoring task's file set, built from each task's last ledger line's
`files` array. This pass is additional to, not a replacement for, per-track verification
already described in `dispatch-levels.md` and above.

---

## Final Summary

Return this block when the task is complete:

```
## Done

**Task:** [original task]
**Status:** Done / Escalated

**Changes:**
- [file] — [what changed]

**Tests:** [N new, all passing / N failing]
**Verify:** not run / APPROVED / [open issues]
```

---

## Adjudication Protocol

The cap is per task — each task's own write→verify→fix loop caps at 5 rounds, counted
independently. Under L2/L3, each parallel track's per-task counter is independent; there is
no shared cross-track counter. **The count is recorded, not held only in-session, for a
plan-backed run** (one with a `.claude/plans/progress.md` for this work — plan-less,
single-request verification counts the cap in-session only and writes nothing, since there
is no `progress.md` to write into): each round appends one line to `progress.md`'s existing
`## Verify Rounds` section in the fixed form `Task N, round R: <finding count> findings.` —
`<finding count>` is the sum across every agent dispatched that round (one combined line, not
one line per agent). On resume (including after a compaction), the cap logic re-reads this
section and resumes counting from the highest recorded round for that task, rather than
silently restarting at 1 — a silent reset would let a task cycle past 5 real rounds across
enough compactions, defeating the cap.

**Every writer dispatch for a task — the task's first, or a forced fix — appends a
fixed-form, round-less line to `## Verify Rounds` the moment it is dispatched:**
`Task N: writer dispatched.` on the task's first (or any ordinary re-)dispatch, and
`Task N: forced fix applied.` specifically for a forced-fix dispatch (below). Both are
distinct from `Task N, round R: <finding count> findings.` and from each other, and neither
is ever edited in place once appended — `## Verify Rounds` stays append-only, with no
exception. This is what makes `## Run Start`, step 3's in-flight-task exclusion (above)
actually work in its stated common case (a compaction landing
between a writer returning and its first verify dispatch): without a `Task N: writer
dispatched.` line, that task would have *no* `## Verify Rounds` entry at all in that window,
and step 3's test would wrongly conclude it is not in-flight.

At the cap, every open finding from checker/reviewer must be explicitly adjudicated —
never silently dropped:
- **Parked** — recorded with a one-line ruling stating why it is not blocking (e.g. cosmetic,
  out of scope, pre-existing). The task is accepted with `status: "complete-with-parked"` in
  the ledger, and the ruling text travels with that ledger line.
- **Forced fix** — if the finding is load-bearing (breaks a stated acceptance criterion,
  introduces a correctness bug), exactly **one** more writer dispatch is made specifically
  to fix it, followed by exactly **one** re-verify pass — neither of which counts against
  the 1-5 round cap, and neither of which can itself trigger another forced-fix cycle. This
  is enforced across a compaction, not just in-session, via the `Task N: forced fix applied.`
  line above, appended the moment the forced-fix writer dispatch is made. If the re-verify
  pass has not yet run when the section is next read (e.g. a compaction landed between the
  forced-fix dispatch and its re-verify), that is exactly the same as any other in-flight
  task per Run Start step 3's exclusion rule — its presence in `## Verify Rounds` with no
  terminal ledger line already marks it in-flight. Before authorizing a forced fix,
  the cap logic checks for a `Task N: forced fix applied.` line for that task; if present, a
  second forced fix is never authorized — the still-open finding escalates to the user
  instead, exactly as an unresolved load-bearing finding does after the one permitted forced
  fix (below). These two round-less lines are never mistaken for a numbered round — they
  carry no round number and cannot be confused with the 1-5 count the cap logic re-reads on
  resume. Whatever the re-verify pass finds after that single fix is adjudicated
  immediately, not re-looped: still-open, non-load-bearing findings park with a ruling as
  above; a still-open load-bearing finding after this one forced fix escalates to the user
  rather than triggering a second forced-fix round — the cap's whole purpose is defeated if
  "forced fix" can itself become an unbounded loop.

**Exception — tester findings are never force-fixed at the cap.** Core Invariant 3 already
governs tester diagnoses: REGRESSION and STALE_TEST have opposite fixes, so a tester finding
that survives to the round cap escalates to the user for a decision, exactly as it would at
round 1 — the cap does not authorize skipping that decision.
