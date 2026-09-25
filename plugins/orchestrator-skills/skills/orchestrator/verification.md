# Verification — Reference

Read this file when deciding whether, and how, to verify a write.

---

## When to verify

Task-scoped verification is discretionary, not mandatory — the orchestrator or operator
decides based on the plan or the current task. Weigh:

- the plan's acceptance criteria — does it call for a check before the task is considered done?
- the blast radius of the change — a one-line fix in an isolated module needs less scrutiny than a shared interface or a hot path;
- whether anything executable changed — pure documentation or comment edits rarely warrant a full pass.

There is a round cap of 5 (see the Adjudication Protocol below) and no requirement to
dispatch checker, reviewer, and tester together. Call whichever of the three the task needs,
whenever it's warranted.

The Final Full-Branch Review (below) is the one exception: for a plan-backed run with
`auto_commit: "confirmed"` it is **mandatory and synchronous** — it always runs once every
file-authoring task is complete, and always dispatches all three verifiers together. A
declined run (`auto_commit: "declined"`) skips this review entirely — see `## Final
Full-Branch Review` below for how a declined run closes instead.

---

## Run Start

A single, unambiguous trigger, defined in terms of an **epoch** rather than a session — the
two are not the same thing: an epoch begins at session start and begins again at every
compaction-resume, so one session ordinarily contains multiple epochs (one per compaction).
Run Start's trigger is: **at most once per epoch, the first time in that epoch a writer is
about to be dispatched for a plan-backed run.** It fires again after a compaction specifically
because a compaction starts a new epoch — the WIP snapshot's re-capture and the
dispatched-but-not-completed task exclusion (step 3, below) both depend on Run Start re-firing
post-compaction, within the same session. This is not tied to `orchestrator/SKILL.md`'s `## Resuming` trigger (session start /
after compaction), which fires at a different frequency and would, folded into it, either
never run in the common archive-then-execute-same-turn path (Resuming never fires there) or
over-fire on a session that never touches this plan.

**This entire mechanism (the round cap's persisted count, this section, and the full-branch
review below) is conditional on a plan-backed run** — one with a Plan Event Log,
`.claude/plans/<stem>.jsonl`, for the work in question, where `<stem>` is the plan archive's
stem (`.claude/plans/<stem>.md`). Plan-less, single-request verification (above) is
unaffected: no confirmation is asked, no commit is made, and the round cap is counted
in-session only, with nothing persisted.

Run Start runs its checks in this order:

1. **Read `get_plan_state(plan).auto_commit`.**
   - **`"declined"`:** stop here. Do not record Base, do not snapshot WIP, do not ask again.
     This plan runs without per-task commits for the rest of its execution: no `commit_failed`
     events and no full-branch review (skipped silently — the user was already told once, at
     the moment they declined, why). Tasks still complete: once a task's verification is
     accepted, write `TaskComplete(kind="task_complete", task=N, attempt=<n>, status=...,
     sha=None, files=<paths>, no_sha_reason="auto_commit_declined")` — this is what lets
     readiness and `plan_complete` still work with no commits ever made. A verification-only
     task (`files: null`) closes the same way regardless of `auto_commit`: `TaskComplete(...,
     sha=None, files=None, no_sha_reason="verification_only")`. See `## Final Full-Branch
     Review` below for how and when a declined run writes `plan_complete`.
   - **`"confirmed"`:** proceed to step 2.
   - **`None` (not yet decided):** state in one line that this run will commit each accepted
     task individually as it is approved, and ask the user to confirm — the natural point to
     discover whether Bash is available for this run at all (see the degraded path in the
     Commit Recipe, below). Then:
     - **Confirms:** `write_plan_event(AutoCommit(kind="auto_commit", status="confirmed", seq=next_seq["auto_commit"]), plan)`. Proceed to step 2.
     - **Declines:** state in one line that this run will proceed without per-task commits or
       a full-branch review (so the "skipped silently" in the `"declined"` branch above means
       silent on later runs, not this one), then `write_plan_event(AutoCommit(kind="auto_commit", status="declined", seq=next_seq["auto_commit"]), plan)`. Stop here, per the
       `"declined"` branch above.
