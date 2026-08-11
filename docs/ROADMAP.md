# EDI MapCheck — Production Viability Roadmap

This roadmap takes MapCheck from "validates a test case" to "guards a
production map." Ten features, three phases, ordered **hardest → easiest**
(3-3-4): the hard items change schemas and grammars that the easier items
build on, so nothing in a later phase gets rebuilt because of an earlier one.

**Process:** one PR per feature, review stop after each. Features marked
**[design-first]** require a reviewed design doc (committed under
`docs/design/`) before any code — they change core schemas or grammars and
are expensive to redo.

**Standing constraints (unchanged from the original missions):**

- Synthetic and public data only. Nothing proprietary from any employer, ever.
- Vendor-neutral. No real company names in examples.
- Backward compatible: the full existing test suite passes after every PR.
- Conventional commits, portfolio quality, every planted defect documented
  in the generator and asserted in the test suite.

---

## Phase 1 — The Hard Three (architecture changers)

### 1.1 Outbound direction (internal → X12) **[design-first]**

The single deepest change: today the engine computes an expected value
*from* X12 and compares it against a generic path in the output. Outbound
inverts that — the source is internal data (JSON/flat/IDoc), the target is
X12, and Loop Context addressing moves to the target side.

- **In scope:** a per-spec direction setting; the engine evaluating rules
  with source = canonical model, target = parsed X12; X12-side addressing
  reusing the existing `BEG03` / `N1[ST]` / `PO1 #n` grammar as *target*
  references; a reference outbound scenario (ERP order data → outbound 855
  or 856) with baseline + planted defects.
- **Out of scope:** generating X12 (MapCheck validates, never translates);
  outbound envelope construction rules beyond the existing control checks.
- **Key design questions:** one spec template for both directions or an
  outbound sheet layout; how CONDITIONAL rules address the internal side in
  conditions; what unmapped-source / unmapped-target mean when the sides flip.
- **Done when:** an outbound reference scenario validates clean, ≥6 planted
  defect categories are caught with correct root causes, and all inbound
  tests are untouched and green.

### 1.2 Multi-transaction interchange validation **[design-first]**

Real files carry many STs per GS and multiple GS per ISA. This changes the
run model: a validation run becomes a set of document-pair results plus a
file-level rollup.

- **In scope:** parsing every transaction in an interchange; a *pairing
  key* declaration in the spec (e.g., "BEG03 pairs to `refs.001.belnr`");
  matching N source transactions to M output documents; per-pair findings;
  file-level findings for orphans on either side (source transaction with
  no output document → `missing_output`; output document with no source →
  `unexpected_output`); duplicate-key detection; CLI and Streamlit
  reporting grouped by document with a rollup summary; SQLite history
  extended to store per-document results under one run.
- **Out of scope:** cross-transaction-set pairing (850↔855); streaming very
  large files (read-whole-file is fine at this stage).
- **Key design questions:** the output-side container for multiple
  documents (JSON array, one file per document, multi-IDoc flat file —
  which the EDI_DC40 layout supports naturally); how findings are keyed so
  regression baselines (2.3) can diff per-document.
- **Done when:** a 3-transaction synthetic interchange with 3 IDocs
  validates clean; scenarios cover a missing output document, an extra
  output document, a duplicated key, and per-document defects;
  single-transaction behavior is unchanged.

### 1.3 Config-driven output adapters + DESADV01/INVOIC02 **[design-first]**

Generalize what the ORDERS05 adapter proved: users describe a fixed-width
or delimited layout declaratively and get an adapter without writing Python.

- **In scope:** a YAML adapter-definition grammar (record identification,
  field offsets/columns, section routing into the canonical dict,
  repeating-line trigger, child folding — the ORDERS05 fold concepts made
  declarative); a loader that registers user-supplied definitions;
  hand-built DESADV01 (856-side) and INVOIC02 (810-side) IDoc adapters in
  both flat and XML, completing the SAP order cycle; scenario packages for
  both.
- **Out of scope:** declarative XML adapters (hand-coded for now — the
  tree walk has more variance); binary formats.
- **Key design questions:** how much of the fold is expressible
  declaratively before it stops being simpler than Python (qualifier-keyed
  sections and last-line child folding: yes; anything conditional: no);
  whether ORDERS05 gets retrofitted onto the declarative engine
  (recommended: yes, as its acceptance test — identical canonical dicts
  before and after).
- **Done when:** a user-defined CSV layout and a user-defined fixed-width
  layout both validate through the engine with zero code changes; DESADV01
  and INVOIC02 scenarios pass with planted defects caught; ORDERS05
  outputs parse identically through the declarative path.

**Phase 1 exit review:** the run model, spec grammar, and adapter seam are
final. Everything after this is additive.

---

## Phase 2 — The Middle Three (team-tool features)

### 2.1 Spec import **[design-first]**

The adoption barrier: nobody retypes a 300-row spec.

- **In scope:** `mapcheck import-spec` for arbitrary Excel/CSV mapping
  documents with a column-mapping step (interactive in Streamlit,
  flag-driven in CLI); heuristic rule-type classification (constants,
  code-list references, conditionals recognized by pattern); a best-effort
  mode that imports what it can and emits a worklist of rows needing human
  classification; a round-trip guarantee (imported spec re-exports to the
  native template).
