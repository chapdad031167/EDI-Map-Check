#!/usr/bin/env python3
"""Regenerate the synthetic example artifacts under examples/.

Everything here is synthetic, built only from the public X12 850 structure
(segment/element definitions from X12.org). No proprietary data.

Usage:
    python scripts/generate_examples.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from openpyxl.worksheet.worksheet import Worksheet  # noqa: E402

from mapcheck.spec.template import build_template  # noqa: E402

EXAMPLES = REPO_ROOT / "examples"


# --------------------------------------------------------------------------
# Reference mapping spec: synthetic retail PO, 850 v004010
# --------------------------------------------------------------------------

# Row ID, Source Field, Loop Context, Target Field, Rule Type,
# Condition (Text), Condition (Coded), Then, Else, Default Value,
# Code List Ref, Data Type, Format, Notes
SPEC_ROWS: list[tuple[str, ...]] = [
    ("M-001", "BEG01", "", "order.tx_purpose", "CODE_LIST", "", "", "", "",
     "", "TX_PURPOSE", "string", "", "Transaction set purpose code."),
    ("M-002", "BEG02", "", "order.po_type", "CODE_LIST", "", "", "", "",
     "", "PO_TYPE", "string", "", "PO type code."),
    ("M-003", "BEG02", "", "order.drop_ship_flag", "CONDITIONAL",
     "If the PO type is drop ship, set the flag; otherwise N.",
     "BEG02 = 'DS'", "'Y'", "'N'", "", "", "string", "len:1..1", ""),
    ("M-004", "BEG03", "", "order.po_number", "DIRECT", "", "", "", "",
     "", "", "string", "len:1..22", "Customer PO number."),
    ("M-005", "BEG05", "", "order.po_date", "DIRECT", "", "", "", "",
     "", "", "date", "%Y-%m-%d", "PO date, CCYYMMDD in source."),
    ("M-006", "CUR02", "", "order.currency", "CONDITIONAL",
     "Map the currency only when a buying-party currency code is sent.",
     "CUR01 = 'BY'", "SOURCE", "SKIP", "", "", "string", "len:3..3", ""),
    ("M-007", "REF02", "REF[DP]", "order.department", "DIRECT", "", "", "", "",
     "", "", "string", "", "Department number."),
    ("M-008", "REF02", "REF[IA]", "order.vendor_number", "DIRECT", "", "", "", "",
     "", "", "string", "", "Internal vendor number."),
    ("M-009", "REF02", "REF[PD]", "order.promo_code", "CONDITIONAL",
     "Map the promotion/deal number only when the trading partner sends one.",
     "EXISTS(REF02)", "SOURCE", "SKIP", "", "", "string", "", ""),
    ("M-010", "DTM02", "DTM[002]", "order.requested_delivery_date", "DIRECT",
     "", "", "", "", "", "", "date", "%Y-%m-%d", "DTM 002 = requested delivery."),
    ("M-011", "DTM02", "DTM[001]", "order.cancel_after_date", "DIRECT",
     "", "", "", "", "", "", "date", "%Y-%m-%d",
     "DTM 001 = cancel after. Optional for this partner."),
    ("M-012", "", "", "order.record_type", "CONSTANT", "", "", "", "",
     "PO_INBOUND", "", "string", "", "Hardcoded record type for downstream routing."),
    ("M-013", "SAC05", "SAC[A]", "order.allowance_amount", "DIRECT", "", "", "", "",
     "", "", "decimal", "implied:2;places:2",
     "SAC05 is X12 N2: implied two decimals. 2500 in source = 25.00 out."),
    ("M-014", "N102", "N1[ST]", "ship_to.name", "DIRECT", "", "", "", "",
     "", "", "string", "len:1..60", ""),
    ("M-015", "N104", "N1[ST]", "ship_to.id", "CONDITIONAL",
     "Map the store number only when the ID qualifier is 92 (assigned by buyer).",
     "N103 = '92'", "SOURCE", "SKIP", "", "", "string", "", ""),
    ("M-016", "N301", "N1[ST]", "ship_to.address1", "DIRECT", "", "", "", "",
     "", "", "string", "", ""),
    ("M-017", "N401", "N1[ST]", "ship_to.city", "DIRECT", "", "", "", "",
     "", "", "string", "", ""),
    ("M-018", "N402", "N1[ST]", "ship_to.state", "DIRECT", "", "", "", "",
     "", "", "string", "len:2..2", ""),
    ("M-019", "N403", "N1[ST]", "ship_to.zip", "DIRECT", "", "", "", "",
     "", "", "string", "len:5..10", ""),
    ("M-020", "N102", "N1[BT]", "bill_to.name", "DIRECT", "", "", "", "",
     "", "", "string", "len:1..60", ""),
    ("M-021", "N104", "N1[BT]", "bill_to.id", "CONDITIONAL",
     "Map the bill-to ID only when the ID qualifier is 92 (assigned by buyer).",
     "N103 = '92'", "SOURCE", "SKIP", "", "", "string", "", ""),
    ("M-022", "PO101", "PO1", "lines[].line_no", "DIRECT", "", "", "", "",
     "", "", "integer", "", "Line sequence number."),
    ("M-023", "PO102", "PO1", "lines[].qty", "DIRECT", "", "", "", "",
     "", "", "integer", "", "Quantity ordered."),
    ("M-024", "PO103", "PO1", "lines[].uom", "CODE_LIST", "", "", "", "",
     "", "UOM", "string", "", "Unit of measure, translated to internal values."),
    ("M-025", "PO104", "PO1", "lines[].unit_price", "DIRECT", "", "", "", "",
     "", "", "decimal", "places:2", "PO104 is X12 R: explicit decimal."),
    ("M-026", "PO107", "PO1", "lines[].upc", "CONDITIONAL",
     "Map the UPC only when the product ID qualifier is UP.",
     "PO106 = 'UP'", "SOURCE", "SKIP", "", "", "string", "len:12..14", ""),
    ("M-027", "PID05", "PO1", "lines[].description", "CONDITIONAL",
     "Map the free-form description when the PID is free-form (PID01 = F).",
     "PID01 = 'F'", "SOURCE", "SKIP", "", "", "string", "len:1..80", ""),
    ("M-028", "CTT01", "", "summary.line_count", "DIRECT", "", "", "", "",
     "", "", "integer", "", "CTT line count as transmitted."),
    ("M-029", "PO1", "", "summary.line_count", "LOOP_COUNT", "", "", "", "",
     "", "", "integer", "",
     "Actual PO1 loop occurrences must also equal the output line count."),
    ("M-030", "AMT02", "AMT[TT]", "summary.total_amount", "DIRECT", "", "", "", "",
     "", "", "decimal", "places:2", "Total transaction amount."),
    ("M-031", "SAC02", "SAC[A]", "order.allowance_code", "DIRECT", "", "", "", "",
     "", "", "string", "len:4..4", "Allowance/charge code (SAC01 = A)."),
    ("M-032", "BEG04", "", "order.release_number", "DIRECT", "", "", "", "",
     "NONE", "", "string", "", "Release number; this partner never sends one, default NONE."),
]

# List Name, Source Value, Target Value, Description
CODE_LIST_ROWS: list[tuple[str, str, str, str]] = [
    ("TX_PURPOSE", "00", "ORIGINAL", "Original transmission"),
    ("TX_PURPOSE", "01", "CANCELLATION", "Cancellation"),
    ("TX_PURPOSE", "05", "REPLACE", "Replacement"),
    ("PO_TYPE", "SA", "STANDALONE", "Stand-alone order"),
    ("PO_TYPE", "NE", "NEW_ORDER", "New order"),
    ("PO_TYPE", "DS", "DROP_SHIP", "Drop ship order"),
    ("PO_TYPE", "RL", "RELEASE", "Release against blanket order"),
    ("UOM", "EA", "EACH", "Each"),
    ("UOM", "CA", "CASE", "Case"),
    ("UOM", "DZ", "DOZEN", "Dozen"),
]

SPEC_META = {
    "Transaction Set": "850",
    "X12 Version": "004010",
    "Spec Name": "Synthetic retail PO - reference example",
    "Author": "EDI MapCheck project",
    "Date": "2026-07-05",
}


def _fill_rows(ws: Worksheet, rows: list[tuple[str, ...]]) -> None:
    for r, row in enumerate(rows, start=2):
        for c, value in enumerate(row, start=1):
            if value != "":
                ws.cell(row=r, column=c, value=value)


def generate_spec(path: Path) -> None:
    """Write the reference 850 mapping spec workbook."""
    wb = build_template()
    _fill_rows(wb["Mapping"], SPEC_ROWS)
    _fill_rows(wb["CodeLists"], CODE_LIST_ROWS)
    ws_meta = wb["Meta"]
    for r in range(2, ws_meta.max_row + 1):
        key = ws_meta.cell(row=r, column=1).value
        if key in SPEC_META:
            ws_meta.cell(row=r, column=2, value=SPEC_META[key])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    print(f"wrote {path.relative_to(REPO_ROOT)}")


# --------------------------------------------------------------------------
# Synthetic X12 850 source files
# --------------------------------------------------------------------------


def build_850(
    business_segments: list[str],
    control_number: str,
    se_count_offset: int = 0,
) -> str:
    """Wrap business segments in a full ISA/GS/ST...SE/GE/IEA interchange.

    ``se_count_offset`` deliberately corrupts the SE segment count so pyx12's
    control checks have something to catch in the defective file.
    """
    icn = control_number.zfill(9)
    st = f"ST*850*{control_number.zfill(4)}"
    # SE count = business segments + ST + SE
    se = f"SE*{len(business_segments) + 2 + se_count_offset}*{control_number.zfill(4)}"
    segments = [
        "ISA*00*          *00*          *ZZ*MAPCHECKSND    *ZZ*MAPCHECKRCV    "
        f"*260615*1200*U*00401*{icn}*0*T*>",
        f"GS*PO*MAPCHECKSND*MAPCHECKRCV*20260615*1200*{int(control_number)}*X*004010",
        st,
        *business_segments,
        se,
        f"GE*1*{int(control_number)}",
        f"IEA*1*{icn}",
    ]
    return "~\n".join(segments) + "~\n"


BASELINE_850 = [
    "BEG*00*SA*PO4400021**20260615",
    "CUR*BY*USD",
    "REF*DP*045",
    "REF*IA*VEND8821",
    "REF*PD*SUMMER26",
    "DTM*002*20260701",
    "DTM*001*20260801",
    "SAC*A*C310***2500",
    "N1*ST*ALPINE OUTFITTERS STORE 118*92*0118",
    "N3*4501 CASCADE AVE",
    "N4*BOULDER*CO*80301",
    "N1*BT*ALPINE OUTFITTERS CORPORATE*92*0001",
    "PO1*1*12*EA*8.5**UP*614141007349",
    "PID*F****TRAIL MIX 12OZ",
    "PO1*2*6*CA*24**UP*614141007350",
    "PID*F****SPRING WATER 24PK",
    "PO1*3*5*DZ*12**UP*614141007351",
    "PID*F****GRANOLA BARS VARIETY",
    "CTT*3",
    "AMT*TT*306",
]

# Sparse but valid: exercises SKIP conditionals, the BEG04 default, and
# NOT TESTED statuses for segments this partner simply does not send.
MINIMAL_850 = [
    "BEG*00*NE*PO7700003**20260620",
    "N1*ST*RIVERBEND MARKET*92*0007",
    "PO1*1*100*EA*0.99**UP*614141007352",
    "PID*F****NO2 PENCILS 10PK",
    "CTT*1",
]

# Deliberately defective source. Planted defects:
#   1. BEG05 is not a valid date (month 13)
#   2. PO103 on line 2 uses UOM code 'XX', absent from the UOM code list
#   3. CTT01 says 5 lines but only 3 PO1 loops are present
#   4. ITD payment terms segment is not referenced by the spec (unmapped)
#   5. The N1[BT] loop is missing entirely
#   6. SE segment count is off by two (control-level defect for pyx12)
DEFECTS_850 = [
    "BEG*00*SA*PO4400022**20261301",
    "CUR*BY*USD",
    "REF*DP*045",
    "REF*IA*VEND8821",
    "REF*PD*SUMMER26",
    "DTM*002*20260701",
    "DTM*001*20260801",
    "ITD*01*3*2**30**60",
    "SAC*A*C310***2500",
    "N1*ST*ALPINE OUTFITTERS STORE 118*92*0118",
    "N3*4501 CASCADE AVE",
    "N4*BOULDER*CO*80301",
    "PO1*1*12*EA*8.5**UP*614141007349",
    "PID*F****TRAIL MIX 12OZ",
    "PO1*2*6*XX*24**UP*614141007350",
    "PID*F****SPRING WATER 24PK",
    "PO1*3*5*DZ*12**UP*614141007351",
    "PID*F****GRANOLA BARS VARIETY",
    "CTT*5",
    "AMT*TT*306",
]


def generate_source_files() -> None:
    source_dir = EXAMPLES / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "850_baseline.edi": build_850(BASELINE_850, "1"),
        "850_minimal.edi": build_850(MINIMAL_850, "2"),
        "850_defects.edi": build_850(DEFECTS_850, "3", se_count_offset=2),
    }
    for name, content in files.items():
        path = source_dir / name
        path.write_text(content)
        print(f"wrote {path.relative_to(REPO_ROOT)}")


def main() -> None:
    generate_spec(EXAMPLES / "specs" / "850_reference_spec.xlsx")
    generate_source_files()


if __name__ == "__main__":
    main()