2. **Record Base.** `PlanState.base_sha is None` → obtain the current HEAD sha (`git
   rev-parse HEAD`) and `write_plan_event(BaseRecorded(kind="base_recorded", sha=<sha>,
   reason="initial", seq=next_seq["base_recorded"]), plan)` — this is a fresh start. A
   `base_sha` already recorded is never silently overwritten by this step — specifically not
   because `base_sha_valid` is `False`, which would reopen the gate incorrectly after a
   rebase (a plan resumed after a history rewrite can have completed tasks whose commits all
   fail ancestor validation while still being a mid-execution resume, not a fresh start). The
   one exception to "never overwritten" is the explicit user instruction described
   immediately below — never an automatic recapture.
   - `base_sha_valid` is computed server-side by `get_plan_state` (never by an orchestrator-run
     ancestor check) — Bash is only needed in this step to run `git rev-parse HEAD` when
     actually recording a Base.
   - **If `base_sha_valid is False`** (the branch was rebased out from under a Base that was
     already recorded): Run Start halts here — it does not proceed to step 3, and no writer is
     dispatched this turn. Surface this to the user explicitly: the branch's history has been
     rewritten since this plan started, the eventual full-branch review has no valid starting
     point, and the user must choose one of two explicit instructions before Run Start can
     proceed — (a) "accept a fresh Base:" the orchestrator writes a new `base_recorded` event
     with the current HEAD sha and `reason: "rebase_accepted"` (the one narrow, explicit
     exception to "never overwritten" above — `get_plan_state` reads the latest
     `base_recorded` line, so this is how the new sha takes effect), accepting that earlier
     completed tasks may fall outside the new diff, and Run Start then proceeds to step 3; or
     (b) "investigate first:" Run Start halts for this turn, nothing is written, and the user
     resolves the history question before the next Run Start. Either way, record
     `write_plan_event(PlanEscalation(kind="escalation", topic="base_rebased",
     seq=next_seq["escalation"], detail=...), plan)`.
   - **If `base_sha_valid is None`** (git unavailable, so the check could not run at all):
     treat this as unverifiable, never as valid — do not proceed as though the Base were good.
   - **If Bash is unavailable when this step needs to run `git rev-parse HEAD`, or
     `base_sha_valid is None`:** write nothing — never a partial or placeholder event — and
     surface this to the user. Run Start halts here (as in the rebase case): no writer is
     dispatched this turn, and the same check is retried the next time Run Start runs for this
     plan. Record `write_plan_event(PlanEscalation(kind="escalation", topic="base_unavailable",
     seq=next_seq["escalation"], detail=...), plan)`.
3. **Snapshot `git status --porcelain`** and write `EpochStart(kind="epoch_start",
   epoch=<get_plan_state(plan).epoch + 1>, wip=<paths or null>, excluded_tasks=<task numbers>,
   after_compaction=<true when this epoch began from a compaction resume>)` — always
   re-captured, every time this step runs, resumed or not. This is the one Run Start artifact
   with no persisted memory across runs, and deliberately so for committed work — unlike
   Base, there is no already-committed work for a fresh WIP snapshot to lose track of. But it
   must exclude the right set of tasks to stay correct: every task where `last_attempt > 0 and
   not ready and status != "dropped"` — dispatched-but-unreturned, returned-but-uncommitted,
   and `commit_failed` are all covered by this single test; `TaskState.in_flight` itself is
   narrower (it clears the moment `writer_returned` lands) and is not what this exclusion uses.
   Using the wider test is what makes the common case — a compaction landing between a writer
   returning and its first verify dispatch — coverable at all: in that window the task's own
   uncommitted edits are still sitting in the working tree, and without this exclusion they'd
   land in `epoch_start.wip` and then get flagged by the WIP guard as the task's own
   pre-existing dirt.
   - **If Bash is unavailable for this snapshot:** proceed without a WIP guard for this Run
     Start — write `epoch_start` with `wip: null` and surface one line to the user noting the
     guard could not run this time, rather than halting the whole run over a snapshot.

