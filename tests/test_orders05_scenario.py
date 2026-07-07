"""The 850-to-ORDERS05 scenario package (Task 3).

One synthetic 850, one composite mapping spec, and the same ORDERS05 IDoc
output written in both flat-file and IDoc-XML form. The load-bearing
guarantee: the two formats are interchangeable — identical canonical
dicts, and byte-identical validation findings for both the clean baseline
and the planted-defect scenario.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapcheck.engine import Category, RunResult, Status, validate_files
from mapcheck.output import load_output

#: (extension, expected adapter) — the same scenario in each IDoc format.
FORMATS = [("txt", "idoc-flat"), ("xml", "idoc-xml")]
EXTS = [ext for ext, _ in FORMATS]


def _output_path(examples_dir: Path, kind: str, ext: str) -> Path:
    return examples_dir / "output" / f"orders05_{kind}.{ext}"


def _run(examples_dir: Path, kind: str, ext: str) -> RunResult:
    return validate_files(
        str(examples_dir / "specs" / "orders05_reference_spec.xlsx"),
        str(examples_dir / "source" / "850_sap.edi"),
        str(_output_path(examples_dir, kind, ext)),
    )


def _fingerprint(result: RunResult) -> list[tuple]:
    """Everything observable about a finding except the output file path."""
    return [
        (f.row_id, f.status, f.category, f.source_ref, f.target,
         f.expected, f.actual, f.message)
        for f in result.findings
    ]


class TestBaseline:
    @pytest.mark.parametrize("ext,format_name", FORMATS)
    def test_clean_pass_in_both_formats(self, examples_dir, ext, format_name):
        out = load_output(_output_path(examples_dir, "baseline", ext))
        assert out.format_name == format_name
        result = _run(examples_dir, "baseline", ext)
        assert result.overall is Status.PASS
        counts = result.counts
        assert counts[Status.FAIL] == 0
        assert counts[Status.WARNING] == 0
        assert counts[Status.NOT_TESTED] == 0


class TestFormatEquivalence:
    @pytest.mark.parametrize("kind", ["baseline", "defects"])
    def test_identical_canonical_dicts(self, examples_dir, kind):
        flat = load_output(_output_path(examples_dir, kind, "txt"))
        xml = load_output(_output_path(examples_dir, kind, "xml"))
        assert flat.data == xml.data

    @pytest.mark.parametrize("kind", ["baseline", "defects"])
    def test_identical_findings(self, examples_dir, kind):
        flat = _run(examples_dir, kind, "txt")
        xml = _run(examples_dir, kind, "xml")
        assert _fingerprint(flat) == _fingerprint(xml)
        assert flat.overall is xml.overall


@pytest.fixture(scope="module", params=EXTS)
def result(examples_dir, request) -> RunResult:
    """The defects run, once per IDoc format."""
    return _run(examples_dir, "defects", request.param)


class TestPlantedDefects:
    """Each planted defect is caught with the intended root cause,
    in both IDoc formats."""

    def _one(self, result: RunResult, **attrs) -> object:
        matches = [
            f for f in result.findings
            if all(getattr(f, name) == value for name, value in attrs.items())
        ]
        assert len(matches) == 1, f"{attrs} matched {len(matches)} findings"
        return matches[0]

    def test_overall_fail(self, result):
        assert result.overall is Status.FAIL

    def test_transposed_po_number(self, result):
        f = self._one(result, row_id="I-003", status=Status.FAIL)
        assert f.category is Category.VALUE_MISMATCH
        assert f.expected == "PO5500077"
        assert f.actual == "PO5500770"

    def test_date_not_sap_format(self, result):
        f = self._one(result, row_id="I-004", status=Status.FAIL)
        assert f.category is Category.FORMAT
        assert "%Y%m%d" in f.message

    def test_currency_wrong_despite_condition(self, result):
        f = self._one(result, row_id="I-006", status=Status.FAIL)
        assert f.category is Category.CONDITION_LOGIC
        assert (f.expected, f.actual) == ("USD", "EUR")

    def test_missing_hardcoded_order_type(self, result):
        f = self._one(result, row_id="I-008", status=Status.FAIL)
        assert f.category is Category.CONSTANT_DEFAULT
        assert f.target == "org.012"

    def test_untranslated_unit_of_measure(self, result):
        f = self._one(result, row_id="I-019", target="lines[0].menee")
        assert f.category is Category.CODE_TRANSLATION
        assert (f.expected, f.actual) == ("ST", "EA")

    def test_dropped_line_count_mismatch(self, result):
        f = self._one(result, category=Category.COUNT_MISMATCH)
        assert f.target == "lines[]"
        assert (f.expected, f.actual) == ("3", "2")

    def test_dropped_line_fields_missing(self, result):
        missing = [
            f for f in result.findings
            if f.category is Category.MISSING_OUTPUT and "lines[2]" in f.target
        ]
        assert len(missing) == 6

    def test_stray_sales_org_is_unmapped_target(self, result):
        f = self._one(result, category=Category.UNMAPPED_TARGET)
        assert f.status is Status.WARNING
        assert f.target == "org.008"

    def test_no_other_failures(self, result):
        fails = [f for f in result.findings if f.status is Status.FAIL]
        warnings = [f for f in result.findings if f.status is Status.WARNING]
        assert len(fails) == 12
        assert len(warnings) == 1
