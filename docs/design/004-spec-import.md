# Design 004 — Spec Import

**Status:** proposed — awaiting review, no code yet
**Roadmap item:** 2.1 (Phase 2, design-first)

## The problem

Every feature so far assumes the mapping spec is already in MapCheck's
Excel template. Nobody will retype a 300-row partner spec into it — so for
real adoption, MapCheck has to **read the mapping documents teams already
have**: partner Excel workbooks and CSVs with wildly varying column
layouts, prose conditions, and inconsistent rule expression.

`mapcheck import-spec` turns one of those into a native MapCheck workbook,
auto-classifying what it confidently can, and **flagging — never silently
guessing** — what it can't, so the human finishes a short worklist instead
of typing the whole thing.

This is the single biggest adoption lever in Phase 2. It builds only on
the existing spec template/loader (`spec/template.py`, `spec/parser.py`)
and changes nothing in the engine.

## Decision 1: a three-stage pipeline

```
  arbitrary tabular file            column mapping              native workbook
  (xlsx / csv, any layout)  ──►  their header → our column  ──►  Mapping/CodeLists/Meta
        [reader]                    [mapper]                       [classifier + writer]
```

* **Reader** — load any `.xlsx` (openpyxl, already a dependency) or `.csv`
  into a uniform list of `{header: value}` row dicts, with the header row
  auto-located (first row whose cells are mostly non-empty short strings).
* **Mapper** — resolve each MapCheck column to one of *their* columns
  (Decision 2).
* **Classifier + writer** — infer each row's Rule Type (Decision 3), emit
  the native template, and mark rows that need human review (Decision 4).

Each stage is independently testable; the messy synthetic partner
workbooks are the fixtures.

## Decision 2: column mapping — auto-detect, then override

MapCheck's 14 Mapping columns and 4 CodeLists columns are the fixed
targets. Their headers rarely match ours, so a **synonym table** drives
auto-detection:

```
Source Field  ← "x12 element", "element", "segment/element", "source"
Target Field  ← "field", "target", "destination", "erp field", "idoc field"
Rule Type     ← "type", "rule", "mapping type"
Condition ...  ← "condition", "logic", "rule/logic", "notes/logic"
Default Value ← "default", "constant", "hardcode", "literal"
Code List Ref ← "code list", "lookup", "translation", "xref"
Data Type     ← "data type", "type", "format"
...
```

Matching is normalized (lowercased, punctuation-stripped, fuzzy on close
variants). The importer prints the proposed mapping and its confidence;
the user confirms or overrides:

* **CLI:** `--map "Source Field=B, Target Field=E, Rule Type=F"` (accepts
  their header *name* or a column *letter*), or `--map-file cols.yaml`.
* **Streamlit:** a per-column dropdown of their headers (Decision 6 / A).

An unmapped required target (no Target Field found) is a hard error — the
importer won't invent a mapping it can't justify.

## Decision 3: rule-type classification — evidence, not guessing

When the source has no explicit, recognizable Rule Type, infer it from the
**evidence in the mapped cells**, in priority order:

| Evidence | Inferred type |
|---|---|
| a Code List Ref / lookup cell is populated | `CODE_LIST` |
| a Default/Constant cell is populated **and** no Source Field | `CONSTANT` |
| a Condition cell is populated | `CONDITIONAL` |
| a Source Field is present, nothing else | `DIRECT` |
| Source Field names a bare loop + target is a count | `LOOP_COUNT` |
| none of the above, or conflicting evidence | **NEEDS REVIEW** |

