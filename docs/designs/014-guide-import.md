# Design 014: Guide import (implementation guides as input)

**Status:** draft, for review before any code
**Roadmap item:** supersedes part of Design 012 Decision 4, and delivers the
first half of the ROADMAP Post-1.0 "partner-rule overlay" item
**Applies to:** CLI (`import-guide`, `draft-spec`), the engine's
required-elements layer, and the Draft spec page

## The reversal, stated plainly

Design 012 Decision 4 put PDF implementation-guide parsing in the "Never"
tier: "the human read of a PDF guide is the curation pass; automating it
badly would relocate errors, not remove them." That reasoning was right
about *arbitrary* PDFs and it stays right: free-form prose guides and
scanned images remain out, permanently.

What it missed is that most real guides are not arbitrary. They are
exports from a small family of spec-authoring tools, and that family
shares one templated layout: a segment header block (`BEG — Beginning
Segment for Purchase Order`, `Pos: 020`, `Max: 1`, `Heading - Mandatory`),
a `User Option (Usage)` line, an **Element Summary** table (`Ref / Id /
Element Name / Req / Type / Min/Max / Usage`), **Code List Summary**
blocks with the partner's code subset, and italic partner notes. That
layout is as parseable as a fixed-width wire format — and this tool's
whole thesis is that fixed-width wire formats deserve real parsers.

So the line moves, precisely: **parse the templated guide family;
everything else stays Never.** A file that doesn't match the family is a
clean load error naming what was expected — never a half-parse.

## The job, precisely

An implementation guide defines the **source side only**: which segments
and elements the partner uses, requiredness, their code subsets, their
notes. It contains no targets — the target half of every mapping still
comes from the crosswalk (Design 012). Guide import therefore does not
replace `draft-spec`; it feeds it:

```
guide (.pdf/.txt) -> parse -> GuideProfile (.yaml, reviewable)
    GuideProfile + crosswalk -> partner-flavored draft spec
    GuideProfile -> partner required-elements overlay -> validate
```

Two consumers, one parse. The first kills transcription for the analyst
building the map. The second closes the audit's headline finding: audit
file 4 (valid base X12 that violates a fictional companion guide)
finally fails — for the partner's reasons, on the partner's rules.

## Decision 1: scope — the templated family only

- **v1:** text-extractable PDF and plain-text guide exports in the
  SpecBuilder-family layout described above.
- **v1.5:** `.docx` exports of the same family.
- **Never (unchanged):** scanned/image PDFs (OCR relocates errors),
  free-form prose guides, and any file whose structure the detector
  cannot fingerprint.

Family detection is structural, not filename-based: the parser requires
the fingerprints (an Element Summary header, `Ref` tokens shaped like
`[A-Z]{2,3}\d{2}`, a `Pos:`/`Max:` header block) before it will emit
anything. Below the confidence bar, the error says which fingerprint was
missing.

## Decision 2: the parse lands in a GuideProfile, not a spec

Parsing straight into a spec would bury extraction decisions inside a
workbook. Instead the parser emits a **GuideProfile** — a YAML artifact
in the crosswalk ethos: inspectable, diffable, versionable, and the
single input to everything downstream.

```yaml
transaction: "850"
version: "004010"
partner: acme            # supplied by the user, never parsed
source: acme_850_guide.pdf
segments:
  - id: BEG
    pos: "020"
    usage: must_use      # from "Must use" / "Used" / "Not used"
    max: 1
    elements:
      - ref: BEG01
        name: Transaction Set Purpose Code
        req: M
        type: ID
        min: 2
        max: 2
        usage: must_use
        codes:
          - {code: "00", name: Original}
      - ref: BEG06
        name: Contract Number
        req: O
        usage: used
        notes: ["Insight Sales Order Number (Drop Ship Orders Only)"]
review:
  - "page 3: PO109 usage column unreadable after line wrap — verify by hand"
```

The **flag-never-guess contract** (Design 004) applies at parse time:
every fact the extractor is not certain of goes to `review`, with page
context — it never lands as data. Same guide in, same profile out,
deterministically.

## Decision 3: consumer one — the partner-flavored draft

`draft-spec` gains a guide input. With a profile present, the draft
changes in exactly four ways:

1. **Source walk narrows and annotates.** Elements the guide marks
   `not_used` leave the Unmapped Source sheet (they are not triage, the
   partner said no); guide notes flow into the draft's Notes column.
2. **Partner code subsets ride along.** Where the crosswalk rule is
   CODE_LIST and the guide carries a code subset, the draft's code list
   is filtered to the partner's codes. A guide code with no crosswalk
   translation becomes a review row — a real decision, surfaced.
