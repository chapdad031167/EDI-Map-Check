# Design 021: who can see the history, and what it holds

**Status:** Draft, for sign-off. No implementation until approved.
**Applies to:** `app.py` (History page, `_history_db`, the download
button), `src/mapcheck/report/history.py`, `README.md` deployment
section, `Dockerfile`.
**Extends:** Design 016 (the run lifecycle in the app) and Design 011
(deployment), both of which assumed a single operator on a laptop.

## Why

Two audit findings share one root cause, so they share one design.

**The store is global and unauthenticated.** `_history_db()` resolves to
one SQLite file for the whole process. Every visitor's runs land in it,
and the History page ends with:

```python
st.download_button("Download history database (.db)", ...)
```

with no gate of any kind. On a single-user laptop that is a convenience.
On a shared deployment it means **any visitor can download every other
visitor's validated field values** — expected and actual, verbatim, for
every run anyone has recorded.

**And the README recommends exactly that deployment.** Line 182:

> To put it online for free, point **Streamlit Community Cloud** at this
> repo with `app.py` as the entrypoint — users just get a URL.

A URL, no auth, one shared database, a download button, and a tool whose
input is partner EDI. The three facts are individually defensible and
jointly a cross-tenant disclosure.

**What is in there is not metadata.** Design 006 stores each finding's
`expected` and `actual` verbatim, because that is what makes a regression
diff possible — a diff of hashes tells you something changed but never
what. So the database holds real field values: party names, addresses,
identifiers, quantities, prices. It is an ordinary unencrypted SQLite
file with no access control of its own.

PR #15 documented that last point, which was the audit's suggested fix
for it. Documentation is the floor, not the ceiling — this design is the
ceiling.

## The tension

Recording is **on by default** and that is deliberate (Design 016,
Decision 2): a tool that only remembers when you remember to ask it is a
tool with no history, and the baseline/regression workflow — the reason
this project exists in CI — depends on runs being there without
ceremony. Any fix that makes recording opt-in trades the product's best
feature for safety it can get another way.

So: keep recording on, change **who can reach what**.

## Decision 1: separate the two deployment modes, in the code

Introduce one explicit setting, `MAPCHECK_MODE`, with two values:

- **`single`** (default) — today's behavior exactly. One database, full
  History page, download button present. This is the laptop and the
  private container, and nothing about it changes.
- **`shared`** — the app assumes more than one person can reach the URL.

Defaulting to `single` keeps every existing install working. Making the
mode explicit means the safe behavior is reachable **without** asking
each operator to reason correctly about their own deployment, which the
current design does implicitly and which the audit shows does not work.

## Decision 2: what `shared` changes

1. **Runs are scoped to a session.** Each browser session gets an opaque
   id, stored on the run row (`session_id`, additive migration, `NULL`
   for every existing row). The History page, trends, and baseline
   lookups filter to the current session. A visitor sees their runs and
   only theirs.
2. **The database download disappears.** Not "requires a click to
   confirm" — absent. There is no version of "here is everyone's data as
   a file" that belongs on a shared URL. Per-run exports (Excel, HTML)
   stay, because those carry only the run the user just did.
3. **Blessing is session-scoped too**, so one visitor cannot repoint
   another's baseline.

Session scoping is privacy, not security: a session id is not an
identity, sessions end, and anyone with filesystem access still reads
everything. It stops the accidental cross-tenant read, which is the
finding. It does not make the app multi-tenant, and Decision 5 says so
out loud rather than implying otherwise.

## Decision 3: optional real authentication

For operators who want more than session scoping, support a shared
password via `MAPCHECK_PASSWORD` gating the whole app (Streamlit's
native auth where available, a simple gate otherwise). Off unless set.

This is deliberately modest. Real multi-tenancy — accounts, per-user
stores, roles — is a different product, and pretending otherwise in a
config flag would be worse than not offering it.

## Decision 4: at-rest options for the history

Add `MAPCHECK_HISTORY_VALUES` with three settings:

- **`full`** (default) — expected/actual stored verbatim. Regression
  diffs work fully. Today's behavior.
- **`redacted`** — findings store status, category, row id and target,
  but expected/actual are replaced by a stable hash. Regression still
  detects *that* a value changed (the hash differs) and never shows
  *what* it was. `format_delta` renders `'<redacted>' -> '<redacted>'`
  where it would have shown values.
- **`none`** — counts and results only; no per-finding rows. Trends and
  pass rates still work, regression does not.

`redacted` is the interesting one: it keeps the regression gate — the
feature CI depends on — while making the database itself uninteresting to
steal. Several teams will want it as their default; it is not ours,
because a diff that cannot show the value it disagrees about is a worse
first experience.

## Decision 5: stop recommending the unauthenticated public deploy

Rewrite the README deployment section. Streamlit Community Cloud stays as
an option, described accurately: fine for the bundled examples and for
evaluating the tool, **not** for real partner data, because the URL is
public and the store is shared. Point real deployments at the container
with `MAPCHECK_MODE=shared`, a password if wanted, and a volume they
control.

Also: the Dockerfile should default `MAPCHECK_MODE=shared`, since a
container someone bothered to deploy is more likely to be shared than a
laptop is.

## Scope guard

Not in this design: user accounts, roles, SSO, encrypting the SQLite file
at rest (filesystem or volume encryption is the operator's layer and this
project should not pretend to do key management), audit logging, or
retention/expiry policies. Not in this design either: what the *scrubber*
masks — that is Design 020, and the two are independent. This one is
about the store; that one is about the files.

## Testing

- `single` mode: every existing test passes unchanged. This is the
  regression bar for the whole design — the default install must not
  move.
- `shared` mode: two simulated sessions record runs; each sees only its
  own in History, trends and baseline lookup; the download button is
  absent from the rendered page; one session cannot bless the other's
  run.
- Migration: a database written before `session_id` existed opens, reads,
  and its rows appear in `single` mode.
- `redacted`: a changed value still produces a regression, and neither
  the stored row nor the rendered delta contains the original value —
  asserted by searching the rendered output for it.
- `none`: trends and pass rates still compute; regression reports that it
  cannot run rather than silently passing. (The audit already caught one
  false-green regression path in PR #14; this must not add a second.)
- Password gate on and off.

## Open questions for review

1. **Is `shared` the right Docker default?** It changes behavior for
   anyone already running the container privately — their History page
   would start scoping to their session and lose the download button. The
   alternative is defaulting `single` everywhere and documenting loudly.
   I lean `shared` in Docker, on the grounds that the failure modes are
   asymmetric, but this one is genuinely your call.
2. **Should `redacted` be the default in `shared` mode?** Coupling them
   is tempting and probably right, but it means a mode flag silently
   changes what the database holds.
3. **Session scoping and CI.** A CI container recording runs across
   invocations has no browser session. It uses the CLI, which is
   unaffected — but confirm that matches how you actually run it.
4. **Do you want the password gate at all**, or is "run it somewhere
   private" the honest answer for this project's size?
