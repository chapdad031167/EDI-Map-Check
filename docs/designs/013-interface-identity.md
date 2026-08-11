# Design 013: Interface identity ("instrument, not toy")

**Status:** draft (requirement raised 2026-08-10: showcase audience is
non-CLI evaluators, and the current UI reads as untouched default-theme
output)
**Roadmap item:** proposed (new), pending triage into ROADMAP.md
**Applies to:** the whole Streamlit app, including the Design 012 page

## Diagnosis: what currently reads as a stock demo

- Untouched default theme (`config.toml` has no `[theme]` block at all).
- Default typography for everything, including X12 notation.
- Default `st.dataframe` styling for the findings table.
- Streamlit chrome intact: hamburger menu, footer, deploy button.
- Header-soup hierarchy: every section announced at the same weight.

None of these are bugs. Together they are the visual signature of
a framework nobody owned. An evaluator who has seen a hundred
default-theme demos pattern-matches this in two seconds.

## Direction

**Instrument, not toy.** MapCheck is an audit instrument for
machine-to-machine commerce documents. Its native world is fixed-width
wire data, control numbers, qualifiers, and test equipment. The interface
should feel like a piece of that world: light, high-contrast, dense,
precise, and **unanimated** (a stated choice: instruments do not animate).

## Decision 1: tokens

| Token | Hex | Role |
|---|---|---|
| `paper` | `#F6F8F7` | app background, cool near-white |
| `panel` | `#EDF1EF` | sidebar / secondary surfaces |
| `ink` | `#1A2421` | text |
| `petrol` | `#0F5468` | accent: actions, links, wordmark |
| `pass` | `#1E7A46` | status only |
| `fail` | `#B42D22` | status only |
| `warn` | `#8A6100` | status only |
| `slate` | `#5C6B66` | labels, NOT TESTED, TODO |

Rules: status hues are **semantic only**, never decorative, and the accent
is deliberately none of them (an accent that is also a status color makes
every button look like a verdict). No gradients anywhere.

## Decision 2: type

**IBM Plex Sans** for interface text; **IBM Plex Mono** for every piece of
EDI notation: segment references (`BEG03`), qualifiers, control numbers,
file names, and the data columns of the findings table. One superfamily,
engineered together, free to bundle.

Mono is not decoration here. X12 is a fixed-width wire format; rendering
its notation proportionally is a small infidelity that practitioners feel
even when they cannot name it.

Fonts are bundled as woff2 under `assets/fonts/` so the app renders
correctly offline and in air-gapped demos. No CDN dependency.

## Decision 3: the signature, spent in one place

The **verdict strip**: after every run, a full-width readout in Plex Mono,
left edge carrying the result color, styled like test-equipment output:

```
29 PASS / 15 FAIL / 2 WARNING / 0 NOT TESTED    RESULT: FAIL
```

Everything else stays quiet and disciplined. The findings table is
rendered through a pandas-to-HTML pass (not `st.dataframe`) for full
control: status cells show a dot plus the word (never color alone,
colorblind-safe), data columns in mono, tight vertical rhythm.

## Decision 4: chrome and mechanics

- `config.toml` gains a `[theme]` block built from the tokens.
- One `styles.css`, injected once at startup: font-faces, chrome removal
  (menu, footer, deploy button), the verdict strip, the findings table,
  mono classes. Small and semantic; resist the urge to restyle every
  widget.
- `st.set_page_config`: wide layout, proper page title, real favicon.
- Wordmark is typographic ("EDI MapCheck," Plex Sans SemiBold, petrol).
  No logo artwork.
- Pin the Streamlit minor version in `pyproject.toml`; CSS that targets
  framework internals is version-fragile, and a pinned version plus a
  small stylesheet keeps the breakage surface tiny.
- The headless-engine rule is restated as law: `app.py` renders, the
  engine decides. No logic migrates into the UI to serve styling.

## Copy standards

- Buttons say what they do: "Run validation," "Download Excel report,"
  "Draft spec."
- One name per concept everywhere: a run is a run, a spec is a spec.
- Errors state cause and fix, in the interface's voice, no apologies:
  "Spec failed to load: Mapping sheet has no Row ID column. Add the
  column or re-export from the template."
- Empty states instruct: "Select a scenario or upload a spec, source, and
  output to begin."
- No emoji. No exclamation points.

## Acceptance: the squint tests

1. A screenshot beside default Streamlit: the framework is not
   identifiable at a glance.
2. An EDI practitioner's first read is "vendor tool," not "hackathon."
3. Zero default chrome, zero emoji, zero gradients.
4. Every X12 reference on screen is monospaced.
5. Status is never conveyed by color alone; contrast meets WCAG AA;
   keyboard focus is visible.

## Out of scope

Framework migration (React or similar). Streamlit's interaction model is
sufficient for a validation instrument; revisit only if the tool outgrows
it, as its own numbered design.
