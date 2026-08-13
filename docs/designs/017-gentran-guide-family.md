# Design 017: a second guide family — the tabular "Data Element Summary" layout

**Status:** Approved 2026-08-13 (open questions answered in review),
implementation in this PR.
**Applies to:** `src/mapcheck/guides/parser.py` (family dispatch + a second
line grammar); everything downstream is unchanged.
**Extends:** Design 014, which built the guide importer for one templated
family and named a second family as future work "if partner demand shows,"
and Design 015, whose per-occurrence dedup this family reuses as-is.

## Why now

Design 014 shipped a parser for the SpecBuilder-style family (Insight's
guide: `BEG … Pos: 020 Max: 1` headers, an `Element Summary` table,
`Must use`/`Used`/`Not used` wording). A real AmerisourceBergen 850 guide
supplied by the maintainer fails detection — cleanly, naming the missing
fingerprints, exactly as designed — because it is a **different authoring
family**: the tabular "Data Element Summary" layout that Gentran,
EDI-Notepad, and their descendants emit. This is one of the most common
guide formats in North American EDI (AmerisourceBergen, McKesson,
Cardinal, and much of pharma/distribution), so the demand Design 014
waited for has arrived.

## The layout, precisely (from the real guide)

A segment's detail page is a **keyed multi-line header** followed by a
**dual-attribute element table**:

```
BEG                                            <- bare segment id, its own line
Segment: Beginning Segment for Purchase Order  <- Segment: <partner's name>
Position: 020
Loop:                                          <- empty, or "N1 Mandatory"
Level: Heading                                 <- Heading | Detail | Summary
Usage: Mandatory                               <- Mandatory | Optional | Conditional
Max Use: 1
Purpose: ...
Syntax Notes: ...                              (optional)
Comments: ...                                  (optional)
Notes: Example: BEG|00|NE|008123456| |20120221~
Data Element Summary                           <- the table marker
Ref.  Data                     Base       User <- two-line column header
Des.  Element  Name            Attributes Attributes
BEG01 353 Transaction Set Purpose Code M ID 2/2 M
Code identifying purpose of transaction set    <- X12 description (skipped)
00 Original                                    <- code subset, bare-indented
BEG02 92 Purchase Order Type Code M ID 2/2 M
Code specifying the type of Purchase Order
DS Dropship
NE New Order
...
```

Element row grammar: `REF Num Name  BaseReq BaseType Min/Max  [UserReq]`

```
BEG01 353 Transaction Set Purpose Code M ID 2/2 M     <- user req present (M)
REF02 127 Reference Identification      C AN 1/30       <- user req absent
```

Front matter (pages 1-2) is a summary **index table**
(`Page Pos Seg Name Base-Guide User-Status Max.Use Repeat`, with
`LOOP ID - N1 200` lines). It restates per-segment usage but carries no
elements, codes, or notes.

## Decision 1: two grammars, one profile, a sniffing dispatcher

`parse_guide(path, transaction, partner)` becomes a **dispatcher**: it
extracts lines once (the existing `extract_lines`, unchanged — text PDF /
`.txt`, pdfplumber `dedupe_chars`), fingerprints the content against each
known family, and delegates to that family's line-grammar parser. Both
parsers build the **same `GuideProfile`**, so *everything downstream is
untouched* — `profile.py`, `overlay.py`, `emit_partner_rules`, the draft
integration, the CLI verbs, the UI. That is the whole elegance of the
Design 014 architecture paying off: a new family is a new front-end, not
a new pipeline.

Detection is explicit and mutually exclusive:

- **Family A (SpecBuilder, Design 014):** a `Pos:/Max:` segment header (one-
  line or split) **and** an `Element Summary` marker.
- **Family B (this design):** a `Data Element Summary` marker **and** the
  `Segment:` / `Position:` / `Usage:` keyed header lines.