---

## Steps

**1 — Clear stale findings:**
```bash
rm -f .claude/pipeline/checker-*-findings.json .claude/pipeline/reviewer-*-findings.json .claude/pipeline/tester-*-findings.json
# or for multi-track:
rm -f .claude/pipeline/<track>/checker-*-findings.json .claude/pipeline/<track>/reviewer-*-findings.json .claude/pipeline/<track>/tester-*-findings.json
```

**Note:** reviewer is always spawned fresh (never reused) — a deliberate correctness-over-cache
choice. A clean diff baseline each time is worth paying a cold cache; do not optimize it into
warm reuse.

**2 — Before dispatching a writer, record the attempt:**

`write_plan_event(WriterDispatched(kind="writer_dispatched", task=N, attempt=<last_attempt +
1>, reason=<"initial" | "fix" | "forced_fix" | "redo" | "branch_fix" | "report_lost">, files=[...]), plan)` —
`attempt` comes from `get_plan_state(plan).tasks[N].last_attempt + 1`. **Attempt rule:**
attempt increments on every hand-off of new work to the writer, with no exception — the
initial dispatch, every ordinary fix-loop round, a forced fix, and a post-revert redispatch
each get a fresh attempt number.

**3 — Dispatch what the task calls for:**

A verifier's `attempt` is the attempt *under review*, not the next one:
`attempt: get_plan_state(plan).tasks[N].last_attempt` — never `+ 1`, which is only for
dispatching a writer (step 2, above). A verification-only task (no writer dispatched for it)
uses `attempt: 1` for both its `verify_round` and its eventual `task_complete`.
```
Agent({ description: "Checker: lint + typecheck + build",  subagent_type: "orchestrator-agents:checker",  prompt: "Files: [list]. Pipeline: .claude/pipeline/[track if multi]. plan: <stem>, task: N, attempt: <n>, seq: <next_seq['verify_round']>." })
Agent({ description: "Reviewer: diff review",              subagent_type: "orchestrator-agents:reviewer", prompt: "Task: [desc]. Modified files: [list]. Diff base: [sha, or omit for the default per-task HEAD diff]. Pipeline: .claude/pipeline/[track if multi]. plan: <stem>, task: N, attempt: <n>, seq: <next_seq['verify_round']>." })
Agent({ description: "Tester: run and diagnose tests",     subagent_type: "orchestrator-agents:tester",   prompt: "Task: [desc]. Intended behavior change: [what the change was meant to alter]. Changed files: [list]. Test: [what]. plan: <stem>, task: N, attempt: <n>, seq: <next_seq['verify_round']>." })
Agent({ description: "Writer: [deliverable]",              subagent_type: "orchestrator-agents:writer",    prompt: "## Context ... plan: <stem>, task: N, attempt: <n>." })
```
For the Final Full-Branch Review, checker/reviewer/tester instead carry `plan`, `branch_round`,
and `seq` (from `next_seq["branch_check"|"branch_review"|"branch_test"]`) in place of `task` +
`attempt` — see below. `plan`, `task`/`attempt`/`branch_round`, and `seq` are echoed back
unchanged by the agent to `write_findings`/`write_report` — never invented by the dispatched
agent. Any subset of the three verifiers is valid for a task-scoped round, in any combination
— there is no requirement to run all three, or in the same turn. `Diff base` is used only by
the `## Final Full-Branch Review` step below — every ordinary per-task reviewer dispatch omits
it.

