# Design 001 — Outbound Direction (internal → X12)

**Status:** proposed — awaiting review, no code yet
**Roadmap item:** 1.1 (Phase 1, design-first)

## The inversion, precisely

Inbound validation derives an **expected** value from the X12 source per
the rule type, and resolves the **actual** value from the canonical output
model:

```
expected = f(rule, X12 document)        actual = canonical.get(target_path)
```

Outbound swaps which document plays which role — nothing else:

```
expected = f(rule, canonical document)  actual = X12.scope(loop_ctx).value(SEGnn)
```

Everything downstream of that swap — rule types, root-cause categories,
format normalization, findings, reports, history — is direction-agnostic
and stays untouched.

## Decision 1: one template, direction-dependent column semantics

A new Meta key **`Direction`** (`inbound` | `outbound`, default `inbound`
— every existing spec is valid unchanged). The Mapping sheet keeps its
exact 14 columns; three of them are interpreted per direction:

| Column | Inbound | Outbound |
|---|---|---|
| Source Field | X12 `SEGnn` (`BEG03`) | canonical path (`order.po_number`, `lines[].qty`) |
| Loop Context | X12-side occurrence selector, on the **source** | same selector, on the **target** |
| Target Field | canonical path (`refs.001.belnr`) | X12 `SEGnn` (`BAK03`) |
| Condition fields | X12 `SEGnn` | canonical paths |

Rationale over an outbound-specific sheet layout: one parser, one
Instructions sheet, and — decisive for roadmap 2.1 — one import target.
The Loop Context column always addresses "the X12 side"; only which side
that is flips. The spec parser validates the notation per direction
(an outbound spec with `BEG03` in Source Field is a load error, not a
silent misread), so the two interpretations can never blur inside one file.

Rejected alternative: separate outbound columns ("Target Segment",
"Target Loop Context", "Source Path"). Cleaner labels, but two template
layouts forever, double the parser surface, and spec import has to
classify which layout it is looking at before it can classify anything else.

## Decision 2: rule-type semantics, flipped mechanically

| Rule type | Outbound meaning |
|---|---|
| DIRECT | internal value, normalized per Data Type, must appear in the X12 element in the declared Format (`%Y%m%d` means the element carries CCYYMMDD) |
| CODE_LIST | internal value → lookup → expected X12 code (CodeLists sheet stays source-value → target-value; in an outbound spec that reads internal → X12) |
| CONSTANT | the X12 element must equal the literal |
| CONDITIONAL | condition evaluated against the **internal** document; SOURCE maps the internal path, SKIP means the X12 element must be empty/absent |
| LOOP_COUNT | Source Field names an internal list (`lines[]`); its length is the expected value of the X12 element (CTT01) |

Conditions describe the mapping decision, and mapping decisions are made
from source data — so condition fields address the source side in **both**
directions. That keeps the grammar symmetric: same operators
(`=`, `!=`, `IN`, `EXISTS`, `AND`), operands are `SEGnn` inbound and
canonical paths outbound. A per-line outbound condition
(`lines[].item_type = 'DS'`) reads the current line's value, exactly as an
inbound per-line condition reads its PO1 scope.

## Decision 3: SKIP / BLANK on an X12 target

X12 cannot distinguish "element present but empty" from "element absent"
(`PO1*1**EA` and a truncated segment read identically through the parser).
This is the same physics as the IDoc fixed-width flat format, so the same
policy applies:

- **SKIP** → the X12 element must resolve to nothing. Testable, fully supported.
- **BLANK** → not representable on an X12 target → the rule is
  **NOT TESTED** with an explanatory note, mirroring the documented IDoc
  flat behavior. The spec parser warns at load time when an outbound spec
  uses BLANK.

## Decision 4: pairing, counts, and the cross-cutting checks

The transaction definition's `output_pairing` ("PO1 pairs with `lines`")
is already direction-neutral — it names an X12 loop and a canonical list.
Outbound reads it mirrored:

- **Per-line rules:** internal `lines[n]` ↔ X12 pairing-loop occurrence
  *n*. A per-line rule is one whose Loop Context is the pairing loop (its
  X12 target side) and whose Source Field is a `lines[]` path.
- **Line-count check:** length of the internal list vs. count of X12 loop
  occurrences; `count_mismatch` either way, message names which side is short.
- **Reconciliation rules** (definition YAML) only ever read the X12
  document, and they still should: outbound, they verify the *produced*
  file's internal consistency (CTT vs. PO1 count, TDS vs. line math). No change.
