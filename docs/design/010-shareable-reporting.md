# Design 010 — Shareable Reporting

**Status:** approved — implemented in this PR
**Roadmap item:** 3.4 (Phase 3, design-first) — the final feature; landing it
triggers the **Phase 3 exit review / project Definition of Done**.

**Resolved (all four recommendations adopted):** (A) `--export-html` on
`validate` for the per-run report + a new `mapcheck report --html` for trends;
(B) zero-dependency inline HTML/CSS with hand-drawn inline SVG, no JavaScript;
(C) PASS rows included but collapsed behind native `<details>`; (D) trends
grouped by spec file.

## The problem

The reports so far are a terminal dump and an Excel workbook — great for the
person running MapCheck, awkward to *share*. When you need to send a partner
"here's exactly what's wrong with your 850," or show a lead "our map pass-rate
over the last month," you want a **single self-contained HTML file**: open it
in any browser, mail it, attach it to a ticket — no server, no spreadsheet app,
no dependencies.

3.4 delivers two things over the data the engine and history DB already
produce:

1. a **single-run HTML report** (findings, rollup, per-document detail), and
2. a **history-trends HTML dashboard** (pass-rate over time per spec, top
   recurring root causes) — the same trends also surfaced in Streamlit.

Both are pure presentation over existing data; the engine, history schema, and
findings are untouched.

## Decision 1: command surface

* **`mapcheck validate … --export-html report.html`** — a single-run (or
  interchange) report, exactly mirroring the existing `--export-xlsx`.
* **`mapcheck report [--db …] [--html trends.html] [--limit N]`** — a new
  command that reads the history DB and writes the trends dashboard (and prints
  a short text summary when `--html` is omitted).

**Open question A:** `--export-html` on `validate` for the per-run report plus a
new `mapcheck report --html` for trends (recommended — each command keeps one
job) — or fold everything into a single unified `report` command? Batch
combined-HTML is a noted fast follow, not in this cut.

## Decision 2: rendering — zero-dependency, self-contained

The file must open anywhere with nothing fetched from the network, so:

* inline `<style>`, no external CSS, fonts, or CDN;
* **no JavaScript** — sorting is done by pre-ordering rows (FAIL → WARNING →
  PASS), and PASS detail hides behind native `<details>`/`<summary>`;
* charts are **inline SVG** drawn by hand (sparklines, bar rows) — no charting
  library, no `<canvas>`, no scripts;
* a clean light theme with strong contrast, print- and email-friendly; values
  are HTML-escaped (the report may carry real partner data).

**Open question B:** zero-dependency inline HTML/CSS + hand-drawn inline SVG,
no JS (recommended — truly portable, safe to mail) — or bundle a JS chart
library for richer interactivity (heavier, blocked by many mail/CSP readers)?

## Decision 3: the single-run report

Sections, top to bottom:

* **header** — spec name, transaction, source/output paths, run time, and a big
  overall result badge (PASS/WARNING/FAIL);
* **summary** — status counts + a root-cause rollup (category → count) as small
  SVG bars;
* **findings table** — color-coded by status, columns matching the Excel report
  (status, row, source, target, expected, actual, category, message), FAIL
  first;
* **interchanges** — a per-document section (using the 1.2 pairing key) plus the
  file-level findings, each document collapsible.

**Open question C:** include PASS rows **collapsed** behind a `<details>` toggle
(recommended — the report is complete and auditable but defaults to the
problems) — or omit PASS rows entirely (findings-only, smaller file)?

## Decision 4: the trends dashboard

Computed from the `runs` + `findings` history tables (a shared
`report/trends.py` used by both the HTML export and Streamlit, so they never
drift):

* **per-spec pass-rate** — group recent runs by spec file; for each, a small
  SVG sparkline of pass/fail over time, the latest result, and run count;
* **top recurring root causes** — aggregate `category` across recent failing
  findings into a ranked bar chart;
* a headline tile row (total runs, overall pass-rate, distinct specs).

**Open question D:** group the trends by **spec file** (recommended — "how
healthy is each map?") — or by transaction set, or by partner (`origin`, which
would need per-finding attribution rolled up to the run)?

## Decision 5: Streamlit + Definition of Done

* **Streamlit** gains a **Trends** view (the same `report/trends.py` data) and a
  **Download HTML report** button on a validation result.
* Because 3.4 is the last feature, this PR also does the **Phase 3 exit
  review / DoD**: full suite green, a README pass over the complete feature
  set, confirm every feature has a synthetic scenario, and a refreshed
  Streamlit screenshot.
* **Out of scope (fast follows):** batch combined-HTML; PDF export; per-partner
  trend attribution; a JSON metrics feed.

## Reference scenario

Reuse existing fixtures — no new engine data needed:

* export the **defective 850** run to HTML and assert the file is
  self-contained (no `http://`/`src=` external refs), carries the FAIL badge,
  the planted root causes, and a findings table with the known failing rows;
* export a **clean** run and assert the PASS badge and that PASS rows are
  present but inside `<details>`;
* export an **interchange** run and assert one section per document plus the
  file-level findings;
* seed a temp history DB with several runs of two specs and assert the trends
  HTML has a per-spec row for each and a top-root-causes chart — and that
  `report/trends.py` returns the same aggregates Streamlit renders.

## Test plan

1. HTML report: self-contained (no external URLs), escaping, badge reflects
   overall status, findings ordering (FAIL first), PASS rows collapsed.
2. Interchange report: per-document sections + file-level findings.
3. Trends aggregation (`report/trends.py`): per-spec pass-rate and top
   root-causes from a seeded DB; empty-DB edge.
4. Trends HTML: renders each spec, headline tiles, self-contained.
5. CLI: `validate --export-html`, `mapcheck report --html`, and text summary;
   missing DB is a clean usage error.
6. Full existing suite green; Streamlit imports/render smoke.

## Open questions for review

1. **Command surface (Decision 1 / A):** `--export-html` + a `report` command
   (recommended) vs one unified command?
2. **Rendering (Decision 2 / B):** zero-dep inline HTML/CSS + SVG, no JS
   (recommended) vs a bundled JS chart library?
3. **PASS rows (Decision 3 / C):** included but collapsed (recommended) vs
   omitted?
4. **Trends grouping (Decision 4 / D):** by spec file (recommended) vs by
   transaction set / partner?
