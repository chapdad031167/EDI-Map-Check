# Audit gap list

Phase 1 audit of MapCheck 1.0.0 (pyx12 4.0.0) against the five-file audit kit
in `tests/fixtures/audit_kit/` and its answer-key README.

## Method

MapCheck has no source-only mode: every run validates a (spec, source,
output) triple. Each fixture was therefore run as
`mapcheck validate --spec <audit spec> --source <fixture> --output <faithful
output> --no-history --no-color` with:

- **Audit spec** — the bundled 850 reference spec's 32 rules plus seven
  fixture-family coverage rows, so that spec-coverage warnings cannot
  contaminate the measurement. Deltas vs. `examples/specs/850_reference_spec.xlsx`:
  - `M-026` re-pointed: UPC read from `PO109` when `PO108 = 'UP'` (the audit
    fixtures carry VN at PO106/07 and UP at PO108/09; the reference files
    carry UP at PO106/07).
  - Added `A-101` `lines[].vendor_part` ← PO107 when `PO106 = 'VN'`;
    `A-102`–`A-104` contact ← PER01/PER02/PER04 (phone when `PER03 = 'TE'`);
    `A-105`/`A-106` buyer ← N102/N104 in `N1[BY]`; `A-107`
    `summary.total_units` ← CTT02.
