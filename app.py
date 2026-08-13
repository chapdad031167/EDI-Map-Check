"""EDI MapCheck — Streamlit UI.

Rendering only: the engine decides, this file draws (Design 013). Identity
lives in .streamlit/config.toml (tokens, fonts) plus assets/styles.css
(chrome removal, wordmark, verdict strip, findings table), injected once.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import html
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from mapcheck.cli import _is_interchange
from mapcheck.engine import (
    InterchangeResult,
    RunResult,
    Status,
    validate_files,
    validate_interchange_files,
)
from mapcheck.output.adapter import OutputLoadError
from mapcheck.report.excel import export_excel
from mapcheck.report.history import RunHistory
from mapcheck.report.html import render_run_html, render_trends_html
from mapcheck.report.regression import RegressionDelta, regress
from mapcheck.report.trends import compute_trends
from mapcheck.spec.overrides import export_spec, resolve_spec
from mapcheck.spec.parser import SpecLoadError, load_spec
from mapcheck.spec.template import build_template
from mapcheck.x12.parser import X12ParseError

ASSETS = Path(__file__).parent / "assets"
EXAMPLES = Path(__file__).parent / "examples"

#: Design 013 tokens, mirrored from .streamlit/config.toml and
#: assets/styles.css. The test suite computes WCAG contrast from these.
TOKENS = {
    "paper": "#F6F8F7",
    "panel": "#EDF1EF",
    "ink": "#1A2421",
    "petrol": "#0F5468",
    "pass": "#1E7A46",
    "fail": "#B42D22",
    "warn": "#8A6100",
    "slate": "#5C6B66",
}

#: scenario -> (spec, source, output)
EXAMPLE_SCENARIOS = {
    "850 clean baseline (all PASS)": (
        "850_reference_spec.xlsx", "850_baseline.edi", "po_baseline.json"),
    "850 defective output (planted mapping bugs)": (
        "850_reference_spec.xlsx", "850_baseline.edi", "po_baseline_defects.json"),
    "850 defective source (bad data, naive translator)": (
        "850_reference_spec.xlsx", "850_defects.edi", "po_from_bad_source.json"),
    "850 minimal PO (optional segments absent)": (
        "850_reference_spec.xlsx", "850_minimal.edi", "po_minimal.json"),
    "850 flat output format": (
        "850_reference_spec.xlsx", "850_baseline.edi", "po_baseline.flat"),
    "856 pick-and-pack ASN (all PASS)": (
        "856_reference_spec.xlsx", "856_pickpack.edi", "asn_pickpack.json"),
    "856 standard-carton ASN (all PASS)": (
        "856_reference_spec.xlsx", "856_standard.edi", "asn_standard.json"),
    "856 defective ASN (HL orphans, bad rollups)": (
        "856_reference_spec.xlsx", "856_defects.edi", "asn_defects.json"),
    "855 PO acknowledgment (accept/reject split)": (
        "855_reference_spec.xlsx", "855_baseline.edi", "poa_baseline.json"),
    "855 defective POA (vanished units, bad status)": (
        "855_reference_spec.xlsx", "855_defects.edi", "poa_defects.json"),
    "810 invoice (clean math)": (
        "810_reference_spec.xlsx", "810_baseline.edi", "invoice_baseline.json"),
    "810 defective invoice (missed allowance)": (
        "810_reference_spec.xlsx", "810_defects.edi", "invoice_defects.json"),
    "940 warehouse ship order (all PASS)": (
        "940_reference_spec.xlsx", "940_baseline.edi", "shiporder_baseline.json"),
    "945 ship advice (declared short-ship)": (
        "945_reference_spec.xlsx", "945_baseline.edi", "shipadvice_baseline.json"),
    "945 defective advice (undeclared short-ship)": (
        "945_reference_spec.xlsx", "945_defects.edi", "shipadvice_defects.json"),
    "943 stock transfer ship (all PASS)": (
        "943_reference_spec.xlsx", "943_baseline.edi", "xfership_baseline.json"),
    "944 stock transfer receipt (all PASS)": (
        "944_reference_spec.xlsx", "944_baseline.edi", "xferreceipt_baseline.json"),
    "947 inventory adjustment (reason codes)": (
        "947_reference_spec.xlsx", "947_baseline.edi", "invadjust_baseline.json"),
    "947 defective adjustment (unknown reason)": (
        "947_reference_spec.xlsx", "947_defects.edi", "invadjust_defects.json"),
    "846 inventory advice (QA/QO/QC buckets)": (
        "846_reference_spec.xlsx", "846_baseline.edi", "invinquiry_baseline.json"),
    "846 defective advice (mystery bucket)": (
        "846_reference_spec.xlsx", "846_defects.edi", "invinquiry_defects.json"),
    "812 credit/debit (signed math)": (
        "812_reference_spec.xlsx", "812_baseline.edi", "creditdebit_baseline.json"),
    "812 defective adjustment (backwards-keyed credit)": (
        "812_reference_spec.xlsx", "812_defects.edi", "creditdebit_defects.json"),
    "867 product transfer report (pharma)": (
        "867_reference_spec.xlsx", "867_baseline.edi", "xferreport_baseline.json"),
    "867 defective report (total lies)": (
        "867_reference_spec.xlsx", "867_defects.edi", "xferreport_defects.json"),
    "844 chargeback request (contract math)": (
        "844_reference_spec.xlsx", "844_baseline.edi", "chargeback_baseline.json"),
    "844 defective chargeback (disputed total)": (
        "844_reference_spec.xlsx", "844_defects.edi", "chargeback_defects.json"),
    "845 price authorization (date window)": (
        "845_reference_spec.xlsx", "845_baseline.edi", "priceauth_baseline.json"),
    "845 defective authorization (inverted window)": (
        "845_reference_spec.xlsx", "845_defects.edi", "priceauth_defects.json"),
    "849 chargeback response (approval statuses)": (
        "849_reference_spec.xlsx", "849_baseline.edi", "cbresponse_baseline.json"),
    "854 delivery discrepancy (reason codes)": (
        "854_reference_spec.xlsx", "854_baseline.edi", "discrepancy_baseline.json"),
    "997 functional acknowledgment (all PASS)": (
        "997_reference_spec.xlsx", "997_baseline.edi", "funcack_baseline.json"),
    "997 defective ack (impossible counts)": (
        "997_reference_spec.xlsx", "997_defects.edi", "funcack_defects.json"),
    "850 to SAP ORDERS05 IDoc flat (clean)": (
        "orders05_reference_spec.xlsx", "850_sap.edi", "orders05_baseline.txt"),
    "850 to SAP ORDERS05 IDoc XML (clean)": (
        "orders05_reference_spec.xlsx", "850_sap.edi", "orders05_baseline.xml"),
    "850 to SAP ORDERS05 defective (flat)": (
        "orders05_reference_spec.xlsx", "850_sap.edi", "orders05_defects.txt"),
    "850 to SAP ORDERS05 defective (XML)": (
        "orders05_reference_spec.xlsx", "850_sap.edi", "orders05_defects.xml"),
    "outbound 855 from POA response (clean)": (
        "855_outbound_reference_spec.xlsx", "poa_response.json", "855_ack_baseline.edi"),
    "outbound 855 defective translation": (
        "855_outbound_reference_spec.xlsx", "poa_response.json", "855_ack_defects.edi"),
    "multi-order interchange (3 x 850, clean)": (
        "850_multi_reference_spec.xlsx", "850_multi_baseline.edi",
        "orders_multi_baseline.json"),
    "multi-order interchange (orphans + dup key)": (
        "850_multi_reference_spec.xlsx", "850_multi_defects.edi",
        "orders_multi_defects.json"),
    "810 to SAP INVOIC02 IDoc flat (clean)": (
        "invoic02_reference_spec.xlsx", "810_sap.edi", "invoic02_baseline.txt"),
    "810 to SAP INVOIC02 defective (XML)": (
        "invoic02_reference_spec.xlsx", "810_sap.edi", "invoic02_defects.xml"),
    "856 to SAP DESADV01 IDoc flat (clean)": (
        "desadv01_reference_spec.xlsx", "856_sap.edi", "desadv01_baseline.txt"),
    "856 to SAP DESADV01 defective (XML)": (
        "desadv01_reference_spec.xlsx", "856_sap.edi", "desadv01_defects.xml"),
}

#: Findings-table columns rendered in mono (X12 refs, ids, wire values).
_MONO_COLUMNS = {"Row ID", "Source", "Target", "Expected", "Actual", "Category"}

_STATUS_CLASS = {
    "PASS": "status-pass",
    "FAIL": "status-fail",
    "WARNING": "status-warning",
    "NOT TESTED": "status-not-tested",
}


def load_css() -> None:
    """Inject the identity stylesheet once at startup."""
    css = (ASSETS / "styles.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def render_verdict_strip(counts: dict[Status, int], result: Status) -> str:
    """The verdict strip: a full-width test-equipment readout.

    Returns the HTML; callers pass it to ``st.markdown(...,
    unsafe_allow_html=True)``. Left edge carries the result color; the
    counts and result render in Plex Mono.
    """
    tone = {
        Status.PASS: "verdict-pass",
        Status.FAIL: "verdict-fail",
        Status.WARNING: "verdict-warning",
    }.get(result, "")
    counts_text = (
        f"{counts[Status.PASS]} PASS / {counts[Status.FAIL]} FAIL / "
        f"{counts[Status.WARNING]} WARNING / "
        f"{counts[Status.NOT_TESTED]} NOT TESTED"
    )
    return (
        f'<div class="verdict-strip {tone}">{counts_text}'
        f'<span class="verdict-result">RESULT: {result.value}</span></div>'
    )


def findings_table_html(frame: pd.DataFrame) -> str:
    """Render a findings DataFrame as a semantic HTML table.

    Status cells show a dot plus the word (never color alone); X12
    reference and value columns render in mono; every cell is escaped.
    """
    columns = list(frame.columns)
    head = "".join(f"<th>{html.escape(col)}</th>" for col in columns)
    rows: list[str] = []
    for record in frame.itertuples(index=False):
        cells: list[str] = []
        for col, value in zip(columns, record):
            text = html.escape(str(value))
            if col == "Status":
                cls = _STATUS_CLASS.get(str(value), "status-not-tested")
                cells.append(
                    f'<td class="status-cell {cls}">'
                    f'<span class="status-dot"></span>{text}</td>'
                )
            elif col in _MONO_COLUMNS:
                cells.append(f'<td class="mono">{text}</td>')
            else:
                cells.append(f"<td>{text}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div class="findings-wrap"><table class="findings">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody>"
        "</table></div>"
    )


def _history_db() -> Path:
    """The history database path — the CLI's default, overridable for
    containers via MAPCHECK_HISTORY_DB (Design 016)."""
    return Path(os.environ.get("MAPCHECK_HISTORY_DB", "mapcheck_history.db"))


def baseline_label(
    spec_path: str, source_path: str, output_path: str, partner_path: str | None = None
) -> str:
    """The app's baseline key, derived from file names only (Design 016).

    Uploads land in fresh temp directories every run, so the CLI's path
    keys can never match here; file names are what stays stable. The
    same formula must be derivable from a stored run row, which is why
    the spec's Meta name does not participate. The CLI reaches the same
    baseline with ``--label`` set to this exact text.
    """
    label = (
        f"{Path(spec_path).name} | {Path(source_path).name} "
        f"-> {Path(output_path).name}"
    )
    if partner_path:
        label = f"{label} | delta: {Path(partner_path).name}"
    return label


def _save_upload(upload, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(upload.getvalue())
        return tmp.name


def _save_upload_named(upload) -> str:
    """Save an upload keeping its original file name (in a fresh temp dir),
    so error messages and reports name the file the user recognizes."""
    directory = Path(tempfile.mkdtemp())
    path = directory / Path(upload.name).name
    path.write_bytes(upload.getvalue())
    return str(path)


def _findings_frame(result: RunResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Status": f.status.value,
                "Row ID": f.row_id or "",
                "Source": f.source_ref,
                "Target": f.target,
                "Expected": f.expected or "",
                "Actual": f.actual or "",
                "Category": f.category.value if f.category else "",
                "Message": f.message,
            }
            for f in result.sorted_findings()
        ]
    )


def _render_findings(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.caption(
            "No findings match the selected statuses. Add PASS to the filter "
            "to see every evaluated row."
        )
        return
    st.markdown(findings_table_html(frame), unsafe_allow_html=True)


def _render_result(result: RunResult) -> None:
    st.subheader("Result")
    if result.transaction_set:
        st.caption(
            f"Detected transaction: `{result.transaction_set}`"
            + (f" — {result.transaction_name}" if result.transaction_name else "")
        )
    st.markdown(
        render_verdict_strip(result.counts, result.overall), unsafe_allow_html=True
    )

    if categories := result.category_counts:
        st.caption(
            "Root causes: "
            + ", ".join(f"`{cat.value}`: {n}" for cat, n in categories.items())
        )

    st.subheader("Findings")
    frame = _findings_frame(result)
    selected = st.multiselect(
        "Show statuses",
        [s.value for s in Status],
        default=["FAIL", "WARNING", "NOT TESTED"],
    )
    _render_findings(frame[frame["Status"].isin(selected)])

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        export_excel(result, tmp.name)
        report_bytes = Path(tmp.name).read_bytes()
    col_xlsx, col_html = st.columns(2)
    with col_xlsx:
        st.download_button(
            "Download Excel report",
            data=report_bytes,
            file_name="mapcheck_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with col_html:
        st.download_button(
            "Download HTML report",
            data=render_run_html(result),
            file_name="mapcheck_report.html",
            mime="text/html",
        )


def main() -> None:
    st.set_page_config(
        page_title="EDI MapCheck",
        page_icon=str(ASSETS / "favicon.png"),
        layout="wide",
    )
    load_css()
    st.markdown('<div class="wordmark">EDI MapCheck</div>', unsafe_allow_html=True)
    pages = st.navigation(
        [
            st.Page(_validate_page, title="Validate", default=True),
            st.Page(_history_page, title="History"),
            st.Page(_draft_page, title="Draft spec"),
            st.Page(_import_page, title="Import"),
            st.Page(_scrub_page, title="Scrub"),
        ]
    )
    pages.run()


def _validate_page() -> None:
    st.markdown(
        "Vendor-neutral validation for EDI mapping work: a **mapping spec**, "
        "the **translation's source file**, and its **translated output** "
        "produce a field-level pass/fail report. Inbound specs validate "
        "X12 to internal (JSON, keyed flat, SAP IDoc); outbound specs "
        "validate internal to X12. The transaction set is auto-detected "
        "from the X12 file's `ST01`."
    )

    with st.sidebar:
        st.header("Inputs")
        use_example = st.toggle("Use bundled example data", value=EXAMPLES.exists())
        spec_path = source_path = output_path = partner_path = None

        if use_example and EXAMPLES.exists():
            scenario = st.selectbox("Scenario", list(EXAMPLE_SCENARIOS))
            spec_name, source_name, output_name = EXAMPLE_SCENARIOS[scenario]
            spec_path = str(EXAMPLES / "specs" / spec_name)
            source_path = str(EXAMPLES / "source" / source_name)
            output_path = str(EXAMPLES / "output" / output_name)
            st.caption(
                f"Spec: `{spec_name}`\n\nSource: `{source_name}`\n\n"
                f"Output: `{output_name}`"
            )
        else:
            spec_upload = st.file_uploader("Mapping spec (.xlsx)", type=["xlsx"])
            partner_upload = st.file_uploader(
                "Partner delta (optional, .xlsx) — merged onto the spec before validating",
                type=["xlsx"],
            )
            source_upload = st.file_uploader(
                "Source file (X12 inbound; internal document outbound)",
                type=["edi", "txt", "x12", "dat", "json", "flat", "xml"],
            )
            output_upload = st.file_uploader(
                "Translated output (internal document inbound; X12 outbound)",
                type=["json", "flat", "txt", "dat", "edi", "x12", "xml"],
            )
            # named saves: history rows and baseline labels carry the
            # file names the user recognizes, not temp gibberish
            if spec_upload:
                spec_path = _save_upload_named(spec_upload)
            if partner_upload:
                partner_path = _save_upload_named(partner_upload)
            if source_upload:
                source_path = _save_upload_named(source_upload)
            if output_upload:
                # a suffix-less output still needs an extension for the
                # format detection; everything else keeps its name
                output_path = (
                    _save_upload_named(output_upload)
                    if Path(output_upload.name).suffix
                    else _save_upload(output_upload, ".flat")
                )

        skip_history = st.toggle(
            "Don't record this run",
            value=False,
            help="Recorded runs feed the History page: baselines, "
            "regression deltas, and trends.",
        )
        st.caption(
            f"Runs record to `{_history_db()}` — the same history the CLI "
            "reads and writes."
        )
        run = st.button(
            "Run validation",
            type="primary",
            disabled=not (spec_path and source_path and output_path),
        )

    if run:
        try:
            merged_spec = None
            merge_notes: list[str] = []
            if partner_path:
                merged_spec, merge_notes = resolve_spec(spec_path, partner_path)
                spec = merged_spec
            else:
                spec = load_spec(spec_path)
            if _is_interchange(spec, source_path, output_path):
                result = validate_interchange_files(
                    spec_path, source_path, output_path, spec=merged_spec
                )
            else:
                result = validate_files(
                    spec_path, source_path, output_path, spec=merged_spec
                )
        except (SpecLoadError, X12ParseError, OutputLoadError) as exc:
            st.error(f"Validation did not run:\n\n```\n{exc}\n```")
            return
        recorded_id = None
        if not skip_history:
            db = _history_db()
            db.parent.mkdir(parents=True, exist_ok=True)
            with RunHistory(db) as history:
                recorded_id = (
                    history.record_interchange(result)
                    if isinstance(result, InterchangeResult)
                    else history.record(result)
                )
        st.session_state["result"] = result
        st.session_state["merge_notes"] = merge_notes
        st.session_state["run_record"] = (
            recorded_id,
            baseline_label(spec_path, source_path, output_path, partner_path),
        )
        if merged_spec is not None:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                export_spec(merged_spec, tmp.name)
                st.session_state["effective_spec"] = Path(tmp.name).read_bytes()
        else:
            st.session_state.pop("effective_spec", None)

    if "result" in st.session_state:
        for note in st.session_state.get("merge_notes", []):
            st.caption(f"Partner merge note: {note}")
        if "effective_spec" in st.session_state:
            st.download_button(
                "Download effective spec (base + partner delta, .xlsx)",
                data=st.session_state["effective_spec"],
                file_name="effective_spec.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        stored = st.session_state["result"]
        if isinstance(stored, InterchangeResult):
            _render_interchange(stored)
        else:
            _render_result(stored)
        record = st.session_state.get("run_record")
        if record is not None:
            _render_regression_strip(record[0], record[1])
    else:
        st.info("Select a scenario or upload a spec, source, and output to begin.")


def draft_preview_html(rows) -> str:
    """Preview the draft: crosswalk-filled rows against amber TODO rows.

    Reuses the findings-table classes — TODO cells render as an amber dot
    plus the word, never color alone. Zero new CSS.
    """
    head = "".join(
        f"<th>{html.escape(col)}</th>"
        for col in ("Row ID", "Source Field", "Loop Context", "Target Field",
                    "Rule Type", "Notes")
    )
    body: list[str] = []
    for row in rows:
        if row.filled:
            rule_cell = f'<td class="mono">{html.escape(row.rule)}</td>'
        else:
            rule_cell = (
                '<td class="status-cell status-warning">'
                '<span class="status-dot"></span>TODO</td>'
            )
        body.append(
            "<tr>"
            f'<td class="mono">{html.escape(row.row_id)}</td>'
            f'<td class="mono">{html.escape(row.source)}</td>'
            f'<td class="mono">{html.escape(row.context)}</td>'
            f'<td class="mono">{html.escape(row.target)}</td>'
            f"{rule_cell}"
            f"<td>{html.escape(row.notes)}</td>"
            "</tr>"
        )
    return (
        '<div class="findings-wrap"><table class="findings">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def _draft_page() -> None:
    from mapcheck.output.idoc import default_output_registry
    from mapcheck.spec.draft import bundled_crosswalks, generate_draft
    from mapcheck.transactions.registry import default_registry

    st.markdown(
        "Generate a draft mapping spec from the built-in definitions: the "
        "structural walk fills what the bundled crosswalk knows, every other "
        "required target becomes a `TODO` row for the analyst, and source "
        "elements no rule references land on the Unmapped Source sheet. "
        "Upload a partner implementation guide and the draft is "
        "partner-flavored: their notes, their code subsets, their "
        "requiredness. The draft loads straight into Validate once curated."
    )

    transactions = [d for d in default_registry.all() if d.elements]
    targets = [f for f in default_output_registry.all() if f.draft_targets]
    if not transactions or not targets:
        st.error(
            "No draftable definitions are registered: a transaction needs an "
            "`elements` dictionary and a target format needs a `draft` block."
        )
        return

    col_tx, col_target = st.columns(2)
    tx_code = col_tx.selectbox(
        "Transaction",
        [d.set_code for d in transactions],
        format_func=lambda code: f"{code} — "
        + next(d.name for d in transactions if d.set_code == code),
    )
    target_format = col_target.selectbox(
        "Target format", [f.format for f in targets]
    )
    override_uploads = st.file_uploader(
        "Crosswalk overrides (optional, .yaml) — layered on the bundled "
        "crosswalk; for the same target path, a later file wins",
        type=["yaml", "yml"],
        accept_multiple_files=True,
    )
    guide_upload = st.file_uploader(
        "Implementation guide (optional, .pdf/.txt in the templated layout, "
        "or a saved guide profile .yaml) — flavors the draft with the "
        "partner's notes, code subsets, and not-used elements",
        type=["pdf", "txt", "yaml", "yml"],
    )
    partner_name = st.text_input(
        "Partner name (with a guide)",
        help="Stamped into the guide profile; findings from its rules name "
        "this partner. A profile upload keeps the name it was saved with.",
    )
    fill_unmapped = st.toggle(
        "Include optional targets as TODO rows",
        help="The draft always carries every required target. This adds the "
        "optional ones too, so the sheet shows the complete target universe.",
    )

    if st.button("Draft spec", type="primary"):
        from mapcheck.guides.parser import GuideParseError, parse_guide
        from mapcheck.guides.profile import GuideProfile, GuideProfileError
        from mapcheck.spec.draft import CrosswalkError, DraftSpecError

        definition = default_registry.get(tx_code)
        target_def = default_output_registry.get(target_format)
        short_target = target_format.rsplit("-", 1)[-1]
        crosswalks = [
            *bundled_crosswalks(tx_code, short_target),
            *(_save_upload_named(upload) for upload in override_uploads or []),
        ]
        try:
            guide = None
            if guide_upload is not None:
                guide_path = Path(_save_upload_named(guide_upload))
                if guide_path.suffix.lower() in (".yaml", ".yml"):
                    guide = GuideProfile.load(guide_path)
                else:
                    guide = parse_guide(
                        guide_path,
                        transaction=tx_code,
                        partner=partner_name.strip(),
                    )
                if guide.transaction != tx_code:
                    st.error(
                        f"The guide profile is for transaction set "
                        f"{guide.transaction} but the draft is a {tx_code}."
                    )
                    return
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                result = generate_draft(
                    definition,
                    target_def,
                    crosswalks,
                    tmp.name,
                    include_optional_todos=fill_unmapped,
                    guide=guide,
                )
                st.session_state["draft"] = (
                    result,
                    Path(tmp.name).read_bytes(),
                    f"draft_{tx_code}_{short_target}.xlsx",
                    guide,
                )
        except (CrosswalkError, DraftSpecError, GuideParseError, GuideProfileError) as exc:
            st.error(f"Draft did not run:\n\n```\n{exc}\n```")
            return

    if "draft" not in st.session_state:
        st.info("Select a transaction and a target format, then run Draft spec.")
        _render_template_download()
        return

    result, draft_bytes, file_name, guide = st.session_state["draft"]
    filled = sum(1 for row in result.rows if row.filled)
    tone = "verdict-pass" if result.prefill >= 0.70 else "verdict-warning"
    st.markdown(
        f'<div class="verdict-strip {tone}">{filled} FILLED / '
        f"{result.todo_count} TODO / {len(result.unmapped_source)} UNMAPPED SOURCE"
        f'<span class="verdict-result">PREFILL: {result.prefill:.2f}</span></div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Prefill = filled required targets / total required targets "
        f"({result.filled_required}/{result.total_required}). "
        f"Crosswalk: `{', '.join(Path(f).name for f in result.crosswalk_files) or '(none)'}`"
    )
    if guide is not None:
        partner_label = guide.partner or "(unnamed partner)"
        st.caption(
            f"Guide: `{guide.source or '(uploaded)'}` for `{partner_label}` — "
            f"parse coverage {guide.parse_coverage:.2f} "
            f"({guide.facts_confident}/{guide.facts_detected} facts). "
            "Not-used elements left Unmapped Source; code lists carry only "
            "the partner's codes."
        )
    st.markdown(draft_preview_html(result.rows), unsafe_allow_html=True)
    review_notes = [
        *(f"Guide parse: {note}" for note in (guide.review if guide else [])),
        *result.guide_review,
    ]
    if review_notes:
        st.subheader(f"Needs review ({len(review_notes)})")
        st.caption(
            "Facts the guide parse would not swear to, and decisions the "
            "draft cannot settle mechanically. Each one is a human call."
        )
        st.markdown(guide_review_table_html(review_notes), unsafe_allow_html=True)
    st.download_button(
        "Download draft (.xlsx)",
        data=draft_bytes,
        file_name=file_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    if guide is not None:
        partner_slug = (guide.partner or "partner").replace(" ", "_")
        st.download_button(
            "Download guide profile (.yaml)",
            data=yaml.safe_dump(guide.to_dict(), sort_keys=False, allow_unicode=True),
            file_name=f"{partner_slug}_{result.transaction}_profile.yaml",
            mime="text/yaml",
            help="The reviewable record of what the guide asserted — re-upload "
            "it here later instead of re-parsing the guide.",
        )
    _render_template_download()


def _render_template_download() -> None:
    """Blank spec template, for specs written from scratch."""
    import io

    st.caption(
        "Prefer to transcribe by hand: download the blank spec template — "
        "it carries the Instructions sheet with the full addressing and "
        "condition grammar."
    )
    col_direction, col_button = st.columns([1, 2])
    direction = col_direction.selectbox(
        "Template direction", ["inbound", "outbound"],
        help="inbound validates X12 to internal; outbound validates internal to X12",
    )
    buffer = io.BytesIO()
    build_template(direction).save(buffer)
    col_button.download_button(
        "Download blank spec template (.xlsx)",
        data=buffer.getvalue(),
        file_name=f"mapcheck_spec_template_{direction}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def worklist_table_html(rows) -> str:
    """The needs-a-human worklist: one amber row per human decision.

    Reuses the findings-table classes; the status cell is a dot plus the
    word REVIEW, never color alone. Zero new CSS.
    """
    head = "".join(
        f"<th>{html.escape(col)}</th>"
        for col in ("Row ID", "Source Field", "Target Field", "Rule Type",
                    "What needs deciding")
    )
    body: list[str] = []
    for row in rows:
        rule = row.values.get("Rule Type", "") or "(unclassified)"
        body.append(
            "<tr>"
            f'<td class="mono">{html.escape(row.row_id)}</td>'
            f'<td class="mono">{html.escape(row.values.get("Source Field", ""))}</td>'
            f'<td class="mono">{html.escape(row.values.get("Target Field", ""))}</td>'
            '<td class="status-cell status-warning">'
            f'<span class="status-dot"></span>{html.escape(rule)}</td>'
            f"<td>{html.escape(row.reason)}</td>"
            "</tr>"
        )
    return (
        '<div class="findings-wrap"><table class="findings">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def guide_review_table_html(notes: list[str]) -> str:
    """Guide review entries in the worklist pattern: one amber row per
    human decision. Reuses the findings-table classes; zero new CSS."""
    head = "".join(
        f"<th>{html.escape(col)}</th>" for col in ("Status", "What needs deciding")
    )
    body = "".join(
        "<tr>"
        '<td class="status-cell status-warning">'
        '<span class="status-dot"></span>REVIEW</td>'
        f"<td>{html.escape(note)}</td>"
        "</tr>"
        for note in notes
    )
    return (
        '<div class="findings-wrap"><table class="findings">'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody>"
        "</table></div>"
    )


def _import_page() -> None:
    from mapcheck.cli import _parse_map_overrides
    from mapcheck.spec.importer import (
        ImportError_,
        import_mapping,
        write_workbook,
        write_worklist,
    )
    from mapcheck.transactions.registry import default_registry

    st.markdown(
        "Bring a partner's existing mapping spreadsheet into the native "
        "template. The importer locates their columns, auto-classifies every "
        "rule the evidence supports, and flags — never silently guesses — "
        "what needs a human. You finish the short worklist below instead of "
        "retyping the whole spec, then validate as usual."
    )

    upload = st.file_uploader(
        "Partner mapping document (.xlsx or .csv)", type=["xlsx", "csv"]
    )
    code_lists_upload = st.file_uploader(
        "Lookup-table document (optional, .xlsx or .csv) — imported into the "
        "CodeLists sheet",
        type=["xlsx", "csv"],
    )
    with st.expander("Import options"):
        col_tx, col_direction = st.columns(2)
        tx_choice = col_tx.selectbox(
            "Transaction Set (Meta)",
            ["(from the document)"] + [d.set_code for d in default_registry.all()],
        )
        direction_choice = col_direction.selectbox(
            "Direction (Meta)", ["(from the document)", "inbound", "outbound"]
        )
        spec_name = st.text_input("Spec Name (Meta)")
        map_override = st.text_input(
            "Column mapping override",
            help="Only when detection picks the wrong columns. Same grammar as "
            "the CLI --map flag: Source Field=B, Target Field=E "
            "(header name or column letter).",
        )

    if st.button("Import mapping", type="primary", disabled=upload is None):
        meta: dict[str, str] = {}
        if tx_choice != "(from the document)":
            meta["Transaction Set"] = tx_choice
        if direction_choice != "(from the document)":
            meta["Direction"] = direction_choice
        if spec_name:
            meta["Spec Name"] = spec_name
        try:
            overrides = _parse_map_overrides(map_override or None)
            result = import_mapping(
                _save_upload_named(upload),
                overrides=overrides,
                meta=meta,
                code_lists_path=(
                    _save_upload_named(code_lists_upload) if code_lists_upload else None
                ),
            )
        except (ImportError_, ValueError) as exc:
            st.error(f"Import did not run:\n\n```\n{exc}\n```")
            return
        stem = Path(upload.name).stem
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            write_workbook(result, tmp.name)
            spec_bytes = Path(tmp.name).read_bytes()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
            write_worklist(result, tmp.name)
            worklist_bytes = Path(tmp.name).read_bytes()
        st.session_state["import"] = (result, spec_bytes, worklist_bytes, stem)

    if "import" not in st.session_state:
        st.info(
            "Upload a partner mapping document, adjust the options if the "
            "defaults misread it, then run Import mapping."
        )
        return

    result, spec_bytes, worklist_bytes, stem = st.session_state["import"]
    classified = len(result.rows) - len(result.review_rows)
    tone = "verdict-pass" if not result.review_rows else "verdict-warning"
    st.markdown(
        f'<div class="verdict-strip {tone}">{len(result.rows)} ROWS / '
        f"{classified} AUTO-CLASSIFIED / {len(result.review_rows)} NEED REVIEW"
        f'<span class="verdict-result">CLASSIFIED: '
        f"{result.auto_classified_ratio:.2f}</span></div>",
        unsafe_allow_html=True,
    )
    mapped = ", ".join(f"{ours} from `{theirs}`" for ours, theirs in result.column_mapping.items())
    st.caption(f"Column mapping: {mapped}")
    if result.unmapped_columns:
        st.caption(
            "Their columns carrying data that matched no MapCheck column "
            "(dropped, nothing lost silently): "
            + ", ".join(f"`{c}`" for c in result.unmapped_columns)
        )

    if result.review_rows:
        st.subheader("Worklist")
        st.caption(
            "These rows load into the spec flagged NEEDS REVIEW — finish them "
            "in the downloaded workbook before the spec will validate."
        )
        st.markdown(worklist_table_html(result.review_rows), unsafe_allow_html=True)
    else:
        st.caption("No rows need review — the imported spec is ready to load.")

    col_spec, col_worklist = st.columns(2)
    with col_spec:
        st.download_button(
            "Download native spec (.xlsx)",
            data=spec_bytes,
            file_name=f"{stem}_mapcheck_spec.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with col_worklist:
        st.download_button(
            "Download worklist (.txt)",
            data=worklist_bytes,
            file_name=f"{stem}_worklist.txt",
            mime="text/plain",
        )


def _scrub_page() -> None:
    from importlib import resources

    from mapcheck.scrub import ProfileError, load_profile
    from mapcheck.scrub.scrubber import scrub_file

    st.markdown(
        "Mask sensitive values in an X12 file while preserving structure, "
        "lengths, and referential consistency — the same input value always "
        "masks to the same output value, so control numbers and pairing keys "
        "survive. Use it to turn a real partner file into a safe test case."
    )

    upload = st.file_uploader(
        "X12 file to scrub", type=["edi", "txt", "x12", "dat"]
    )
    bundled = sorted(
        entry.name[: -len(".yaml")]
        for entry in (resources.files("mapcheck.scrub") / "profiles").iterdir()
        if entry.name.endswith(".yaml")
    )
    col_profile, col_seed = st.columns(2)
    profile_name = col_profile.selectbox(
        "Profile", bundled,
        help="Which elements get masked. Bundled profiles ship with the tool; "
        "upload a custom one below to override.",
    )
    seed = col_seed.text_input(
        "Seed (optional)",
        help="Same seed plus same input produces the same masked output — "
        "use one when a partner needs reproducible test data.",
    )
    profile_upload = st.file_uploader("Custom profile (optional, .yaml)", type=["yaml", "yml"])

    if st.button("Scrub file", type="primary", disabled=upload is None):
        try:
            profile = load_profile(
                _save_upload_named(profile_upload) if profile_upload else profile_name
            )
            source_path = Path(_save_upload_named(upload))
            out_path = source_path.with_suffix(f".scrubbed{source_path.suffix}")
            written, report = scrub_file(source_path, out_path, profile, seed=seed or None)
            st.session_state["scrub"] = (
                written.read_bytes(),
                written.name,
                report.render(),
            )
        except (ProfileError, ValueError, OSError) as exc:
            st.error(f"Scrub did not run:\n\n```\n{exc}\n```")
            return

    if "scrub" not in st.session_state:
        st.info("Upload an X12 file and pick a profile, then run Scrub file.")
        return

    scrubbed_bytes, scrubbed_name, report_text = st.session_state["scrub"]
    st.download_button(
        "Download scrubbed file",
        data=scrubbed_bytes,
        file_name=scrubbed_name,
        mime="text/plain",
    )
    st.caption("Masking report")
    st.code(report_text)


def delta_table_html(delta: RegressionDelta) -> str:
    """The regression delta in the findings-table pattern: change kind as
    a dot-plus-word status cell, regressions first. Zero new CSS."""
    head = "".join(
        f"<th>{html.escape(col)}</th>" for col in ("Change", "Where", "Detail")
    )
    body: list[str] = []
    for change in sorted(delta.changes, key=lambda c: not c.regression):
        if change.regression:
            tone = "status-fail"
        elif change.kind == "RESOLVED":
            tone = "status-pass"
        else:
            tone = "status-warning"
        body.append(
            "<tr>"
            f'<td class="status-cell {tone}">'
            f'<span class="status-dot"></span>{html.escape(change.kind)}</td>'
            f'<td class="mono">{html.escape(change.where)}</td>'
            f"<td>{html.escape(change.detail)}</td>"
            "</tr>"
        )
    return (
        '<div class="findings-wrap"><table class="findings">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def regression_strip_html(delta: RegressionDelta, baseline_run_id: int) -> str:
    """Verdict strip for a delta: regressions decide the tone."""
    new = len(delta.of_kind("NEW"))
    resolved = len(delta.of_kind("RESOLVED"))
    changed = len(delta.changes) - new - resolved
    if delta.is_empty:
        tone, text = "verdict-pass", "NO CHANGES"
    elif delta.is_regression:
        tone = "verdict-fail"
        text = f"{len(delta.regressions)} REGRESSION(S) — {new} NEW / {resolved} RESOLVED / {changed} CHANGED"
    else:
        tone = "verdict-pass"
        text = f"NO REGRESSIONS — {new} NEW / {resolved} RESOLVED / {changed} CHANGED"
    return (
        f'<div class="verdict-strip {tone}">{text}'
        f'<span class="verdict-result">VS BASELINE RUN #{baseline_run_id}</span></div>'
    )


def _render_regression_strip(run_id: int | None, label: str) -> None:
    """After a recorded run: the delta vs its baseline, or the offer to
    become one (Design 016). Comparing is automatic; blessing is a click."""
    st.subheader("Vs baseline")
    if run_id is None:
        st.caption("This run was not recorded, so there is nothing to compare.")
        return
    db = _history_db()
    with RunHistory(db) as history:
        baseline = history.baseline_for(label)
        if baseline is not None and baseline["run_id"] == run_id:
            st.caption(f"This run is the blessed baseline for `{label}`.")
            return
        if baseline is not None:
            delta = regress(history, baseline["run_id"], run_id)
            st.markdown(
                regression_strip_html(delta, baseline["run_id"]),
                unsafe_allow_html=True,
            )
            if delta.is_empty:
                st.caption(
                    f"Identical findings to baseline run #{baseline['run_id']} "
                    f"(`{label}`)."
                )
            else:
                st.markdown(delta_table_html(delta), unsafe_allow_html=True)
            st.caption(
                "A better run can take over as the baseline from the "
                "History page."
            )
            return
    st.caption(
        f"No baseline for `{label}` yet. Bless this run and every future "
        "run of the same files reports only what changed."
    )
    name = st.text_input(
        "Baseline name (optional)",
        help="A display name for the History page. Matching always uses "
        "the derived label above; the CLI reaches it with --label.",
    )
    if st.button("Bless this run as baseline"):
        with RunHistory(db) as history:
            history.bless(run_id, label, label=name.strip() or None)
        st.rerun()


def _stored_findings_frame(rows: list[dict]) -> pd.DataFrame:
    """Findings from the history database, in the live findings-frame
    shape so the same table renderer draws them."""
    return pd.DataFrame(
        [
            {
                "Status": r["status"],
                "Row ID": r["row_id"] or "",
                "Source": r["source_ref"] or "",
                "Target": r["target"] or "",
                "Expected": r["expected"] or "",
                "Actual": r["actual"] or "",
                "Category": r["category"] or "",
                "Message": r["message"],
            }
            for r in rows
        ]
    )


def runs_table_html(runs: list[dict], blessed: dict[int, dict], children: dict[int, int]) -> str:
    """Recent runs in the findings-table pattern: result as a dot-plus-word
    status cell, a BASELINE marker on blessed runs. Zero new CSS."""
    head = "".join(
        f"<th>{html.escape(col)}</th>"
        for col in ("Run", "When (UTC)", "Result", "P / F / W / NT", "Files", "Baseline")
    )
    tones = {"PASS": "status-pass", "FAIL": "status-fail", "WARNING": "status-warning"}
    body: list[str] = []
    for run in runs:
        files = f"{Path(run['source_file']).name} -> {Path(run['output_file']).name}"
        if children.get(run["id"]):
            files = f"{files} ({children[run['id']]} documents)"
        tone = tones.get(run["result"], "status-warning")
        if run["id"] in blessed:
            marker = (
                '<td class="status-cell status-pass">'
                '<span class="status-dot"></span>BASELINE</td>'
            )
        else:
            marker = "<td></td>"
        body.append(
            "<tr>"
            f'<td class="mono">#{run["id"]}</td>'
            f'<td class="mono">{html.escape(str(run["run_at"]))}</td>'
            f'<td class="status-cell {tone}">'
            f'<span class="status-dot"></span>{html.escape(str(run["result"]))}</td>'
            f'<td class="mono">{run["passed"]} / {run["failed"]} / '
            f'{run["warnings"]} / {run["not_tested"]}</td>'
            f'<td class="mono">{html.escape(files)}</td>'
            f"{marker}"
            "</tr>"
        )
    return (
        '<div class="findings-wrap"><table class="findings">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def _history_page() -> None:
    st.markdown(
        "Every recorded validation run, in one place: open a run's "
        "findings, bless a run as the **baseline** its future runs are "
        "measured against, and read the trends. The Validate page "
        "compares each recorded run to its baseline automatically."
    )
    db = _history_db()
    if not db.exists():
        st.info(
            "No runs recorded yet — run a validation on the Validate page "
            "and it lands here."
        )
        return
    with RunHistory(db) as history:
        runs = history.recent_runs(limit=50)
        blessed = {b["run_id"]: b for b in history.baselines()}
        if not runs:
            st.info(
                "No runs recorded yet — run a validation on the Validate "
                "page and it lands here."
            )
            return
        children_count: dict[int, int] = {}
        for run in runs:
            if run.get("interchange_id"):
                children_count[run["interchange_id"]] = (
                    children_count.get(run["interchange_id"], 0) + 1
                )
        parents = [r for r in runs if not r.get("interchange_id")]

        st.subheader(f"Recent runs ({len(parents)})")
        st.markdown(
            runs_table_html(parents, blessed, children_count),
            unsafe_allow_html=True,
        )

        options = {
            f"Run #{r['id']} — {r['result']} — "
            f"{Path(r['source_file']).name} -> {Path(r['output_file']).name} "
            f"({r['run_at']})": r
            for r in parents
        }
        choice = st.selectbox("Open a run", list(options))
        run_row = options[choice]

        st.subheader(f"Run #{run_row['id']}")
        counts = {
            Status.PASS: run_row["passed"],
            Status.FAIL: run_row["failed"],
            Status.WARNING: run_row["warnings"],
            Status.NOT_TESTED: run_row["not_tested"],
        }
        try:
            overall = Status(run_row["result"])
        except ValueError:
            overall = Status.NOT_TESTED
        st.markdown(render_verdict_strip(counts, overall), unsafe_allow_html=True)

        detail_id = run_row["id"]
        child_rows = history.child_runs(run_row["id"])
        if child_rows:
            doc = st.selectbox(
                "Document",
                ["(file-level findings)"] + [c["document_key"] or "?" for c in child_rows],
            )
            if doc != "(file-level findings)":
                detail_id = next(
                    c["id"] for c in child_rows if (c["document_key"] or "?") == doc
                )
        frame = _stored_findings_frame(history.findings_for(detail_id))
        if frame.empty:
            st.caption("No findings were recorded for this run.")
        else:
            selected = st.multiselect(
                "Show statuses",
                sorted(frame["Status"].unique()),
                default=[
                    s for s in ("FAIL", "WARNING", "NOT TESTED")
                    if s in set(frame["Status"])
                ],
            )
            shown = frame[frame["Status"].isin(selected)]
            if shown.empty:
                st.caption(
                    "No findings match the selected statuses. Add PASS to "
                    "the filter to see every evaluated row."
                )
            else:
                st.markdown(findings_table_html(shown), unsafe_allow_html=True)

        st.subheader("Baseline")
        derived = baseline_label(
            run_row["spec_file"], run_row["source_file"], run_row["output_file"]
        )
        held = blessed.get(run_row["id"])
        if held is not None:
            shown_name = held["label"] or held["baseline_key"]
            st.caption(f"This run is the blessed baseline for `{shown_name}`.")
        key_value = st.text_input(
            "Baseline label (the key future runs must derive)",
            value=derived,
            help="Runs made with a partner delta append "
            "' | delta: <file name>' — bless those from the Validate page "
            "right after running to get the exact label automatically. "
            "The CLI reaches this baseline with --label.",
        )
        previous = history.baseline_for(key_value.strip()) if key_value.strip() else None
        if previous is not None and previous["run_id"] != run_row["id"]:
            st.caption(
                f"Blessing replaces the baseline currently held by run "
                f"#{previous['run_id']}."
            )
        if st.button("Bless as baseline", disabled=not key_value.strip()):
            history.bless(run_row["id"], key_value.strip())
            st.rerun()

        st.subheader("Trends")
        trends = compute_trends(history)
        if trends.is_empty:
            st.caption("Trends appear after the first recorded runs.")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Runs", trends.total_runs)
            c2.metric("Overall pass rate", f"{trends.overall_pass_rate:.0%}")
            c3.metric("Specs tracked", trends.distinct_specs)
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Spec": s.spec,
                            "Pass rate": f"{s.pass_rate:.0%}",
                            "Runs": s.total,
                            "Latest": s.latest,
                        }
                        for s in trends.specs
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
            if trends.top_categories:
                st.caption("Top root causes")
                st.bar_chart(
                    pd.DataFrame(trends.top_categories, columns=["category", "count"])
                    .set_index("category")
                )
            st.download_button(
                "Download trends report (HTML)",
                data=render_trends_html(trends),
                file_name="mapcheck_trends.html",
                mime="text/html",
            )
    st.download_button(
        "Download history database (.db)",
        data=db.read_bytes(),
        file_name="mapcheck_history.db",
        mime="application/x-sqlite3",
        help="The raw SQLite file — every run, finding, and baseline. "
        "In Docker it lives on a named volume; this button is how you "
        "hold it in your hand.",
    )
    st.caption(f"History database: `{db.resolve()}`")


def _render_interchange(result: InterchangeResult) -> None:
    st.subheader("Interchange result")
    st.caption(f"{len(result.documents)} documents paired")
    st.markdown(
        render_verdict_strip(result.counts, result.overall), unsafe_allow_html=True
    )

    if categories := result.category_counts:
        st.caption(
            "Root causes: "
            + ", ".join(f"`{cat.value}`: {n}" for cat, n in categories.items())
        )

    if result.file_findings:
        st.subheader("File-level findings (pairing)")
        file_result = RunResult(
            spec_path="", source_path="", output_path="", findings=result.file_findings
        )
        _render_findings(_findings_frame(file_result))

    st.subheader("Documents")
    for document in result.documents:
        overall = document.result.overall.value
        with st.expander(f"{document.key} — {document.source_ref} — {overall}"):
            _render_findings(_findings_frame(document.result))


if __name__ == "__main__":
    main()
