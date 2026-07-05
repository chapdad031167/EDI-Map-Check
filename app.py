"""EDI MapCheck — Streamlit UI.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from mapcheck.engine import RunResult, Status, validate_files
from mapcheck.output.adapter import OutputLoadError
from mapcheck.report.excel import export_excel
from mapcheck.spec.parser import SpecLoadError
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
    st.download_button(
        "Download Excel report",
        data=report_bytes,
        file_name="mapcheck_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def main() -> None:
    st.set_page_config(page_title="EDI MapCheck", page_icon="✅", layout="wide")
    st.title("EDI MapCheck")
    st.markdown(
        "Vendor-neutral validation for EDI mapping work: upload a **mapping spec**, "
        "an **X12 850 source**, and the **translated output** — get a field-level "
        "pass/fail report."
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
            source_upload = st.file_uploader("X12 850 source", type=["edi", "txt", "x12", "dat"])
            output_upload = st.file_uploader(
                "Translated output (.json or keyed flat)", type=["json", "flat", "txt", "dat"]
            )
            if spec_upload:
                spec_path = _save_upload(spec_upload, ".xlsx")
            if source_upload:
                source_path = _save_upload(source_upload, ".edi")
            if output_upload:
                # keep the original extension so the adapter picks JSON vs flat
                output_path = _save_upload(output_upload, Path(output_upload.name).suffix or ".flat")

        run = st.button(
            "Run validation",
            type="primary",
            disabled=not (spec_path and source_path and output_path),
        )

    if run:
        try:
            result = validate_files(spec_path, source_path, output_path)
        except (SpecLoadError, X12ParseError, OutputLoadError) as exc:
            st.error(f"Could not run validation:\n\n```\n{exc}\n```")
            return
        st.session_state["result"] = result

    if "result" in st.session_state:
        _render_result(st.session_state["result"])
    else:
        st.info("Choose the three inputs in the sidebar, then hit **Run validation**.")


if __name__ == "__main__":
    main()
