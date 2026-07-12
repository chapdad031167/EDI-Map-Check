# Design 005 — Partner Overrides

**Status:** proposed — awaiting review, no code yet
**Roadmap item:** 2.2 (Phase 2, design-first)

## The problem

One trading relationship rarely has one spec. A distributor runs *the same*
850 map for 40 partners, each with small deviations: a different ID
qualifier, an extra conditional, a partner-specific code translation, one
rule that doesn't apply. Today that means 40 near-identical full specs that
drift apart the moment the base map changes — the exact maintenance trap
MapCheck exists to remove.

**Partner overrides** keep one **base spec** plus a small **delta** per
partner. `--partner acme.xlsx` resolves the two into the effective spec for
that partner, validated exactly as a hand-written spec would be. Only the
spec layer is touched; the engine validates the merged result unchanged.

## Decision 1: merge after load, keyed by Row ID

The base and each delta are ordinary spec workbooks. Resolution is a merge
of loaded `MappingSpec` objects, not a workbook edit:

```
load_spec(base)  +  load_delta(partner)  ──►  merged MappingSpec  ──►  validate()
```

Rules are identified by their **Row ID** (already unique within a spec, and
already the loader's key). For each delta rule:

| Delta row | Effect on the merged spec |
|---|---|
| Row ID **not** in base | **add** the rule (appended after base rules) |
| Row ID **in** base | **replace** the base rule wholesale |
| Rule Type cell is `REMOVE` | **delete** the base rule with that Row ID |

Replace is wholesale (the delta row is the complete new rule), not a
field-level patch — field-level merge is where partner specs get subtly
wrong, and "here is the rule for ACME" is what a spec author actually
writes. A `REMOVE` for a Row ID absent from the base is a load warning, not
an error (the base may have changed).

**Open question A:** `REMOVE` as a recognized Rule Type value in the delta
loader (no change to the core `RuleType` enum — the delta loader intercepts
it before rule parsing) — or a separate `Action` column (add/replace/remove)
on delta sheets? I recommend the `REMOVE`-sentinel approach: no template
change, and a delta sheet stays a normal Mapping sheet you can also import
(2.1) or hand-edit.

## Decision 2: code lists shadow whole-list

A delta's CodeLists sheet **shadows** the base list of the same name
entirely — the partner's `UOM` list replaces the base `UOM` list, it does
not merge entries. Whole-list shadowing is predictable ("this partner's UOM
table is *this*") and avoids the per-entry ambiguity of "did they mean to
add EA→EACH or override it?". Lists the delta doesn't mention are inherited
from the base unchanged.

**Open question C:** whole-list shadow (recommended) vs. per-entry merge?
Whole-list is simpler to reason about and to export; confirm.

## Decision 3: provenance on every rule and finding

`MappingRule` gains an additive `origin` field (`"base"` or the partner
label, e.g. `"partner:acme"`), defaulting to `"base"` so every existing
spec and test is unaffected. The merge stamps each rule's origin; a finding
already carries its Row ID, and reports gain an origin tag so a reviewer
sees *"this failure is on an ACME-specific override"* vs. a base rule. This
is the difference between "the map is wrong" and "the ACME delta is wrong."

Meta: the merged spec's `Transaction Set` and `Direction` must agree
between base and delta (a delta can't change direction or transaction set —
that's a different spec, not an override). Disagreement is a hard error.

## Decision 4: resolution and the merged-spec export

* **Validate with an override:**
  `mapcheck validate --spec base.xlsx --partner acme.xlsx --source … --output …`.
  The `--partner` path is an explicit delta workbook (not a registry) for
  this PR.
* **See the effective spec:**
  `mapcheck merge-spec base.xlsx --partner acme.xlsx --output effective.xlsx`
  writes the fully-resolved workbook — every rule with its origin in Notes —
  so a partner spec is always auditable as one sheet. The merged export
  round-trips through `load_spec` (the correctness gate, reusing the 2.1
  round-trip discipline).

**Open question B:** one delta per validate this PR, with **stacked** deltas
(base → regional → partner, applied in order) as a fast follow — or stacked
now? I recommend single-delta now; the merge is written to fold a list so
stacking is a small follow-on, but the scenarios and review stay tight.

## Decision 5: scope boundaries

* **No engine/grammar changes.** The merged `MappingSpec` is exactly what
  the validator already consumes; `origin` is additive metadata.
* **Deltas are spec workbooks**, so they benefit from `import-spec` (2.1)
  and `init-spec` for free — a partner delta is authored the same way.
* **Registry of partners** (a directory resolved by `--partner ACME`) — out;
  explicit `--partner path.xlsx` this PR.
* **Streamlit partner picker** — out; a fast follow, like the 2.1 UI.

## Reference scenario

A base 850 spec plus **two synthetic partner deltas**, validated against
one source to produce three distinguishable outcomes:

* **base** (no `--partner`) — the reference result.
* **partner ACME** — a delta that *replaces* one rule (a different ship-to
  ID qualifier), *adds* one rule (an ACME-only reference field), and
  *shadows* the `UOM` code list (ACME uses different unit codes). The same
  source now passes/fails differently on exactly those points.
* **partner GLOBEX** — a delta that *removes* one base rule (GLOBEX never
  sends the promo field) and adds a partner-specific conditional.

The merged export for each partner is asserted to load and to carry the
right per-rule origins; a planted defect on an ACME override is shown
tagged as an override failure, not a base failure.

## Test plan

1. Merge semantics: add, replace, remove, remove-of-absent (warning),
   code-list shadow, inherited lists.
2. Meta guards: direction / transaction-set disagreement is an error.
3. Provenance: merged rules carry correct origins; findings surface them.
4. Merged export: writes, loads, and round-trips; Notes show origin.
5. Scenario: base vs ACME vs GLOBEX produce the three intended outcomes;
   an override defect is tagged to the partner.
6. Full existing suite green — overrides are additive (`origin` defaults to
   base; no `--partner` means today's behavior exactly).

## Open questions for review

1. **Remove mechanism (Decision 1 / A):** `REMOVE` Rule Type sentinel in
   the delta loader (recommended, no template change) vs. an `Action`
   column?
2. **Stacking (Decision 4 / B):** single delta this PR with stacked deltas
   as a fast follow (recommended), or stacked now?
3. **Code-list granularity (Decision 2 / C):** whole-list shadow
   (recommended) vs. per-entry merge?
4. **Provenance surface:** an `origin` field on rules + an origin tag in
   findings and the merged export (recommended) — enough, or do you want a
   fuller merge audit (which delta touched which rule) this PR?
