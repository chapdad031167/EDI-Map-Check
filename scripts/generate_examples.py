#!/usr/bin/env python3
"""Regenerate the synthetic example artifacts under examples/.

Everything here is synthetic, built only from the public X12 850 structure
(segment/element definitions from X12.org). No proprietary data.

Usage:
    python scripts/generate_examples.py
"""

from __future__ import annotations

import json
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


def generate_spec(
    path: Path,
    rows: list[tuple[str, ...]],
    code_lists: list[tuple[str, str, str, str]],
    meta: dict[str, str],
) -> None:
    """Write a reference mapping spec workbook."""
    wb = build_template()
    _fill_rows(wb["Mapping"], rows)
    _fill_rows(wb["CodeLists"], code_lists)
    ws_meta = wb["Meta"]
    for r in range(2, ws_meta.max_row + 1):
        key = ws_meta.cell(row=r, column=1).value
        if key in meta:
            ws_meta.cell(row=r, column=2, value=meta[key])
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


# --------------------------------------------------------------------------
# Translated output files (the artifact under test)
# --------------------------------------------------------------------------

BASELINE_LINES = [
    {"line_no": 1, "qty": 12, "uom": "EACH", "unit_price": 8.5,
     "upc": "614141007349", "description": "TRAIL MIX 12OZ"},
    {"line_no": 2, "qty": 6, "uom": "CASE", "unit_price": 24.0,
     "upc": "614141007350", "description": "SPRING WATER 24PK"},
    {"line_no": 3, "qty": 5, "uom": "DOZEN", "unit_price": 12.0,
     "upc": "614141007351", "description": "GRANOLA BARS VARIETY"},
]

BASELINE_OUTPUT: dict = {
    "order": {
        "tx_purpose": "ORIGINAL",
        "po_type": "STANDALONE",
        "drop_ship_flag": "N",
        "po_number": "PO4400021",
        "release_number": "NONE",
        "po_date": "2026-06-15",
        "currency": "USD",
        "department": "045",
        "vendor_number": "VEND8821",
        "promo_code": "SUMMER26",
        "requested_delivery_date": "2026-07-01",
        "cancel_after_date": "2026-08-01",
        "record_type": "PO_INBOUND",
        "allowance_code": "C310",
        "allowance_amount": 25.0,
    },
    "ship_to": {
        "name": "ALPINE OUTFITTERS STORE 118",
        "id": "0118",
        "address1": "4501 CASCADE AVE",
        "city": "BOULDER",
        "state": "CO",
        "zip": "80301",
    },
    "bill_to": {"name": "ALPINE OUTFITTERS CORPORATE", "id": "0001"},
    "lines": BASELINE_LINES,
    "summary": {"line_count": 3, "total_amount": 306.0},
}

MINIMAL_OUTPUT: dict = {
    "order": {
        "tx_purpose": "ORIGINAL",
        "po_type": "NEW_ORDER",
        "drop_ship_flag": "N",
        "po_number": "PO7700003",
        "release_number": "NONE",
        "po_date": "2026-06-20",
        "record_type": "PO_INBOUND",
    },
    "ship_to": {"name": "RIVERBEND MARKET", "id": "0007"},
    "lines": [
        {"line_no": 1, "qty": 100, "uom": "EACH", "unit_price": 0.99,
         "upc": "614141007352", "description": "NO2 PENCILS 10PK"},
    ],
    "summary": {"line_count": 1},
}


