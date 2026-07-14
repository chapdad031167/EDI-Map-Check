# Design 009 — Data Scrubber

**Status:** approved — implemented in this PR
**Roadmap item:** 3.3 (Phase 3, design-first)

**Resolved (all four recommendations adopted):** (A) masking policy is a
standalone scrub profile with a shipped pharma default; (B) masking is
deterministic and length- & character-class-preserving; (C) a random salt per
run, with `--seed` to reproduce a corpus; (D) ISA/GS trading-partner IDs are
masked by default.

## The problem

To build a MapCheck test case you need a real translated file — but a real
X12 file carries names, addresses, and DEA/HIN/NDC-shaped identifiers you
cannot check into a repo or paste into a bug report. Today the only safe path
is hand-writing synthetic files (which is exactly how *this* repo's examples
are built). `mapcheck scrub` closes that gap for **users**: point it at a real
X12 file and get back a structurally identical file with the sensitive element
values masked — safe to share, still valid to validate.

The hard requirement is **fidelity**: the scrubbed file must keep the same
structure, delimiters, segment counts, element **lengths**, and — critically —
**referential consistency** (the same input value always masks to the same
output, so a pairing key that ties a source transaction to its output document
still ties after scrubbing). Only the *values* of configured element positions
change.

**Policy:** this feature helps users sanitize their own data. It changes
nothing about this repo — every bundled example stays fully synthetic, and the
scrubber's own test fixtures are synthetic files that merely *look* like they
carry PII.

## Decision 1: what to mask — a scrub profile

Masking policy lives in a standalone **scrub profile** (YAML), not baked into
the transaction-definition YAMLs. A profile is a list of rules keyed by
segment + element, optionally gated on a qualifier:

```yaml
# pharma.yaml (the shipped default profile)
name: pharma-default
rules:
  - segment: N1   # N102 = entity name
    element: 2
    strategy: name
  - segment: N3   # N301/N302 = address lines
    element: 1
    strategy: text
  - segment: N4   # N401 = city
    element: 1
    strategy: text
  - segment: PER  # PER04 = contact number/email
    element: 4
    strategy: text
  - segment: REF  # REF02 only when REF01 is a DEA/HIN qualifier
    element: 2
    when: { element: 1, in: [DEA, HN, "1J"] }
    strategy: id
```

A rule targets the same element across every occurrence of a segment — a
segment's identity already carries its meaning (N3 is always an address), so
no loop scoping is needed. The `when` clause makes a rule qualifier-aware
(mask `REF02` only when `REF01` marks a DEA/HIN number). This keeps PII policy
decoupled from structure, reusable across transaction sets, and user-editable
without touching the definitions.

**Open question A:** ship masking policy as a **standalone scrub profile**
(recommended — decoupled, reusable, user-overridable) or embed `sensitive:`
marks in the transaction-definition YAMLs, as the roadmap sketched? The profile
keeps the definitions about *structure* and PII policy in one editable place.

## Decision 2: how to mask — deterministic, shape-preserving

Every strategy is **length-preserving** and **deterministic**: the masked value
is derived from a keyed hash of `(original value, salt)`, so the same input
always yields the same output (referential consistency) and nothing is a
reversible table lookup.

| Strategy | For | Behavior |
|---|---|---|
| `name` | entity names | length-preserving synthetic uppercase token |
| `text` | addresses, cities, free text | same as `name`, spaces kept |
| `id` | DEA/HIN/NDC-shaped identifiers | **character-class preserving** — digit→digit, letter→letter, separators (`-`, space) untouched; so a DEA `AB1234563` stays 2-alpha + 7-digit and an NDC `12345-678-90` keeps its dashes |
| `redact` | anything | fixed length-preserving filler (`X…`) — non-reversible, when you don't need realistic shape |

Character-class preservation means a scrubbed file still *looks* like valid X12
(a masked NDC is still NDC-shaped) so it exercises the same format/length rules
the real one did.

**Open question B:** deterministic, length- and character-class-preserving
pseudonymization (recommended — keeps referential integrity and realistic
shapes) or plain fixed-filler redaction (simpler, but loses shape and can break
length/format checks)?