**4 — Read findings after dispatched agents complete:**

Each writes structured findings via `write_findings`, which appends the corresponding
`verify_round`/`branch_check`/`branch_review`/`branch_test` event before writing the pipeline
file; a `PostToolUse` hook auto-injects each file's contents into your context as it lands, so
you usually receive them without a manual read. This mirrors the auto-injection for reports
written by `write_report`, though reports are not this file's concern — findings are the
proof-of-execution signal verification acts on. To read explicitly:
```bash
cat .claude/pipeline/checker-*-findings.json .claude/pipeline/reviewer-*-findings.json .claude/pipeline/tester-*-findings.json
```
`checker-<label>-findings.json` carries `checks[]` only (no `issues[]`). `reviewer-<label>-findings.json`
carries `issues[]` at `file:line` plus a `checks[]` entry for the review pass.
`tester-<label>-findings.json` carries the per-suite `checks` table plus a `failures` list, each
`{ test, classification, evidence, recommendation }`.

**5 — Branch on result. The two signals are handled differently:**

*Checker / reviewer findings (lint / typecheck / diff review)* — translate directly into an
ordinary writer dispatch:
- `status: PASS` + `review: APPROVED` → that side is clear
- `FAIL` or open `issues[]` → read the findings file(s) and dispatch a writer with its single
  input contract:
  - `## Context` — the findings from `checker-<label>-findings.json` / `reviewer-<label>-findings.json`
  - `## Task` — the required fix, lint and typecheck failures addressed before diff-review issues
  - `## Files to modify` — the affected files

  Precede this dispatch with `write_plan_event(writer_dispatched{task, attempt, reason: "fix",
  files})` as in step 2.

*Tester diagnoses (test failures)* — **do NOT auto-fix.** Tester is readonly and classifies
each failure as REGRESSION / STALE_TEST / FLAKY / UNCLEAR. Because REGRESSION (fix the code)
and STALE_TEST (update the test) have opposite fixes, the orchestrator **presents the
diagnoses to the user and asks them to decide** what to do. Record
`write_plan_event(PlanEscalation(kind="escalation", topic="tester_diagnosis",
seq=next_seq["escalation"], detail=...), plan)` at this point. Only after the user decides do
you dispatch a writer — with the decision folded into its `## Task`, and `reason: "fix"`
recorded as in step 2 — to act on it. Never guess which side a failure falls on, and never
dispatch a test-authoring or test-fixing writer without a user decision.

---

## Commit Recipe

For a plan-backed run with `auto_commit: "confirmed"` (see `## Run Start`, above): once
checker/reviewer approve a task (step 5, above), the orchestrator —
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
  excludes as every not-yet-ready task, in the epoch's `excluded_tasks` — so nothing would
  catch foreign dirt swept in on those paths).
  Instead: `read_plan_events(plan, kind="writer_returned", task=N)`, take the last line for
  that attempt, and commit from its `in_scope` list. If that list is empty too (the prior
  edits are still in the working tree — only the report was lost, and there is no
  `writer_returned` for this attempt), do not commit from it either. Redispatch the writer
  instead of escalating immediately: `write_plan_event(WriterDispatched(kind=
  "writer_dispatched", task=N, attempt=<last_attempt + 1>, reason="report_lost",
  files=[...]), plan)`, have it re-report the same (already-acceptable) work, and commit from
  the new attempt's `writer_returned.in_scope`. Only if that redispatch also fails to produce
  a usable report does the orchestrator ask the user how to proceed, recording
  `write_plan_event(PlanEscalation(kind="escalation", topic="writer_report_lost",
  seq=next_seq["escalation"], detail=...), plan)`.
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