- **Control notes** (pyx12 envelope checks) now audit the produced file —
  which is precisely what you want on an outbound map. No change.
- **Unmapped checks keep their meanings, not their sides.**
  `unmapped_source` = source data no rule references → outbound, that is a
  `walk_paths()` sweep of the internal document. `unmapped_target` =
  output data no rule produces → outbound, that is every non-envelope X12
  element present in the file but not covered by any rule's Loop Context +
  Target Field (the existing `business_segments()` walk provides the
  iteration; envelope segments stay excluded).

## Decision 5: engine shape — two side-readers, one rule loop

No `if direction == ...` threaded through the validator. The engine
already touches each document through a narrow seam (`Scope.value` /
`_evaluate_condition` on the X12 side; `CanonicalOutput.get` /
`line_count` / `walk_paths` on the canonical side). Formalize that as two
small internal adapters:

- **SourceReader** — `value(rule, line_index)`, `condition(rule, line_index)`,
  `list_count(ref)`, `unmapped_sweep()`. Implemented by wrapping
  `TransactionDocument` (inbound, extracted from today's code — behavior
  identical) and `CanonicalOutput` (outbound, new).
- **TargetReader** — `actual(rule, line_index)`, `line_count()`,
  `unmapped_sweep()`. Implemented by wrapping `CanonicalOutput` (inbound,
  extracted) and `TransactionDocument` (outbound, new: Loop Context +
  `SEGnn` → `tx.scopes(ctx)[index].value(seg, elem)` — the very machinery
  inbound uses for source resolution, reused verbatim).

`validate()` composes the pair by direction; `_expected_for`, the category
mapping, format handling, and findings assembly are shared, unmodified
code paths. The inbound wrappers are pure extraction — every one of the
353 existing tests must pass before the outbound wrappers are added.

One typing note: the outbound *source* can be typed (JSON). Source-side
normalization goes through the existing typed-aware
`normalize_actual`-style path rather than the string-only
`normalize_source`; the X12 *target* side is always lexical, like every
untyped output today.

## Decision 6: CLI, loaders, and detection

`--source` remains "the translation's input", `--output` remains "the
translation's result" — the spec's `Direction` decides which loader each
gets. Outbound: `--source` loads through the existing output adapters
(JSON / keyed flat / IDoc — the canonical model is just "the internal
document" now), `--output` parses as X12 with ST01 auto-detection, and the
spec's `Transaction Set` must agree with the X12 file, whichever side it
is on. `init-spec --direction outbound` emits the template with the Meta
key preset and the outbound Instructions section.

## Reference scenario (recommendation: outbound 855)

Synthetic ERP order-response JSON → outbound 855, using the existing 855
definition. The 855 exercises header/party/line/summary plus CTT and code
lists without dragging HL hierarchy onto the target side in the same PR
(outbound 856 becomes a natural follow-on stress test once this lands).
Baseline validates clean; the defect file plants ≥6 root-cause categories:
`value_mismatch`, `code_translation`, `condition_logic`,
`constant_default`, `format` (date rendered ISO instead of CCYYMMDD),
`count_mismatch` + `missing_output` (dropped PO1), `unmapped_target`
(stray REF segment nobody mapped).

## Explicitly out of scope

Generating or repairing X12; outbound envelope authoring rules beyond the
existing control checks; outbound 856/HL scenario; multi-transaction files
(that is 1.2, and the side-reader seam is built so 1.2 slots in per
document-pair without touching this design).

## Test plan

1. Extraction refactor lands first, green against all existing tests
   (pure behavior-preserving move).
2. Outbound unit tests: parser direction validation, path-operand
   conditions, X12-target resolution incl. per-line indexing, SKIP/BLANK
   policy, flipped unmapped sweeps.
3. Scenario tests: baseline clean in outbound mode; each planted defect
   asserted with category; inbound reference scenarios re-run untouched.

## Open questions for review

1. **One template with per-direction semantics (Decision 1)** — or do you
   want distinct outbound column headers despite the import cost?
2. **BLANK → NOT TESTED on X12 targets (Decision 3)** — acceptable, or
   should outbound specs hard-reject BLANK at load?
3. **855 as the reference scenario** — or would you rather the first
   outbound proof be a 940→warehouse-facing flow you see more often?
4. **Condition operands stay source-side in both directions (Decision 2)**
   — confirm; allowing target-side conditions is possible but doubles the
   grammar's addressing rules for a case no mapping spec I know of needs.
