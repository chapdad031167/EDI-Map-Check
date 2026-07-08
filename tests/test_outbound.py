"""Outbound direction (design 001): internal document → X12 target.

Covers the per-direction spec grammar, the X12 target-side normalizer,
and the outbound 855 reference scenario — the clean baseline must be
silent and every planted defect must be caught with its root cause.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mapcheck.engine import Category, RunResult, Status, validate_files
from mapcheck.engine.formats import NormalizationError, normalize_x12
from mapcheck.spec.conditions import ConditionSyntaxError, parse_condition
from mapcheck.spec.formats import parse_format
from mapcheck.spec.model import DataType, Direction
from mapcheck.spec.parser import SpecLoadError, load_spec
from mapcheck.spec.template import build_template

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

OUTBOUND_META = {"Transaction Set": "855", "Direction": "outbound"}


def write_spec(
    path: Path,
    rows: list[tuple],
    code_rows: list[tuple] = (),
    meta: dict[str, str] | None = None,
) -> Path:
    """Write a minimal spec workbook from raw Mapping-sheet rows."""
    wb = build_template()
    for sheet, data in (("Mapping", rows), ("CodeLists", code_rows)):
        ws = wb[sheet]
        for r, row in enumerate(data, start=2):
            for c, value in enumerate(row, start=1):
                if value not in ("", None):
                    ws.cell(row=r, column=c, value=value)
    ws_meta = wb["Meta"]
    for r in range(2, ws_meta.max_row + 1):
        key = ws_meta.cell(row=r, column=1).value
        if meta and key in meta:
            ws_meta.cell(row=r, column=2, value=meta[key])
    wb.save(path)
    return path


def load_errors(path: Path) -> str:
    with pytest.raises(SpecLoadError) as excinfo:
        load_spec(path)
    return str(excinfo.value)


def rule_row(**overrides) -> tuple:
    """A valid outbound DIRECT rule row, overridable per test."""
    cells = {
        "row_id": "T-001", "source": "order.po_number", "context": "",
        "target": "BAK03", "rule_type": "DIRECT", "cond_text": "",
        "cond": "", "then": "", "else_": "", "default": "",
        "code_list": "", "data_type": "string", "fmt": "", "notes": "",
    }
    cells.update(overrides)
    return tuple(cells.values())


# ---------------------------------------------------------------------------
# spec grammar per direction
# ---------------------------------------------------------------------------


class TestOutboundSpecGrammar:
    def test_direction_and_notation_load(self, tmp_path):
        spec = load_spec(write_spec(
            tmp_path / "ok.xlsx",
            [
                rule_row(),
                rule_row(row_id="T-002", source="lines[].qty", context="PO1",
                         target="PO102", data_type="integer"),
                rule_row(row_id="T-003", source="vendor.name", context="N1[SE]",
                         target="N102"),
                rule_row(row_id="T-004", source="lines[]", target="CTT01",
                         rule_type="LOOP_COUNT", data_type="integer"),
            ],
            meta=OUTBOUND_META,
        ))
        assert spec.direction is Direction.OUTBOUND
        by_id = {r.row_id: r for r in spec.rules}
        assert not by_id["T-001"].is_per_line
        assert by_id["T-002"].is_per_line  # bare loop context
        assert not by_id["T-003"].is_per_line  # qualified context
        assert by_id["T-002"].source_field == "lines[].qty"  # case preserved
        assert by_id["T-003"].target_ref() == "N1[SE] N102"

    def test_unknown_direction_rejected(self, tmp_path):
        errors = load_errors(write_spec(
            tmp_path / "bad.xlsx", [rule_row()],
            meta={"Transaction Set": "855", "Direction": "sideways"},
        ))
        assert "Direction must be 'inbound' or 'outbound'" in errors

    def test_element_ref_source_rejected(self, tmp_path):
        errors = load_errors(write_spec(
            tmp_path / "bad.xlsx", [rule_row(source="BAK03")], meta=OUTBOUND_META,
        ))
        assert "outbound Source Field must be a canonical path" in errors

    def test_path_target_rejected(self, tmp_path):
        errors = load_errors(write_spec(
            tmp_path / "bad.xlsx", [rule_row(target="order.po_number")],
            meta=OUTBOUND_META,
        ))
        assert "outbound Target Field must be an X12 element" in errors

    def test_outbound_condition_must_use_paths(self, tmp_path):
        errors = load_errors(write_spec(
            tmp_path / "bad.xlsx",
            [rule_row(rule_type="CONDITIONAL", cond="N103 = '92'", then="SOURCE")],
            meta=OUTBOUND_META,
        ))
        assert "expected a canonical path" in errors

    def test_inbound_condition_must_use_elements(self):
        with pytest.raises(ConditionSyntaxError, match="segment"):
            parse_condition("order.currency = 'USD'")
        condition = parse_condition("order.currency = 'USD'", allow_paths=True)
        assert condition.predicates[0].field == "order.currency"

    def test_per_line_path_requires_bare_context(self, tmp_path):
        errors = load_errors(write_spec(
            tmp_path / "bad.xlsx", [rule_row(source="lines[].qty", target="PO102")],
            meta=OUTBOUND_META,
        ))
        assert "requires a bare repeating Loop Context" in errors

    def test_loop_count_source_must_be_list_ref(self, tmp_path):
        errors = load_errors(write_spec(
            tmp_path / "bad.xlsx",
            [rule_row(source="PO1", target="CTT01", rule_type="LOOP_COUNT")],
            meta=OUTBOUND_META,
        ))
        assert "outbound LOOP_COUNT source must be a list reference" in errors

    def test_blank_outcome_records_load_note(self, tmp_path):
        spec = load_spec(write_spec(
            tmp_path / "blank.xlsx",
            [rule_row(rule_type="CONDITIONAL",
                      cond="EXISTS(order.po_number)", then="BLANK")],
            meta=OUTBOUND_META,
        ))
        assert len(spec.load_notes) == 1
        assert "BLANK" in spec.load_notes[0]
        assert "NOT TESTED" in spec.load_notes[0]

    def test_inbound_specs_unchanged(self, examples_dir):
        spec = load_spec(examples_dir / "specs" / "850_reference_spec.xlsx")
        assert spec.direction is Direction.INBOUND
        assert spec.load_notes == ()


# ---------------------------------------------------------------------------
# X12 target-side normalization
# ---------------------------------------------------------------------------


class TestNormalizeX12:
    def test_date_defaults_to_ccyymmdd(self):
        value, _ = normalize_x12("20260615", DataType.DATE, parse_format(None))
        assert value.isoformat() == "2026-06-15"
        with pytest.raises(NormalizationError, match="%Y%m%d"):
            normalize_x12("2026-06-15", DataType.DATE, parse_format(None))

    def test_date_pattern_override(self):
        value, _ = normalize_x12("260615", DataType.DATE, parse_format("%y%m%d"))
        assert value.isoformat() == "2026-06-15"

    def test_implied_decimals(self):
        value, _ = normalize_x12("1250", DataType.DECIMAL, parse_format("implied:2"))
        assert str(value) == "12.50"
        with pytest.raises(NormalizationError, match="implied:2"):
            normalize_x12("12.50", DataType.DECIMAL, parse_format("implied:2"))

    def test_places_requires_shown_decimals(self):
        value, _ = normalize_x12("8.50", DataType.DECIMAL, parse_format("places:2"))
        assert str(value) == "8.50"
        with pytest.raises(NormalizationError, match="2 decimal places"):
            normalize_x12("8.5", DataType.DECIMAL, parse_format("places:2"))

    def test_invalid_values(self):
        with pytest.raises(NormalizationError):
            normalize_x12("twelve", DataType.INTEGER, parse_format(None))
        with pytest.raises(NormalizationError):
            normalize_x12("1.2.3", DataType.DECIMAL, parse_format(None))


# ---------------------------------------------------------------------------
# the outbound 855 reference scenario
# ---------------------------------------------------------------------------


def _run(examples_dir: Path, output_name: str, source: Path | None = None) -> RunResult:
    return validate_files(
        str(examples_dir / "specs" / "855_outbound_reference_spec.xlsx"),
        str(source or examples_dir / "source" / "poa_response.json"),
        str(examples_dir / "output" / output_name),
    )


@pytest.fixture(scope="module")
def out_baseline(examples_dir: Path) -> RunResult:
    return _run(examples_dir, "855_ack_baseline.edi")


@pytest.fixture(scope="module")
def out_defects(examples_dir: Path) -> RunResult:
    return _run(examples_dir, "855_ack_defects.edi")


def _one(run: RunResult, **attrs):
    matches = [
        f for f in run.findings
        if all(getattr(f, name) == value for name, value in attrs.items())
    ]
    assert len(matches) == 1, f"{attrs} matched {len(matches)} findings"
    return matches[0]


class TestOutboundBaseline:
    def test_clean_pass(self, out_baseline):
        assert out_baseline.overall is Status.PASS
        counts = out_baseline.counts
        assert counts[Status.PASS] == 37  # 10 header/summary + 9 per-line x 3
        assert counts[Status.FAIL] == 0
        assert counts[Status.WARNING] == 0
        assert counts[Status.NOT_TESTED] == 0

    def test_paths_keep_their_roles(self, out_baseline):
        assert out_baseline.source_path.endswith("poa_response.json")
        assert out_baseline.output_path.endswith("855_ack_baseline.edi")

    def test_date_translated_to_ccyymmdd(self, out_baseline):
        finding = _one(out_baseline, row_id="O-004")
        assert finding.status is Status.PASS
        assert finding.expected == "2026-06-15"  # normalized display

    def test_per_line_labels(self, out_baseline):
        finding = _one(out_baseline, row_id="O-016", target="PO1 #2 ACK02")
        assert finding.status is Status.PASS
        assert finding.source_ref == "lines[1].qty_acknowledged"


class TestOutboundPlantedDefects:
    def test_overall_fail(self, out_defects):
        assert out_defects.overall is Status.FAIL
        counts = out_defects.counts
        assert counts[Status.FAIL] == 15
        assert counts[Status.WARNING] == 2

    def test_transposed_po_number(self, out_defects):
        f = _one(out_defects, row_id="O-003")
        assert f.category is Category.VALUE_MISMATCH
        assert (f.expected, f.actual) == ("PO4400021", "PO4400012")

    def test_iso_date_is_format_defect(self, out_defects):
        f = _one(out_defects, row_id="O-004")
        assert f.category is Category.FORMAT
        assert "%Y%m%d" in f.message

    def test_leaked_else_literal_is_condition_logic(self, out_defects):
        f = _one(out_defects, row_id="O-005")
        assert f.category is Category.CONDITION_LOGIC
        assert f.actual == "NONE"

    def test_wrong_hardcoded_qualifier(self, out_defects):
        f = _one(out_defects, row_id="O-006")
        assert f.category is Category.CONSTANT_DEFAULT
        assert f.target == "N1[SE] N103"
        assert (f.expected, f.actual) == ("92", "ZZ")

    def test_untranslated_status_code(self, out_defects):
        f = _one(out_defects, row_id="O-015", target="PO1 #1 ACK01")
        assert f.category is Category.CODE_TRANSLATION
        assert (f.expected, f.actual) == ("IA", "ACCEPTED")

    def test_dropped_line(self, out_defects):
        count = _one(out_defects, target="PO1 loops")
        assert count.category is Category.COUNT_MISMATCH
        assert (count.expected, count.actual) == ("3", "2")
        missing = [
            f for f in out_defects.findings
            if f.category is Category.MISSING_OUTPUT and "#3" in f.target
        ]
        assert len(missing) == 8
        constant = _one(out_defects, row_id="O-013", target="PO1 #3 PO106")
        assert constant.category is Category.CONSTANT_DEFAULT

    def test_recon_audits_produced_file(self, out_defects):
        f = _one(out_defects, source_ref="recon:ctt-line-count")
        assert f.status is Status.WARNING
        assert "output reconciliation failed" in f.message

    def test_stray_ref_is_unmapped_target(self, out_defects):
        f = _one(out_defects, category=Category.UNMAPPED_TARGET)
        assert f.status is Status.WARNING
        assert f.target == "header REF"
        assert "REF02='123456'" in f.message


class TestOutboundEngineEdges:
    def test_skip_expected_but_x12_populated(self, examples_dir, tmp_path):
        """Condition false → SKIP, but the map still wrote the element."""
        source = json.loads(
            (examples_dir / "source" / "poa_response.json").read_text()
        )
        del source["vendor"]["id"]
        path = tmp_path / "no_vendor_id.json"
        path.write_text(json.dumps(source))
        run = _run(examples_dir, "855_ack_baseline.edi", source=path)
        f = _one(run, row_id="O-008")
        assert f.status is Status.FAIL
        assert f.category is Category.CONDITION_LOGIC
        assert "expected no value" in f.message
        assert f.actual == "7731"

    def test_absent_source_field_not_tested(self, examples_dir, tmp_path):
        """A missing internal field makes its rule untestable, and the X12
        value it should have fed becomes unexpected output."""
        source = json.loads(
            (examples_dir / "source" / "poa_response.json").read_text()
        )
        del source["order"]["po_number"]
        path = tmp_path / "no_po.json"
        path.write_text(json.dumps(source))
        run = _run(examples_dir, "855_ack_baseline.edi", source=path)
        f = _one(run, row_id="O-003")
        assert f.status is Status.FAIL
        assert f.category is Category.UNEXPECTED_OUTPUT
        assert "absent from the source document" in f.message

    def test_blank_rule_not_tested_and_load_note_surfaces(
        self, examples_dir, tmp_path
    ):
        spec_path = write_spec(
            tmp_path / "blank.xlsx",
            [rule_row(row_id="B-001", source="order.po_date", target="BAK04",
                      rule_type="CONDITIONAL",
                      cond="EXISTS(order.po_number)", then="BLANK")],
            meta=OUTBOUND_META,
        )
        run = validate_files(
            str(spec_path),
            str(examples_dir / "source" / "poa_response.json"),
            str(examples_dir / "output" / "855_ack_baseline.edi"),
        )
        blank = _one(run, row_id="B-001")
        assert blank.status is Status.NOT_TESTED
        assert "BLANK outcome is not testable against an X12 target" in blank.message
        note = _one(run, source_ref="(spec)")
        assert note.status is Status.WARNING
        assert "BLANK" in note.message

    def test_wrong_transaction_set_names_output_side(self, examples_dir, tmp_path):
        spec_path = write_spec(
            tmp_path / "mismatch.xlsx", [rule_row()],
            meta={"Transaction Set": "850", "Direction": "outbound"},
        )
        with pytest.raises(SpecLoadError, match="output file is a 855"):
            validate_files(
                str(spec_path),
                str(examples_dir / "source" / "poa_response.json"),
                str(examples_dir / "output" / "855_ack_baseline.edi"),
            )
