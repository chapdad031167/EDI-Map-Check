# EDI MapCheck

**Vendor-neutral validation for EDI mapping work.** Give it three artifacts — a
mapping spec, an X12 source file, and the translated output — and it tells
you, field by field, whether the output actually does what the spec says.

Transactions are **declarative**: each supported set is a YAML definition file
(segment dictionary, loop hierarchy, reconciliation rules), not parser code.
The transaction is auto-detected from the file's ST01. `mapcheck transactions`
lists what's registered.

![CI](https://github.com/chapdad031167/EDI-Map-Check/actions/workflows/ci.yml/badge.svg)

## Why

Every EDI integration ships on the back of a mapping spec, and every EDI
specialist has burned days eyeballing a translator's output against that spec
line by line. Middleware vendors each have their own map-testing story, tied to
their own product. There was no small, open, product-agnostic tool that answers
the only question that matters at unit-test time:

> *Does the output file match what the spec says the source file should produce?*

EDI MapCheck answers that with a field-level PASS/FAIL report, a root-cause
summary, and an audit trail.

## What it checks

For every row of the mapping spec, the engine evaluates:

| # | Rule category | Example defect it catches |
|---|---------------|--------------------------|
| 1 | Value accuracy | `BEG03` PO number transposed on its way to `order.po_number` |
| 2 | Conditional logic | drop-ship flag set although `BEG02` ≠ `DS` |
| 3 | Code list translations | `EA` passed through untranslated instead of `EACH` |
| 4 | Hardcoded defaults | the constant `record_type` missing from the output |
| 5 | Data type & format | dates in the wrong format, implied decimals not applied (`2500` ≠ `25.00`), length violations |
| 6 | Loop / repeat counts | a dropped line item; a CTT count the translator trusted but the loops contradict |
| 7 | Unmapped elements | source data no rule references; output fields no rule produces |

Statuses are **PASS / FAIL / WARNING / NOT TESTED**, each failure tagged with a
root cause (`value_mismatch`, `condition_logic`, `code_translation`,
`constant_default`, `format`, `count_mismatch`, `source_data`,
`unmapped_source`, `unmapped_target`, `control`). Interchange-level control
problems (SE counts, control numbers) surface as warnings via
[pyx12](https://github.com/azoner/pyx12).

## Quickstart

```bash
git clone https://github.com/chapdad031167/EDI-Map-Check.git
cd EDI-Map-Check
pip install -e ".[dev]"

# validate the bundled synthetic example set
mapcheck validate \
  --spec examples/specs/850_reference_spec.xlsx \
  --source examples/source/850_baseline.edi \
  --output examples/output/po_baseline_defects.json \
  --export-xlsx report.xlsx
```

That run points the clean synthetic 850 at an output file with eleven planted
mapping defects, and catches all of them:

```text
STATUS     ROW     FIELD                            DETAIL
FAIL       M-003   order.drop_ship_flag             expected='N' actual='Y' — expected 'N', output has 'Y' (condition "BEG02 = 'DS'" is false)
FAIL       M-004   order.po_number                  expected='PO4400021' actual='PO4400012' — expected 'PO4400021', output has 'PO4400012'
FAIL       M-005   order.po_date                    expected='2026-06-15' actual='06/15/2026' — format violation: '06/15/2026' does not match the required date format '%Y-%m-%d'
FAIL       M-012   order.record_type                expected='PO_INBOUND' actual=None — target field is missing from the output (hardcoded constant)
FAIL       M-013   order.allowance_amount           expected='25.00' actual='2500' — expected '25.00', output has '2500'
FAIL       M-018   ship_to.state                    expected='CO' actual='COLO' — format violation: length 4 outside the allowed range 2..2 for 'COLO'
...
Summary: 29 PASS / 15 FAIL / 2 WARNING / 0 NOT TESTED — RESULT: FAIL
Root causes: missing_output: 7, format: 3, value_mismatch: 2, condition_logic: 1,
             constant_default: 1, code_translation: 1, count_mismatch: 1, unmapped_target: 1
```

Exit code is `0` on PASS, `1` on FAIL — drop it straight into CI.

The transaction set is auto-detected, so any of the 17 supported sets works
the same way. An 856 ASN with a corrupted HL tree, for instance:

```bash
mapcheck validate \
  --spec examples/specs/856_reference_spec.xlsx \
  --source examples/source/856_defects.edi \
  --output examples/output/asn_defects.json
```

```text
FAIL  -  (hierarchy)  hierarchical structure defect: HL at line 26:
         parent id '9' does not reference an earlier hierarchical loop (orphan)
WARNING  recon:ctt02-unit-sum  CTT02=999 != sum(SN102 over HL[I])=96
```

### Streamlit UI

```bash
streamlit run app.py
```

Upload the three files (or flip on the bundled example scenarios), run, filter
by status, download the color-coded Excel report:

![EDI MapCheck Streamlit UI](docs/screenshot_streamlit.png)

### Other commands

```bash
mapcheck transactions             # list registered transaction definitions
mapcheck init-spec my_spec.xlsx   # blank spec template with instructions sheet
mapcheck history                  # recent runs from the SQLite audit trail
mapcheck validate --help          # all options (--transaction, --verbose, --db, ...)
```

## Transaction coverage

| Set | Name | Status | Notes |
|-----|------|--------|-------|
| 850 | Purchase Order | ✅ Supported | Reference spec + full synthetic test set |
| 856 | Ship Notice/Manifest (ASN) | ✅ Supported | Full HL hierarchy: standard, pick-and-pack, and palletized structures; orphan/nesting integrity; SN1 rollup reconciliation |
| 855 | Purchase Order Acknowledgment | ✅ Supported | ACK line-status code lists; accept/reject splits reconcile against ordered quantities |
| 810 | Invoice | ✅ Supported | TDS total reconciles against line extensions + charges − allowances (declarative arithmetic) |
| 940 | Warehouse Shipping Order | ✅ Supported | Bare W01 line loops; ship-to / warehouse party loops |
| 945 | Warehouse Shipping Advice | ✅ Supported | LX-wrapped lines; W03 total + undeclared-short-ship reconciliation |
| 943 | Warehouse Stock Transfer Shipment | ✅ Supported | Transfer pair (ship side); W03 total vs line sums |
| 944 | Warehouse Stock Transfer Receipt | ✅ Supported | Transfer pair (receipt side); W14 total vs line sums |
| 947 | Warehouse Inventory Adjustment | ✅ Supported | W19 adjustment-reason code list; signed adjustment quantities |
| 846 | Inventory Inquiry/Advice | ✅ Supported | Multi-qualifier QTY buckets (QA/QO/QC) via path addressing `LIN>QTY[QA]` |
| 812 | Credit/Debit Adjustment | ✅ Supported | Signed amounts; header total reconciles as a signed sum of line amounts |
| 867 | Product Transfer and Resale | ✅ Supported | Pharma trace/rebate flow: PTD lines, resale price, header-total quantity rollup |
| 844 | Product Transfer Account Adjustment | ✅ Supported | Chargeback request: contract number + debit-amount rollup; line-level (WAC − contract) × qty math is backlogged |
| 845 | Price Authorization Acknowledgment | ✅ Supported | Contract pricing; authorization date-window check (`not_after`) |
| 849 | Response to 844 | ✅ Supported | Approval status code list; approved total vs line sum. 844⇄849 pairing is a future cross-transaction feature |
| 854 | Shipment Delivery Discrepancy | ✅ Supported | Discrepancy reason code list |
| 997 | Functional Acknowledgment | ✅ Supported | AK1/AK2/AK9; acknowledgment code lists; AK9 count sanity (accepted ≤ received ≤ included) |

**All 17 roadmap transaction sets are supported.**

Each transaction is a YAML file under `src/mapcheck/transactions/definitions/`
declaring its areas, segment dictionary, loops (including HL-style
parent-child trees), envelope expectations, and declarative reconciliation
rules (e.g. *CTT01 must equal the PO1 loop count*, *CTT02 must equal the sum
of item SN1 quantities*). The parser and engine are generic; adding a set
means adding a definition file, a reference spec, and synthetic test data —
no parser code.

**856 HL addressing:** an item-level spec rule (Loop Context `HL[I]`) reads
its own segments first, then its ancestors' — so `PRF01` resolves from the
item's parent order and `MAN02` from its carton, with no extra spec syntax.
Orphaned HL02 references, unknown level codes, and illegal nesting (an item
directly under a shipment) are structural failures. Assumption noted for the
reference spec: shipment-level TD1 lading quantity reconciles against the
pack-loop count (cartons), while CTT02 covers the unit rollup — TD102 with a
carton packaging code counts cartons, not units.

**Pharma set (844/845/849/854):** public documentation on these is thin, so
the reference definitions use minimal synthetic conventions built from
standard X12 segments — GS01 codes, BGN element usage, the CTP
class-of-trade WS/CT discriminator for WAC vs contract price, and the LQ
list qualifiers (RS response status, DR discrepancy reason) are all
explicitly flagged in each definition file's header for amendment against a
real partner guide. Everything in the synthetic files (NDCs included) is
fabricated.

**Warehouse suite (940/945/943/944/947):** built as a family from public 4010
companion guides. The 945 detail is LX-wrapped (`W12` shipped-item segments)
while the 940 uses bare `W01` line loops. Reconciliations declared per set:
945 checks `W03` total shipped against the line sum and flags *undeclared*
short-ships (ordered − shipped must equal the declared `W12` differences);
943/944 check `W03`/`W14` totals against their line quantities; 947 leans on
the `ADJ_REASON` code list with signed adjustment quantities. Element-usage
assumptions (e.g. `W12` positional meaning) are noted in each definition
file's header for amendment against a specific partner guide.

## The spec template

The mapping spec is a structured Excel workbook (`Mapping`, `CodeLists`,
`Meta`, and `Instructions` sheets). One row per mapping rule:

| Column | Purpose | Example |
|--------|---------|---------|
| Source Field | plain segment+element notation | `BEG03`, `N104`, `PO102` |
| Loop Context | which occurrence it comes from | `N1[ST]`, `REF[DP]`, `PO1` (each line) |
| Target Field | dot path into the output | `order.po_number`, `lines[].qty` |
| Rule Type | `DIRECT`, `CONDITIONAL`, `CODE_LIST`, `CONSTANT`, `LOOP_COUNT` | |
| Condition (Text / Coded) | human text + machine predicate | `N103 = '92'`, `EXISTS(REF02)` |
| Then / Else | `SOURCE`, `SKIP`, `BLANK`, or `'literal'` | |
| Default Value | constant, or fallback when the source is empty | `NONE` |
| Code List Ref | lookup table on the CodeLists sheet | `UOM` |
| Data Type / Format | `date` + `%Y-%m-%d`, `decimal` + `implied:2;places:2`, `len:2..2` | |

The coded condition grammar is tiny and safe (no `eval`): `=`, `!=`, `IN`,
`EXISTS`, joined with `AND`. Everything is documented on the template's
Instructions sheet; `mapcheck init-spec` gives you a blank one.

## Output formats

The validation engine never reads the output file directly — every format
loads into one canonical model addressed by the spec's Target Field paths.
That seam is what makes MapCheck vendor-neutral on the *output* side too:
the same spec validates a translation whether the target is a staging file
or an ERP's native inbound document.

* **JSON** — nested `order` / `ship_to` / `lines[]` / `summary`
* **Keyed flat** — record-per-line `H|k=v|...`, `A|role=ship_to|...`, `D|...`, `S|...`
* **SAP IDoc ORDERS05** — the real-world X12-to-ERP case, in **both**
  wire formats: the fixed-width IDoc flat file (EDI_DC40 control record +
  EDI_DD40 data records) and IDoc XML. Both parse through one shared fold,
  so the flat and XML renditions of the same IDoc produce identical
  canonical data — and therefore identical findings. Specs address IDoc
  fields mechanically (`refs.001.belnr`, `partners.we.name1`,
  `lines[].ids.003.idtnr`); what a qualifier *means* stays in the spec,
  same as X12-side `REF[DP]` addressing.

```bash
# same 850, same spec, either IDoc format — identical results
mapcheck validate --spec examples/specs/orders05_reference_spec.xlsx \
  --source examples/source/850_sap.edi \
  --output examples/output/orders05_baseline.txt   # or .xml
```

Adding a format is one parsing function in `mapcheck/output/` that emits
the canonical dict; the engine, spec grammar, and reports come for free.

## Test data policy

**Everything in `examples/` is synthetic**, generated by
`scripts/generate_examples.py` from the public X12 850 structure. No
proprietary specs, no partner data, no employer artifacts — and the defective
files are defective *on purpose* (each planted defect is documented in the
generator and asserted in the test suite).

## Project layout

```
src/mapcheck/
├── spec/          Excel template, rule model, condition grammar, spec loader
├── transactions/  declarative transaction definitions (YAML) + registry
├── x12/           pyx12-backed generic parser, driven by the definitions
├── output/        JSON, keyed-flat, and SAP IDoc ORDERS05 (flat + XML) adapters
├── engine/        rule evaluation, format checks, reconciliation, findings
├── report/        terminal report, Excel export, SQLite history
└── cli.py         the mapcheck command
app.py             Streamlit UI
examples/          synthetic specs + source files + outputs (clean and defective)
scripts/           example-set generator
tests/             pytest suite (every rule category, every planted defect)
```

## Scope

Inbound X12 → internal or ERP-native output (JSON, keyed flat, SAP IDoc
ORDERS05), one spec template format. Not yet:
outbound direction, arbitrary spec formats, partner-specific overrides,
cross-transaction pairing (e.g. 844/849). The layering above is built so
those grow without rework.

## Development

```bash
pip install -e ".[dev]"
pytest                              # full suite
python scripts/generate_examples.py # regenerate the synthetic example set
```

## License

MIT
