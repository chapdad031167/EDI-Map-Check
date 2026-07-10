# Design 003 — Config-Driven Output Adapters + DESADV01 / INVOIC02

**Status:** approved 2026-07-10 — all four open questions resolved as
recommended (CLI `--output-def` + runtime-registration API this PR with
Streamlit upload as a fast follow; DESADV01/INVOIC02 as declarative
definitions; ORDERS05 retrofit onto the generic engine guarded by the
golden-dict test; DESADV01 scoped to the flat E1EDL20→E1EDL24 item list)
**Roadmap item:** 1.3 (Phase 1, design-first) — closes Phase 1

## The problem

Adding an ERP output format today means writing a Python adapter. The
ORDERS05 adapter (`output/orders05.py`) proved the shape — a shared
`_fold` routes segments into the canonical dict, a fixed-width table gives
field offsets, and the XML parser filters to the same fields so both
renditions agree — but every new IDoc type re-implements that by hand.

The ORDERS05 fold is **not opinionated**; it is five mechanical routing
rules driven by data. If those rules and the field tables move into a YAML
definition (exactly as transaction structure did in Phase 0), a user can
onboard a fixed-width or delimited ERP layout **without touching Python**,
and MapCheck's own IDoc adapters become definitions rather than code.

This closes Phase 1. It builds directly on the transaction-definition
loader pattern (`transactions/loader.py`, `registry.py`) and the proven
ORDERS05 fold.

## Decision 1: the routing kinds are already finite

Every canonical section the ORDERS05 fold produces is one of five
mechanical shapes. These, and only these, become the declarative grammar:

| Kind | ORDERS05 example | Canonical result |
|---|---|---|
| `object` | E1EDK01 → `header` | section dict of the segment's fields |
| `keyed` | E1EDK14 QUALF→ORGID → `org` | `section.{qualifier} = value` (or a sub-dict when >1 value field) |
| `partner` | E1EDKA1 PARVW→… → `partners` | `section.{qualifier.lower()} = {fields}` |
| `line` | E1EDP01 → `lines[]` | append a new dict of the segment's fields |
| `line_child` | E1EDP02/E1EDP19 → `lines[-1]` | fold into the current line under a group, qualifier-keyed |

`partner` is just `keyed` with a lowercased key and a forced sub-dict, so
the engine really has **three** primitives (`object`, `keyed`, `line` +
`line_child`). A `line_child` before any `line` is the same structural
error the hand-coded fold already raises. This is a faithful generalization,
not a new model — which is what makes the ORDERS05 retrofit a real test.

## Decision 2: one definition drives both flat and XML

A single YAML definition per IDoc basic type carries the field tables and
routing; both the flat reader and the XML reader consume it, exactly as
ORDERS05 does today. Sketch:

```yaml
format: idoc-orders05          # format_name on the CanonicalOutput
basic_type: ORDERS05           # IDoc control sanity-check (flat + XML)
layout: fixed                  # 'fixed' | 'delimited'
sdata_start: 63                # flat only: SDATA offset
segments:
  E1EDK01:
    route: {kind: object, section: header}
    fields: {ACTION: [0,3], CURCY: [4,3], BSART: [79,4]}
  E1EDK14:
    route: {kind: keyed, section: org, qualifier: QUALF, value: ORGID}
    fields: {QUALF: [0,3], ORGID: [3,35]}
  E1EDKA1:
    route: {kind: partner, section: partners, qualifier: PARVW,
            values: [PARTN, NAME1, STRAS, ORT01, PSTLZ, REGIO]}
    fields: {PARVW: [0,3], PARTN: [3,17], NAME1: [37,35], ...}
  E1EDP01:
    route: {kind: line}
    fields: {MENGE: [11,15], MENEE: [26,3], VPREI: [54,15]}
  E1EDP02:
    route: {kind: line_child, group: refs, qualifier: QUALF, values: [ZEILE]}
    fields: {QUALF: [0,3], ZEILE: [38,6]}
```

For a **delimited** layout, `fields` values are integer column indices and
`layout: delimited` names a `delimiter`. Everything else — routing,
folding, MISSING semantics — is identical; only the field *reader* differs
(slice by offset vs. split by delimiter). The XML reader ignores field
positions entirely and matches on element tag = field name, filtering to
the declared field set so flat and XML stay byte-identical (the exact
ORDERS05 rule).

## Decision 3: detection and registration mirror the transaction registry

A new `output/definitions/*.yaml` directory holds the bundled IDoc
definitions (ORDERS05, DESADV01, INVOIC02), auto-discovered and registered
like `transactions/definitions/`. Each definition declares how
`load_output` recognizes it:

```yaml
detect:
  flat: {control_record: EDI_DC40, basic_type_in_line: true}
  xml:  {root: ORDERS05}
```

