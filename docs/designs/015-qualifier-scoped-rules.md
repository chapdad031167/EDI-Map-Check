# Design 015: qualifier-scoped rules

**Status:** Approved 2026-08-13 (review conversation), implemented.
**Applies to:** the transaction-definition schema, the validation
engine's presence checks, and partner-rules overlay emission
(`import-guide` / `validate --partner-rules`).
**Extends:** Design 014, whose Decision 4 scope guard limited v1
enforcement to element and segment *presence* and named these two rule
shapes as backlog rather than half-building them.

## The problem, stated plainly

Design 014's overlay could ask *"does this segment/element exist?"* but
not *"does it exist with this qualifier?"*. That left two honest gaps,
both flagged in every overlay's `review` list:

1. **Scoped element requirements.** "REF02 is required *within the
   REF\*IA occurrence*" could only be enforced as segment presence — a
   file carrying `REF*IA~` (qualifier present, value empty) passed. The
   rule could not be emitted unconditionally because a file may carry
   other REF occurrences (`REF*ZZ`) the partner says nothing about.
2. **Qualifier pairs.** X12 product-ID pairs are positional but
   code-keyed: PO106/07 and PO108/09 each carry (qualifier, value), and
   a sender may put a given code in either slot. "Every PO1 must carry a
   UP pair" was enforced positionally (PO108/PO109 must be filled),
   which is wrong in both directions: a compliant file with UP in the
   first slot pair fails, and a filled-but-UP-less segment (VN + BP)
   passes.

## Decision 1: two rule shapes, in the definition schema

Both shapes live in `transactions/schema.py` beside their Design 014
siblings, so overlays keep matching the definition schema exactly and
base definitions may declare them too.

- `RequiredElementDef` gains `qualifier` / `qualifier_element`
  (mirroring `RequiredSegmentDef`): with a qualifier set, only
  occurrences whose qualifier element equals that code are checked.
  Finding: `REF02 (Reference Identification) in REF*IA is required by
  partner acme_pharma but is empty`. When the qualified occurrence is
  absent entirely, the scoped rule is vacuous — the segment-presence
  rule reports that case, so nothing double-reports.
- `RequiredPairDef(segment, code, first_element=6, last_element=24,
  step=2)`: per occurrence of the segment, scan the qualifier slots
  (`first, first+step, …, last`); the rule is satisfied by `code` in
  any slot with a non-empty companion value. Finding:
  `no UP (UPC Consumer Package Code) qualifier pair in this PO1 —
  required by partner acme_pharma`, one per violating occurrence.

The semantics, as the truth table that drove the design (850 PO1, guide
requires a UP pair):

| PO1 content | Positional v1 verdict | This design |
|---|---|---|
| `VN*SAF-00110` only | FAIL (right) | FAIL — no UP pair |
| `UP*…` only, first slots | FAIL (false) | pass |
| `VN*…*BP*…`, no UP | pass (miss) | FAIL — no UP pair |
| `…*UP*` (empty value) | — | FAIL — pair needs a value |

## Decision 2: emission — scoped rules replace review notes

`emit_partner_rules` changes for guide blocks it previously could not
express:

- A single-code qualified segment (REF\*IA, DTM\*002) now emits scoped
  element rules for its other `must_use` elements; the "cannot yet be
  scoped" review note is gone. Per-occurrence blocks (Insight's three
  N1 blocks) emit per-qualifier scoped rules; dedup keys include the
  qualifier.
- Paired segments (`_PAIRED_SEGMENTS`: PO1 and IT1, slots 6–24 step 2 —
  a data map, extended when a guide demands another segment) turn a
  `must_use` qualifier slot pinned to one code into a pair rule,
  consuming its companion value slot. A multi-code slot stays a
  positional requirement with a review note — flag-never-guess.
- `apply()` dedup: an unconditional base element rule still suppresses
  a partner rule for the same element (scoped or not — the base rule is
  stronger); pairs dedup on (segment, code).

With these shapes, the synthetic Acme guide's overlay carries an empty
`review` list: nothing it asserts is beyond the schema anymore.

## What this closes, and what remains

The audit file 4 loop tightens: 4 FAILs (DTM\*002, REF\*IA presence,
one semantic "no UP pair" per line) instead of 6 positional ones, and
the two enforcement holes above are covered by regression tests
(`TestQualifierScopedEnforcement` — the truth table as tests, plus the
`REF*IA~` empty-value case).

Still named, still honest:

- **Loop-scoped placement.** "N3 required *within the N1[ST] loop*"
  enforces as global presence; a file with N3 in the wrong loop passes.
  Same class of work (a loop-context filter on presence rules); waiting
  for a real guide to demand it.
- **Multi-code qualifiers.** A REF block allowing {IA, DP} still emits
  an unqualified requirement plus a review note — picking one would be
  guessing.

## Testing

Truth-table enforcement tests (engine-level, inline EDI variants of
audit file 4); loader validation for both shapes (definition YAML and
overlay YAML, every problem named); emission tests (scoped rules,
pair rules, consumed value slots, multi-code fallback, per-qualifier
dedup); round-trips; the updated audit file-4 closure test.
