# Plan Format — Reference

The plan is the design. By the time it is approved, every decision the implementation
could otherwise resolve on its own has already been made here: what will exist afterwards,
what breaks, and what each changed interface looks like. What is left is writing bodies
against a settled specification.

The plan describes **the code**, never the work of producing it. It names no agents,
assigns no dispatch, and prescribes no parallelism — those belong to the orchestrator
routing guide, which reads the plan and decides. A section that starts describing who does
something has drifted; rewrite it as a property the code must have.

Read this file before writing the plan document in Step 4.

---

## Sections

Every plan carries all nine sections in this order. A section with genuinely nothing to
report says so explicitly — an omitted section reads as "not considered".

### 1. Header

```markdown
# [Feature Name] — Orchestrator Plan

**Goal:** [one sentence]
**Date:** YYYY-MM-DD
**In scope:** [what this plan will change]
**Out of scope:** [adjacent things it deliberately will not touch]
```

`Out of scope` is not filler. It is what rules out "while I was in here" edits, and what
tells a reviewer that an untouched neighbour was a decision, not an oversight.

### 2. Explanation

Prose, for a human deciding whether to approve. What the research turned up, what the
approach is, why it is structured this way, which constraints forced which choices, and
what was traded away. Name the alternative you rejected and why — an approval is worth
more when the reviewer can see what they are not getting.

### 3. Conventions in Force

The rules the code must follow, **discovered from the files being touched** — not a
generic checklist. Every rule cites a real precedent read during research.

```markdown
## Conventions in Force

| Rule | Precedent |
|---|---|
| `con: sqlite3.Connection \| None = None` is the last param | `tasks.py:31` |
| Commit inside the function; close only a connection you opened | `bulk.py:12` |
| HTTP 404 is raised in `api.py`, never in the data module | `api.py:64` |
```

Rules for this table:

- One row per rule the change actually has to obey. Not every convention in the repo —
  the ones that constrain *this* code.
- The precedent must be a file and line you read. No precedent means it is not a
  convention in force; it is a preference, and it does not belong here.
- Cover at least: naming, signature shape, error and exception placement, typing,
  import style, and test structure — where each is relevant to the change.

If the change genuinely needs something with no precedent, it goes in a separate block:

```markdown
### New convention introduced

- [what is new] — **Why:** [reason]. Nearest existing pattern: `file.py:NN`.
```

This block is load-bearing. A new pattern may only enter the codebase with a stated
reason, and this is where the reason is stated. An empty block means the change introduces
nothing new — every line of it follows an existing precedent.

### 4. Artifacts

Everything that will exist after the change, or exist differently. Source files are the
smallest part of this — the point of the section is the artifacts that are easy to forget
until they break something.

```markdown
## Artifacts

| Kind | Artifact | Action | Notes |
|---|---|---|---|
| source | `tasks.py` | modify | +1 function |
| source | `db.py` | modify | schema DDL |
| test | `tests/test_archive.py` | create | mirrors `test_bulk.py` |
| schema | `tasks.archived` column | create | `INTEGER NOT NULL DEFAULT 0` |
| dependency | — | none | no new packages |
| config | — | none | |
| generated | `tasks.db` | mutate | existing rows get the default |
| docs | `CLAUDE.md` module table | modify | new function listed |
| version | `orchestrator-skills` 1.15.0 → 1.16.0 | modify | both manifests |
```

Walk every kind and answer it — `none` is a valid answer, a missing row is not:

**source · test · dependency · schema or migration · config file · environment variable ·
generated or build output · on-disk data · docs · plugin or package version · CI
workflow · transient directory**

Two rules make this section useful rather than decorative:

- Paths here are exact and must match the paths in the task file sets, section 7.
- A dependency row names the package *and* the version constraint, because adding one is
  a lock-file change and a supply-chain decision, not a detail.

### 5. Side Effects & Blast Radius

What the change does beyond the files it edits. This is the section that requires
research rather than reasoning — call sites are **enumerated from `LSP` find-references or
`rg`, never guessed**.

```markdown
## Side Effects & Blast Radius

| Effect | Where | Impact | Handled by |
|---|---|---|---|
| `complete_task` signature gains a param | `api.py:88`, `main.py:41` | both call sites updated | task 2 |
| Existing rows lack `archived` | live `tasks.db` | DDL default backfills | task 1 |
| `test_row_shape` asserts column count | `tests/test_tasks.py:120` (also `:121`, `:122` — same function) | 1 failing test — STALE_TEST, update in task 4 | task 4 |
```

Answer each category explicitly:

- **Call sites** — every caller of every signature that changes, listed by `file:line`.
- **Behavior visible to existing tests** — which current tests will change result, and
  whether that is a regression or an expected update. Committing to that split in advance
  is what makes a later test run readable: a failure the plan predicted is an update, and
  one it did not is a defect.
  **Count failing test *functions*, not failing assertions.** A test aborts at its first
  failing `assert`, so three broken assertions inside one function are one reported
  failure. Name the function, and list its assertion lines beneath it. Predicting in the
  wrong unit turns a correct prediction into a phantom miss — the plan says five, the test
  run reports three, and two predictions look unfulfilled when nothing is actually wrong.