- **Faithful output** — exactly what a correct translator produces from that
  source under the audit spec; defective source values copied through raw
  (the repo's existing "naive translator" convention), empty sources
  omitted. Any finding therefore reflects the tool's view of the *source*.

Harness files (spec generator + four outputs) were session-local for this
phase; Phase 2 committed the harness as the permanent regression suite in
`tests/test_audit_kit.py` (spec rows, faithful outputs, and exact expected
finding sets, inline and reviewable).

## Per-file findings record

### File 1 — `850_01_clean.edi`

**RESULT: PASS** — 40 PASS / 0 FAIL / 0 WARNING / 6 NOT TESTED, exit 0.
No false positives; **no tool fixes were needed**. The six NOT TESTED rows
are spec rules for optional segments genuinely absent from the file
(`REF[IA]`, `DTM[001]`, `SAC[A]` ×2, `N1[BT]`, `AMT[TT]`) — correct
behavior, not flags. pyx12 emitted zero control notes.

### File 2 — `850_02_structural_errors.edi`

**RESULT: WARNING** — 30 PASS / 0 FAIL / 4 WARNING / 9 NOT TESTED, exit 0.

| Seeded defect | Caught | Exact message emitted |
|---|---|---|
| 1. SE01 = 9, actual ST–SE count 11 | **yes** (WARNING, `control`) | `interchange control: SE count of 9 for SE02=0002 is wrong. I count 11` |
| 2. SE02 = 0002 ≠ ST02 = 0001 | **yes** (WARNING, `control`) | `interchange control: SE id=0002 does not match ST id=0001` |
| 3. GE01 = 2, group contains 1 | **yes** (WARNING, `control`) | `interchange control: GE count of 2 for GE02=102 is wrong. I count 1` |
| 4. IEA02 = 000000999 ≠ ISA13 = 000000102 | **yes** (WARNING, `control`) | `interchange control: IEA id=000000999 does not match ISA id=000000102` |

All four caught, 4/4. Note the severity: they surface as WARNINGs (as the
README says), so the run's overall result is WARNING and the exit code is
0 — a structurally broken envelope does not fail a `validate` run. `--strict`
(promote WARNING to failure) exists only in `batch` mode.

### File 3 — `850_03_semantic_errors.edi`

**RESULT: FAIL** — 32 PASS / 3 FAIL / 0 WARNING / 11 NOT TESTED, exit 1.

| Seeded defect | Caught | Exact message emitted |
|---|---|---|
| 1. BEG01 = ZZ (invalid purpose code) | **yes** (FAIL, `source_data`) | `source data invalid: source value 'ZZ' has no entry in code list TX_PURPOSE (valid: 00, 01, 05)` |
| 2. BEG03 empty (PO number mandatory) | **no** — NOT TESTED | `source element BEG03 is empty` |
| 3. BEG05 = 20261415 (month 14) | **yes** (FAIL, `source_data`) | `source data invalid: BEG05 '20261415' is not a valid X12 date (CCYYMMDD or YYMMDD)` |
| 4. N402 = XX (invalid state code) | **no** — PASS | (none — `XX` satisfies the rule's only constraint, `len:2..2`; no state-code validation exists) |
| 5. PO103 = XX (invalid UOM) | **yes** (FAIL, `source_data`) | `source data invalid: source value 'XX' has no entry in code list UOM (valid: CA, DZ, EA)` |
| 6. PO102 empty while PO103 present | **no** — NOT TESTED | `source element PO102 is empty` |

3 of 6 caught. The three catches are all spec-driven (code lists, date
format). The three misses share one root cause: neither the spec model nor
the transaction definitions can express that an element is *required*, so an
empty mandatory element degrades to NOT TESTED and an invalid-but-well-formed
value with no code list passes.

### File 4 — `850_04_partner_rules.edi`

**RESULT: PASS** — 39 PASS / 0 FAIL / 0 WARNING / 7 NOT TESTED, exit 0.

Passes, exactly as the answer key predicts for valid base X12. The three
fictional companion-guide requirements it violates surface only as neutral
non-findings: missing `DTM*002` and `REF*IA` → NOT TESTED, missing `UP`
qualifier pairs → conditional rules silently (and correctly) SKIP.

**Scope finding, not a bug:** base-standard validation cannot see
companion-guide rules. At audit time the gap was structural: required-ness
did not exist in the spec model, so even a partner delta merged with
`merge-spec` (Design 005) could change *mappings* but not enforce
*presence*. Design 014 closed the presence half: `import-guide --overlay`
derives partner rules from an implementation guide and
`validate --partner-rules` FAILs this file on all three seeded defects
(pinned in `TestFile4PartnerRules`). Qualifier-*pair* rules ("the UP pair
may arrive in either qualifier slot") remain backlog — today's enforcement
of PO108/PO109 is positional.

### File 5 — `850_05_truncated.edi`

**Failure is graceful in both entry points. No stack trace.**

- CLI: `mapcheck: tests/fixtures/audit_kit/850_05_truncated.edi: transaction
  is not terminated by an SE segment`, exit 2.
- UI (`app.py`): the same `X12ParseError` is caught and rendered via
  `st.error` ("Could not run validation: …").

Parser-level detail (matters for the Phase 2 fix): pyx12 tokenizes through
the last *terminated* segment (`N4`), **silently drops** the unterminated
partial trailer (`PO1*1*24*EA*18.75**VN*SAF-0`), and emits zero control
notes about the missing SE/GE/IEA. The graceful message comes from
MapCheck's own open-ST check in `parse_interchange`. So today: no
"truncated" wording, no naming of the last complete segment, no mention of
the missing GE/IEA, and the swallowed partial segment is invisible. That is
the Phase 2 P0.

## Missed defects

| # | Defect (file 3) | Today | Recommendation | Reasoning |
|---|---|---|---|---|
| 1 | BEG03 empty — mandatory PO number | NOT TESTED | **Implement in Phase 2** | Base-standard element required-ness is spec-independent and belongs in the transaction definition; one mechanism closes both this and #3. |
| 2 | N402 = XX — invalid state code | PASS | **Backlog** | Needs a jurisdiction code table — geography/partner data, not engine logic; already catchable today by spec authors via a `CODE_LIST` rule, which is the pattern to document. |
| 3 | PO102 empty while PO103 present | NOT TESTED | **Implement in Phase 2** | X12 850 syntax note C0302 (if PO103 then PO102) is a definition-level relational condition; same mechanism as #1 with a `when` clause. |

File 2 missed nothing (4/4 caught).

## False flags

None. File 1 produced zero FAIL and zero WARNING findings, so no
false-positive fixes were made (Phase 1 step 1 permitted them; none were
needed).

## README overclaims

None found within the measured scope. Specifically verified as accurate:

- "Interchange-level control problems (SE counts, control numbers) surface
  as warnings via pyx12" — measured exactly (file 2, 4/4, all WARNINGs).
- The "What it checks" categories 1–7 all demonstrated on files 1–4 (value
  accuracy, conditional logic, code lists, constants, date/format, loop
  counts, unmapped sweeps).
- No claim is made of state-code validation, element required-ness, check
  digits, or companion-guide enforcement — and none exists.

Accuracy notes to fold into the Phase 2 README rewrite (implicit-scope
clarifications, not falsehoods):

1. Control warnings leave exit code 0 in `validate`: a file with a broken
   envelope still "passes" for CI purposes unless `batch --strict` is used.
   Say so explicitly.
2. No source-only mode exists: MapCheck audits a translation, not a bare
   X12 file. (This audit had to construct a spec + faithful output per
   fixture to measure the tool. A future `audit`-style verb that runs
   envelope + definition + required-ness checks on a lone `.edi` is a
   natural roadmap candidate.)
3. The partner-rule gap (file 4) should be stated as an explicit roadmap
   item: "valid X12" ≠ "valid for this partner", and today required-ness
   cannot be expressed even in a partner delta. *(Since closed for
   presence rules by Design 014 — see the file 4 section above.)*
4. UPC check digits are not validated (file 1's are valid, so nothing was
   missed; scope note only).
