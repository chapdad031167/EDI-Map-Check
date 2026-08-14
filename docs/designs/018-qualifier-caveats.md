# Design 018: closing the Design 015 caveats

**Status:** Approved 2026-08-13 ("proceed with all above"), implementation
in this PR.
**Applies to:** the transaction-definition schema, the loader, the
validation engine's presence checks, and partner-rules overlay emission.
**Closes:** the two caveats Design 015 named and left honest —
loop-scoped placement and multi-code qualifiers.

## The two holes

Design 015 gave the overlay qualifier-scoped element rules and code-keyed
pair rules, and named what it did not close:

1. **Loop-scoped placement.** "PER required *within the N1 loop*"
   enforced as global presence. A segment that legitimately appears in
   several contexts — PER in the heading, again inside the N1 party loop,
   again inside the PO1 line loop — could satisfy a "PER required" rule
   with the *wrong* occurrence: a heading PER passes a rule the partner
   meant about the ship-to party's contact.
2. **Multi-code qualifiers.** A guide REF block listing REF01 ∈ {IA, DP}
   emitted an *unqualified* requirement plus a review note — the "one of
   these" information was dropped rather than enforced.

Both are additive: nothing in Design 015's single-qualifier or pair paths
changes.

## Decision 1: loop scope on the presence rules

`RequiredSegmentDef` and `RequiredElementDef` gain `loop: str = ""`.
Empty keeps today's behavior (any context). Non-empty is a loop-context
string matched against the label the parser already attaches to every
business segment (`business_segments()` yields `N1[ST]`, `PO1 #1`, or an
area id):

- a **bare** loop id (`N1`) matches any occurrence of that loop —
  `N1[ST]`, `N1[BT]`, `N1 #1`;
- a **qualified** loop context (`N1[ST]`) matches only that occurrence.

The check counts a rule satisfied only by occurrences whose label is in
scope, so "PER within N1" ignores a heading PER. The finding names the
scope: `required segment PER within the N1 loop is missing`.

This is orthogonal to the segment's own `qualifier` (REF\*IA is the
segment's element-01 code; N1-scope is the enclosing loop) and the two
compose.

## Decision 2: a code *set* on the presence rules

`RequiredSegmentDef` and `RequiredElementDef` gain
`qualifiers: tuple[str, ...] = ()`. When non-empty, an occurrence
matches if its qualifier element is **any** of the codes — "at least one
REF whose REF01 ∈ {IA, DP}" for a segment rule, "REF02 required in REF
occurrences whose REF01 ∈ {IA, DP}" for an element rule. The existing
single `qualifier` is the one-code case and is untouched; `qualifiers`
takes precedence when both are somehow set (loader forbids that). The
finding renders the set: `required segment REF*{IA|DP} is missing`.

Reading, stated: a guide block that lists several allowed qualifier codes
for a **must_use** segment means "a segment carrying one of these is
required" — not "one of each." Separate required occurrences are separate
guide blocks (three N1 blocks → three single-code rules, unchanged);
several codes in *one* block are alternatives.

## Decision 3: emission uses both

`emit_partner_rules` changes in exactly two spots:

- **Multi-code qualified family** (REF/DTM/N1/... block whose element-01
  carries more than one code): emit `qualifiers=(codes…)` instead of the
  old unqualified requirement, and emit the block's other `must_use`
  elements as `qualifiers`-scoped element rules. The "emitted unqualified"
  review note is gone — the information is enforced now.
- **Loop-member segments**: a `must_use` segment that sits in a loop it
  does not trigger (`segment.loop` set and `segment.id != segment.loop` —
  X12 names a loop after its trigger, so this cleanly distinguishes a
  member like PID-in-PO1 or PER-in-N1 from the trigger itself) emits
  `loop=segment.loop`, tightening "required" to "required within its
  loop." The trigger keeps its qualifier/plain rule.

A loop-member that is itself a qualified family (PER-in-N1 whose PER01
carries a code) composes cleanly: emission produces a rule scoped by
*both* its own qualifier and its bare loop (`PER*IC within the N1
loop`) — enforced, not dropped. What the guides still cannot pin is
narrower: *which* occurrence of a repeated loop the member belongs to
(`PER within N1[ST]` vs `N1[BT]`), because the guide lists PER under
"Loop: N1" without saying which N1. That one residual is hand-editable
in the overlay YAML (the engine enforces a qualified loop context; only
emission cannot infer the occurrence). It is a general property of
loop-scoping, so it is stated here rather than repeated as a per-rule
review note that would fire on every qualified loop member.

## Scope guard

Additive schema fields with empty defaults; no change to the single-
qualifier, pair, `when_present`, or base-standard paths; the audit
file-4 overlay is unaffected (acme has no multi-code family and no
must_use loop member), so that closure test is unchanged. No UI change.

## Testing

- Loader/overlay YAML round-trip for `loop` and `qualifiers`, each
  problem named; `qualifier` + `qualifiers` together is a load error.
- Loop-scope enforcement: a multi-context PER fixture where a heading
  occurrence does not satisfy an N1-scoped rule, and does satisfy a bare
  rule; bare-vs-qualified matching.
- Multi-code enforcement: a REF\*{IA|DP} rule satisfied by either code,
  failed by neither present; the scoped element variant.
- Emission: a multi-code guide block yields `qualifiers` rules and no
  review note; a loop-member must_use segment yields a `loop` rule while
  the loop trigger does not.
- The audit file-4 closure test still passes unchanged.