def _defective_baseline_output() -> dict:
    """Baseline output with deliberately planted mapping defects.

    Planted defects (validated against 850_baseline.edi):
      1. po_number transposed                     -> value_mismatch
      2. po_date in US format                     -> format
      3. drop_ship_flag Y though BEG02 is SA      -> condition_logic
      4. line 1 uom left untranslated ('EA')      -> code_translation
      5. record_type constant missing             -> constant_default
      6. allowance_amount implied decimal missed  -> value_mismatch (100x)
      7. third line dropped                       -> count_mismatch + missing_output
      8. extra field warehouse_code               -> unmapped_target warning
      9. ship_to.state four characters            -> format (len:2..2)
     10. release_number default not applied       -> missing_output
     11. line 2 qty carried as a JSON string      -> format warning
    """
    out = json.loads(json.dumps(BASELINE_OUTPUT))  # deep copy
    out["order"]["po_number"] = "PO4400012"
    out["order"]["po_date"] = "06/15/2026"
    out["order"]["drop_ship_flag"] = "Y"
    out["lines"][0]["uom"] = "EA"
    del out["order"]["record_type"]
    out["order"]["allowance_amount"] = 2500
    del out["lines"][2]
    out["order"]["warehouse_code"] = "WH9"
    out["ship_to"]["state"] = "COLO"
    del out["order"]["release_number"]
    out["lines"][1]["qty"] = "6"
    return out


def _naive_bad_source_output() -> dict:
    """What a naive translator emits from 850_defects.edi.

    It slices the invalid date into shape, passes the unknown UOM code
    through, trusts the (wrong) CTT count, and still emits a hardcoded
    bill_to that the source no longer sends.
    """
    out = json.loads(json.dumps(BASELINE_OUTPUT))
    out["order"]["po_number"] = "PO4400022"
    out["order"]["po_date"] = "2026-13-01"
    out["lines"][1]["uom"] = "XX"
    out["summary"]["line_count"] = 5
    return out


def _flat_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _to_flat(data: dict) -> str:
    """Render a canonical output dict in the keyed flat reference format."""
    lines = ["# EDI MapCheck keyed flat output"]
    order = "|".join(f"{k}={_flat_value(v)}" for k, v in data["order"].items())
    lines.append(f"H|{order}")
    for role in (k for k in data if k not in ("order", "lines", "summary")):
        fields = "|".join(f"{k}={_flat_value(v)}" for k, v in data[role].items())
        lines.append(f"A|role={role}|{fields}")
    for line in data.get("lines", []):
        fields = "|".join(f"{k}={_flat_value(v)}" for k, v in line.items())
        lines.append(f"D|{fields}")
    summary = "|".join(f"{k}={_flat_value(v)}" for k, v in data["summary"].items())
    lines.append(f"S|{summary}")
    return "\n".join(lines) + "\n"


def generate_output_files() -> None:
    out_dir = EXAMPLES / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_files = {
        "po_baseline.json": BASELINE_OUTPUT,
        "po_minimal.json": MINIMAL_OUTPUT,
        "po_baseline_defects.json": _defective_baseline_output(),
        "po_from_bad_source.json": _naive_bad_source_output(),
    }
    for name, data in json_files.items():
        path = out_dir / name
        path.write_text(json.dumps(data, indent=2) + "\n")
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    flat_path = out_dir / "po_baseline.flat"
    flat_path.write_text(_to_flat(BASELINE_OUTPUT))
    print(f"wrote {flat_path.relative_to(REPO_ROOT)}")


# --------------------------------------------------------------------------
# 856 Ship Notice/Manifest: reference spec, sources, and outputs
# --------------------------------------------------------------------------