3. **Requiredness shows.** A `must_use` element with no crosswalk hit is
   still a TODO row, now marked required-by-partner in Notes — the
   analyst sees which TODOs are load-bearing.
4. **Everything else is unchanged.** Targets, prefill, TODO parity,
   determinism — all exactly as Design 012 shipped them.

## Decision 4: consumer two — the partner required-elements overlay

The Phase 2 engine already enforces definition-driven required elements
(BEG03, PO102-when-PO103). The overlay reuses that tested mechanism with
partner data: `import-guide` emits a **partner overlay** file whose
`required_elements` entries match the transaction-definition schema
exactly, and `validate` gains `--partner-rules overlay.yaml`, which
appends those entries to the definition for the run.

Scope guard, honest: v1 enforcement covers **element and segment
presence** (`DTM*002 required`, `REF*IA required in the header`).
Qualifier-pair rules ("every PO1 must carry a UP pair") are not yet
expressible in the required-elements schema; they stay a named backlog
item rather than a silent gap. Code-subset enforcement needs no engine
work at all — the partner draft's filtered code lists already fail
out-of-subset values through the existing CODE_LIST path.

Rejected alternative: building a new companion-guide rule engine.
Presence and code subsets cover the audit's measured gap with machinery
that already has tests; a rule DSL can come when a real guide demands it.

## Decision 5: verbs and UI

```
mapcheck import-guide acme_850.pdf --transaction 850 --partner acme \
    --profile acme_850_profile.yaml [--overlay acme_rules.yaml]
mapcheck draft-spec --transaction 850 --target orders05 \
    --guide acme_850_profile.yaml --output draft_acme.xlsx
mapcheck validate --spec ... --source ... --output ... \
    --partner-rules acme_rules.yaml
```

`import-guide` parses and writes the profile (plus the overlay when asked
for); `draft-spec --guide` accepts a profile or a raw guide file. The
**Draft spec page** gains one optional upload ("Implementation guide,
.pdf or .txt") and a partner-name field; when present, the draft is
partner-flavored, the profile is downloadable, and parse-review entries
render in the existing worklist pattern. No new page, and no new CSS —
if the page needs a style that does not exist, that is a Design 013 gap
to report, not to patch.

## Dependency

PDF text extraction is a real new dependency. **pdfplumber** (layout-aware,
which the Element Summary columns need) ships as a `guides` extra —
`pip install "edi-mapcheck[guides]"` — so the core stays lean; the `.txt`
path works with no extra at all, and a missing extra is a clean error
naming the install command.

## Coverage metric

`parse coverage = facts extracted at full confidence / facts detected`,
printed by every `import-guide` run and stored in the profile. No target
number is invented here: the feasibility spike (below) measures it on
real material first, and the number goes in this doc's acceptance
criteria at review.

## Feasibility spike, before any merge

The parser is built against synthetic fixtures typed from the public
SpecBuilder-style layout (fictional data, committed as `.txt` plus one
small generated PDF). Before this design is marked accepted, the spike
runs against at least one **real** guide supplied by the maintainer
(manually redacted; Scrub does not handle PDFs) and the measured parse
coverage is recorded here. If the family assumption fails on real
material, this design stops and says so.

## Testing

- Golden GuideProfile for the synthetic guide fixture (parsed-content
  comparison, as with draft goldens).
- Flag-never-guess: fixtures with a wrapped usage column, an unknown code
  table, a missing Element Summary — each lands in `review`/errors, never
  in data.
- Partner-flavored draft golden: notes flow, code subsets filter,
  not-used elements leave triage, required-by-partner TODOs marked.
- **The audit closes its loop:** the answer key's fictional Acme Pharma
  companion guide (DTM*002 required, REF*IA required, UP pair per PO1)
  becomes a guide fixture; the emitted overlay makes audit file 4 FAIL on
  the two presence rules — asserted exactly — with the qualifier-pair rule
  asserted as the named backlog gap.
- Determinism and family-detection rejection tests.

## Open questions

1. Which real guide does the spike run against, and can a redacted copy
   live in the repo as a fixture (or must it stay local-only)?
2. Overlay file home: `examples/partner_specs/` beside the delta
   workbooks, or a new `examples/partner_rules/`?
3. Is `pdfplumber` acceptable as the extraction dependency (pure-Python
   alternatives are materially worse at column layout)?
4. Does the audit-kit README's file 4 section get updated to point at the
   overlay once it exists, or stay frozen as the historical answer key?
