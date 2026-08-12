# MapCheck Audit Kit

Five synthetic X12 850 files (version 004010, `*` element separator, `~` segment terminator, `>` component separator, newline after each segment for readability). **All data is fictional.** Zero Cardinal or real trading partner content. Safe to commit to the public repo as official test fixtures.

**Purpose:** you know every defect in these files. Run MapCheck against each one, record what it actually reports, and compare against this answer key and against the README's claims. The gap list is your roadmap.

---

## File 1: `850_01_clean.edi`

Fully valid. Correct SE count (15), matching control numbers end to end, valid codes, valid UPC check digits, CTT hash matches line quantities.

**Expected result: passes everything.**

If MapCheck flags anything here, that is Finding #1 and it is a bug in the tool, not the file.

---

## File 2: `850_02_structural_errors.edi`

Four seeded envelope/structural defects:

1. **SE01 = 9**, actual segment count ST through SE is **11**
2. **SE02 = 0002**, does not match **ST02 = 0001**
3. **GE01 = 2**, but the group contains only **1** transaction set
4. **IEA02 = 000000999**, does not match **ISA13 = 000000102**

**Expected result: all four flagged.** These are the bread-and-butter checks. If any slip through, the structural layer is weaker than the README claims.

---

## File 3: `850_03_semantic_errors.edi`

Structurally perfect (counts and control numbers all reconcile). Six seeded content defects:

1. **BEG01 = ZZ**, not a valid transaction set purpose code
2. **BEG03 empty**, PO number is mandatory
3. **BEG05 = 20261415**, month 14 does not exist
4. **N402 = XX**, invalid state code
5. **PO103 = XX** on line 1, invalid unit of measure
6. **PO102 empty** on line 2, quantity missing while UOM is present

**Expected result:** this is the layer that separates a real validator from a segment counter. A tool that only checks structure passes this file completely. Whatever it catches here defines what "validation" actually means in your README.

---

## File 4: `850_04_partner_rules.edi`

**100% valid base X12.** No structural or semantic defects at all.

It violates a fictional companion guide. Pretend Acme Pharma's 850 spec says:

- `DTM*002` (requested delivery date) is **required**
- `REF*IA` (internal vendor number) is **required** in the header
- Every `PO1` **must** carry a `UP` (UPC) qualifier pair

This file omits all three.

**Expected result, base run:** MapCheck passes it, because base-standard validation cannot see companion guide rules. The gap between "valid X12" and "valid for this partner" is the entire reason EDI analysts exist.

**Expected result, with partner rules (Design 014):** the fictional guide above exists as a synthetic fixture (`tests/fixtures/guides/acme_pharma_850_guide.txt`); `import-guide --overlay` derives a partner-rules overlay from it, and `validate --partner-rules` then FAILs this file on all three seeded defects — missing `DTM*002`, missing `REF*IA`, and empty `PO108`/`PO109` on both lines (the UP pair, enforced positionally; a true qualifier-*pair* rule is still backlog). Both halves are pinned by `tests/test_audit_kit.py::TestFile4PartnerRules`.

---

## File 5: `850_05_truncated.edi`

Dies mid-element in the first PO1. No PID, CTT, SE, GE, or IEA. No trailing terminator. This is what a dropped AS2 or SFTP transfer looks like in the wild.

**Expected result: graceful failure with a useful message** ("interchange truncated, missing SE/GE/IEA"). An unhandled Python stack trace here means the tool has never met a real-world file. That is a fix worth making before anyone else sees the repo.

---

## The Audit Procedure

- [ ] Run File 1. Confirm clean pass.
- [ ] Run File 2. Record findings. Compare to the four seeded defects.
- [ ] Run File 3. Record findings. Compare to the six seeded defects.
- [ ] Run File 4. Confirm it passes bare, and FAILs with `--partner-rules`.
- [ ] Run File 5. Record whether failure is graceful or a stack trace.
- [ ] Write the gap list: everything missed, everything falsely flagged, everything the README claims that the tool did not do.

That gap list becomes two things: the honest scope statement for the README, and the backlog. Closing it is what makes the scope claims true.

## Robustness Follow-Ups (later, optional)

- **Wire format:** strip all newlines from File 1 (one continuous stream) and re-run. Real files arrive both ways.
- **Alternate delimiters:** swap `*` for `|` and `~` for `'`. Delimiters are declared in the ISA, a real parser reads them from position, not assumption.
- **5010 variant:** same files with ISA12 = 00501, GS08 = 005010.
- **Encoding:** add a UTF-8 BOM to the front of File 1 and see if the parser chokes.