SPEC856_ROWS: list[tuple[str, ...]] = [
    ("A-001", "BSN01", "", "shipment.purpose", "CODE_LIST", "", "", "", "",
     "", "TX_PURPOSE", "string", "", "Transaction set purpose."),
    ("A-002", "BSN02", "", "shipment.asn_number", "DIRECT", "", "", "", "",
     "", "", "string", "len:2..30", "Shipment identification."),
    ("A-003", "BSN03", "", "shipment.asn_date", "DIRECT", "", "", "", "",
     "", "", "date", "%Y-%m-%d", ""),
    ("A-004", "BSN04", "", "shipment.asn_time", "DIRECT", "", "", "", "",
     "", "", "time", "%H:%M", ""),
    ("A-005", "BSN05", "", "shipment.structure_code", "CODE_LIST", "", "", "", "",
     "", "ASN_STRUCTURE", "string", "", "Hierarchical structure code."),
    ("A-006", "DTM02", "DTM[011]", "shipment.ship_date", "DIRECT", "", "", "", "",
     "", "", "date", "%Y-%m-%d", "DTM 011 = shipped."),
    ("A-007", "TD101", "HL[S]", "shipment.packaging_code", "CONDITIONAL",
     "Map the packaging code when a shipment-level TD1 is sent.",
     "EXISTS(TD101)", "SOURCE", "SKIP", "", "", "string", "", ""),
    ("A-008", "TD102", "HL[S]", "shipment.carton_count", "CONDITIONAL",
     "Map the lading quantity when a shipment-level TD1 is sent.",
     "EXISTS(TD102)", "SOURCE", "SKIP", "", "", "integer", "", ""),
    ("A-009", "TD503", "HL[S]", "shipment.scac", "CONDITIONAL",
     "Map the carrier code only when the ID qualifier says SCAC (2).",
     "TD502 = '2'", "SOURCE", "SKIP", "", "", "string", "len:2..4", ""),
    ("A-010", "TD504", "HL[S]", "shipment.ship_mode", "CODE_LIST", "", "", "", "",
     "", "SHIP_METHOD", "string", "", "Transportation method."),
    ("A-011", "REF02", "HL[S]", "shipment.bol_number", "CONDITIONAL",
     "Map the bill of lading number from the shipment-level REF.",
     "REF01 = 'BM'", "SOURCE", "SKIP", "", "", "string", "", ""),
    ("A-012", "", "", "shipment.record_type", "CONSTANT", "", "", "", "",
     "ASN_INBOUND", "", "string", "", "Hardcoded routing constant."),
    ("A-013", "N102", "N1[ST]", "ship_to.name", "DIRECT", "", "", "", "",
     "", "", "string", "len:1..60", "Party loop nested in the shipment HL."),
    ("A-014", "N104", "N1[ST]", "ship_to.id", "CONDITIONAL",
     "Map the location number only when the ID qualifier is 92.",
     "N103 = '92'", "SOURCE", "SKIP", "", "", "string", "", ""),
    ("A-015", "N301", "N1[ST]", "ship_to.address1", "DIRECT", "", "", "", "",
     "", "", "string", "", ""),
    ("A-016", "N401", "N1[ST]", "ship_to.city", "DIRECT", "", "", "", "",
     "", "", "string", "", ""),
    ("A-017", "N402", "N1[ST]", "ship_to.state", "DIRECT", "", "", "", "",
     "", "", "string", "len:2..2", ""),
    ("A-018", "N403", "N1[ST]", "ship_to.zip", "DIRECT", "", "", "", "",
     "", "", "string", "len:5..10", ""),
    ("A-019", "PRF01", "HL[I]", "lines[].po_number", "DIRECT", "", "", "", "",
     "", "", "string", "len:1..22",
     "Read from the item's ancestor order (O) level."),
    ("A-020", "SN101", "HL[I]", "lines[].line_no", "DIRECT", "", "", "", "",
     "", "", "integer", "", ""),
    ("A-021", "SN102", "HL[I]", "lines[].qty_shipped", "DIRECT", "", "", "", "",
     "", "", "integer", "", "Units shipped for the item."),
    ("A-022", "SN103", "HL[I]", "lines[].uom", "CODE_LIST", "", "", "", "",
     "", "UOM", "string", "", ""),
    ("A-023", "LIN03", "HL[I]", "lines[].upc", "CONDITIONAL",
     "Map the UPC only when the product ID qualifier is UP.",
     "LIN02 = 'UP'", "SOURCE", "SKIP", "", "", "string", "len:12..14", ""),
    ("A-024", "PID05", "HL[I]", "lines[].description", "CONDITIONAL",
     "Map the free-form description when the PID is free-form.",
     "PID01 = 'F'", "SOURCE", "SKIP", "", "", "string", "len:1..80", ""),
    ("A-025", "MAN02", "HL[I]", "lines[].sscc", "CONDITIONAL",
     "Map the carton SSCC (from the ancestor pack level) when marked GM.",
     "MAN01 = 'GM'", "SOURCE", "SKIP", "", "", "string", "len:18..20",
     "Standard-carton ASNs have no pack level; the field is simply absent."),
    ("A-026", "CTT01", "", "summary.hl_count", "DIRECT", "", "", "", "",
     "", "", "integer", "", "HL count as transmitted."),
    ("A-027", "HL", "", "summary.hl_count", "LOOP_COUNT", "", "", "", "",
     "", "", "integer", "", "Actual HL loops must also match the output."),
    ("A-028", "CTT02", "", "summary.total_units", "DIRECT", "", "", "", "",
     "", "", "integer", "", "Hash total of SN1 quantities."),
]

