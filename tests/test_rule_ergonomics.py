"""Rule ergonomics (design 007): tolerances, date arithmetic, file lookups.

Covers the Format grammar additions (``tol:``, ``shift:``), the loader's
type cross-checks and ``file:`` code-list resolution, the engine behavior
(within-tolerance PASS-with-note, boundary, date shift both directions), and
the bundled 850 ergonomics scenario end to end.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from mapcheck.engine import Category, Status, validate_files
from mapcheck.spec.formats import FormatSpec, FormatSpecError, parse_format
from mapcheck.spec.parser import SpecLoadError, _load_code_list_file, load_spec
from mapcheck.spec.template import build_template

SPEC = "850_ergonomics_spec.xlsx"
SRC = "850_ergonomics.edi"


# ---------------------------------------------------------------------------
# Format grammar
# ---------------------------------------------------------------------------


class TestFormatGrammar:
    def test_tolerance_parses_as_decimal(self):
        assert parse_format("tol:0.01").tolerance == Decimal("0.01")
        assert parse_format("tol:5").tolerance == Decimal("5")

    def test_shift_days_and_weeks(self):
        assert parse_format("shift:+5d").shift_days == 5
        assert parse_format("shift:-30d").shift_days == -30
        assert parse_format("shift:+2w").shift_days == 14
        assert parse_format("shift:-1w").shift_days == -7

    def test_combined_with_pattern(self):
        spec = parse_format("%Y-%m-%d; shift:+5d")
        assert spec.pattern == "%Y-%m-%d" and spec.shift_days == 5

    def test_unknown_and_malformed_tokens_raise(self):
        with pytest.raises(FormatSpecError):
            parse_format("shift:5")  # missing unit
        with pytest.raises(FormatSpecError):
            parse_format("shift:+1m")  # months unsupported
        with pytest.raises(FormatSpecError):
            parse_format("tol:abc")

    def test_defaults_are_none(self):
        empty = FormatSpec()
        assert empty.tolerance is None and empty.shift_days is None


# ---------------------------------------------------------------------------
# external lookup file loader
# ---------------------------------------------------------------------------


class TestFileLookupLoader:
    def _csv(self, tmp_path: Path, text: str) -> Path:
        p = tmp_path / "xref.csv"
        p.write_text(text, encoding="utf-8")
        return p

    def test_positional_with_header_and_description(self, tmp_path):
        self._csv(tmp_path, "source,target,description\nEA,EACH,Each\nCA,CASE,Case\n")
        cl = _load_code_list_file("xref.csv", tmp_path)
        assert cl.translate("EA") == "EACH"
        assert cl.translate("CA") == "CASE"
        assert cl.descriptions["EA"] == "Each"

    def test_header_optional(self, tmp_path):
        self._csv(tmp_path, "EA,EACH\nCA,CASE\n")
        cl = _load_code_list_file("xref.csv", tmp_path)
        assert cl.translate("EA") == "EACH" and len(cl.entries) == 2

    def test_missing_file_raises_oserror(self, tmp_path):
        with pytest.raises(OSError, match="not found"):
            _load_code_list_file("nope.csv", tmp_path)

    def test_duplicate_source_raises(self, tmp_path):
        self._csv(tmp_path, "EA,EACH\nEA,EACHES\n")
        with pytest.raises(ValueError, match="duplicate"):
            _load_code_list_file("xref.csv", tmp_path)

    def test_short_row_raises(self, tmp_path):
        self._csv(tmp_path, "EA\n")
        with pytest.raises(ValueError, match="source,target"):
            _load_code_list_file("xref.csv", tmp_path)


# ---------------------------------------------------------------------------
# loader cross-checks (build tiny specs, load only — no EDI needed)
# ---------------------------------------------------------------------------


def _spec_with(tmp_path: Path, *, data_type: str, fmt: str, code_ref: str = "",
               rule_type: str = "DIRECT", source: str = "BEG03") -> Path:
    wb = build_template()
    wb["Meta"].cell(row=2, column=2, value="850")
    wb["Mapping"].append(
        ["R-001", source, "", "order.field", rule_type, "", "", "", "", "",
         code_ref, data_type, fmt, ""]
    )
    p = tmp_path / "s.xlsx"
    wb.save(p)
    return p


class TestLoaderCrossChecks:
    def test_shift_on_non_date_is_a_load_error(self, tmp_path):
        with pytest.raises(SpecLoadError, match="shift"):
            load_spec(_spec_with(tmp_path, data_type="string", fmt="shift:+5d"))

    def test_shift_on_date_loads(self, tmp_path):
        spec = load_spec(_spec_with(tmp_path, data_type="date", fmt="%Y-%m-%d; shift:+5d"))
        assert spec.rules[0].format == "%Y-%m-%d; shift:+5d"

    def test_tolerance_on_non_decimal_is_a_load_note(self, tmp_path):
        spec = load_spec(_spec_with(tmp_path, data_type="string", fmt="tol:0.01"))
        assert any("tol:" in note and "NEEDS REVIEW" in note for note in spec.load_notes)

    def test_missing_lookup_file_is_a_load_error(self, tmp_path):
        with pytest.raises(SpecLoadError, match="not found"):
            load_spec(_spec_with(
                tmp_path, data_type="string", fmt="", rule_type="CODE_LIST",
                source="PO103", code_ref="file:absent.csv",
            ))


# ---------------------------------------------------------------------------
# bundled 850 ergonomics scenario
# ---------------------------------------------------------------------------


def _run(examples_dir: Path, output: str):
    return validate_files(
        str(examples_dir / "specs" / SPEC),
        str(examples_dir / "source" / SRC),
        str(examples_dir / "output" / output),
    )


class TestScenario:
    def test_baseline_is_clean_pass(self, examples_dir):
        result = _run(examples_dir, "ergonomics_baseline.json")
        assert result.overall is Status.PASS
        assert result.counts[Status.FAIL] == 0
        assert result.counts[Status.WARNING] == 0

    def test_within_tolerance_passes_with_delta_note(self, examples_dir):
        result = _run(examples_dir, "ergonomics_baseline.json")
        tol = next(f for f in result.findings if f.row_id == "E-006")
        assert tol.status is Status.PASS
        assert "within tol:0.01" in tol.message and "Δ" in tol.message

    def test_date_shift_applied(self, examples_dir):
        result = _run(examples_dir, "ergonomics_baseline.json")
        shifted = next(f for f in result.findings if f.row_id == "E-005")
        assert shifted.status is Status.PASS
        assert "shifted +5d" in shifted.message

    def test_file_lookup_expands_uom(self, examples_dir):
        result = _run(examples_dir, "ergonomics_baseline.json")
        uom = [f for f in result.findings if f.row_id == "E-009"]
        assert all(f.status is Status.PASS for f in uom)
        assert any("file:uom_xref.csv" in f.message for f in uom)

    def test_defects_are_exactly_one_per_feature(self, examples_dir):
        result = _run(examples_dir, "ergonomics_defects.json")
        fails = {f.row_id: f for f in result.findings if f.status is Status.FAIL}
        assert set(fails) == {"E-005", "E-006", "E-009"}
        # tolerance breach and date miss are value mismatches; uom is translation
        assert fails["E-006"].category is Category.VALUE_MISMATCH
        assert fails["E-005"].category is Category.VALUE_MISMATCH
        assert fails["E-009"].category is Category.CODE_TRANSLATION

    def test_tolerance_boundary_and_outside(self, examples_dir, tmp_path):
        # boundary (exactly 0.01 off) passes; just outside fails
        import json

        base = json.loads(
            (examples_dir / "output" / "ergonomics_baseline.json").read_text()
        )
        for amount, expect_pass in ((306.015, True), (306.016, False)):
            base["order"]["total_amount"] = amount
            out = tmp_path / f"o_{amount}.json"
            out.write_text(json.dumps(base))
            result = validate_files(
                str(examples_dir / "specs" / SPEC),
                str(examples_dir / "source" / SRC),
                str(out),
            )
            e006 = next(f for f in result.findings if f.row_id == "E-006")
            assert (e006.status is Status.PASS) is expect_pass
