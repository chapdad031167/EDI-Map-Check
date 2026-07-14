"""EDI MapCheck — Streamlit UI.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

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
from mapcheck.report.trends import compute_trends
from mapcheck.spec.parser import SpecLoadError, load_spec
from mapcheck.x12.parser import X12ParseError

EXAMPLES = Path(__file__).parent / "examples"

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

_STATUS_COLORS = {
    "PASS": "background-color: #c6efce; color: #006100",
    "FAIL": "background-color: #ffc7ce; color: #9c0006",
    "WARNING": "background-color: #ffeb9c; color: #9c6500",
    "NOT TESTED": "background-color: #d9d9d9; color: #595959",
}


def _save_upload(upload, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(upload.getvalue())
        return tmp.name


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


def _render_result(result: RunResult) -> None:
    counts = result.counts
    overall = result.overall.value

    st.subheader("Result")
    if result.transaction_set:
        st.caption(
            f"Detected transaction: **{result.transaction_set}"
            + (f" — {result.transaction_name}**" if result.transaction_name else "**")
        )
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Overall", overall)
    m2.metric("PASS", counts[Status.PASS])
    m3.metric("FAIL", counts[Status.FAIL])
    m4.metric("WARNING", counts[Status.WARNING])
    m5.metric("NOT TESTED", counts[Status.NOT_TESTED])

    if result.overall is Status.PASS:
        st.success("Output matches the mapping spec.")
    elif result.overall is Status.FAIL:
        st.error("Output does not match the mapping spec — see findings below.")
    else:
        st.warning("Output matches, with warnings.")

    if categories := result.category_counts:
        st.caption(
            "Root causes: "
            + ", ".join(f"{cat.value}: {n}" for cat, n in categories.items())
        )

    st.subheader("Findings")
    frame = _findings_frame(result)
    selected = st.multiselect(
        "Show statuses",
        [s.value for s in Status],
        default=["FAIL", "WARNING", "NOT TESTED"],
    )
    filtered = frame[frame["Status"].isin(selected)]
    st.dataframe(
        filtered.style.map(
            lambda v: _STATUS_COLORS.get(v, ""), subset=["Status"]
        ),
        use_container_width=True,
        hide_index=True,
        height=420,
    )

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
    st.set_page_config(page_title="EDI MapCheck", page_icon="✅", layout="wide")
    st.title("EDI MapCheck")
    st.markdown(
        "Vendor-neutral validation for EDI mapping work: upload a **mapping spec**, "
        "the **translation's source file**, and its **translated output** — get a "
        "field-level pass/fail report. Inbound specs validate X12 → internal "
        "(JSON, keyed flat, SAP IDoc); outbound specs validate internal → X12. "
        "The transaction set is auto-detected from the X12 file's ST01."
    )

    with st.sidebar:
        st.header("Inputs")
        use_example = st.toggle("Use bundled example data", value=EXAMPLES.exists())
        spec_path = source_path = output_path = None

        if use_example and EXAMPLES.exists():
            scenario = st.selectbox("Scenario", list(EXAMPLE_SCENARIOS))
            spec_name, source_name, output_name = EXAMPLE_SCENARIOS[scenario]
            spec_path = str(EXAMPLES / "specs" / spec_name)
            source_path = str(EXAMPLES / "source" / source_name)
            output_path = str(EXAMPLES / "output" / output_name)
            st.caption(f"Spec: {spec_name}\n\nSource: {source_name}\n\nOutput: {output_name}")
        else:
            spec_upload = st.file_uploader("Mapping spec (.xlsx)", type=["xlsx"])
            source_upload = st.file_uploader(
                "Source file (X12 inbound; internal document outbound)",
                type=["edi", "txt", "x12", "dat", "json", "flat", "xml"],
            )
            output_upload = st.file_uploader(
                "Translated output (internal document inbound; X12 outbound)",
                type=["json", "flat", "txt", "dat", "edi", "x12", "xml"],
            )
            if spec_upload:
                spec_path = _save_upload(spec_upload, ".xlsx")
            if source_upload:
                # keep the original extension so the right loader is picked
                source_path = _save_upload(
                    source_upload, Path(source_upload.name).suffix or ".edi"
                )
            if output_upload:
                output_path = _save_upload(
                    output_upload, Path(output_upload.name).suffix or ".flat"
                )

        run = st.button(
            "Run validation",
            type="primary",
            disabled=not (spec_path and source_path and output_path),
        )

    if run:
        try:
            spec = load_spec(spec_path)
            if _is_interchange(spec, source_path, output_path):
                result = validate_interchange_files(spec_path, source_path, output_path)
            else:
                result = validate_files(spec_path, source_path, output_path)
        except (SpecLoadError, X12ParseError, OutputLoadError) as exc:
            st.error(f"Could not run validation:\n\n```\n{exc}\n```")
            return
        st.session_state["result"] = result

    if "result" in st.session_state:
        stored = st.session_state["result"]
        if isinstance(stored, InterchangeResult):
            _render_interchange(stored)
        else:
            _render_result(stored)
    else:
        st.info("Choose the three inputs in the sidebar, then hit **Run validation**.")

    _render_trends()


def _render_trends() -> None:
    """History-trends panel, shown when a history DB exists in the cwd."""
    db = Path("mapcheck_history.db")
    if not db.exists():
        return
    with RunHistory(db) as history:
        trends = compute_trends(history)
    if trends.is_empty:
        return
    with st.expander("📈 History trends", expanded=False):
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


def _render_interchange(result: InterchangeResult) -> None:
    counts = result.counts
    st.subheader("Interchange result")
    st.caption(f"**{len(result.documents)}** documents paired")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Overall", result.overall.value)
    m2.metric("PASS", counts[Status.PASS])
    m3.metric("FAIL", counts[Status.FAIL])
    m4.metric("WARNING", counts[Status.WARNING])
    m5.metric("NOT TESTED", counts[Status.NOT_TESTED])

    if result.overall is Status.PASS:
        st.success("Every document matches the mapping spec and all pair up.")
    elif result.overall is Status.FAIL:
        st.error("The interchange has failures — see the document and file-level findings.")
    else:
        st.warning("The interchange matches, with warnings.")

    if categories := result.category_counts:
        st.caption(
            "Root causes: "
            + ", ".join(f"{cat.value}: {n}" for cat, n in categories.items())
        )

    if result.file_findings:
        st.subheader("File-level findings (pairing)")
        file_result = RunResult(
            spec_path="", source_path="", output_path="", findings=result.file_findings
        )
        st.dataframe(
            _findings_frame(file_result).style.map(
                lambda v: _STATUS_COLORS.get(v, ""), subset=["Status"]
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("Documents")
    for document in result.documents:
        overall = document.result.overall.value
        icon = {"PASS": "✅", "FAIL": "❌", "WARNING": "⚠️"}.get(overall, "•")
        with st.expander(f"{icon} {document.key} — {document.source_ref} — {overall}"):
            frame = _findings_frame(document.result)
            st.dataframe(
                frame.style.map(
                    lambda v: _STATUS_COLORS.get(v, ""), subset=["Status"]
                ),
                use_container_width=True,
                hide_index=True,
            )


if __name__ == "__main__":
    main()
