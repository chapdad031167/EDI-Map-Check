# Design 022: if / else-if chains

**Status:** Draft, for sign-off. No implementation until approved.
**Applies to:** the spec grammar (`spec/conditions.py`, `spec/parser.py`,
`spec/model.py`), the engine's expected-value step
(`engine/validator.py`), the template's Instructions sheet, `import-spec`,
README.
**Extends:** the CONDITIONAL rule type, which today is one condition, one
Then and one Else.

## Why

A CONDITIONAL row answers one question: is this condition true? Real
mapping documents ask a sequence of them. "If the ship-to has a store
number use that, else if there is a reference number use that, else
hardcode a default." Three outcomes, three different source fields, one
target.

There is no way to write that today, and the obvious attempt is worse
than nothing. Put two CONDITIONAL rows on one target and each is judged
alone. The first row's Else defaults to SKIP, so whenever its condition is
false it expects the target to be **absent**, at exactly the moment the
second row expects it to hold a value. One of the two fails on every
document. The spec loads, runs, and reports a defect the map does not
have.

So an author with a chain has one honest option: mark the row TODO and
accept NOT TESTED. These are not rare rows. They are where the judgment in
a map lives, which makes them the rows most worth testing.

## Decision 1: `NEXT` as an Else outcome

One new keyword, in one existing column. `Else = NEXT` means: this row's
condition was false, so the decision passes to the next Mapping row.

| Row ID | Source Field | Loop Context | Target Field | Rule Type | Condition (Coded) | Then | Else | Default Value |
|---|---|---|---|---|---|---|---|---|
| R-10 | `N104` | `N1[ST]` | `partners.we.partn` | CONDITIONAL | `N103 = '92'` | `SOURCE` | `NEXT` | |
| R-11 | `REF02` | `REF[ST]` | `partners.we.partn` | CONDITIONAL | `EXISTS(REF02)` | `SOURCE` | `NEXT` | |
| R-12 | | | `partners.we.partn` | CONSTANT | | | | `UNKNOWN` |

Rows linked by NEXT form a **chain**. It is read top to bottom and the
first true condition decides. Each row keeps its own Source Field, Loop
Context, Code List Ref, Data Type and Format, so a branch can read a
different segment, translate through a different list, or format
differently from its neighbours.

The last row is the chain's **tail**, and it can be any rule that could
stand alone: a CONDITIONAL with an ordinary Else, or an unconditional
DIRECT, CODE_LIST or CONSTANT serving as the final "else".

No new column and no new rule type. A spec that never writes NEXT loads
and behaves exactly as it does now.

**Why not a "Branch Group" column.** It would change the template for
every existing spec, the importer and the writer, to record something
adjacency already says.

**Why not a richer cell** (`CASE ... WHEN ... ELSE` inside one condition).
One cell would have to carry several source fields, loop contexts and
formats. The template's strength is one decision per row, readable by
someone who has never seen the grammar.

## Decision 2: the loader refuses a malformed chain

All of these are errors at spec load, naming the rows. None can surface
as a strange finding at run time.

- `NEXT` anywhere but the Else of a CONDITIONAL row.
- A row whose Else is `NEXT` followed by a row with a different Target
  Field, or by nothing.
- A chain that mixes scopes: every row is per-line on the same loop, or
  every row is header-level. Qualifiers may differ between rows; the
  scope may not.
- A TODO row in the middle of a chain. It has no condition, so it cannot
  pass the decision on.

A TODO row **as the tail** is allowed and means "the final else is not
decided yet". The chain is tested whenever an earlier branch decides, and
reports NOT TESTED only on documents that reach the tail.

Outbound specs use the same grammar. Conditions test the source side, as
they do now.

## Decision 3: one chain, one finding

The engine evaluates a chain as a unit. It walks the rows, and the first
row whose condition is true decides, using that row's Then, source,
context, code list and format. If no condition is true the tail decides.
A chain produces exactly one finding per scope: one for a header-level
chain, one per line for a per-line chain.

**The finding is filed under the chain's first Row ID, whichever row
decided.** This is the part worth arguing about. Regression identity is
built on Row ID. If a finding were filed under the deciding row, a
partner sending different data next month would take a different branch,
and the baseline comparison would read that as one finding resolved and
an unrelated one appearing. Filed under the first row, it reads as what
it is: the same target, changed.

The message carries what the Row ID no longer does:

```
decided by R-11: R-10 N103 = '92' is false; R-11 EXISTS(REF02) is true
```

The root-cause category comes from the deciding row's rule type. In the
unmapped sweeps, every element any row of the chain reads (as a source or
in a condition) counts as referenced, and the target counts as produced.

## Decision 4: OR needs no operator

"If A or B, use X" is two rows with the same Then:

| Condition (Coded) | Then | Else |
|---|---|---|
| `N103 = '92'` | `SOURCE` | `NEXT` |
| `N103 = 'ZZ'` | `SOURCE` | `SKIP` |

The condition grammar stays at four operators joined by AND. README
documents the pattern.

## Decision 5: a lookup is still a lookup

A chain in which every row tests the same field against a fixed value and
yields a fixed value is a code list with a Default Value, and should be
written as one: shorter, and its misses report as `code_translation`
rather than as a generic value mismatch. README says so. The loader does
not try to detect it; that is the author's call.

## Scope guard

Not in this design: `OR`, `NOT` or parentheses in the condition grammar;
comparing two fields with each other; greater-than and less-than;
arithmetic, concatenation, substring. A chain inside a branch of another
chain. `draft-spec` emitting chains. Any UI for editing them.

## Testing

- **Unchanged behavior.** Every existing test passes untouched. A spec
  without `NEXT` is the regression bar for the whole design.
- **Loader.** One test per refusal in Decision 2, each asserting the
  message names the rows.
- **Engine.** First true condition wins when two are true. Tail as a
  CONDITIONAL with an Else, and as an unconditional DIRECT, CODE_LIST and
  CONSTANT. No condition true with a SKIP tail expects the target absent.
  Each row's own Loop Context is honored. A per-line chain decides
  independently on each line.
- **The failure this replaces.** Two plain CONDITIONAL rows on one target
  produce a false FAIL today; the same logic written as a chain passes.
- **Identity.** Two recorded runs in which different branches decide
  produce a regression delta of one changed finding, not one resolved and
  one new.
- **OR** written as two rows.
- **Outbound** chain.
- **TODO tail.** Tested when an earlier branch decides, NOT TESTED when
  the tail is reached.
- **`import-spec`** carries `NEXT` through.
- A bundled reference pair (spec, clean output, defect output) whose
  defect variant trips exactly one finding, in the style of the existing
  examples.

## Open questions for review

1. **The keyword.** `NEXT`, or `ELSE IF`, or `CONTINUE`? I lean `NEXT`:
   one word, and it says where the decision goes.
2. **TODO as a tail.** Allow it (partial coverage, NOT TESTED only when
   reached) or refuse it (simpler rule)? I lean allow.
3. **Identity under the first Row ID.** Agree, or file under the deciding
   row and accept noisier regression deltas in exchange for a simpler
   reading of a single report?
4. **A nudge toward CODE_LIST.** Should the loader warn when a chain is a
   lookup in disguise? I lean no.
