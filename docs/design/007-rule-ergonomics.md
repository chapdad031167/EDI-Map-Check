# Design 007 — Rule Ergonomics

**Status:** approved — implemented in this PR
**Roadmap item:** 3.1 (Phase 3, design-first) — opens Phase 3

**Resolved (all four recommendations adopted):** (A) within-tolerance match is
PASS with an informational delta note; (B) date arithmetic is a Format
`shift:±Nd`/`±Nw` token (days + weeks, no months), leaving Source Field a pure
reference; (C) `file:` lookups resolve relative to the spec's directory as a
`source,target[,description]` CSV with an optional header auto-skipped; (D) the
scenario is a trimmed 850 (`850_ergonomics_spec.xlsx`) exercising all three —
kept separate from the reference spec so its exact assertions stay stable,
while reusing the 850 machinery.

## The problem

The rule grammar is expressive enough for "this element equals that field,"
but real partner guides lean on three patterns it can't say yet:

1. **Tolerances** — a money total the translator rounds to 2 places should
   pass when it's within a penny of the recomputed value, not fail on the
   third decimal.
2. **Date arithmetic** — a promised-delivery date is *"order date + 5 days,"*
   not a copied element; today you can't express the offset.
3. **External cross-references** — an item or UOM xref is a thousand-row CSV
   the partner maintains, not something you paste into a spec's CodeLists
   sheet by hand.

3.1 adds all three as **grammar extensions only**. Nothing in the engine's
structure changes: each feature lands in a place that already exists — the
Format column parser, the expected-value derivation, and the code-list
resolver — and every existing spec, scenario, and test keeps working because
the new notation is strictly opt-in.

This is deliberately the first Phase 3 item: the roadmap held it until the
addressing/format grammar was final after Phases 1–2, so these are additive
tokens on a stable base.

## Decision 1: tolerances — a `tol:` token in the Format column

The Format column is already the `;`-separated home of `implied:N`,
`places:N`, and `len:MIN..MAX`. Add:

```
tol:0.01     # decimal comparisons pass when |actual - expected| <= 0.01
```

`FormatSpec` gains `tolerance: Decimal | None`. The only touched comparison is
the single `normalized != expected.value` line in the validator: when both
sides are `Decimal` and a tolerance is set, compare
`abs(normalized - expected) <= tolerance`. It is meaningful only for
`DataType.DECIMAL`; the loader flags `tol:` on a non-decimal row as a
NEEDS-REVIEW load note rather than silently ignoring it.

**Open question A (tolerance match semantics):** when a value matches *within*
the tolerance but isn't exact, I recommend **PASS with an informational note**
(`"within tol:0.01 (Δ0.004)"`) so the near-miss is visible in the report and
the audit trail — versus a silent PASS (loses the signal) or a WARNING
(too noisy for an expected rounding). Confirm PASS-with-note.

## Decision 2: date arithmetic — a `shift:` token in the Format column

Rather than overload the strict Source Field grammar (a single element ref
inbound, a canonical path outbound — parsed and shown in reports in many
places), the offset also lives in Format, next to the date pattern:

```
%Y-%m-%d; shift:+5d      # expected = source date + 5 days, rendered %Y-%m-%d
implied is n/a; shift:-30d
```

`FormatSpec` gains `shift_days: int | None`. In the expected-value derivation,
after the source DATE normalizes, the shift is applied to produce the expected
date; the actual output date is compared as usual. It is symmetric across
directions (inbound: X12 source date + offset; outbound: canonical source date
+ offset → expected X12 date) and is valid only on `DataType.DATE` rows —
`shift:` elsewhere is a load error.

**Open question B (units & placement):** I recommend supporting **days (`d`)
and weeks (`w`)** only — month arithmetic is genuinely ambiguous (calendar
lengths, end-of-month clamping) and a foot-gun in a validation tool — and
keeping the offset **in the Format column** (`shift:+5d`) rather than as an
inline Source Field expression (`DTM02 + 5d`), so the Source Field stays a
pure reference. Confirm Format-token + d/w, or ask for an inline expression /
month support.