CODE_LIST_856_ROWS: list[tuple[str, str, str, str]] = [
    ("TX_PURPOSE", "00", "ORIGINAL", "Original transmission"),
    ("TX_PURPOSE", "01", "CANCELLATION", "Cancellation"),
    ("TX_PURPOSE", "05", "REPLACE", "Replacement"),
    ("ASN_STRUCTURE", "0001", "SHIPMENT_ORDER_PACK_ITEM", "Pick and pack"),
    ("ASN_STRUCTURE", "0002", "SHIPMENT_ORDER_ITEM", "Standard carton"),
    ("ASN_STRUCTURE", "0004", "SHIPMENT_ORDER_TARE_PACK_ITEM", "Palletized"),
    ("SHIP_METHOD", "M", "MOTOR", "Motor (common carrier)"),
    ("SHIP_METHOD", "A", "AIR", "Air"),
    ("SHIP_METHOD", "R", "RAIL", "Rail"),
    ("UOM", "EA", "EACH", "Each"),
    ("UOM", "CA", "CASE", "Case"),
    ("UOM", "DZ", "DOZEN", "Dozen"),
]

SPEC856_META = {
    "Transaction Set": "856",
    "X12 Version": "004010",
    "Spec Name": "Synthetic retail ASN - reference example",
    "Author": "EDI MapCheck project",
    "Date": "2026-07-05",
}

PICKPACK_856 = [
    "BSN*00*ASN20260708001*20260708*1015*0001",
    "DTM*011*20260708",
    "HL*1**S",
    "TD1*CTN25*2",
    "TD5**2*RDWY*M",
    "REF*BM*BOL8802214",
    "N1*ST*ALPINE OUTFITTERS DC 12*92*0012",
    "N3*880 GRANITE PARKWAY",
    "N4*DENVER*CO*80201",
    "HL*2*1*O",
    "PRF*PO4400021",
    "HL*3*2*P",
    "MAN*GM*00061414100734900012",
    "HL*4*3*I",
    "LIN**UP*614141007349",
    "SN1*1*12*EA",
    "PID*F****TRAIL MIX 12OZ",
    "HL*5*3*I",
    "LIN**UP*614141007350",
    "SN1*2*24*EA",
    "PID*F****SPRING WATER 24PK",
    "HL*6*2*P",
    "MAN*GM*00061414100734900029",
    "HL*7*6*I",
    "LIN**UP*614141007351",
    "SN1*3*60*EA",
    "PID*F****GRANOLA BARS VARIETY",
    "CTT*7*96",
]

STANDARD_856 = [
    "BSN*00*ASN20260712002*20260712*0830*0002",
    "DTM*011*20260712",
    "HL*1**S",
    "TD5**2*UPSN*M",
    "REF*BM*BOL8802290",
    "N1*ST*RIVERBEND MARKET*92*0007",
    "N3*15 HARBOR ROW",
    "N4*PORTLAND*OR*97201",
    "HL*2*1*O",
    "PRF*PO7700003",
    "HL*3*2*I",
    "LIN**UP*614141007352",
    "SN1*1*100*EA",
    "PID*F****NO2 PENCILS 10PK",
    "HL*4*2*I",
    "LIN**UP*614141007353",
    "SN1*2*40*EA",
    "PID*F****MARKERS 8CT",
    "CTT*4*140",
]