**WIP guard:** the current epoch's `epoch_start.wip` (re-captured every epoch, excluding every
not-yet-ready task's own file set — the epoch's `excluded_tasks`) is checked against each task's file set before that task's
commit. If any path was already dirty at the snapshot moment, surface it to the user before
committing rather than silently including their pre-existing uncommitted work, and record
`write_plan_event(PlanEscalation(kind="escalation", topic="wip_dirty", seq=next_seq["escalation"],
detail=...), plan)`. If the current
epoch has no `epoch_start` event (Run Start never fired because no writer was dispatched that
epoch — e.g. a re-verify-only epoch after a compaction): skip the WIP guard for this commit and
surface one line to the user stating it was skipped, never commit silently as if a stale
snapshot still applied.

**Record every outcome via `write_plan_event`, on every write, not only the degraded path
below** — never a hand-rolled `Read`/`Write` append:
- Commit succeeds → `TaskComplete(kind="task_complete", task=N, attempt=<n>, status="complete"
  | "complete-with-parked", sha=<sha>, files=<paths>, no_sha_reason=null)`.
- Commit fails (Bash denied or unavailable for this commit, distinct from `auto_commit:
  "declined"`, which stops per-task commits for the whole run before any commit is attempted)
  → `CommitFailed(kind="commit_failed", task=N, attempt=<n>, seq=next_seq["commit_failed"],
  reason=<why>, files=<paths>)`, retried on a later turn with a fresh `seq`. Surface this to
  the user immediately.

**Failure path:**
- Task already committed, needs undoing → `git revert <sha>` (a new commit, never a history
  rewrite) → `write_plan_event(TaskReverted(kind="task_reverted", task=N, attempt=<n>,
  sha=<revert-sha>, reverts=<original-sha>), plan)`.
- Task not yet committed → discard the writer's edits; no event is written.

**`task_amended`:** write `write_plan_event(TaskAmended(kind="task_amended", task=N,
seq=next_seq["task_amended"], files=<full new file set for the task, not just the addition>,
deliverable=<new deliverable text, if it changed>, why=...), plan)` for any mid-run amendment
to a task's plan — not only `branch_fix` waves — whenever a task's file set or deliverable
changes after it was originally planned. `files`/`deliverable` are only the fields that
changed; omit whichever did not.

**`branch_fix` waves** (writer dispatches made to resolve Final Full-Branch Review findings,
below): one writer dispatch, one return, and one commit per task. A file shared by more than
one task's fix is assigned to exactly one task for that wave; any file the fix touches that
belongs to no task's file set needs a `task_amended` event (as above) recording the full new
file set before it can be committed under a task.

**`task_dropped`:** write `write_plan_event(TaskDropped(kind="task_dropped", task=N,
why=...), plan)` when the user cuts a task from the plan mid-run. A dropped task is excluded
from `ready_for_final_review` and from the Final Full-Branch Review's `<files>` union — see
the precondition in `## Final Full-Branch Review` below.

**`plan_abandoned`:** write `write_plan_event(PlanAbandoned(kind="plan_abandoned", why=...,
superseded_by=<new plan stem, if the user is replacing this plan with another>), plan)` when
the user abandons a plan outright or replaces it with a new one, instead of letting it run to
`plan_complete`. See `orchestrator-plan/SKILL.md` Step 6 for the matching
`plan_archived.supersedes` write on the new plan.

---

## Final Full-Branch Review

**A declined run (`auto_commit: "declined"`) skips this review entirely** — once
`get_plan_state(plan).ready_for_final_review` is true, write `write_plan_event(PlanComplete(
kind="plan_complete", status="clean"), plan)` and stop; there is no final-review pass to park
findings from, so `status` is always `"clean"` for a declined run (`"parked"` means this
review parked a finding, which never happens when the review itself is skipped). This is the
only place a declined run closes. Everything below applies to a `"confirmed"` run only.

