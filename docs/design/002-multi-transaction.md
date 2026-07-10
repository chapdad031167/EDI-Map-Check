# Design 002 — Multi-Transaction Interchange Validation

**Status:** proposed — awaiting review, no code yet
**Roadmap item:** 1.2 (Phase 1, design-first)

## The problem

Today a validation run is exactly one transaction against one output
document. Real production files break both halves of that assumption:

* An interchange carries **many ST/SE transactions** per GS, and multiple
  GS per ISA. `parse_transaction` already tokenizes the whole file but
  parses only the first ST/SE — the rest are noted and dropped
  (`x12/parser.py`: "only the first transaction is validated").
* The translated side is **many documents**, one per source transaction.
  The canonical model (`CanonicalOutput`) holds a single document's dict.

Making MapCheck a production tool means validating an interchange of N
transactions against a container of M output documents: pair them up, run
today's single-document validation on each pair, and add file-level
findings for anything left unpaired.

This is the second Phase-1 architecture-changer. It builds on the
side-reader seam from design 001 (per-pair validation is just today's
`validate()` called in a loop) and its keying feeds regression mode (2.3).

## Decision 1: the run model — a document set with a rollup

A new **`InterchangeResult`** wraps a list of per-document results plus
file-level findings:

```
InterchangeResult
├── documents: list[DocumentResult]      # one per matched pair
│     ├── key: str                       # the pairing key value ("PO4400021")
│     ├── result: RunResult              # today's per-document findings, unchanged
│     └── source_ref / output_ref        # ST control no. / output locator
├── file_findings: list[Finding]         # orphans, duplicate keys, envelope
└── rollup: counts + overall across everything
```

`RunResult` is untouched — it remains "everything one document produced,"
and `validate()` still returns one. `InterchangeResult.overall` is FAIL if
any document or file-level finding is FAIL, WARNING if any WARNING, else
PASS. A **single-transaction file is just an InterchangeResult with one
document** — the existing `validate_files` keeps returning a `RunResult`
for backward compatibility (every current test and caller unchanged), and
a new `validate_interchange_files` returns the richer type.

Rejected: flattening everything into one `RunResult` with a document tag
on each finding. It preserves the current type but loses the per-document
rollup that both reporting and regression mode need, and it makes "PASS on
document A, FAIL on document B" unreadable.

## Decision 2: parsing every transaction

`parse_transaction` grows a sibling **`parse_interchange`** that returns
`list[TransactionDocument]` — one per ST/SE, each built by the existing
`_StructureWalker` exactly as today. The single-transaction function stays
(it is the right tool when you know there is one), reimplemented to call
`parse_interchange` and return the first, so there is one parsing path.

Envelope and control notes: pyx12's interchange-level checks already run
over the whole file; each `TransactionDocument` keeps the shared envelope
plus its own ST/SE control note slice. Mixed transaction sets in one
interchange are allowed (an 850 and an 855 under different GS is legal) —
each document resolves its own definition from its ST01, so a file can
even pair against more than one spec (Decision 4).

## Decision 3: the output-side container

The internal side must now carry M documents. Two container conventions,
both loading through the existing adapters with no engine change:

* **JSON array** — a top-level `[ {...}, {...} ]` instead of one object.
  `load_output` already rejects non-object JSON; it grows an array branch
  that yields M `CanonicalOutput`s.
* **Multi-document flat / IDoc** — the keyed-flat and IDoc formats are
  naturally concatenative. A record/segment that re-opens the document
  (a new `EDI_DC40` control record; a configurable "document break" record
  for keyed flat) starts the next `CanonicalOutput`. The ORDERS05 flat
  layout already has EDI_DC40 as its natural delimiter.

A single-object JSON / single-document flat file stays exactly what it is
today — one document. The multi-document loaders are additive.

**Open question A** (for review): for the *first* cut, is it acceptable to
support the **JSON array** container only, and defer multi-document flat /
IDoc to a follow-on? It covers the common "ERP staging emits a JSON array"
case and keeps this PR from also touching every flat adapter. My
recommendation: yes — land the run model + JSON array, fast-follow the
concatenative formats.

## Decision 4: pairing — a spec-declared key

Pairing is by a **key value read from both sides**, declared in the spec's
Meta sheet:

```
Pairing Key (source):  BEG03           # X12 element, or Loop Context + element
Pairing Key (target):  order.po_number # canonical path
```

For each source transaction the engine reads the source key; for each
output document it reads the target key; documents pair when the keys are
equal. This reuses the exact addressing both sides already speak — no new
grammar. Direction (design 001) still applies: outbound, the X12 side is
the output, so the two key columns simply follow the same source/target
roles the rest of the spec does.