- **Out of scope:** PDF extraction (low reliability — parked); map-vendor
  proprietary export formats until public samples exist.
- **Done when:** three deliberately-messy synthetic "partner spec"
  workbooks (different column orders, merged cells, prose conditions)
  import with ≥80% of rows auto-classified and the remainder flagged,
  never silently guessed.

### 2.2 Partner overrides

- **In scope:** a base spec plus per-partner delta workbooks (add / replace
  / remove rules by Row ID; partner-specific code lists that shadow base
  ones); `--partner <name>` resolves the merged spec; merged-spec export so
  the effective ruleset is always visible; provenance on every finding
  (base rule vs. partner override).
- **Key design decision:** merge semantics — replace-by-Row-ID, delete via
  an explicit `REMOVE` rule type, code lists shadow whole-list not
  per-entry. Simple to reason about beats clever.
- **Done when:** one base 850 spec + two synthetic partner deltas produce
  three distinguishable validation outcomes on the same source file, and
  the merged export matches what validated.

### 2.3 Regression mode / golden baselines

- **In scope:** `mapcheck bless <run-id>` marks a run as the golden
  baseline for a spec + partner + direction combination; `mapcheck regress`
  re-runs and reports only the delta — new failures, fixed failures,
  changed expected/actual values, new/removed documents (per-document,
  using the 1.2 keying); a Streamlit baseline-vs-current view; nonzero exit
  on regression.
- **Done when:** a scenario proves the loop — bless a clean run, introduce
  one defect in the synthetic map output, and `regress` reports exactly
  that one delta and nothing else.

**Phase 2 exit review:** a team can onboard a real spec, layer partners,
and guard map changes.

---

## Phase 3 — The Final Four (polish and reach)

### 3.1 Rule ergonomics

Tolerances (`tol:0.01` on decimal formats), date arithmetic in expected
values (`DTM[002] + 5d`), and external lookup files
(`Code List Ref: file:item_xref.csv` for thousand-row cross-references,
loaded and cached, missing entry → `code_translation` finding). Grammar
extensions only — no engine restructuring, which is why this waits until
the grammar is final after Phase 1.

### 3.2 CI & batch mode

`mapcheck validate-dir` driven by a `mapcheck.yaml` manifest of
spec/source/output/partner entries; JUnit-XML output; meaningful exit codes
(0 pass, 1 findings, 2 execution error); a documented GitHub Actions
example workflow. Multi-transaction (1.2) and regress (2.3) both slot in as
manifest entry types.

### 3.3 Data scrubber

`mapcheck scrub` for X12 files: masks configured element positions (names,
addresses, DEA/HIN/NDC-shaped identifiers, via the transaction definition
YAMLs marking sensitive elements) while preserving structure, lengths, and
referential consistency (same input value → same masked value, so pairing
keys survive). Ships with a pharma-oriented default profile. **Policy note:
scrubbing helps users create test cases safely, but this repo's own
examples remain fully synthetic.**

### 3.4 Shareable reporting

A standalone single-file HTML report (findings, rollups, per-document
detail — no server needed, mailable to a partner); history trends from the
SQLite DB (pass rate per spec/partner over time, top recurring root causes)
in both Streamlit and the HTML export.

**Phase 3 exit review = project Definition of Done:** full suite green,
README rewritten around the complete feature set, every feature has a
synthetic scenario package, Streamlit screenshot refresh.

---

## Sizing

Phase 1 is more than half the total effort — 1.1 and 1.2 each rival the
original multi-transaction-set expansion in scope, and each produces a
design doc that deserves real review. Phase 2 items are a few days' scale
each. Phase 3 items are each roughly a single-PR effort. The 3-3-4 split
front-loads all schema risk, which is exactly where you want it.

---

## Post-1.0 — from the audit (docs/audit-gap-list.md)

The five-file audit kit measured what the validator actually catches; these
items came out of that gate.

### Next major: partner-rule overlay

The audit's headline scope finding (file 4): MapCheck cannot enforce a
companion guide. "DTM*002 is required for this partner", "every PO1 must
carry a UP qualifier pair" are *presence* obligations, and required-ness
cannot currently be declared per partner — `merge-spec` deltas override
mappings, not obligations. Design sketch: per-partner required
segments/elements/qualifier-pairs declared in a delta-like overlay and
merged the way spec deltas already are. This is the item that turns "valid
X12" into "valid for this partner."

### Backlog

- **N402 state-code list.** Usage varies across the industry (US states,
  Canadian provinces, country codes, arbitrary partner codes); an invalid
  value doesn't break translation and the fix belongs upstream with the
  trading partner. If shipped: a `STATE` code list covering US states plus
  Canadian provinces, surfacing as a **warning**, never a failure. Spec
  authors can do this today with a `CODE_LIST` rule.
- **UPC / GTIN check-digit validation** (length is already enforced).
- **Source-only audit verb** — run the envelope, truncation, and
  required-element layers against a lone `.edi` with no spec, so MapCheck
  is useful before a map exists.
- **Segment-level required-ness** — the required-elements layer checks
  elements within present segments; "this segment must appear at least
  once" (e.g. a missing BEG entirely) is the natural next step of the same
  mechanism.
- **Extend required-element tables** beyond the 850's BEG03 and
  PO102-when-PO103 — pure definition data now that the mechanism exists.