`load_output` consults the registry: `.xml` → match root tag; first-line
`EDI_DC40` → match the basic type named in the control record; else the
existing keyed-flat / JSON paths (unchanged). A **user-supplied**
definition is registered from an external file — the "zero Python" path —
via `register_output_definition(path)` and a CLI `--output-def PATH` flag
on `mapcheck validate`.

**Open question A:** for user-supplied formats in *this* PR, is the
external-file mechanism (`--output-def path.yaml` + a runtime-registration
API, proven by a test that onboards a synthetic CSV layout with zero code)
sufficient — or do you also want Streamlit upload of a definition now? I
recommend CLI + API this PR, Streamlit upload as a fast follow.

## Decision 4: ORDERS05 retrofit is the acceptance test

`output/orders05.py` becomes a thin definition
(`output/definitions/orders05.yaml`) consumed by the generic engine. The
existing `load_orders05_flat` / `load_orders05_xml` entry points stay as
one-line shims so nothing downstream changes. The test that guards the
refactor: for every bundled ORDERS05 example (baseline + defects, flat +
XML), the declaratively-parsed `.data` must equal what the current
hand-coded adapter produces — captured as golden dicts before the refactor,
asserted after. If the generalization isn't faithful, that test fails.

## Decision 5: DESADV01 and INVOIC02 as definitions

Both are new `output/definitions/*.yaml`, exercising the grammar on real
SAP basic types, each with a flat + XML scenario package:

* **DESADV01** (856 ASN → shipping notification): E1EDL20 delivery header
  (`object`), E1EDL24 items (`line`) with E1EDL41 child references
  (`line_child`), E1EDL18/E1EDL21 as `keyed`/`object` shipment data.
  Scoped to the **flat item list** (E1EDL20→E1EDL24) — no HL-on-IDoc
  nesting, matching the single-repeating-list canonical model.
* **INVOIC02** (810 invoice → invoice IDoc): E1EDK01 header (`object`),
  E1EDKA1 partners (`partner`), E1EDP01 line items (`line`) with E1EDP19
  product ids (`line_child`), E1EDS01 summary totals (`keyed`).

Both complete the SAP order cycle alongside ORDERS05 (order → ship → bill).

**Open question B:** build these as declarative definitions consumed by the
generic engine (my recommendation — it's the honest proof the engine works,
and less code), or hand-code them like the original ORDERS05 and keep the
declarative engine only for *user* formats? Declarative is the whole point
of 1.3, so I recommend definitions.

## Decision 6: scope boundaries

* **Declarative XML adapters** stay tag-name based (no positional XML) —
  the tree walk has more real-world variance than fixed-width, so the
  declarative surface is field *routing*, and the XML reader is one shared
  walker. Fine, because IDoc XML is regular.
* **Conditional routing** (a field that changes section based on a value
  beyond a single qualifier) is out — qualifier-keyed covers every real
  IDoc case I know; anything conditional belongs in the *spec*, not the
  adapter, exactly as today.
* **No engine/spec/validation changes** — this is output-side only, like
  the original ORDERS05 work. The canonical model and the single-repeating-
  list constraint are unchanged.

## Reference scenarios

Two new scenario packages, mirroring the ORDERS05 one:

* **856 → DESADV01**: synthetic 856 source + composite spec, DESADV01 output
  in flat + XML; clean baseline PASS in both formats; ≥6 planted defects
  across rule categories; flat and XML produce identical findings.
* **810 → INVOIC02**: synthetic 810 source + composite spec, INVOIC02
  output in flat + XML; same guarantees.

Plus a **user-format** scenario: a synthetic delimited (CSV-ish) layout
described by an external YAML, registered at runtime, validating an 850
output with zero Python — the proof of the config-driven claim.

## Test plan

1. ORDERS05 golden-dict equivalence: declarative parse == current hand-coded
   parse for all four ORDERS05 examples (the retrofit gate).
2. Grammar unit tests: each routing kind, fixed vs. delimited field readers,
   flat/XML equivalence, MISSING semantics, `line_child`-before-`line` error,
   bad-definition load errors.
3. DESADV01 and INVOIC02 scenarios: baseline clean in both formats, each
   planted defect caught with its category, flat == XML findings.
4. User-format scenario: external delimited definition onboarded with no
   code change.
5. Full existing suite (404) green throughout — output-side only.

## Open questions for review

1. **User-format delivery (Decision 3 / A):** CLI `--output-def` + runtime
   registration API this PR, Streamlit upload as a fast follow — agree?
2. **DESADV01/INVOIC02 as definitions vs. hand-coded (Decision 5 / B):** I
   recommend declarative definitions (the point of 1.3).
3. **ORDERS05 retrofit (Decision 4):** retrofit ORDERS05 onto the generic
   engine now (guarded by the golden-dict test), or leave it hand-coded and
   only build the generic engine for the new types? I recommend retrofitting
   — an un-exercised generic engine that ORDERS05 doesn't use would rot.
4. **DESADV01 scope (Decision 5):** flat E1EDL20→E1EDL24 item list only
   (no HL-on-IDoc) for this PR — confirm that's the right first cut.
