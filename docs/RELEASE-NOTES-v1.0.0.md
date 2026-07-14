# EDI MapCheck v1.0.0

**The first stable release.** EDI MapCheck answers one question that EDI teams
otherwise answer by hand: *does this translated file actually match what the
mapping spec says the X12 source should produce?* Point it at a **spec**, an
**X12 source**, and the **translated output**, and get a field-level pass/fail
report — vendor-neutral, in either direction, across **17 transaction sets**,
with a meaningful exit code for CI.

## Highlights

- ✅ **Validate any of 17 X12 sets** (810, 812, 844, 845, 846, 849, 850, 854,
  855, 856, 867, 940, 943–947, 997) — auto-detected from `ST01`.
- 🔁 **Both directions & many formats** — X12 → JSON / keyed-flat / SAP IDoc
  (ORDERS05 · DESADV01 · INVOIC02) / your own YAML-defined layout, and internal
  → X12. Multi-transaction interchanges paired by a spec-declared key.
- 🧩 **Real-world workflows** — import a partner's mapping doc, layer per-partner
  overrides, freeze **golden baselines** and gate on regressions, and express
  tolerances / date math / external lookups right in the spec.
- 🤖 **CI-native** — `mapcheck batch` runs a whole `mapcheck.yaml` manifest and
  emits **JUnit-XML**; exit codes are `0` pass · `1` findings · `2` error.
- 🧼 **Data scrubber** — turn a real X12 file into a shareable test case by
  masking names / addresses / DEA-HIN-NDC-shaped ids while keeping structure,
  lengths, and referential consistency intact.
- 📤 **Shareable reports** — terminal, Excel, and a single-file **HTML report**
  (dependency-free, mail-safe), plus **history trends** (pass-rate per spec,
  top root causes).
- 🖥️ **Run it as an app** — `docker compose up` → a browser URL, no terminal.
  `$PORT`-aware for Cloud Run / Render / Railway / Fly.io; image on GHCR;
  Streamlit Community Cloud & `pipx` documented.

## Run it in 30 seconds

```bash
# as an app (no terminal)
docker compose up            # then open http://localhost:8501

# or the CLI
pipx install "git+https://github.com/chapdad031167/EDI-Map-Check.git"
mapcheck validate --spec spec.xlsx --source po.edi --output out.json --export-html report.html
```

Container image:

```bash
docker run -p 8501:8501 ghcr.io/chapdad031167/edi-map-check:1.0.0
```

## Quality & security

- **611 tests** over a **fully synthetic** example set (no proprietary or
  partner data).
- Hardened against report/parse abuse: spreadsheet **formula injection**,
  **decimal-expansion** and **XML-entity-bomb** DoS, and batch runs that keep
  going when one check fails.

## Requirements

- Python ≥ 3.11 (for the CLI / from source). No Python needed to run the
  container.

## Full detail

See [`CHANGELOG.md`](https://github.com/chapdad031167/EDI-Map-Check/blob/main/CHANGELOG.md)
and the design docs in [`docs/design/`](https://github.com/chapdad031167/EDI-Map-Check/tree/main/docs/design).

**Full Changelog**: https://github.com/chapdad031167/EDI-Map-Check/commits/v1.0.0
