# Design 012: Draft Spec (definition-driven spec generation)

**Status:** draft (approved in principle 2026-08-10; GUI requirement folded
into Design 013)
**Roadmap item:** proposed (new), pending triage into ROADMAP.md

## The job, precisely

Authoring a mapping spec is two activities fused together: **transcription**
(walking the guideline and the target schema line by line, writing down the
obvious) and **judgment** (knowing that BEG03 lands in E1EDK02 qualifier 001,
that EA must become ST, which DTM qualifiers a partner actually uses).
Transcription is mechanical and slow. Judgment is the analyst's job.

`draft-spec` kills the transcription and preserves the judgment. It emits a
**spec** (the rules document an analyst sends to whoever builds the map),
never a map. The draft is a starting point that flows directly into
`validate` after human curation.

```
definitions in -> structural walk + crosswalk + TODOs -> draft .xlsx
    -> analyst curates -> rules to the mapper -> mapper builds
    -> validate -> bless -> regress
```

## Decision 1: same repo, one new verb

```
mapcheck draft-spec --transaction 850 --target orders05 \
    --output draft_850_orders05.xlsx [--crosswalk FILE]... [--fill-unmapped]
```

Both structure sources already live here: the X12 side in
`transactions/definitions/*.yaml`, the target side in
`output/definitions/*.yaml`. The spec writer exists (`spec/template.py`).
The verb joins the existing spec family (`init-spec`, `import-spec`,
`merge-spec`).

Rejected alternative: a separate repository. It would import this entire
package and split the story of one lifecycle tool into two half-tools.

## Decision 2: three-layer generation

**Layer 1, structural walk (deterministic code).** Enumerate source elements
with loop context from the transaction definition; enumerate target paths
from the output definition. This produces the two sides of the worksheet and
nothing else.

**Layer 2, canonical crosswalk (curated data, the crown jewel).** A
maintainer-authored YAML file of known pairings, applied automatically:

```yaml
- source: BEG03
  target: refs.001.belnr
  rule: DIRECT
  note: E1EDK02 QUALF 001, customer PO number
- source: BEG05
  target: refs.001.datum
  rule: DIRECT
  format: "%Y%m%d"
- source: PO103
  target: lines[].menee
  rule: CODE_LIST
  code_list: UOM_SAP
- source: N1[ST]
  target: partners.WE
  rule: DIRECT
  note: ship-to party
```

Fields: `source`, `target`, `rule`, then optionally `code_list`,
`condition` / `then` / `else`, `format`, `note`. Entries are validated
against the spec schema at load; a malformed crosswalk is a load error, not
a silent skip. Crosswalks are data, not code: reviewable in a diff,
extensible by users via repeated `--crosswalk` flags (later files win).

**Layer 3, TODO emission (honesty about gaps).** Every required target path
with no crosswalk hit becomes a row with Rule Type `TODO`. The spec loader
treats `TODO` exactly as Design 001 treats BLANK: the row loads as
NOT TESTED with a load warning, so an uncurated draft can never
silently pass validation. Source elements no rule references are listed on
an **Unmapped Source** sheet for human triage.

## Decision 3: determinism first, assistance optional

The default run is fully deterministic: same definitions plus same
crosswalks produce byte-identical drafts. A later `--assist` mode (CLI flag,
UI toggle) may propose candidates for TODO rows; proposals are always
labeled `SUGGESTED`, never auto-accepted, and the mode is off by default.

Rationale: a wrong silent guess inside a spec is strictly worse than an
honest TODO, and CI (Design 008) needs reproducible output.

## Decision 4: input tiers, scoped honestly

- **v1:** built-in definitions on both sides only. No file parsing at all.
- **v1.5:** machine-readable guidelines (.xlsx/.csv through the existing
  import plumbing); SEF import investigated.
- **Never:** PDF implementation-guide parsing. The human read of a PDF
  guide is the curation pass; automating it badly would relocate errors,
  not remove them.

Partner deviations stay where Design 005 put them: delta files merged with
`merge-spec`. `draft-spec` never learns partner rules.

## Coverage metric

`prefill = filled required rows / total required rows`, printed at the end
of every run and stored in the draft's Meta sheet. Target: >= 0.70 for
850 -> ORDERS05 with the shipped starter crosswalk.

## UI (per Design 013)

A **Draft Spec** page: two selects populated from the registries
(Transaction, Target format), one "Draft spec" action, a preview table
(crosswalk-filled rows vs. amber TODO rows), the prefill metric, and
"Download draft (.xlsx)". No uploads in v1, which makes it the lowest-
friction demonstration in the app.

## Testing

- Golden drafts for 850->orders05, 856->desadv01, 810->invoic02.
- Crosswalk schema violations produce load errors with row context.
- Round trip: draft, complete the TODOs from the reference spec, run the
  baseline scenario, expect PASS.
- Loader treats `TODO` rows as NOT TESTED with a warning (Design 001
  parity).

## Open questions

1. Crosswalk packaging: one file per (transaction, target) pair under
   `src/mapcheck/crosswalks/` (recommended) vs. one monolith.
2. Does `confidence` belong in the crosswalk schema now, or only when
   `--assist` lands?
3. EDIFACT source side: worth a definition family later?