An explicit Rule Type column whose value maps cleanly to one of our five
(`direct`, `constant`, `xref`→`CODE_LIST`, `conditional`, ...) wins over
inference. Every classification carries a **reason string** ("inferred
CODE_LIST: 'Lookup' column populated with 'UOM'") written to Notes, so the
human can audit it.

## Decision 4: best-effort output — a flagged draft, not dropped rows

The importer produces a **complete draft workbook** — every source row is
present — with two review affordances:

* Rows classified **NEEDS REVIEW** get their Rule Type left blank, a
  yellow fill, and a Notes reason. The workbook is a *draft*: it won't
  `load_spec` until those rows are resolved (the loader already requires
  Rule Type), which is the honest state — you can't validate against an
  incomplete spec.
* A **worklist** is printed (and written next to the output as
  `<name>.worklist.txt`): every NEEDS REVIEW row with its number, the raw
  source cells, and why it couldn't be classified.

Rejected: emitting only the confidently-classified rows as a loadable
spec. It's silently lossy — the dropped rows are exactly the ones a
reviewer must see — and it hides how much of the map is unvalidated.

**Open question B:** is "draft workbook + printed/written worklist" the
right deliverable, or do you also want a machine-readable worklist
(JSON/CSV) for tooling this PR? I recommend text worklist now, JSON as a
fast follow if a use emerges.

## Decision 5: conditions — translate the simple, flag the rest

Partner conditions are prose ("map only when qualifier ST", "if BEG02 =
DS"). The importer:

* always copies the raw text into **Condition (Text)** (the human column),
* attempts **Condition (Coded)** only for patterns it can parse
  unambiguously into the existing grammar — `FIELD op 'VALUE'`
  (`N101 = ST`, `N101=ST`, "when N101 is ST"), `EXISTS(field)`, and simple
  `AND` chains,
* leaves Coded blank and marks the row NEEDS REVIEW when the prose isn't
  mechanically translatable.

This reuses `spec/conditions.py` as the validator: a derived coded string
is only accepted if `parse_condition` accepts it. No new condition
grammar, and no fuzzy natural-language guessing that could invert a rule's
meaning.

## Decision 6: round-trip guarantee

Import → native workbook → `load_spec` → `export`  must be **stable**: a
fully-classified imported spec re-exports to a byte-equivalent-in-content
workbook (same rules, code lists, meta). This is the correctness gate — if
the importer can't produce something the loader round-trips, it produced
garbage. Tested on a clean synthetic partner workbook (one with no NEEDS
REVIEW rows).

## Decision 7: scope boundaries

* **PDF extraction** — out (low reliability), per roadmap.
* **Map-vendor proprietary exports** (Gentran, Sterling, ...) — out until
  we have public samples; the tabular importer covers the Excel/CSV
  exports those tools already produce.
* **CodeLists import** — in: a lookup sheet/section maps to the CodeLists
  sheet by the same column-mapping mechanism. A spec that references a
  code list the import didn't find flags NEEDS REVIEW.
* **No engine/spec-grammar changes** — output is the existing template;
  the loader and validator are untouched.

## Reference fixtures

Three deliberately-messy **synthetic** partner workbooks (no real company
data), exercising the classifier and mapper:

1. *tidy-but-renamed* — clean rows, headers named differently
   ("X12 Element", "ERP Field", "Logic"); should auto-classify ~100%.
2. *mixed-evidence* — no Rule Type column; types must be inferred from
   Default/Lookup/Condition cells; a few genuinely ambiguous rows →
   NEEDS REVIEW.
3. *prose-conditions* — conditions in English, merged header cells, a
   stray banner row above the header; exercises header auto-location and
   condition translation.

**DoD:** across the three, ≥80% of rows auto-classified, the remainder
flagged with reasons (never silently guessed), and the clean workbook
round-trips.

## Test plan

1. Reader: header auto-location, xlsx + csv, blank/banner rows skipped.
2. Mapper: synonym auto-detect, `--map` override (name and letter),
   unmapped-required-column error.
3. Classifier: each evidence rule, explicit-type-wins, NEEDS REVIEW on
   conflict, reason strings.
4. Conditions: simple patterns derived and accepted by `parse_condition`;
   prose left to human + flagged.
5. Round-trip: clean workbook import → load → export stable.
6. Scenario: the three fixtures hit the ≥80% DoD; worklist lists the rest.
7. Full existing suite green — import is purely additive.

## Open questions for review

1. **Streamlit column-mapping UI (Decision 2 / 6):** CLI `--map` +
   auto-detect this PR, interactive Streamlit picker as a fast follow —
   agree? (Mirrors how `--output-def` shipped in 1.3.)
2. **Worklist format (Decision 4 / B):** text worklist this PR, JSON as a
   fast follow — or do you want JSON now?
3. **Ambiguity bar:** how aggressive should inference be? I lean
   *conservative* — flag anything with conflicting or thin evidence — since
   a wrong auto-classification is worse than a flagged one (it silently
   validates the wrong thing). Confirm you want conservative.
4. **CodeLists import (Decision 7):** import lookup tables in this PR (I
   recommend yes — a spec without its code lists can't validate
   CODE_LIST rows), or defer and flag all CODE_LIST rows for manual code
   entry?
