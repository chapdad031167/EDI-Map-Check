# Design 006 — Regression Mode

**Status:** approved — implemented in this PR
**Roadmap item:** 2.3 (Phase 2, design-first) — closes Phase 2

**Resolved (all four recommendations adopted):** (A) auto-key by the
`spec|source|output|partner` paths with a `--label` override; (B) finding
identity is `(document_key, row_id or "", target or source_ref)` — `category`
stays out of the key and a category change reads as CHANGED; (C) the nonzero
gate trips on any NEW **FAIL**, any PASS/WARNING→FAIL **CHANGED**, or a
**DOC REMOVED** — new warnings and improvements are informational; (D) the
first `regress` with no baseline records the run and prints how to bless it
(exit 0) rather than auto-blessing.

## The problem

The workflow that actually keeps a production map healthy isn't "validate
once" — it's *"I changed the map (or upgraded the translator); what
broke?"* Today every run is standalone: you eyeball two full reports and
diff them in your head. That doesn't scale to a 300-row spec across 40
partners.

**Regression mode** blesses a known-good run as a **golden baseline**, then
`regress` re-runs the same inputs and reports **only the delta** — new
failures, fixed failures, changed values, added/removed documents — and
exits nonzero when something regressed. It's map change control: run it in
a pipeline before anything ships.

This closes Phase 2. It builds only on the existing history DB
(`report/history.py`, already storing runs + findings, and per-document
rows from 1.2) and changes nothing in the engine.

## Decision 1: baselines live in the history DB, keyed by the inputs

A new **`baselines`** table (additive, created with the same
`CREATE TABLE IF NOT EXISTS` + column-guard migration as 1.2) maps a
**baseline key** to the blessed `run_id`:

```
baselines(id, baseline_key TEXT UNIQUE, run_id INTEGER, label TEXT, blessed_at TEXT)
```

The **baseline key** is what makes two runs "the same validation to
compare": the normalized `spec | source | output | partner` the run used.
Re-running those same paths (with changed *content* — the point of a
regression) recomputes the same key and finds its baseline. A `--label`
overrides the key for portability when paths differ between environments.
One blessed run per key; blessing again replaces it.

**Open question A:** auto-key by the `(spec, source, output, partner)`
paths (recommended, with `--label` override) — or require an explicit
`--label` always? Auto-key matches the "guard this exact validation" reflex
and needs no bookkeeping; confirm.

## Decision 2: finding identity for the diff

Two runs are diffed by matching findings on a **stable identity**, not by
line order:

```
finding_key = (document_key, row_id or "", target or source_ref)
```

* `document_key` is empty for a single-document run, the 1.2 pairing key
  for an interchange — so per-document regressions are attributed.
* `row_id` ties rule findings; file-level/unmapped findings (no row_id)
  fall back to `source_ref`.
* `expected` / `actual` / `status` / `category` are the *payload* compared
  within a matched pair — not part of the key.

This is deliberately coarse: one check at one location has one identity, and
its outcome is what changed. Message text is never part of the key (wording
tweaks must not read as regressions).

**Open question B:** is `(document_key, row_id, target/source_ref)` the
right identity, or do you want `category` in the key too (so a location
changing *why* it fails reads as remove+add rather than "changed")? I
recommend keeping category out of the key and reporting a category change
as a CHANGED finding.

## Decision 3: the delta classes

| Class | Condition | Regression? |
|---|---|---|
| **NEW** | key present now, absent in baseline, and now FAIL/WARNING | yes (FAIL) |
| **RESOLVED** | key present in baseline (FAIL/WARNING), absent or PASS now | no (good) |
| **CHANGED** | key in both; status, expected, actual, or category differs | yes if it became FAIL |
| **DOC ADDED** | a document key present now, not in the baseline | reported |
| **DOC REMOVED** | a document key in the baseline, gone now | yes |

`regress` prints these grouped, then a one-line verdict. A PASS→PASS or
identical finding is silent — the report is only the change.

**Open question C:** what trips a **nonzero exit** (the CI gate)? I
recommend: any NEW **FAIL**, any PASS/WARNING→FAIL **CHANGED**, or a
**DOC REMOVED** → exit 1; new warnings and resolved/improved findings are
informational (exit 0). Confirm the gate, or widen it to warnings.

## Decision 4: commands

* **`mapcheck bless <run_id> [--label NAME] [--db …]`** — mark an existing
  recorded run (from `mapcheck history`) as the baseline for its key.
* **`mapcheck regress --spec … --source … --output … [--partner …] [--label …]`**
  — validate now, find the matching baseline, print the delta, exit per the
  gate. With no baseline yet, it records the run and prints
  *"no baseline — bless run #N to establish one"* (exit 0), so the first run
  bootstraps.
* Regress **records its run** like `validate` does, so the history stays a
  complete audit trail and a fresh run can itself be blessed.

Interchange (1.2) baselines work the same way: the diff is per document
(keyed) plus file-level, and DOC ADDED/REMOVED fall out of comparing the
document-key sets.

## Decision 5: scope boundaries

* **No engine/spec changes** — regression is a pure history-layer feature
  over findings already recorded.
* **Baseline history/rollback** (keeping N past baselines, diffing two
  arbitrary runs) — out; one current baseline per key, re-bless to move it.
  A `--against <run_id>` ad-hoc diff is a natural fast follow.
* **Streamlit regress view** — out; a fast follow, like the other 2.x UIs.

## Reference scenario

Reuse a bundled scenario (e.g. the 850 baseline) as the golden run, then
regress a **mutated output** to exercise every delta class in one diff:

* bless the clean 850 run,
* regress against a defect output that: introduces one **NEW** failure,
  **RESOLVES** nothing / everything (both directions shown), **CHANGES** a
  finding's expected value, and — via the multi-transaction scenario — adds
  and removes a **document**.

Asserted: the delta lists exactly those classes, the verdict is a
regression, and the exit code is nonzero; a re-run against the *same* output
as the baseline yields an empty delta and exit 0.

## Test plan

1. `baselines` table + migration on a legacy DB; one baseline per key;
   re-bless replaces.
2. Diff classifier: NEW / RESOLVED / CHANGED / DOC ADDED / DOC REMOVED,
   including no-row_id findings keyed by source_ref.
3. Identity: reordered findings and message-only changes produce an empty
   delta; a value change produces CHANGED.
4. Exit gate: regression → nonzero; clean re-run → zero; bootstrap (no
   baseline) → zero with guidance.
5. Interchange: per-document attribution + DOC ADDED/REMOVED.
6. Full existing suite green — additive over history.

## Open questions for review

1. **Baseline key (Decision 1 / A):** auto-key by inputs with `--label`
   override (recommended) vs. always explicit `--label`?
2. **Finding identity (Decision 2 / B):** `(document_key, row_id,
   target/source_ref)` (recommended) — include `category` too?
3. **Exit gate (Decision 3 / C):** NEW FAIL + →FAIL CHANGED + DOC REMOVED
   trip nonzero (recommended); should new **warnings** gate too?
4. **Bootstrap behavior (Decision 4):** first `regress` with no baseline
   records + guides at exit 0 (recommended) — or should it auto-bless the
   first run instead?