A step after the last task's commit (and, for L2/L3, after the existing integration pass in
`dispatch-levels.md`) — applies to multi-task L1 work too, which is why the pointer to this
section lives in `orchestrator/SKILL.md` rather than the whole mechanism living in
`dispatch-levels.md` (scoped to L2/L3 only, an L1 orchestrator never opens it). Per-task
review (the checker/reviewer/tester dispatch above) always runs *before* that task's commit,
so it always sees uncommitted working-tree content — nothing about per-task review changes.

**Precondition: `PlanState.ready_for_final_review`.** This is true once every non-dropped
file-authoring task has `TaskState.ready`. If any file-authoring task's `TaskState.ready` is
false, that task is not actually done — this review does not run; surface every such task to
the user instead, including one still showing `status: "complete"` whose later `branch_fix`/
redo attempt is open (`status` reflects only the last terminal event; `ready` is the real
signal). A
verification-only task (`files: null`) never participates in this precondition or in `<files>`
below.

This review is **mandatory for confirmed runs, and synchronous**: checker, reviewer, and tester are dispatched
together every round, all three carrying the same `branch_round` — `PlanState.
current_branch_round + 1` for a fresh round, or `current_branch_round` itself while the round
is still incomplete (see below) — and each its own `seq` from
`next_seq["branch_check"|"branch_review"|"branch_test"]`. Dispatch a
fresh `reviewer` scoped to the whole branch, diffing against `PlanState.base_sha` — not `git
merge-base <base-branch> HEAD`, which is undefined when working directly on `main` or when
there is no clear base branch. `<files>` is the union of every file-authoring task's file set —
`TaskState.files`, the task's current planned set as derived from the full event log (not just
its latest `task_complete.files`, which after a `branch_fix` wave is only that one attempt's
committed set and would silently drop files committed by an earlier attempt).

**Recovery is state-triggered, not phase-triggered:** while `PlanState.branch_round_complete ==
false` (fewer than all three of checker/reviewer/tester have reported for
`current_branch_round`), the orchestrator's next action for this plan is to dispatch *only the
missing kind(s)*, at that same `current_branch_round`, in any epoch, regardless of whether Run
Start fires this turn — never the full triad again, and never a new round. This covers both an
interruption and a verifier that failed at the tool level without writing an event. **While
`branch_round_complete == false`, no `writer_dispatched` with `reason: "branch_fix"` may be
issued** — the fix wave waits for a complete round.

Once the round is complete and every finding is adjudicated with nothing outstanding, write
`write_plan_event(PlanComplete(kind="plan_complete", status=<"clean" | "parked">), plan)`. A
final-review finding is adjudicated one of two ways: fixed via a `branch_fix` wave, or parked
with a branch-level `write_plan_event(Ruling(kind="ruling", task=None, seq=next_seq["ruling"],
text=<one-line reason>), plan)` — the same `ruling` event as a task-scoped park, with `task`
written explicitly as `None` (the field has no default; only `PlanEscalation` may omit `task`).
`status` is `"parked"` if this review parked any finding this way, else `"clean"`.
This pass is additional to, not a replacement for, per-track verification already described in
`dispatch-levels.md` and above.

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
independently, read from `TaskState.round_count`. Under L2/L3, each parallel track's per-task
counter is independent; there is no shared cross-track counter. `round_count` counts only
attempts with a non-forced `verify_round` whose `writer_dispatched.reason != "branch_fix"` — a
`branch_fix` attempt's own per-task verification does not count against this cap, because the
Final Full-Branch Review's own round structure already governs it. It also counts only
attempts strictly after the highest-attempt `task_reverted` for that task: the cap resets after
a revert. This is derived from the event log on every read, including after a compaction, so
there is no silent-reset risk — `get_plan_state` always recomputes it from the full history.