When no Pairing Key is declared **and** both sides have exactly one
document, they pair positionally (today's behavior, so every existing
spec keeps working). A declared key is required the moment either side has
more than one document — pairing multiple documents positionally is the
kind of silent mis-pair this feature exists to catch.

**Open question B:** positional fallback for a *declared-keyless* multi-doc
file — hard error ("this interchange has 3 transactions but the spec
declares no Pairing Key"), or best-effort positional with a loud WARNING?
Recommendation: **hard error** — a keyless multi-document validation can't
be trusted, and failing loudly is the honest result.

## Decision 5: file-level findings (the new value)

The point of the feature is catching what per-document validation can't
see. New file-level findings, all with existing categories:

| Situation | Category | Status |
|---|---|---|
| source transaction, no output document with its key | `missing_output` | FAIL |
| output document, no source transaction with its key | `unexpected_output` | FAIL |
| two source transactions share a key | `count_mismatch` | FAIL |
| two output documents share a key | `count_mismatch` | FAIL |
| interchange-level control note (pyx12) | `control` | WARNING |

No new `Category` values — these are the same root causes the single-doc
engine already emits, raised to the file level. Reporting labels them with
the key and the ST control number / document locator so a finding points
at a specific transaction.

## Decision 6: reporting, history, CLI, UI

* **Terminal / Excel:** a per-document section (keyed header + today's
  table) then a file-level section and the rollup. Single-document runs
  render exactly as now.
* **History:** the `runs` table gains a nullable `interchange_id` and a
  `document_key`; one interchange writes one parent row plus a child run
  row per document, so `mapcheck history` can show either granularity.
  Existing single-doc runs get a null interchange_id — no migration of old
  rows needed (the schema is `CREATE TABLE IF NOT EXISTS` + additive
  columns via `ALTER TABLE ... ADD COLUMN` guarded by a column check).
* **CLI:** `mapcheck validate` auto-detects — if the X12 file has >1
  transaction or the output is an array, it runs the interchange path and
  prints the sectioned report; exit code is FAIL if the rollup is FAIL.
  No new subcommand; `--source`/`--output`/`--spec` are unchanged.
* **Streamlit:** the scenario picker gains a multi-transaction example;
  results render per document with an interchange summary at the top.

## Decision 7: what stays out

* **Cross-transaction-set pairing** (an 850 paired to its 855 by PO) — a
  different feature (matching two *different* specs' documents to each
  other), explicitly deferred.
* **Streaming very large interchanges** — read-whole-file is fine at this
  scale; a 10,000-transaction file is a later concern.
* **Multi-document flat / IDoc containers** — deferred per open question A
  if you agree; the run model is built so they slot in as new loaders.

## Reference scenario

A synthetic interchange of **three 850 transactions** (distinct PO
numbers) under one ISA/GS, paired against a **JSON array of three order
documents** by `BEG03 ↔ order.po_number`. Baseline: all three pair and
pass clean. Defect file plants, across the set:

1. a per-document field defect in document 2 (proves per-doc validation
   still fires inside the loop),
2. a source transaction whose PO has **no** matching output document
   (`missing_output`, file level),
3. an extra output document with a PO **not** in the source
   (`unexpected_output`, file level),
4. two source transactions sharing a PO (`count_mismatch`, duplicate key).

## Test plan

1. `parse_interchange` returns N documents; the single-transaction wrapper
   still returns the first and all existing parser tests pass unchanged.
2. Pairing: exact-key match, positional single-doc fallback, declared-key
   requirement error, duplicate-key detection, orphans both directions.
3. `InterchangeResult` rollup math; single-doc equivalence
   (`validate_files` output identical to before).
4. Scenario: baseline all-pass; each planted defect asserted at the right
   level with the right category; history writes parent + child rows.
5. Full existing suite (385) green throughout — the single-document path
   is behavior-preserving.

## Open questions for review

1. **Container scope (Decision 3 / A):** JSON-array-only for this PR,
   multi-document flat/IDoc as a fast follow — agree?
2. **Keyless multi-doc (Decision 4 / B):** hard error vs. best-effort
   positional with a warning — I recommend hard error.
3. **Pairing key location:** two Meta keys (`Pairing Key (source)` /
   `Pairing Key (target)`) as proposed, or one column on the Mapping sheet
   flagged as the pairing row? Meta keeps it out of the per-rule flow;
   confirm that's the right home.
4. **Reference scenario:** three 850s as described, or would you rather the
   first multi-transaction proof mix sets (an 850 + an 855 in one
   interchange) to exercise per-document definition resolution too? That's
   a bigger scenario but a more honest one.
