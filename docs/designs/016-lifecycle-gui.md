# Design 016: the run lifecycle in the app (GUI Tier 3)

**Status:** Draft, for review — no code until sign-off.
**Applies to:** `app.py` (a new History page, a regression strip on the
Validate page), `docker-compose.yml` (history volume), README.
**Depends on:** the existing lifecycle engine — `RunHistory` (SQLite:
runs, findings, baselines), `regression.regress`/`RegressionDelta`,
`trends.compute_trends` — all shipped and CLI-exercised. This design
adds **no engine features**; it puts the existing ones on screen.

## Context

The CLI already carries the full run lifecycle: `validate` records
history, `bless` marks a golden baseline, `regress` re-validates and
reports only the delta, `report` shows trends. The app has none of it:
the Validate page runs and forgets, and the only trace of history is a
read-only trends expander that appears if a CLI-created
`mapcheck_history.db` happens to sit in the working directory. For the
GUI-first user — the reason Tiers 1 and 2 exist — "did this partner's
file get better or worse since last month?" is unanswerable without
dropping to a terminal.

## The job, precisely

1. Recorded runs: a validation run in the app lands in the same
   history database the CLI writes, by default, visibly.
2. A **History** page: browse recent runs, open any run's findings,
   bless a run as the baseline for its inputs, see trends.
3. Regression on the Validate page: when a just-recorded run's inputs
   have a blessed baseline, show the delta (new failures, resolved,
   changed) instead of making the user eyeball two findings tables.
4. Durable by construction: the history file is a named, visible
   artifact that survives restarts — including in Docker.

## Decision 1: baselines key by label in the app, and why

The CLI keys a baseline by normalized input *paths*
(`spec|source|output[|partner]`), with `--label` as the escape hatch
for paths that differ across machines. In the app, every upload lands
in a fresh temporary directory — the same three files produce three new
paths per run, so path keys can never match across runs. Path keying is
not merely inconvenient in the app; it is structurally wrong there.

So the app always keys by **label**, derived from what is stable across
uploads: the spec's Meta `Spec Name` (falling back to the spec's file
name) plus the original source and output file names, which the upload
helpers already preserve:

```
850 reference spec | 850_baseline.edi -> po_baseline.json
```

The derived label is shown and **editable at bless time** — an analyst
who wants "Acme JuneGoLive" types it once and future runs of those
inputs match it. Matching is exact, on the label the run derives — the
edit box exists for naming, not for fuzzy matching.

CLI interop is explicit, not accidental: `mapcheck bless N --label
"<same label>"` and `mapcheck regress --label "<same label>"` hit the
same baseline row the app uses. A CLI baseline blessed *without*
`--label` stays path-keyed and the app will not match it — the README
gets one sentence saying so.

Rejected: content-hash keys (opaque to humans, and a scrubbed
re-export of the same order would silently miss its baseline) and
partner-delta-aware keys (the delta workbook's name folds into the
label derivation the same way the CLI folds it into the path key —
`| delta: partner_acme_delta.xlsx` — no special machinery).

## Decision 2: recording is on by default, one visible toggle

The Validate page records every run to the history database unless the
user flips "Don't record this run" — the exact polarity of the CLI's
`--no-history`. The caption under the toggle names the database file
and its location, so the artifact is never invisible. Bundled example
scenarios record too: the examples are how a new user learns the
lifecycle, and a history of demo runs against synthetic files is a
feature of the demo, not pollution.

## Decision 3: one new History page

Navigation gains **History** between Validate and Draft spec —
lifecycle order, left to right. The page has three sections, top to
bottom, all in the existing identity (zero new CSS — findings-table
classes, dot-plus-word status cells, verdict strip):

1. **Recent runs.** One row per recorded run: id, when (UTC), result
   as a status cell, PASS/FAIL/WARN/N-T counts, `source -> output`
   names, and a baseline marker on blessed runs. Interchange parents
   show their document count; their per-document child runs open from
   the parent.
2. **Run detail.** Selecting a run renders its verdict strip and full
   findings table from the stored findings — the same table the run
   showed live, rebuilt from the database.
3. **Bless.** On the selected run: the derived label (Decision 1),
   editable, and a "Bless as baseline" button. Blessing a run for a
   label that already has a baseline replaces it — the engine's
   existing upsert — and the page says which run held it before.
4. **Trends.** The existing trends panel (runs, pass rate, per-spec
   table, top root causes, HTML download) moves here from the Validate
   page — it is history's summary, not a run's. The Validate page
   loses the expander; one page owns the past.

Rejected: a separate Regress page. Regression is not a place you go,
it is what a validation run tells you when it has a baseline — it
belongs on the Validate page, next to the result it qualifies.

## Decision 4: the regression strip on Validate

After a recorded run, the app derives the run's label and looks up its
baseline:

- **Baseline exists:** render the delta — a verdict strip
  (`N REGRESSIONS` in fail tone, or `NO REGRESSIONS — n improved` in
  pass tone) over a table of changes: kind as a status cell
  (NEW = fail tone, RESOLVED = pass tone, CHANGED = warning tone —
  regression-flagged rows first), where, and the compact
  "was X, now Y" detail the CLI prints. Interchange deltas include
  DOC ADDED / DOC REMOVED rows.
- **No baseline:** one quiet line — "No baseline for these inputs" —
  with a "Bless this run" button and the editable label, inline. The
  first run of a new partner file becomes the baseline in one click
  without visiting the History page.

The comparison is automatic when a baseline exists; there is nothing
to configure. Blessing remains deliberate; comparing is free.

## Decision 5: durability, including Docker

The database default is `mapcheck_history.db` in the app's working
directory — the CLI's default, so app and CLI share one history when
run from the same place. `docker-compose.yml` gains a named volume
mapped over a data directory and the containerized app points its
database there, so `docker compose up` keeps history across rebuilds.
The History page footer names the database path in use. No retention
policy and no delete button in v1: history is an audit trail; pruning
is deleting a file the user owns and can see.

## Scope guard

No engine changes; no schema changes; no multi-user story (SQLite,
one writer — same as the CLI today); no baseline management beyond
bless-and-replace (no un-bless, no baseline list page — the runs table
shows blessed runs); batch/CI, JUnit, and exit-code gating stay CLI.
If a needed style does not exist in the identity system, that is a
Design 013 gap to report, not to patch inline.

## Testing

- Label derivation: spec-name fallback chain, partner delta folding,
  determinism across re-uploads of the same files (fresh temp paths,
  same label).
- Record-then-browse round trip: a validated run appears in recent
  runs; its stored findings rebuild the same table content the live
  run showed (parsed-content comparison, per the draft-spec golden
  convention).
- Bless + regress through the app-facing helpers: baseline hit on
  matching label, miss on path-style CLI keys, replacement reported.
- Delta rendering: kinds, regression-first ordering, interchange
  DOC ADDED/REMOVED, and AST-level identity checks (no emoji, no
  exclamations) as in Design 013's tests.
- Live Playwright pass: run → bless → re-run with a seeded defect →
  regression strip shows the NEW failure; History page shows both
  runs and the baseline marker.

## Open questions

1. **Trends placement:** move entirely to the History page (this
   design), or also keep the collapsed expander on Validate?
2. **Label ergonomics:** is the derived
   `spec name | source -> output` default the right shape, or would
   you rather it default to just the spec name and lean on editing?
3. **Recording examples:** record bundled example scenarios by
   default (this design), or exempt them from history?
4. **Docker data path:** a named volume managed by compose (this
   design — zero setup, survives rebuilds) vs. a bind mount to a host
   folder (visible file on the host, but host-specific setup)?