**Every writer dispatch for a task — the task's first, a fix, a forced fix, a
redo, or a report-lost redispatch — is recorded the moment it is dispatched** via
`writer_dispatched` (step 2 of `## Steps`,
above), with `reason` distinguishing the kind of dispatch. This is what makes `## Run Start`,
step 3's dispatched-but-not-completed exclusion (above) actually work in its stated common case
(a compaction landing between a writer returning and its first verify dispatch): `last_attempt`
is set from the moment `writer_dispatched` lands, and the task stays excluded (`last_attempt >
0 and not ready`) until a `task_complete` with no later attempt makes it ready — a
`commit_failed`/`task_reverted` leaves it excluded — a wider window than `TaskState.
in_flight`, which clears as soon as `writer_returned` lands.

At the cap, every open finding from checker/reviewer must be explicitly adjudicated —
never silently dropped:
- **Parked** — `write_plan_event(Ruling(kind="ruling", task=N, seq=next_seq["ruling"],
  text=<one-line reason it is not blocking, e.g. cosmetic, out of scope, pre-existing>), plan)`.
  The task is accepted with `status: "complete-with-parked"` on its `task_complete` event.
- **Forced fix** — if the finding is load-bearing (breaks a stated acceptance criterion,
  introduces a correctness bug), exactly **one** more writer dispatch is made specifically
  to fix it (`writer_dispatched` with `reason: "forced_fix"`), followed by exactly **one**
  re-verify pass — neither of which counts against the round cap (`round_count` excludes a
  forced-fix attempt's `verify_round`), and neither of which can itself trigger another
  forced-fix cycle. `TaskState.forced_fix_used` is derived from the event log, so this is
  enforced across a compaction, not just in-session. Before authorizing a forced fix, check
  `forced_fix_used`; if true, a second forced fix is never authorized — the still-open finding
  escalates to the user instead, exactly as an unresolved load-bearing finding does after the
  one permitted forced fix (below). `forced_fix_used` resets after a revert, the same
  as `round_count`. Whatever the re-verify pass finds after that single fix is adjudicated
  immediately, not re-looped: still-open, non-load-bearing findings park with a ruling as
  above; a still-open load-bearing finding after this one forced fix escalates to the user
  rather than triggering a second forced-fix round — the cap's whole purpose is defeated if
  "forced fix" can itself become an unbounded loop. Record
  `write_plan_event(PlanEscalation(kind="escalation", topic="forced_fix_exhausted",
  seq=next_seq["escalation"], detail=...), plan)` at that escalation.

**Escalations:** the task-scoped `writer_blocked` escalation is never written by the
orchestrator — the server writes it itself, automatically, when a writer's `write_report`
carries `context_request`. The orchestrator only writes the plan-level form:
`write_plan_event(PlanEscalation(kind="escalation", topic=<one of the six plan-level topics>,
seq=next_seq["escalation"], detail=<why>), plan)`, with `task` omitted or `null`.

**Concurrent lens-split results for one attempt are combined, not overwritten:** when a single
attempt's review is split across parallel lenses (see `dispatch-levels.md`), their
`verify_round` events for that `(task, attempt, source)` are combined as FAIL if any lens
reports FAIL — "last in file order wins" applies only to a *sequential re-run* of the same
check (e.g. a FLAKY tester re-run, or one filling a branch-round gap), which takes a fresh
`next_seq[kind]` and is resolved last-in-file-order; reusing a `seq` is only an idempotent
retry of an identical call (e.g. a timeout retry) and never produces a second line — it is
deduped, never treated as a re-run's result. Concurrent lens-split results for the same
attempt are a distinct case from either: to land distinctly rather than dedupe as a repeat of
the same call, each concurrent lens must be given its own `seq` (`next_seq["verify_round"]`,
`next_seq["verify_round"]+1`, ...) — never the same `seq` reused across lenses.

**Exception — tester findings are never force-fixed at the cap.** Core Invariant 3 already
governs tester diagnoses: REGRESSION and STALE_TEST have opposite fixes, so a tester finding
that survives to the round cap escalates to the user for a decision, exactly as it would at
round 1 — the cap does not authorize skipping that decision.
