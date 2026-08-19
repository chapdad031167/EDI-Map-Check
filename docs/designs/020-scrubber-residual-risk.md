# Design 020: the scrubber tells you what it did *not* mask

**Status:** Draft, for sign-off. No implementation until approved.
**Applies to:** `src/mapcheck/scrub/` (profile model, scrubber, report),
`src/mapcheck/scrub/profiles/pharma.yaml`, `mapcheck scrub` and the UI's
Scrub page.
**Extends:** Design 009 (the scrubber itself), which this revisits after
the audit.

## Why

Design 009 built the scrubber as an **allow-list**: a profile names
`(segment, element)` positions and those get masked. Everything else is
passed through untouched. For a tool whose whole job is letting someone
hand a real EDI file to a third party, that default is backwards — an
element nobody thought of is an element that ships in the clear, and the
tool says nothing.

This is not hypothetical. Scrubbing **this repo's own shipped PII
example** with the **shipped default profile** leaves real identifiers in
the output. Measured, `mapcheck scrub examples/source/850_pii.edi --seed
demo --report`:

```
N4*BOULDER*CO*80301   ->  N4*MLGNYCV*CO*80301
```

The city is masked. The **state and the 5-digit ZIP are not** — and with a
ZIP that specific, masking the city buys nothing, because the ZIP names
the city.

```
N1*ST*RIVERSIDE MARKET*92*0042  ->  N1*ST*ZLZWNRZCR FAAXRJ*92*0042
N1*BT*RIVERSIDE MARKET*92*0001  ->  N1*BT*ZLZWNRZCR FAAXRJ*92*0001
```

Worse: both parties mask to the *same* pseudonym (correct — referential
consistency), but each keeps its **distinct party identifier** in N104
(`0042`, `0001`). The identifiers still tell the two parties apart, and
anyone holding the ID-to-name mapping — which is exactly the trading
partner you are sending the file to — reverses the name mask by lookup.
**The identifier defeats the mask sitting next to it.**

Also surviving untouched: `BEG03` (the PO number, `POPII001`) and
`PO107` (the UPC, `614141007349`). `REF02` masks only under four
qualifiers (`DEA`, `HN`, `1J`, `9L`); every other REF qualifier passes
through. `NTE` and `MSG` — free text, where operators paste anything —
have no rule at all, in any bundled profile.

And the report says:

```
Masked 11 value(s) (10 distinct):
  GS02: 1  GS03: 1  ISA06: 1  ISA08: 1  N102: 2
  N301: 1  N401: 1  PER02: 1  PER04: 1  REF02: 1
```

Eleven masked values, no mention of the ZIP, the party IDs, the PO
number or the UPC still in the file. **The report is a list of successes
where the user needs a list of suspicions.** Someone reads "Masked 11
values", believes the file is clean, and sends it.

## The shape of the fix

The obvious move is "invert it: deny by default, keep a structural
allow-list". That is right in spirit but wrong as the *whole* answer,
because of a constraint Design 009 was built around and which still
holds: **the scrubbed file has to stay validatable.** That is the entire
point of shape-preserving masking. Two things follow.

**Codes must survive.** Specs and definitions address data by literal
code — `REF[DEA]`, `N1[ST]`, `BEG02 = 'DS'`, loop qualifiers, code-list
translations. Mask `ST` to `XY` and every rule that addresses the ship-to
party stops matching; the file is not a quieter version of itself, it is
a broken one. Codes are shared vocabulary, not partner data.

**Everything that is not a code is a candidate.** Names, addresses,
identifiers, references, free text, and — uncomfortably — quantities,
prices and dates, which are business-sensitive but also what the math
checks (CTT, SE/GE counts, invoice totals) run on.

So there is no single default that is both maximally safe and always
useful. This design therefore ships **three layers**, and the middle one
is the important one.

## Decision 1: close the known gaps in the shipped profile

Add to `pharma.yaml`: `N4` element 3 (postal code) and element 2 (state),
`N1` element 4 (party identifier), `N3` element 3+, `BEG03` (PO number),
`NTE` and `MSG` free text, and widen `REF` to mask element 2 under *any*
qualifier rather than four named ones.

Cheap, immediate, and it removes every leak measured above. It does not
solve the class of problem — the next unlisted element is still silent —
which is what Decision 2 is for.

Masking more source elements is safe for validation **provided both
sides are scrubbed with the same `--seed`**, since referential
consistency then maps the same input to the same output on both files.
That is already how the tool is meant to be used; Decision 4 makes it
harder to get wrong.

## Decision 2: `--report` becomes a residual-risk report

**This is the core of the design.** Instead of listing what was masked,
the report names **what survived and looks like it should not have**.

After masking, the scrubber walks every element it did *not* mask and
flags a value when it matches any of:

| Signal | Example | Why |
|---|---|---|
| 5 or 9 consecutive digits in a non-numeric position | `80301` | ZIP |
| 10–11 digit run | `3035551212` | phone |
| 12–14 digit run | `614141007349` | UPC / GTIN |
| 2 letters + 7 digits | `AB1234563` | DEA |
| `nnnnn-nnn-nn` | `12345-678-90` | NDC |
| anything containing `@` | | email |
| a token ≥ 6 chars mixing letters and digits | `POPII001` | account / reference |
| **any** value in a free-text segment (`NTE`, `MSG`, `PID`) | | prose |
| a value in a position the profile masks *elsewhere* in the file | | inconsistent coverage |

with one suppression: a value that is a **known code** for its position —
present in the transaction definition's code list, or in the spec's
`CodeLists` sheet when a spec is available — is not flagged, because
codes are supposed to survive.

Output becomes:

```
Masked 11 value(s) (10 distinct).

3 value(s) look like identifiers and were NOT masked:
  N403  80301          postal-code shape      (2 occurrences)
  N104  0042, 0001     party identifier beside a masked N102
  PO107 614141007349   UPC/GTIN shape
Review these before sharing the file, or add rules to the profile.
```

The last flag in that table is worth calling out: **an identifier sitting
beside a masked name is the specific failure that makes the mask
worthless**, and it is detectable structurally — the profile masks
`N102`, so an unmasked `N104` in the same segment is suspicious by
construction, whatever it contains.

False positives are acceptable and expected here. A residual-risk report
that occasionally flags a harmless value costs the user ten seconds; one
that stays quiet about a real one costs them a disclosure.

## Decision 3: a `strict` profile, not a strict *default*

Ship a second bundled profile, `strict`, that inverts the rule: mask
every element **except** a keep-list of
  - envelope control numbers and counts (ISA13/IEA02, GS06/GE02, ST02/SE02,
    SE01, GE01, IEA01, CTT01) — these must reconcile or envelope
    reconciliation, a headline feature, fails on the scrubbed file;
  - qualifier and code positions, resolved from the transaction
    definition (`qualifier_element`, loop qualifiers) plus values found
    in the definition's or spec's code lists;
  - dates and numerics **only** when `--keep-math` is passed, since
    masking them breaks CTT/SE totals and invoice arithmetic.

Selected with `mapcheck scrub --profile strict`. Not the default,
because a default that silently breaks the math checks would be its own
kind of dishonesty; `pharma` plus a loud residual report is the better
everyday posture, and `strict` is there for the person who needs it.

## Decision 4: make the two-file workflow explicit

`scrub` masks one file. A validation needs source *and* output scrubbed
with the same seed or every value comparison fails. Today nothing says
so. Add:
  - `mapcheck scrub --pair SOURCE OUTPUT -o DIR`, scrubbing both with one
    generated seed and reporting once across both files;
  - a warning when `--seed` is omitted and the output path suggests a
    pair is intended;
  - README wording for the workflow.

## Decision 5: document what `--seed` costs

A fixed seed makes masking reproducible **and reversible by brute force**
for low-entropy fields: with the seed, an attacker enumerates all 100k
ZIPs, masks each, and matches. That is inherent to deterministic,
shape-preserving masking and is a fair trade for a reusable test corpus —
but it must be stated, not discovered. README and `--seed` help text.

## Scope guard

Not in this design: encrypting anything; a UI for editing profiles;
detecting PII by named-entity recognition or any model; changing the
masking primitives themselves (the length- and character-class-preserving
pseudonymizer from Design 009 stays exactly as it is); scrubbing the
history database (that is Design 021).

## Testing

- The measured leaks above become regression tests: after Decision 1, the
  shipped PII example scrubs with **no** value flagged by the residual
  scanner.
- Each detector gets positive and negative cases, and a code-list value in
  a flagged-looking position must **not** be flagged.
- A scrubbed source + scrubbed output pair, same seed, still validates to
  the same findings as the unscrubbed pair — the property that makes the
  whole feature worth having. This is the test that would have caught the
  design going wrong.
- `strict` profile: the scrubbed file still parses, envelope
  reconciliation still passes, and CTT/SE counts still reconcile.
- A profile with an unknown segment, and a file with a segment no rule
  mentions, both behave (no crash, flagged in the report).

## Open questions for review

1. **Decision 1's breadth.** Masking `BEG03` (PO number) makes scrubbed
   files harder to talk about — "which order was that?" becomes
   unanswerable. Mask it, or flag it and leave it? I lean mask, since the
   PO number is often the partner's own sequence and identifying.
2. **Decision 3's `--keep-math` default.** On (math survives, dates and
   amounts in the clear) or off (safer, breaks totals)? I lean on, since
   a `strict` file that fails its own validation invites people back to
   `pharma` for the wrong reason.
3. **Residual report exit code.** Should `scrub --report` exit non-zero
   when anything is flagged, so CI can gate on it? I lean yes behind an
   explicit `--fail-on-residual`, so the default stays informational.
4. **Scope of Decision 4.** Is `--pair` worth building now, or is a
   README section plus the missing-seed warning enough for this round?