# Deliberately defective ASN. Planted defects:
#   1. HL*4 is an item directly under the shipment (illegal nesting)
#   2. HL*6 points at parent id 9, which does not exist (orphan)
#   3. HL*7 uses unknown level code X (and X is no valid child of O)
#   4. CTT01 says 9 HL loops; the file has 7
#   5. CTT02 hash total 999 vs actual SN1 sum of 96
#   6. TD1 claims 5 cartons; only one pack (P) loop exists
#   7. PKG segment is not in the 856 definition (unmapped structure)
#   8. HL*7 carries a REF no spec rule references (unmapped source data)
DEFECTS_856 = [
    "BSN*00*ASN20260715003*20260715*1400*0001",
    "DTM*011*20260715",
    "HL*1**S",
    "TD1*CTN25*5",
    "TD5**2*RDWY*M",
    "REF*BM*BOL8802333",
    "PKG*F*01",
    "N1*ST*ALPINE OUTFITTERS DC 12*92*0012",
    "N3*880 GRANITE PARKWAY",
    "N4*DENVER*CO*80201",
    "HL*2*1*O",
    "PRF*PO4400022",
    "HL*3*2*P",
    "MAN*GM*00061414100734900036",
    "HL*4*1*I",
    "LIN**UP*614141007349",
    "SN1*1*12*EA",
    "PID*F****TRAIL MIX 12OZ",
    "HL*5*3*I",
    "LIN**UP*614141007350",
    "SN1*2*24*EA",
    "PID*F****SPRING WATER 24PK",
    "HL*6*9*I",
    "LIN**UP*614141007351",
    "SN1*3*60*EA",
    "PID*F****GRANOLA BARS VARIETY",
    "HL*7*2*X",
    "REF*ZZ*MYSTERY",
    "CTT*9*999",
]


def _asn_line(
    line_no: int, qty: int, upc: str, description: str,
    po_number: str | None = None, sscc: str | None = None,
) -> dict:
    line: dict = {}
    if po_number is not None:
        line["po_number"] = po_number
    line.update(
        {"line_no": line_no, "qty_shipped": qty, "uom": "EACH",
         "upc": upc, "description": description}
    )
    if sscc is not None:
        line["sscc"] = sscc
    return line


PICKPACK_OUTPUT: dict = {
    "shipment": {
        "purpose": "ORIGINAL",
        "asn_number": "ASN20260708001",
        "asn_date": "2026-07-08",
        "asn_time": "10:15",
        "structure_code": "SHIPMENT_ORDER_PACK_ITEM",
        "ship_date": "2026-07-08",
        "packaging_code": "CTN25",
        "carton_count": 2,
        "scac": "RDWY",
        "ship_mode": "MOTOR",
        "bol_number": "BOL8802214",
        "record_type": "ASN_INBOUND",
    },
    "ship_to": {
        "name": "ALPINE OUTFITTERS DC 12", "id": "0012",
        "address1": "880 GRANITE PARKWAY", "city": "DENVER",
        "state": "CO", "zip": "80201",
    },
    "lines": [
        _asn_line(1, 12, "614141007349", "TRAIL MIX 12OZ",
                  po_number="PO4400021", sscc="00061414100734900012"),
        _asn_line(2, 24, "614141007350", "SPRING WATER 24PK",
                  po_number="PO4400021", sscc="00061414100734900012"),
        _asn_line(3, 60, "614141007351", "GRANOLA BARS VARIETY",
                  po_number="PO4400021", sscc="00061414100734900029"),
    ],
    "summary": {"hl_count": 7, "total_units": 96},
}