## Decision 3: determinism & the salt

Referential consistency *within a file* is always on (a value maps
consistently through one run). Reproducibility *across* runs is opt-in via a
`--seed`:

* **no `--seed`** → a random per-run salt: every scrub of the same file
  produces a different (still internally consistent) result, and there's no
  fixed mapping to reverse;
* **`--seed VALUE`** → that salt, so a team can regenerate an identical
  scrubbed corpus deterministically.

**Open question C:** default to a **random per-run salt** with `--seed` for
reproducibility (recommended — safest) or a fixed default salt (always
reproducible, but a stable mapping across everyone's runs)?

## Decision 4: envelope & structure

Structure is never touched: segment order, counts, delimiters (read from the
ISA, not assumed to be `*`/`~`), sub-element separators, ISA fixed-width
padding, and all control numbers (ISA13, GS06, ST02, SE01) pass through
unchanged so the file still parses and reconciles.

The one judgment call is the **envelope trading-partner IDs** (ISA06/ISA08
sender/receiver, GS02/GS03). These identify the partners and are arguably
sensitive.

**Open question D:** also mask the **ISA/GS partner IDs** by default (`id`
strategy, length-preserving so ISA stays fixed-width) — recommended, since a
shared file otherwise names both trading partners — or leave the envelope
completely untouched and mask only business segments?

## Decision 5: command & scope

```
mapcheck scrub INPUT.edi [-o OUTPUT.edi] [--profile pharma.yaml] [--seed S] [--report]
```

Defaults to the bundled pharma profile; `-o` defaults to `INPUT.scrubbed.edi`;
`--report` prints a summary of how many values were masked per segment/element
(no original values shown). Interchanges with many transactions scrub in one
pass (the whole file is tokenized once).

* **Out of scope (fast follows):** masking the *output*/canonical side (JSON,
  IDoc) — this is X12-only for now; a profile that redacts by regex over free
  text; and configurable per-partner profiles. A Streamlit "scrub" button is a
  UI fast follow like the others.

## Reference scenario

A **synthetic** 850 that merely *looks* sensitive — fake names
(`RIVERSIDE MARKET`), a street address, a DEA-shaped `REF*DEA*AB1234563`, an
NDC-shaped id — is scrubbed with the default profile. Asserted:

* every configured element's value **changed**, and every non-configured
  element is **untouched**;
* **lengths preserved** everywhere; the DEA stays 2-alpha-7-digit, dashes in
  the NDC survive;
* **referential consistency** — a value repeated in two segments masks to the
  same token; a `--seed` run reproduces byte-for-byte;
* the scrubbed file still **parses and validates** against the 850 spec with
  the same structural result (pairing keys survive).

Nothing in the fixture is real data — it is generated by
`scripts/generate_examples.py` like everything else in `examples/`.

## Test plan

1. Profile loader: valid parse; `when` qualifier gating; unknown strategy /
   malformed rule → clear error.
2. Strategies: `name`/`text` length-preserving; `id` character-class
   preserving (digits, letters, separators); `redact` filler.
3. Determinism: same value → same mask in one run; `--seed` reproducible;
   no-seed runs differ.
4. Fidelity: non-`*`/`~` delimiters round-trip; ISA stays fixed-width;
   control numbers and segment counts unchanged; scrubbed file re-parses.
5. Envelope masking on/off per Decision 4.
6. Scenario: the synthetic 850 scrubs, still validates, pairing survives.
7. Full existing suite green — scrub is a new, isolated module + command.

## Open questions for review

1. **Profile source (Decision 1 / A):** standalone scrub profile + shipped
   pharma default (recommended) vs marks embedded in the definition YAMLs?
2. **Masking strategy (Decision 2 / B):** deterministic length/char-class
   preserving (recommended) vs fixed-filler redaction?
3. **Determinism (Decision 3 / C):** random salt per run with `--seed`
   (recommended) vs a fixed default salt?
4. **Envelope IDs (Decision 4 / D):** mask ISA/GS partner IDs by default
   (recommended) vs leave the envelope untouched?