A file matching neither is rejected as today, now naming **both**
families' fingerprints so the message tells the user what shapes are in
scope. A file matching both (it won't in practice) is a defined error, not
a coin flip. The family that matched is recorded on the profile
(`GuideProfile.family`) and printed by `import-guide` — the user always
knows which grammar read their guide.

## Decision 2: usage — User attribute, falling back to Base (confirmed)

The dual columns are **Base Attributes** (the X12 standard requiredness)
and **User Attributes** (this partner's overrides). Per the maintainer's
domain guidance: *the User column overrides only when present; a blank
User attribute means "no partner-specific override — use the base / X12
default."* So the requiredness of every element is:

```
effective = user_req if user_req present else base_req
must_use  if effective == M
used      if effective in (O, C, X)
```

Consequently this family rarely yields `not_used` from the detail pages —
partners express "don't send this" by omitting the element from the
Data Element Summary, not by blanking a column. `not_used` still arises
only if a summary/detail explicitly says so. The segment's own usage comes
from its `Usage:` line the same way (`Mandatory` → must_use, etc.).

This rule matters for the overlay: a `must_use` REF\*IA still emits the
Design 015 scoped element/pair rules; a segment whose base is `M` but is
never populated is simply a required segment. Nothing in `emit_partner_
rules` changes — it already reads normalized `must_use`/`used`/`not_used`.

## Decision 3: code subsets, with name-wrapping

Codes appear as **bare indented `<code> <name>` lines** under ID-type
elements — no `Code List Summary` header. Two honest parsing rules:

1. Only elements whose **type is `ID`** carry a code list; under any
   other type, an indented line is description prose, never a code. This
   is the reliable discriminator this layout gives us.
2. A long code **name wraps** onto following lines
   (`N1 National Drug Code in 4-4-2` then `Format`). A line that does not
   begin with a fresh `<code>` token is appended to the open code's name.
   A line that is ambiguous (could be a code or a continuation) goes to
   `review` with page context — flag-never-guess, unchanged.

The first line after an element row is always the standard X12
description; it is skipped (as the SpecBuilder grammar skips
`Description:`), never stored as a code.

## Decision 4: partner-flavored names are kept

This guide labels segments with the partner's own names — `N1 ABC
Division Name`, `N1 Ship-To Name`, `PO104 … Net Invoice Cost`. Those are
the partner's language and are exactly what makes a partner-flavored draft
useful, so the `Segment:` name and element names are stored verbatim.
Segments recur once per qualifier as separate detail pages (three REF
pages for RQ / 0B / CO, three N1 divisions) — the same per-occurrence
shape Insight had, and Design 015's per-qualifier dedup already handles
it without change.

## Decision 5: the summary index table is parsed and cross-checked

Segment usage is taken from each detail page's `Usage:` line — the
detail pages are the richer, authoritative source (they carry the
elements, codes, and notes). But the front index table is not discarded:
its rows (`page pos seg name base [user] maxuse`) are parsed with the
same User-falls-back-to-Base rule, and after the detail pages are read
the two views are **cross-checked**. Disagreements become review facts
with page context, surfaced at import time:

- an index row with no matching detail page (or the reverse);
- an occurrence-count mismatch for a (segment, position) that repeats
  per qualifier (three REF rows at 050 but only two detail pages);
- an effective-usage disagreement (index says Mandatory, the detail
  page says Optional).

Per the maintainer: catching these up front answers questions before a
mapping session, not during one. A guide with no index at all (some
exports omit it) skips the cross-check silently — absence of the table
is a layout variant, not a defect.

## Scope guard

No engine changes; no `GuideProfile` schema change beyond an additive,
optional `family` label; no change to overlay emission, draft integration,
CLI verbs, or UI. The two remaining Design 015 caveats (loop-scoped
placement, multi-code qualifiers) are unchanged and still honest. Scanned
/ image PDFs and free-form guides stay out of scope for both families. A
third family, if one ever shows up, slots in behind the same dispatcher.

## Real-guide spike — run and measured (2026-08-13)

Against the maintainer's real AmerisourceBergen 850 guide (25 pages; the
PDF is not committed — the repo stays vendor-neutral): **parse coverage
1.0000 — 101/101 facts.** All 20 segment blocks, 61 elements, the
per-qualifier REF/N1/PID occurrences, and the code subsets including
PO106's page-spanning list all extract into the profile. Six review
entries, all correct behavior:

- Four flags on the appendix sample-EDI pages ("SAMPLE DATA", raw
  segment strings) — code-shaped lines under a non-ID element, refused
  as data and named for a human, exactly per flag-never-guess.
- **Two cross-check findings that caught a real editing defect in the
  published guide itself:** the front index lists ITD at position 030
  while ITD's detail page says position 120. This is the
  "questions up front, not during mapping sessions" value the
  cross-check was approved for, demonstrated on its first real run.

Page furniture (the running letterhead on all 25 pages, the dated
footers) is stripped before parsing and produced zero fake codes.

## Testing

- **Family routing:** a Family-A fixture parses via grammar A, a Family-B
  fixture via grammar B, a non-guide is rejected naming both families'
  fingerprints, and each parser records the right `family` on the profile.
- **Golden Family-B profile:** a new synthetic, vendor-neutral fixture in
  the Gentran layout (fictional data, committed as `.txt` plus a generated
  PDF twin), parsed-content comparison as with the Design 014 golden.
- **Usage fallback:** elements with present vs absent User attributes map
  to the confirmed effective requiredness; a blank User under base `M`
  is `must_use`, under base `O`/`C` is `used`.
- **Code subsets:** bare-indented codes attach to their ID element;
  wrapped code names reassemble; a code under a non-ID element or an
  ambiguous line lands in `review`, never in data.
- **Downstream unchanged:** `emit_partner_rules` on a Family-B profile
  yields the same rule shapes (scoped elements, pairs) as Family A; a
  guided draft flows partner names and code subsets; determinism holds.
- **Real-guide spike:** run the parser against the maintainer's real
  AmerisourceBergen guide locally, record the measured parse coverage
  here, and commit only the synthetic fixture (repo stays vendor-neutral).

## Open questions — answered (2026-08-13)

1. **Fixture partner name:** a second fictional name, so the two family
   fixtures are visibly distinct. The Family-B fixture partner is
   **Bluewater Medical** (initialism "BMD" in its partner-flavored
   segment names, mirroring how the real guide brands its N1s).
2. **`family` surfaced in the UI?** Not necessary — the `import-guide`
   CLI line is enough. The Draft-spec caption stays as it is.
3. **Index-table cross-check:** in scope for v1 — "it would help with
   questions up front, not during mapping sessions." Decision 5 above
   was updated from "future enhancement" to the shipped behavior.
