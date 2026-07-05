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
| 855 / 810 | PO Ack / Invoice | 🔜 Next | Order cycle |
| 940 / 945 / 943 / 944 / 947 | Warehouse suite | Planned | 3PL flows |
| 846 / 812 / 867 | Inventory & product movement | Planned | |
| 844 / 845 / 849 / 854 | Pharma contract & chargeback | Planned | Built from public X12 documentation |
| 997 | Functional Acknowledgment | Planned | |

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

Two reference output formats ship with the MVP, behind one adapter seam:

* **JSON** — nested `order` / `ship_to` / `lines[]` / `summary`
* **Keyed flat** — record-per-line `H|k=v|...`, `A|role=ship_to|...`, `D|...`, `S|...`

The engine only ever sees the canonical model, so adding a format is one
parsing function in `mapcheck/output/`.

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
├── output/        JSON + keyed-flat adapters onto one canonical model
├── engine/        rule evaluation, format checks, reconciliation, findings
├── report/        terminal report, Excel export, SQLite history
└── cli.py         the mapcheck command
app.py             Streamlit UI
examples/          synthetic specs + source files + outputs (clean and defective)
scripts/           example-set generator
tests/             pytest suite (every rule category, every planted defect)
```

## Scope

Inbound X12 → generic internal output, one spec template format. Not yet:
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
