# Design 019: a third guide family — the "EDI Specifications User Guide" layout

**Status:** Approved 2026-08-13 ("proceed with all above"), implementation
in this PR.
**Applies to:** `src/mapcheck/guides/parser.py` (a third family behind the
existing dispatcher); everything downstream is unchanged.
**Extends:** Designs 014 (family one) and 017 (family two + the
dispatcher). This is the third and, on the material seen so far, last
common family.

## Why

The Design 014 spike rejected a real Arnecom 850 guide as a different
authoring family and named it as still-unsupported. With families one and
two shipped, this closes the third. Its shape (`Segment BEG – name`
headers, `Level` / `Max. Use` prose, a `Data Segment Sequence` index, and
element rows with no element number) is the classic terse
"EDI Specifications User Guide" layout many mid-market vendors emit.

## The layout, precisely (from the real guide)

The guide has **two complementary regions**, and — unlike family two,
where the index merely restates the detail — here they carry *different*
facts that must be **joined**:

**1. Front `Data Segment Sequence` tables** give segment-level usage and
loop:

```
Data Segment Sequence for Heading Area
Seg. Name Usage Max. Loop
ID Use Repeat
ST Transaction Set Header M 1
BEG Beginning Segment for Purchase Order M 1
N1 Name O 1 N1 / 3
```

Row grammar: `SEG  name…  U  maxuse  [loop / repeat]`, where `U` is the
X12 usage letter (`M`/`O`/`C`; a `Not used` segment is simply absent).
The loop column reads `N1 / 3` (loop id N1). A glossary page defines the
letters (`M` Mandatory, `O` Optional, `C` Conditional, `N` Not used).

**2. Detail pages** give elements, requiredness, and codes:

```
Segment N1 - Name
Level Heading
Max. Use 3
Purpose To identify a party …
Comments …
Example N1*BY*BUYER NAME*92*CC
ID ELEMENT NAME FEATURES COMMENTS
N101 Entity Identifier Code M ID 2/3 Code identifying …:
"BY" = Buying Party ( Purchaser )
"SU" = Supplier / Manufacturer
N102 Name C AN 1/60
N103 Identification Code Qualifier C ID 1/2 "92" = Assigned by Buyer
```

Element row grammar: `REF  name…  REQ  [TYPE  MIN/MAX]  comments…` — **no
element number**, a **single** requiredness letter (the guide *is* the
partner's spec, so there is one effective requiredness: `M`/`O`/`C`/`X`,
and `N` = not used, where `TYPE MIN/MAX` may be absent). This is the same
M/O/C/N/X mapping the maintainer already gave for family two's base
column: `M` → must_use, `O`/`C`/`X` → used, `N` → not_used.

## Decision 1: a two-pass parse joined by segment id

Family one and two read everything from the detail pages. Family three
must **join** the front index (segment usage + loop) to the detail pages
(elements + codes) by segment id. The parser runs two passes over the
extracted lines: the `Data Segment Sequence` rows populate
``{seg_id: usage}`` and ``{seg_id: loop}`` maps; the detail pages build
the segments; usage/loop is filled from the maps. A detail segment
**absent from the index** is a review fact — its usage is unknown, a real
gap. The reverse (an index row with no detail page) is *not* flagged:
envelope segments (ST/SE) and unused optional segments routinely appear
in the index without a detail page, so flagging them would fill the
review list with benign noise. Only detail-page segments become profile
segments; the index exists to supply their usage and loop.

## Decision 2: codes are freeform, extracted conservatively

Codes are not a clean table. They live inside the FEATURES/COMMENTS prose
as quoted tokens with a separator, sometimes two to a line:

```
"BY" = Buying Party ( Purchaser )
"EA" – Each "MR" – Meter
00 = Original
```

Extraction rule: under an **ID-type** element (the same discriminator
families one and two use), a `"CODE"`/`CODE` token followed by `=`, `–`
(en-dash), or `-` and a name is a code; several may appear on one line.
The first prose line under an element that carries no code token is the
X12 description and is skipped. A line that looks code-ish but does not
cleanly parse is a **review** fact, never data. This is honestly lossier
than the other two families' clean code tables, so the spike measures it
and the number is recorded here; segments, elements, and requiredness
parse regardless, and the overlay simply emits fewer *qualified* rules
when a qualifier's codes did not extract.

## Decision 3: detail metadata that is prose, not facts

`Purpose`, `Comments`, and `Example(s)` are keyed prose. `Comments`
becomes a partner note (with any inline `Example` / raw-EDI sample line
filtered, as family two does); `Purpose` is skipped (standard-text);
`Example` lines are dropped. The `Level` and `Max. Use` lines populate
the segment's area/max; `Max. Use` and the index's max agree by
construction and are not cross-checked (one number, two prints).

## Decision 4: it slots behind the same dispatcher

`parse_guide` gains a third fingerprint set — a `Data Segment Sequence`
table, `Segment X – name` headers, and `ID ELEMENT NAME` element tables —
and a third `family` label (``terse``). Detection stays mutually
exclusive; a file matching more than one family is still the defined
error. Everything downstream (`GuideProfile`, overlay emission, drafts,
CLI, UI) is unchanged — the third family is a third front-end, exactly as
Design 017 set up.

Composition with Design 018 (separate PR): Arnecom's N1 lists several
N101 codes on one page, so once both land the overlay emits an
``N1 qualifiers={BY,SU,ST,…}`` set rather than an unqualified rule — the
two features meet with no extra work here.

## Scope guard

No engine changes; no `GuideProfile` schema change (the ``terse`` label
uses the existing `family` field). The lossy code extraction is the one
honest capability gap and it is measured, not hidden. A fourth family, if
one ever appears, slots in the same way. Scanned/image PDFs stay out.

## Testing

- Family routing: the family-three fixture parses via the new grammar
  and records ``family == "terse"``; families one and two still route to
  their own grammars; rejection names all three families' fingerprints.
- Golden family-three profile: a synthetic, vendor-neutral fixture in the
  terse layout (fictional data, `.txt` + generated PDF twin, parsed-
  content parity).
- The two-pass join: segment usage/loop taken from the index, elements
  from the detail; an index/detail mismatch is a review fact.
- Requiredness mapping incl. `N` → not_used and the missing-`TYPE MIN/MAX`
  row; freeform code extraction incl. two-codes-on-one-line and the
  quote/dash variants; an unparseable code-ish line → review.
- Real-guide spike: parse the maintainer's Arnecom guide locally, record
  the measured parse coverage (segments/elements vs codes) here; commit
  only the synthetic fixture.

## Real-guide spike — run and measured (2026-08-13)

Against the maintainer's real Arnecom 850 guide (18 pages; the PDF is not
committed — the repo stays vendor-neutral): **parse coverage 1.0000 —
83/83 facts, 16 segments, 51 elements, 39 codes, zero review.** The
freeform code extraction the design worried about performed far better
than feared: it correctly pulled multi-code-per-line lists (FOB01 →
CC/PP/PC/TP/ZZ, PO103 → EA/MR/KG/LT/PC/ZZ, N101 → BY/SU/ST), handled the
quote-and-both-dash variants, and produced **no** false codes from prose
sentences (`If N101 = "BY" this will be…` did not leak a code, because
the code-line gate requires the line to *start* with a code token). The
two-pass join filled every detail segment's usage and loop from the
front index. On this material the lossy-codes risk did not materialize;
the honest gate and the ID-type discriminator held it clean.

## Open questions — none

The requiredness mapping and the lossy-codes tradeoff were settled by
prior maintainer guidance and the flag-never-guess contract; the spike
(above) measured the result at full coverage.
