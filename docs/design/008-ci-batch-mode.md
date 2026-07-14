# Design 008 — CI & Batch Mode

**Status:** approved — implemented in this PR
**Roadmap item:** 3.2 (Phase 3, design-first)

**Resolved (all four recommendations adopted):** (A) check paths resolve
relative to the manifest's directory, default `./mapcheck.yaml`; (B) the
command is `mapcheck batch`; (C) warnings don't fail by default, `--strict`
promotes them; (D) one JUnit `<testcase>` per check with findings summarized in
the `<failure>` body.

## The problem

Every command so far validates **one** translation. A team guarding a real
integration has dozens — many partners, many transaction sets — and wants to
run them **all** on every map change, in a pipeline, and fail the build when
anything regresses. Today that means N shell invocations and eyeballing N
reports; there's no single "is the whole integration still correct?" gate and
nothing a CI system can render.

3.2 adds a **manifest-driven batch run**: one YAML file lists every check, one
command runs them all, prints a roll-up, emits **JUnit-XML** for CI to display,
and returns a **meaningful exit code**. It's pure orchestration over the
existing engine — validate, interchange (1.2), and regress (2.3) are the
building blocks; nothing in them changes.

## Decision 1: the manifest

A `mapcheck.yaml` lists checks; each check is the arguments a single `validate`
(or `regress`) run already takes:

```yaml
# optional shared defaults applied to every check
defaults:
  db: mapcheck_history.db

checks:
  - name: acme-850                 # friendly id (used as the JUnit testcase name)
    spec: specs/850.xlsx
    source: in/acme_850.edi
    output: out/acme_order.json
    partner: partners/acme.xlsx    # optional — merged onto spec (2.2)
    transaction: "850"             # optional — else auto-detected
    output-def: defs/flat.yaml     # optional — user output format (1.3)

  - name: globex-810-regress
    spec: specs/810.xlsx
    source: in/globex_810.edi
    output: out/globex_inv.json
    regress: true                  # diff vs the blessed baseline (2.3); fail on regression
    label: globex-810              # optional baseline label
```

Multi-transaction interchanges (1.2) need no special entry type — a check is
auto-detected as an interchange exactly as `validate` does today. A
`regress: true` check runs regression mode instead of a plain validate.

**Open question A (paths & default):** I recommend check paths resolve
**relative to the manifest file's directory** (a manifest is portable and
self-contained, like the `file:` lookups in 3.1), and the command defaults to
`./mapcheck.yaml` when no path is given. Confirm, or prefer cwd-relative.

## Decision 2: the command

```
mapcheck batch [MANIFEST] [--junit report.xml] [--strict] [--db DB] [--no-color]
```

It runs every check in listed order (deterministic, sequential), prints a
roll-up table (check · result · pass/fail/warn counts), and — like `validate` —
records each run in the history DB unless `--no-history`. `regress` checks need
that history for their baseline.

**Open question B (command name):** the roadmap sketched `validate-dir`, but the
input is a manifest, not a directory to scan (explicit entries keep the run
deterministic — no surprise files). I recommend naming it **`mapcheck batch`**;
alternatives are `validate-dir` (roadmap's name) or `mapcheck ci`. Confirm the
name.

## Decision 3: exit codes & strictness

The single-run codes already fit — batch just aggregates them:

| Code | Meaning |
|---|---|
| **0** | every check passed (warnings allowed unless `--strict`) |
| **1** | at least one check has a FAIL finding, or a regression |
| **2** | an execution error — bad manifest, missing file, spec load error — in any check |

A code-2 execution error in one check still runs the rest (so one broken path
doesn't hide the others) but forces the final code to 2. A regression (2.3)
counts as a failing check (1).

**Open question C (warnings):** I recommend **warnings do not fail the build by
default** (consistent with single `validate`, whose exit is 1 only on FAIL),
with **`--strict`** promoting any WARNING to a build failure. Confirm, or make
warnings always fail.

## Decision 4: JUnit-XML

`--junit report.xml` writes a standard JUnit document CI systems render
natively:

* one `<testsuite>` for the run (totals: tests, failures, errors);
* one **`<testcase>` per manifest check** (`name` = check name,
  `classname` = spec/transaction), so the CI UI lists each partner check;
* a failing check → a `<failure>` whose body is the finding summary (category
  counts + the top findings, or per-document rollup for an interchange);
* an execution-error check → an `<error>` with the reason;
* a passing check → a bare `<testcase>`.

**Open question D (granularity):** I recommend **one testcase per check** with
the findings summarized in the failure body (matches how a CI reader thinks —
"which partner check failed?") rather than one testcase per individual finding
(finer but floods the CI UI for a 300-row spec). Confirm.

## Decision 5: GitHub Actions example + scope

* A documented **example workflow** (in the README / `docs/`) showing
  `pip install`, `mapcheck batch --junit report.xml`, and a JUnit-publish step
  — illustrative, not this repo's own CI.
* **Out of scope (fast follows):** parallel execution (sequential is
  deterministic and fast enough for a portfolio suite); directory
  auto-discovery / globbing of checks; a JSON/SARIF report format; and manifest
  `include:` composition.

## Reference scenario

A bundled `examples/mapcheck.yaml` (paths pointing at existing 850 fixtures)
with three checks: a clean pass, a check whose output has planted defects, and
a `regress` check. Asserted:

* the roll-up lists all three with correct per-check results;
* the exit code is 1 (defect check fails) and 2 when a path is broken;
* `--junit` emits well-formed XML with one testcase per check, a `<failure>`
  on the defect check, and an `<error>` on a broken one;
* `--strict` flips a warning-only check to a failure.

## Test plan

1. Manifest loader: valid parse; `defaults` merge; unknown keys and missing
   required keys are clear errors; paths resolve relative to the manifest.
2. Batch run: mixed pass/fail/regress; order preserved; history recorded;
   `--no-history` honored.
3. Exit codes: all-pass → 0; a FAIL/regression → 1; a broken path → 2 (and the
   other checks still run); `--strict` promotes warnings to 1.
4. JUnit: schema-valid; testcase count = checks; failure/error bodies; totals.
5. Regress entry: bootstrap (no baseline) vs a real regression.
6. Full existing suite green — batch is additive over the engine.

## Open questions for review

1. **Paths & default (Decision 1 / A):** manifest-relative paths + default
   `./mapcheck.yaml` (recommended) vs cwd-relative?
2. **Command name (Decision 2 / B):** `mapcheck batch` (recommended) vs
   `validate-dir` vs `mapcheck ci`?
3. **Warnings (Decision 3 / C):** warnings don't fail by default, `--strict`
   opts in (recommended) vs warnings always fail?
4. **JUnit granularity (Decision 4 / D):** one testcase per check (recommended)
   vs one per finding?
