"""Engine tests: every rule category, exercised through the synthetic set.

The deliberately defective artifacts are the real fixtures here — each
planted defect must be caught, with the right status and root-cause
category, and the clean runs must stay silent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapcheck.engine import Category, RunResult, Status, validate_files


@pytest.fixture(scope="module")
def baseline_run(examples_dir: Path) -> RunResult:
    return validate_files(
        str(examples_dir / "specs" / "850_reference_spec.xlsx"),
        str(examples_dir / "source" / "850_baseline.edi"),
        str(examples_dir / "output" / "po_baseline.json"),
    )


@pytest.fixture(scope="module")
def flat_run(examples_dir: Path) -> RunResult:
    return validate_files(
        str(examples_dir / "specs" / "850_reference_spec.xlsx"),
        str(examples_dir / "source" / "850_baseline.edi"),
        str(examples_dir / "output" / "po_baseline.flat"),
    )


@pytest.fixture(scope="module")
def defective_output_run(examples_dir: Path) -> RunResult:
    return validate_files(
        str(examples_dir / "specs" / "850_reference_spec.xlsx"),
        str(examples_dir / "source" / "850_baseline.edi"),
        str(examples_dir / "output" / "po_baseline_defects.json"),
    )


@pytest.fixture(scope="module")
def bad_source_run(examples_dir: Path) -> RunResult:
    return validate_files(
        str(examples_dir / "specs" / "850_reference_spec.xlsx"),
        str(examples_dir / "source" / "850_defects.edi"),
        str(examples_dir / "output" / "po_from_bad_source.json"),
    )


@pytest.fixture(scope="module")
def minimal_run(examples_dir: Path) -> RunResult:
    return validate_files(
        str(examples_dir / "specs" / "850_reference_spec.xlsx"),
        str(examples_dir / "source" / "850_minimal.edi"),
        str(examples_dir / "output" / "po_minimal.json"),
    )


def _by_row(run: RunResult, row_id: str, target: str | None = None):
    matches = [
        f
        for f in run.findings
        if f.row_id == row_id and (target is None or f.target == target)
    ]
    assert matches, f"no finding for {row_id} {target or ''}"
    assert len(matches) == 1, f"multiple findings for {row_id} {target}: {matches}"
    return matches[0]


class TestCleanRuns:
    def test_baseline_all_pass(self, baseline_run: RunResult):
        assert baseline_run.overall is Status.PASS
        counts = baseline_run.counts
        assert counts[Status.FAIL] == 0
        assert counts[Status.WARNING] == 0
        assert counts[Status.NOT_TESTED] == 0
        assert counts[Status.PASS] == 44  # 26 header/summary + 6 per-line x 3 lines

    def test_flat_output_equivalent(self, flat_run: RunResult):
        assert flat_run.overall is Status.PASS
        assert flat_run.counts == {
            Status.PASS: 44,
            Status.FAIL: 0,
            Status.WARNING: 0,
            Status.NOT_TESTED: 0,
        }

    def test_exit_codes(self, baseline_run: RunResult, defective_output_run: RunResult):
        assert baseline_run.exit_code == 0
        assert defective_output_run.exit_code == 1


class TestPlantedOutputDefects:
    """Each planted defect in po_baseline_defects.json, one by one."""

    def test_value_accuracy(self, defective_output_run):  # rule category 1
        f = _by_row(defective_output_run, "M-004")
        assert f.status is Status.FAIL
        assert f.category is Category.VALUE_MISMATCH
        assert f.expected == "PO4400021" and f.actual == "PO4400012"

    def test_conditional_logic(self, defective_output_run):  # rule category 2
        f = _by_row(defective_output_run, "M-003")
        assert f.status is Status.FAIL
        assert f.category is Category.CONDITION_LOGIC
        assert f.expected == "N" and f.actual == "Y"

    def test_code_list_translation(self, defective_output_run):  # rule category 3
        f = _by_row(defective_output_run, "M-024", target="lines[0].uom")
        assert f.status is Status.FAIL
        assert f.category is Category.CODE_TRANSLATION
        assert f.expected == "EACH" and f.actual == "EA"

    def test_hardcoded_constant_missing(self, defective_output_run):  # rule category 4
        f = _by_row(defective_output_run, "M-012")
        assert f.status is Status.FAIL
        assert f.category is Category.CONSTANT_DEFAULT

    def test_default_not_applied(self, defective_output_run):  # rule category 4
        f = _by_row(defective_output_run, "M-032")
        assert f.status is Status.FAIL
        assert f.expected == "NONE"

    def test_date_format(self, defective_output_run):  # rule category 5
        f = _by_row(defective_output_run, "M-005")
        assert f.status is Status.FAIL
        assert f.category is Category.FORMAT

    def test_implied_decimal(self, defective_output_run):  # rule category 5
        f = _by_row(defective_output_run, "M-013")
        assert f.status is Status.FAIL
        assert f.expected == "25.00" and f.actual == "2500"

    def test_length_violation(self, defective_output_run):  # rule category 5
        f = _by_row(defective_output_run, "M-018")
        assert f.status is Status.FAIL
        assert f.category is Category.FORMAT
        assert "length 4" in f.message

    def test_type_warning_on_string_qty(self, defective_output_run):  # rule category 5
        f = _by_row(defective_output_run, "M-023", target="lines[1].qty")
        assert f.status is Status.WARNING
        assert f.category is Category.FORMAT

    def test_dropped_line_flagged(self, defective_output_run):  # rule category 6
        count_findings = [
            f
            for f in defective_output_run.findings
            if f.category is Category.COUNT_MISMATCH and f.row_id is None
        ]
        assert len(count_findings) == 1
        assert count_findings[0].expected == "3" and count_findings[0].actual == "2"
        f = _by_row(defective_output_run, "M-023", target="lines[2].qty")
        assert f.status is Status.FAIL
        assert f.category is Category.MISSING_OUTPUT

    def test_unmapped_target(self, defective_output_run):  # rule category 7
        f = [
            f
            for f in defective_output_run.findings
            if f.category is Category.UNMAPPED_TARGET
        ]
        assert len(f) == 1
        assert f[0].target == "order.warehouse_code"
        assert f[0].status is Status.WARNING


class TestBadSourceRun:
    def test_invalid_source_date(self, bad_source_run):
        f = _by_row(bad_source_run, "M-005")
        assert f.status is Status.FAIL
        assert f.category is Category.SOURCE_DATA
        assert "20261301" in f.message

    def test_untranslatable_code(self, bad_source_run):
        f = _by_row(bad_source_run, "M-024", target="lines[1].uom")
        assert f.status is Status.FAIL
        assert f.category is Category.SOURCE_DATA
        assert "no entry in code list UOM" in f.message

    def test_ctt_trusted_but_loop_count_catches(self, bad_source_run):
        # The naive translator copied CTT01=5 into the output, so the CTT
        # rule agrees with it — but LOOP_COUNT counts the actual loops.
        assert _by_row(bad_source_run, "M-028").status is Status.PASS
        f = _by_row(bad_source_run, "M-029")
        assert f.status is Status.FAIL
        assert f.category is Category.COUNT_MISMATCH
        assert f.expected == "3" and f.actual == "5"

    def test_stale_bill_to(self, bad_source_run):
        f = _by_row(bad_source_run, "M-020")
        assert f.status is Status.FAIL
        assert f.category is Category.UNEXPECTED_OUTPUT
        f = _by_row(bad_source_run, "M-021")
        assert f.status is Status.FAIL
        assert f.category is Category.CONDITION_LOGIC

    def test_unmapped_source_itd(self, bad_source_run):  # rule category 7
        findings = [
            f for f in bad_source_run.findings if f.category is Category.UNMAPPED_SOURCE
        ]
        assert len(findings) == 1
        assert "ITD" in findings[0].source_ref
        assert "ITD01='01'" in findings[0].message

    def test_control_note_surfaces(self, bad_source_run):
        findings = [f for f in bad_source_run.findings if f.category is Category.CONTROL]
        assert len(findings) == 1
        assert findings[0].status is Status.WARNING
        assert "SE count" in findings[0].message


class TestMinimalRun:
    def test_passes_overall(self, minimal_run):
        assert minimal_run.overall is Status.PASS
        assert minimal_run.counts[Status.NOT_TESTED] == 12

    def test_absent_optional_segment_not_tested(self, minimal_run):
        f = _by_row(minimal_run, "M-010")
        assert f.status is Status.NOT_TESTED
        assert "DTM[002] not present" in f.message

    def test_loop_member_message_names_the_member(self, minimal_run):
        f = _by_row(minimal_run, "M-016")  # N3 within the present N1[ST] loop
        assert f.status is Status.NOT_TESTED
        assert "N3 not present in N1[ST]" in f.message

    def test_skip_condition_passes_when_absent(self, minimal_run):
        f = _by_row(minimal_run, "M-006")  # no CUR segment -> SKIP
        assert f.status is Status.PASS
        assert "condition" in f.message

    def test_default_applied(self, minimal_run):
        f = _by_row(minimal_run, "M-032")
        assert f.status is Status.PASS
        assert f.expected == "NONE"