- **Persisted state** — schema, migrations, data already on disk, and whether it survives.
- **Runtime effects** — filesystem writes, network calls, subprocesses, background work.
- **Backward compatibility** — public API, CLI flags, config keys, serialized formats.
- **Guards and hooks** — anything in `.claude/hooks/` or CI that will fire on these paths.
- **Concurrency** — shared connections, locking, transaction boundaries.

### 6. Change Contracts

Per file, the exact interface after the change. This is the specification the code is
built against, so it must be complete enough to implement from without re-deriving
anything — assume whoever implements it has this section and the precedents it cites, and
nothing else.

```markdown
## Change Contracts

### `tasks.py` — modify

**Add** `def archive_task(task_id: int, con: sqlite3.Connection | None = None) -> bool`
- Returns `True` when a row was updated, `False` when `task_id` is absent.
- Raises nothing — the caller decides the HTTP status.
- Mirrors `complete_task` (`tasks.py:58`) in connection handling and commit placement.

**Change** `load_tasks` — exclude archived rows by default; add
`include_archived: bool = False` as the last param before `con`.

### `api.py` — modify

**Add** route `PATCH /tasks/{id}/archive` → 200 on success, 404 when `archive_task`
returns `False`. Mirrors the `/complete` route (`api.py:80`).
```

What belongs here: signatures with full type annotations, return values, error and
exception behavior, the "mirrors X" pointer that anchors it to an existing precedent, and
any constant or literal whose value is a decision.

What does not: function bodies, algorithm walkthroughs, or anything derivable from the
contract plus its precedent. Pinning a body makes the plan rot the moment the file moves,
and it duplicates work that is better done with the file open.

**One exception** — inline literal code when the contract cannot express the requirement:
an exact SQL DDL statement, a regex, a precise error string other code matches on, or a
data structure whose shape *is* the specification.

### 7. Tasks

Deliverables, named after *what changes* — never after who changes it, and never after the
agent that would do it.

```markdown
## Tasks

1. `archive_task` + schema column — files: `tasks.py`, `db.py` — contracts: §6 `tasks.py`
2. archive route + CLI flag — files: `api.py`, `main.py` — contracts: §6 `api.py`
3. lint, typecheck, and diff review clean across the changed files
4. archive tests + update `test_row_shape` — files: `tests/test_archive.py`, `tests/test_tasks.py`
```

Every task carries its **file set** — the files that deliverable touches. Two tasks naming
the same file are two changes to one file: a fact about the change, and one that belongs on
the page rather than being discovered later.

State any **dependency between tasks** explicitly, because file sets cannot express it:
task B may call or import what task A creates while sharing no file with it. Nothing in the
file lists reveals that ordering — only the contracts do, and only if you write it down.

### 8. Acceptance & Verification

What must be true of the code when it is done, beyond a green suite. State it as
falsifiable claims about behavior — a change that predicted its own test churn in advance
is far cheaper to check than one that did not.

```markdown
## Acceptance & Verification

- `archive_task` returns `False` for an unknown id (not an exception).
- Archived tasks are absent from `GET /tasks` and present with `?include_archived=1`.
- Expected test churn: `test_row_shape` — STALE_TEST, updated in task 4. Any *other*
  failure in `test_tasks.py` is a regression.
```

### 9. Risks & Rollback

Only real ones. What could go wrong, how you would notice, and how to undo it. A schema
change with no rollback path is a risk that has to be stated, not one to leave implicit.

---

## Completeness Gate

Do not call `ExitPlanMode` until every line is true. Each one maps to a failure this
format exists to prevent.

- [ ] Every **authored** path in Artifacts (§4) — anything a task creates or edits —
      appears in exactly one task's file set (§7), and every path in a file set appears in
      Artifacts. Artifacts no task authors are exempt: a directory an agent writes at
      runtime, a generated database, a build output. Mark each one `not authored by this
      plan` in its Notes column, so the exemption is a decision on the page rather than a
      silent gap.
- [ ] Every changed signature in Change Contracts (§6) has its call sites enumerated in
      Blast Radius (§5), sourced from `LSP`/`rg` output — not recalled.
- [ ] Every rule in Conventions in Force (§3) cites a `file:line` that was actually read.
- [ ] Every artifact kind in §4 is answered, `none` included.
- [ ] Every side-effect category in §5 is answered, `none` included.
- [ ] Anything not derivable from a contract plus its precedent is pinned as a literal.
- [ ] Nothing outside `In scope` is modified by any task.

If a checkbox fails because research is missing, go back and research it. Filling it from
memory is how a plan comes out confident and wrong.