## Decision 3: external lookup files — a `file:` Code List Ref

A `CODE_LIST` rule's **Code List Ref** normally names a list on the CodeLists
sheet. Extend it to accept:

```
file:item_xref.csv       # load the CSV as this rule's code list
```

Resolution happens **at spec load**, so the rest of the engine is unchanged —
the `file:` ref becomes an ordinary `CodeList` object keyed by the ref string,
and the existing membership check, translation, and "no entry →
`code_translation` finding" path all work as-is. A missing *file* is a
`SpecLoadError` (fail fast); a missing *entry* at validate time is the ordinary
code-translation defect. Files are loaded once and cached by resolved path for
the duration of the load, so a thousand-row xref referenced by many rows is
read once.

**Open question C (path base & CSV shape):** I recommend resolving the path
**relative to the spec file's directory** (portable — no absolute paths or
cwd assumptions baked into a shared spec) and a CSV shape of
**`source,target[,description]`** with an optional header row auto-skipped when
its first cell is the literal `source` (case-insensitive). Confirm, or ask for
cwd-relative / a strict named-column format.

## Decision 4: scope boundaries

* **No engine restructuring.** Two new Format tokens, one comparison tweak,
  one loader branch. The validator's control flow is untouched.
* **Backward compatible.** New notation is opt-in; `FormatSpec`'s new fields
  default to `None`. Every existing spec and the full suite stay green.
* **Out of scope (natural fast follows):** arbitrary expression language
  (multi-term math, cross-field references in expected values), currency-aware
  tolerances, remote (URL) lookup files, and month/business-day date math.

## Reference scenario

Extend the synthetic 850 (or a small dedicated spec) so one scenario exercises
all three:

* a **decimal** line-extension or total with `tol:0.01`, where the output is
  correctly rounded and passes within tolerance (and a defect variant just
  outside it fails as `value_mismatch`);
* a **date** rule `%Y-%m-%d; shift:+5d` deriving a promised date from an order
  date (defect variant off by a day);
* a **`file:` code list** — a small synthetic `uom_xref.csv` beside the spec —
  translating a source code, with a defect variant whose source value is absent
  from the file → `code_translation`.

Asserted: the clean output passes; each defect variant produces exactly its
one expected finding of the right category; the near-miss inside tolerance is a
PASS carrying the delta note.

## Test plan

1. `parse_format`: `tol:`, `shift:+5d`/`-30d`/`+2w` parse; unknown/negative-unit
   tokens raise `FormatSpecError`.
2. Tolerance: within → PASS+note; on the boundary → PASS; just outside → FAIL
   `value_mismatch`; `tol:` on a non-decimal row → load note.
3. Date shift: inbound and outbound; `+`/`-`; d and w; `shift:` on a
   non-date row → load error.
4. External lookup: relative-path load; caching (one read for many rows);
   header auto-skip; missing file → `SpecLoadError`; missing entry →
   `code_translation`.
5. Reference scenario: clean pass + each defect variant.
6. Full existing suite green — additive over the grammar.

## Open questions for review

1. **Tolerance semantics (Decision 1 / A):** within-tolerance match is
   PASS-with-note (recommended) vs silent PASS vs WARNING?
2. **Date arithmetic (Decision 2 / B):** `shift:+Nd` Format token, days+weeks
   only (recommended) vs inline `DTM02 + 5d` Source Field expression / add
   months?
3. **External lookups (Decision 3 / C):** path relative to the spec dir +
   `source,target[,description]` CSV with optional header (recommended) vs
   cwd-relative / strict named columns?
4. **Scenario shape (Reference scenario):** extend the existing 850 spec with
   the three new rules (recommended — reuses fixtures) vs a dedicated
   standalone ergonomics spec?
