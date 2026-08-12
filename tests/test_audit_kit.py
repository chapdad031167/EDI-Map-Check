"""The audit kit as a permanent regression harness.

Five synthetic 850s under ``tests/fixtures/audit_kit/`` carry known seeded
defects (see the kit's README — the answer key). Each file is validated
against the *audit spec* — the 850 reference spec's rules plus
fixture-family coverage rows — paired with a *faithful output*: exactly
what a correct translator produces from that source (defective values
copied through raw, empty sources omitted). Every test asserts the exact
expected finding set, so any drift in what the validator catches — a lost
check, a reworded message, a severity change — fails here.

Phase-1 audit record: ``docs/audit-gap-list.md``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mapcheck.engine.results import Category, RunResult, Status
from mapcheck.engine.validator import validate_files
from mapcheck.spec.template import build_template
from mapcheck.x12.parser import X12ParseError, parse_transaction

KIT = Path(__file__).resolve().parent / "fixtures" / "audit_kit"

# ---------------------------------------------------------------------------
# The audit spec: the 850 reference spec's rules, adjusted only so the spec
# covers this fixture family's data shape (PER contact, N1*BY buying party,
# VN part / UP pair at PO106-PO109, CTT02). Without the coverage rows the
# clean file would emit unmapped-source warnings that measure spec coverage,
# not the validator.
# ---------------------------------------------------------------------------

SPEC_ROWS: list[tuple[str, ...]] = [
    ("M-001", "BEG01", "", "order.tx_purpose", "CODE_LIST", "", "", "", "",
     "", "TX_PURPOSE", "string", "", ""),
    ("M-002", "BEG02", "", "order.po_type", "CODE_LIST", "", "", "", "",
     "", "PO_TYPE", "string", "", ""),
    ("M-003", "BEG02", "", "order.drop_ship_flag", "CONDITIONAL",
     "If the PO type is drop ship, set the flag; otherwise N.",
     "BEG02 = 'DS'", "'Y'", "'N'", "", "", "string", "len:1..1", ""),
    ("M-004", "BEG03", "", "order.po_number", "DIRECT", "", "", "", "",
     "", "", "string", "len:1..22", ""),
    ("M-005", "BEG05", "", "order.po_date", "DIRECT", "", "", "", "",
     "", "", "date", "%Y-%m-%d", ""),
    ("M-006", "CUR02", "", "order.currency", "CONDITIONAL",
     "Map the currency only when a buying-party currency code is sent.",
     "CUR01 = 'BY'", "SOURCE", "SKIP", "", "", "string", "len:3..3", ""),
    ("M-007", "REF02", "REF[DP]", "order.department", "DIRECT", "", "", "", "",
     "", "", "string", "", ""),
    ("M-008", "REF02", "REF[IA]", "order.vendor_number", "DIRECT", "", "", "", "",
     "", "", "string", "", ""),
    ("M-009", "REF02", "REF[PD]", "order.promo_code", "CONDITIONAL",
     "Map the promotion/deal number only when the trading partner sends one.",
     "EXISTS(REF02)", "SOURCE", "SKIP", "", "", "string", "", ""),
    ("M-010", "DTM02", "DTM[002]", "order.requested_delivery_date", "DIRECT",
     "", "", "", "", "", "", "date", "%Y-%m-%d", ""),
    ("M-011", "DTM02", "DTM[001]", "order.cancel_after_date", "DIRECT",
     "", "", "", "", "", "", "date", "%Y-%m-%d", ""),
    ("M-012", "", "", "order.record_type", "CONSTANT", "", "", "", "",
     "PO_INBOUND", "", "string", "", ""),
    ("M-013", "SAC05", "SAC[A]", "order.allowance_amount", "DIRECT", "", "", "", "",
     "", "", "decimal", "implied:2;places:2", ""),
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
     "", "", "integer", "", ""),
    ("M-023", "PO102", "PO1", "lines[].qty", "DIRECT", "", "", "", "",
     "", "", "integer", "", ""),
    ("M-024", "PO103", "PO1", "lines[].uom", "CODE_LIST", "", "", "", "",
     "", "UOM", "string", "", ""),
    ("M-025", "PO104", "PO1", "lines[].unit_price", "DIRECT", "", "", "", "",
     "", "", "decimal", "places:2", ""),
    ("M-026", "PO109", "PO1", "lines[].upc", "CONDITIONAL",
     "Map the UPC only when the second product ID qualifier is UP.",
     "PO108 = 'UP'", "SOURCE", "SKIP", "", "", "string", "len:12..14",
     "Audit fixtures carry VN at PO106/07 and UP at PO108/09."),
    ("M-027", "PID05", "PO1", "lines[].description", "CONDITIONAL",
     "Map the free-form description when the PID is free-form (PID01 = F).",
     "PID01 = 'F'", "SOURCE", "SKIP", "", "", "string", "len:1..80", ""),
    ("M-028", "CTT01", "", "summary.line_count", "DIRECT", "", "", "", "",
     "", "", "integer", "", ""),
    ("M-029", "PO1", "", "summary.line_count", "LOOP_COUNT", "", "", "", "",
     "", "", "integer", "", ""),
    ("M-030", "AMT02", "AMT[TT]", "summary.total_amount", "DIRECT", "", "", "", "",
     "", "", "decimal", "places:2", ""),
    ("M-031", "SAC02", "SAC[A]", "order.allowance_code", "DIRECT", "", "", "", "",
     "", "", "string", "len:4..4", ""),
    ("M-032", "BEG04", "", "order.release_number", "DIRECT", "", "", "", "",
     "NONE", "", "string", "", ""),
    ("A-101", "PO107", "PO1", "lines[].vendor_part", "CONDITIONAL",
     "Map the vendor part number when the product ID qualifier is VN.",
     "PO106 = 'VN'", "SOURCE", "SKIP", "", "", "string", "", ""),
    ("A-102", "PER01", "", "contact.function", "DIRECT", "", "", "", "",
     "", "", "string", "len:2..2", ""),
    ("A-103", "PER02", "", "contact.name", "DIRECT", "", "", "", "",
     "", "", "string", "", ""),
    ("A-104", "PER04", "", "contact.phone", "CONDITIONAL",
     "Map the phone number when the communication qualifier is TE.",
     "PER03 = 'TE'", "SOURCE", "SKIP", "", "", "string", "", ""),
    ("A-105", "N102", "N1[BY]", "buyer.name", "DIRECT", "", "", "", "",
     "", "", "string", "len:1..60", ""),
    ("A-106", "N104", "N1[BY]", "buyer.id", "CONDITIONAL",
     "Map the buyer ID only when the ID qualifier is 92 (assigned by buyer).",
     "N103 = '92'", "SOURCE", "SKIP", "", "", "string", "", ""),
    ("A-107", "CTT02", "", "summary.total_units", "DIRECT", "", "", "", "",
     "", "", "integer", "", ""),
]

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
    "Spec Name": "Audit-kit 850 spec",
}

# ---------------------------------------------------------------------------
# Faithful outputs: what a correct translator produces from each source.
# ---------------------------------------------------------------------------

SHIP_TO = {
    "name": "ACME PHARMA DC COLUMBUS",
    "id": "ST4401",
    "address1": "4400 DISTRIBUTION DR",
    "city": "COLUMBUS",
    "state": "OH",
    "zip": "43228",
}
CONTACT = {"function": "BD", "name": "JASON CHAPMAN", "phone": "6145550142"}
BUYER = {"name": "SADIE ASH DISTRIBUTION", "id": "BUY001"}


def _order(po_number: str | None, po_date: str, tx_purpose: str = "ORIGINAL",
           requested: str | None = None) -> dict:
    doc = {
        "tx_purpose": tx_purpose,
        "po_type": "NEW_ORDER",
        "drop_ship_flag": "N",
        "release_number": "NONE",
        "po_date": po_date,
        "department": "054",
        "record_type": "PO_INBOUND",
    }
    if po_number is not None:
        doc["po_number"] = po_number
    if requested is not None:
        doc["requested_delivery_date"] = requested
    return doc


OUTPUTS: dict[str, dict] = {
    "850_01_clean": {
        "order": _order("PO-2026-0810", "2026-08-10", requested="2026-08-17"),
        "contact": CONTACT,
        "buyer": BUYER,
        "ship_to": SHIP_TO,
        "lines": [
            {"line_no": 1, "qty": 24, "uom": "EACH", "unit_price": 18.75,
             "vendor_part": "SAF-00110", "upc": "012345678905",
             "description": "ALCOHOL PREP PADS 200CT"},
            {"line_no": 2, "qty": 12, "uom": "CASE", "unit_price": 96.0,
             "vendor_part": "SAF-00244", "upc": "036000291452",
             "description": "NITRILE EXAM GLOVES M"},
        ],
        "summary": {"line_count": 2, "total_units": 36},
    },
    "850_02_structural_errors": {
        "order": _order("PO-2026-0811", "2026-08-10", requested="2026-08-18"),
        "ship_to": SHIP_TO,
        "lines": [
            {"line_no": 1, "qty": 24, "uom": "EACH", "unit_price": 18.75,
             "vendor_part": "SAF-00110",
             "description": "ALCOHOL PREP PADS 200CT"},
        ],
        "summary": {"line_count": 1, "total_units": 24},
    },
    # Defective source values copied through raw (naive translator
    # convention); empty sources omitted.
    "850_03_semantic_errors": {
        "order": _order(None, "20261415", tx_purpose="ZZ", requested="2026-08-19"),
        "ship_to": {**SHIP_TO, "state": "XX"},
        "lines": [
            {"line_no": 1, "qty": 24, "uom": "XX", "unit_price": 18.75,
             "vendor_part": "SAF-00110",
             "description": "ALCOHOL PREP PADS 200CT"},
            {"line_no": 2, "uom": "CASE", "unit_price": 96.0,
             "vendor_part": "SAF-00244",
             "description": "NITRILE EXAM GLOVES M"},
        ],
        "summary": {"line_count": 2, "total_units": 24},
    },
    "850_04_partner_rules": {
        "order": _order("PO-2026-0813", "2026-08-10"),
        "contact": CONTACT,
        "buyer": BUYER,
        "ship_to": SHIP_TO,
        "lines": [
            {"line_no": 1, "qty": 24, "uom": "EACH", "unit_price": 18.75,
             "vendor_part": "SAF-00110",
             "description": "ALCOHOL PREP PADS 200CT"},
            {"line_no": 2, "qty": 12, "uom": "CASE", "unit_price": 96.0,
             "vendor_part": "SAF-00244",
             "description": "NITRILE EXAM GLOVES M"},
        ],
        "summary": {"line_count": 2, "total_units": 36},
    },
}


@pytest.fixture(scope="module")
def harness_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the audit spec and faithful outputs once for the module."""
    root = tmp_path_factory.mktemp("audit_kit_harness")
    wb = build_template()
    mapping = wb["Mapping"]
    for r, row in enumerate(SPEC_ROWS, start=2):
        for c, value in enumerate(row, start=1):
            if value != "":
                mapping.cell(row=r, column=c, value=value)
    code_lists = wb["CodeLists"]
    for r, row in enumerate(CODE_LIST_ROWS, start=2):
        for c, value in enumerate(row, start=1):
            code_lists.cell(row=r, column=c, value=value)
    meta = wb["Meta"]
    for r in range(2, meta.max_row + 1):
        key = meta.cell(row=r, column=1).value
        if key in SPEC_META:
            meta.cell(row=r, column=2, value=SPEC_META[key])
    wb.save(root / "audit_spec.xlsx")
    for name, doc in OUTPUTS.items():
        (root / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")
    return root


def _run(harness_dir: Path, name: str) -> RunResult:
    return validate_files(
        str(harness_dir / "audit_spec.xlsx"),
        str(KIT / f"{name}.edi"),
        str(harness_dir / f"{name}.json"),
    )


def _statuses(run: RunResult) -> dict[Status, int]:
    return {s: n for s, n in run.counts.items()}


def _rows(run: RunResult, status: Status) -> set[str]:
    return {f.row_id for f in run.findings if f.status is status and f.row_id}


def _fail_messages(run: RunResult) -> list[str]:
    return sorted(f.message for f in run.findings if f.status is Status.FAIL)


class TestFile1Clean:
    """File 1 is fully valid: any finding is a validator bug."""

    def test_no_findings(self, harness_dir: Path):
        run = _run(harness_dir, "850_01_clean")
        assert run.overall is Status.PASS
        counts = _statuses(run)
        assert counts[Status.FAIL] == 0
        assert counts[Status.WARNING] == 0
        assert counts[Status.PASS] == 40
        # NOT TESTED only for spec rules whose optional segments are absent.
        assert _rows(run, Status.NOT_TESTED) == {
            "M-008", "M-011", "M-013", "M-020", "M-030", "M-031",
        }


class TestFile2StructuralErrors:
    """Four seeded envelope defects — all strict failures, exact messages."""

    def test_exact_findings(self, harness_dir: Path):
        run = _run(harness_dir, "850_02_structural_errors")
        assert run.overall is Status.FAIL
        assert run.exit_code == 1
        counts = _statuses(run)
        assert counts[Status.FAIL] == 4
        assert counts[Status.WARNING] == 0
        assert counts[Status.PASS] == 30
        control = [f for f in run.findings if f.category is Category.CONTROL]
        assert len(control) == 4
        assert all(f.status is Status.FAIL for f in control)
        assert _fail_messages(run) == [
            "GE01 transaction count mismatch: GE claims 2 transaction set(s) "
            "but functional group 102 contains 1",
            "IEA02 control number mismatch: IEA02 is 000000999 but ISA13 is "
            "000000102",
            "SE01 segment count mismatch: SE claims 9 segments but transaction "
            "0001 contains 11 (ST through SE)",
            "SE02 control number mismatch: SE02 is 0002 but its ST02 is 0001",
        ]


class TestFile3SemanticErrors:
    """Six seeded content defects; five are caught (N402 is backlogged)."""

    def test_exact_findings(self, harness_dir: Path):
        run = _run(harness_dir, "850_03_semantic_errors")
        assert run.overall is Status.FAIL
        counts = _statuses(run)
        assert counts[Status.FAIL] == 5
        assert counts[Status.WARNING] == 0
        assert _fail_messages(run) == [
            "source data invalid: BEG03 (PO number) is a mandatory element in "
            "the 850 but is empty",
            "source data invalid: BEG05 '20261415' is not a valid X12 date "
            "(CCYYMMDD or YYMMDD)",
            "source data invalid: PO102 (quantity ordered) is required when "
            "PO103 (unit of measure) is present, but is empty",
            "source data invalid: source value 'XX' has no entry in code list "
            "UOM (valid: CA, DZ, EA)",
            "source data invalid: source value 'ZZ' has no entry in code list "
            "TX_PURPOSE (valid: 00, 01, 05)",
        ]

    def test_required_element_findings_name_their_occurrence(self, harness_dir: Path):
        run = _run(harness_dir, "850_03_semantic_errors")
        refs = {
            f.source_ref
            for f in run.findings
            if f.status is Status.FAIL and "required" in f.message or
               f.status is Status.FAIL and "mandatory" in f.message
        }
        assert "header BEG03" in refs
        assert "PO1 #2 PO102" in refs

    def test_n402_state_code_is_backlogged_not_flagged(self, harness_dir: Path):
        """N402=XX passes by design (backlog: state/province code list)."""
        run = _run(harness_dir, "850_03_semantic_errors")
        state = [f for f in run.findings if f.target == "ship_to.state"]
        assert len(state) == 1
        assert state[0].status is Status.PASS


class TestFile4PartnerRules:
    """Valid base X12; companion-guide gaps are neutral non-findings."""

    def test_no_findings(self, harness_dir: Path):
        run = _run(harness_dir, "850_04_partner_rules")
        assert run.overall is Status.PASS
        counts = _statuses(run)
        assert counts[Status.FAIL] == 0
        assert counts[Status.WARNING] == 0
        assert counts[Status.PASS] == 39
        # The three fictional companion-guide requirements the file violates
        # surface only as NOT TESTED (DTM*002, REF*IA) — the partner-rule
        # overlay is a roadmap item, not a base-standard check.
        assert _rows(run, Status.NOT_TESTED) == {
            "M-008", "M-010", "M-011", "M-013", "M-020", "M-030", "M-031",
        }


class TestFile5Truncated:
    """Truncation dies gracefully with a precise message, never a traceback."""

    EXPECTED = (
        "interchange truncated: transaction 0001 (ST at line 3) is missing "
        "its SE/GE/IEA trailers; last complete segment is N4 at line 7; the "
        "file ends with an unterminated segment 'PO1*1*24*EA*18.75**VN*SAF-0'"
    )

    def test_parse_raises_with_truncation_message(self):
        with pytest.raises(X12ParseError) as excinfo:
            parse_transaction(KIT / "850_05_truncated.edi")
        assert str(excinfo.value).endswith(self.EXPECTED)

    def test_cli_fails_gracefully_without_traceback(self, harness_dir: Path):
        result = subprocess.run(
            [
                sys.executable, "-m", "mapcheck.cli", "validate",
                "--spec", str(harness_dir / "audit_spec.xlsx"),
                "--source", str(KIT / "850_05_truncated.edi"),
                "--output", str(harness_dir / "850_01_clean.json"),
                "--no-history", "--no-color",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "interchange truncated" in result.stderr
        assert "last complete segment is N4 at line 7" in result.stderr
        assert "Traceback" not in result.stderr
        assert "Traceback" not in result.stdout


class TestRobustness:
    """Wire-format variations of the clean file must validate identically."""

    @staticmethod
    def _signature(run: RunResult) -> list[tuple]:
        return sorted(
            (f.status.value, f.row_id or "", f.target, f.message)
            for f in run.findings
        )

    def test_single_stream_no_newlines(self, harness_dir: Path, tmp_path: Path):
        """Real files arrive as one continuous stream as often as not."""
        text = (KIT / "850_01_clean.edi").read_text(encoding="utf-8")
        stream = tmp_path / "850_01_stream.edi"
        stream.write_text(text.replace("\n", ""), encoding="utf-8")
        run = validate_files(
            str(harness_dir / "audit_spec.xlsx"),
            str(stream),
            str(harness_dir / "850_01_clean.json"),
        )
        baseline = _run(harness_dir, "850_01_clean")
        assert run.overall is Status.PASS
        assert self._signature(run) == self._signature(baseline)

    def test_alternate_delimiters(self, harness_dir: Path, tmp_path: Path):
        """Delimiters are declared in the ISA, not assumed: | for *, ' for ~."""
        text = (KIT / "850_01_clean.edi").read_text(encoding="utf-8")
        assert "|" not in text and "'" not in text
        swapped = tmp_path / "850_01_delims.edi"
        swapped.write_text(
            text.replace("*", "|").replace("~", "'"), encoding="utf-8"
        )
        run = validate_files(
            str(harness_dir / "audit_spec.xlsx"),
            str(swapped),
            str(harness_dir / "850_01_clean.json"),
        )
        baseline = _run(harness_dir, "850_01_clean")
        assert run.overall is Status.PASS
        assert self._signature(run) == self._signature(baseline)

    def test_non_ascii_bytes_rejected_gracefully(self, tmp_path: Path):
        """A BOM (or any non-ASCII byte) is not X12: clean reject, no crash."""
        bom_file = tmp_path / "850_01_bom.edi"
        bom_file.write_bytes(
            b"\xef\xbb\xbf" + (KIT / "850_01_clean.edi").read_bytes()
        )
        with pytest.raises(X12ParseError) as excinfo:
            parse_transaction(bom_file)
        assert str(excinfo.value).endswith(
            "file is not valid X12 (non-ASCII bytes at position 0)"
        )

    def test_version_mismatch_warns_but_validates(
        self, harness_dir: Path, tmp_path: Path
    ):
        """A 5010-declared file is validated against the 4010 definition,
        with the mismatch called out as a warning."""
        text = (KIT / "850_01_clean.edi").read_text(encoding="utf-8")
        variant = tmp_path / "850_01_5010.edi"
        variant.write_text(
            text.replace("*U*00401*", "*U*00501*").replace(
                "*X*004010~", "*X*005010~"
            ),
            encoding="utf-8",
        )
        run = validate_files(
            str(harness_dir / "audit_spec.xlsx"),
            str(variant),
            str(harness_dir / "850_01_clean.json"),
        )
        assert run.overall is Status.WARNING
        assert run.exit_code == 0  # still validates; the mismatch is advisory
        warnings = [f for f in run.findings if f.status is Status.WARNING]
        assert len(warnings) == 1
        assert warnings[0].message == (
            "interchange control: file declares version 005010 (GS08) but the "
            "850 definition is 004010 — validated against the 004010 structure"
        )
        # Every rule still evaluated exactly as on the 4010 file.
        assert run.counts[Status.PASS] == 40
        assert run.counts[Status.FAIL] == 0