STANDARD_OUTPUT: dict = {
    "shipment": {
        "purpose": "ORIGINAL",
        "asn_number": "ASN20260712002",
        "asn_date": "2026-07-12",
        "asn_time": "08:30",
        "structure_code": "SHIPMENT_ORDER_ITEM",
        "ship_date": "2026-07-12",
        "scac": "UPSN",
        "ship_mode": "MOTOR",
        "bol_number": "BOL8802290",
        "record_type": "ASN_INBOUND",
    },
    "ship_to": {
        "name": "RIVERBEND MARKET", "id": "0007",
        "address1": "15 HARBOR ROW", "city": "PORTLAND",
        "state": "OR", "zip": "97201",
    },
    "lines": [
        _asn_line(1, 100, "614141007352", "NO2 PENCILS 10PK", po_number="PO7700003"),
        _asn_line(2, 40, "614141007353", "MARKERS 8CT", po_number="PO7700003"),
    ],
    "summary": {"hl_count": 4, "total_units": 140},
}

# What a naive translator emits from the defective ASN: it trusts CTT
# outright and carries whatever parent context each item actually has.
DEFECTS_856_OUTPUT: dict = {
    "shipment": {
        "purpose": "ORIGINAL",
        "asn_number": "ASN20260715003",
        "asn_date": "2026-07-15",
        "asn_time": "14:00",
        "structure_code": "SHIPMENT_ORDER_PACK_ITEM",
        "ship_date": "2026-07-15",
        "packaging_code": "CTN25",
        "carton_count": 5,
        "scac": "RDWY",
        "ship_mode": "MOTOR",
        "bol_number": "BOL8802333",
        "record_type": "ASN_INBOUND",
    },
    "ship_to": {
        "name": "ALPINE OUTFITTERS DC 12", "id": "0012",
        "address1": "880 GRANITE PARKWAY", "city": "DENVER",
        "state": "CO", "zip": "80201",
    },
    "lines": [
        _asn_line(1, 12, "614141007349", "TRAIL MIX 12OZ"),
        _asn_line(2, 24, "614141007350", "SPRING WATER 24PK",
                  po_number="PO4400022", sscc="00061414100734900036"),
        _asn_line(3, 60, "614141007351", "GRANOLA BARS VARIETY"),
    ],
    "summary": {"hl_count": 9, "total_units": 999},
}


def generate_856_files() -> None:
    source_dir = EXAMPLES / "source"
    out_dir = EXAMPLES / "output"
    sources = {
        "856_pickpack.edi": build_856(PICKPACK_856, "11"),
        "856_standard.edi": build_856(STANDARD_856, "12"),
        "856_defects.edi": build_856(DEFECTS_856, "13"),
    }
    for name, content in sources.items():
        path = source_dir / name
        path.write_text(content)
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    outputs = {
        "asn_pickpack.json": PICKPACK_OUTPUT,
        "asn_standard.json": STANDARD_OUTPUT,
        "asn_defects.json": DEFECTS_856_OUTPUT,
    }
    for name, data in outputs.items():
        path = out_dir / name
        path.write_text(json.dumps(data, indent=2) + "\n")
        print(f"wrote {path.relative_to(REPO_ROOT)}")


def build_856(business_segments: list[str], control_number: str) -> str:
    """Wrap 856 business segments in a full interchange (GS01 = SH)."""
    icn = control_number.zfill(9)
    segments = [
        "ISA*00*          *00*          *ZZ*MAPCHECKSND    *ZZ*MAPCHECKRCV    "
        f"*260708*1200*U*00401*{icn}*0*T*>",
        f"GS*SH*MAPCHECKSND*MAPCHECKRCV*20260708*1200*{int(control_number)}*X*004010",
        f"ST*856*{control_number.zfill(4)}",
        *business_segments,
        f"SE*{len(business_segments) + 2}*{control_number.zfill(4)}",
        f"GE*1*{int(control_number)}",
        f"IEA*1*{icn}",
    ]
    return "~\n".join(segments) + "~\n"


def main() -> None:
    generate_spec(
        EXAMPLES / "specs" / "850_reference_spec.xlsx",
        SPEC_ROWS, CODE_LIST_ROWS, SPEC_META,
    )
    generate_source_files()
    generate_output_files()
    generate_spec(
        EXAMPLES / "specs" / "856_reference_spec.xlsx",
        SPEC856_ROWS, CODE_LIST_856_ROWS, SPEC856_META,
    )
    generate_856_files()


if __name__ == "__main__":
    main()
