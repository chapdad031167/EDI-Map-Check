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
    ("M-006", "CUR02", "", "order.currency", "DIRECT", "", "", "", "",
     "USD", "", "string", "len:3..3", "Defaults to USD when CUR absent."),
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
    ("M-015", "N104", "N1[ST]", "ship_to.id", "DIRECT", "", "", "", "",
     "", "", "string", "", "Store number (N103 qualifier 92)."),
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
    ("M-021", "N104", "N1[BT]", "bill_to.id", "DIRECT", "", "", "", "",
     "", "", "string", "", ""),
    ("M-022", "PO101", "PO1", "lines[].line_no", "DIRECT", "", "", "", "",
     "", "", "integer", "", "Line sequence number."),
    ("M-023", "PO102", "PO1", "lines[].qty", "DIRECT", "", "", "", "",
     "", "", "integer", "", "Quantity ordered."),
    ("M-024", "PO103", "PO1", "lines[].uom", "CODE_LIST", "", "", "", "",
     "", "UOM", "string", "", "Unit of measure, translated to internal values."),
    ("M-025", "PO104", "PO1", "lines[].unit_price", "DIRECT", "", "", "", "",
     "", "", "decimal", "places:2", "PO104 is X12 R: explicit decimal."),
    ("M-026", "PO107", "PO1", "lines[].upc", "DIRECT", "", "", "", "",
     "", "", "string", "len:12..14", "PO106 qualifier UP."),
    ("M-027", "PID05", "PO1", "lines[].description", "DIRECT", "", "", "", "",
     "", "", "string", "len:1..80", "Item description from the PID inside the PO1 loop."),
    ("M-028", "CTT01", "", "summary.line_count", "DIRECT", "", "", "", "",
     "", "", "integer", "", "CTT line count as transmitted."),
    ("M-029", "PO1", "", "summary.line_count", "LOOP_COUNT", "", "", "", "",
     "", "", "integer", "",
     "Actual PO1 loop occurrences must also equal the output line count."),
    ("M-030", "AMT02", "AMT[TT]", "summary.total_amount", "DIRECT", "", "", "", "",
     "", "", "decimal", "places:2", "Total transaction amount."),
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


def main() -> None:
    generate_spec(EXAMPLES / "specs" / "850_reference_spec.xlsx")


if __name__ == "__main__":
    main()
