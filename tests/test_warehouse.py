"""Phase 3 tests: the warehouse suite — 940, 945, 943, 944, 947.

The five sets share family DNA (data-driven baseline checks), with
targeted tests for what each brings: the 945's short-ship declaration
math, the transfer pair's total checks, and the 947's adjustment-reason
code list with signed quantities.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapcheck.engine import Category, RunResult, Status, validate_files
from mapcheck.transactions import default_registry

_SETS = {
    "940": ("shiporder", "OW"),
    "945": ("shipadvice", "SW"),
    "943": ("xfership", "AR"),
    "944": ("xferreceipt", "RE"),
    "947": ("invadjust", "AW"),
}


def _run(examples_dir: Path, set_code: str, kind: str) -> RunResult:
    prefix = _SETS[set_code][0]
    return validate_files(
        str(examples_dir / "specs" / f"{set_code}_reference_spec.xlsx"),
        str(examples_dir / "source" / f"{set_code}_{kind}.edi"),
        str(examples_dir / "output" / f"{prefix}_{kind}.json"),
    )


class TestFamily:
    @pytest.mark.parametrize("set_code", sorted(_SETS))
    def test_registered_with_group(self, set_code):
        definition = default_registry.get(set_code)
        assert definition.functional_group == _SETS[set_code][1]

    @pytest.mark.parametrize("set_code", sorted(_SETS))
    def test_baseline_all_pass(self, examples_dir, set_code):
        result = _run(examples_dir, set_code, "baseline")
        assert result.overall is Status.PASS, result.sorted_findings()[:5]
        counts = result.counts
        assert counts[Status.FAIL] == 0
        assert counts[Status.WARNING] == 0
        assert counts[Status.NOT_TESTED] == 0
        assert result.transaction_set == set_code

    @pytest.mark.parametrize("set_code", sorted(_SETS))
    def test_defects_fail(self, examples_dir, set_code):
        result = _run(examples_dir, set_code, "defects")
        assert result.overall is Status.FAIL
        assert result.exit_code == 1
        # every defective file plants an invalid date -> source_data FAIL
        assert any(
            f.category is Category.SOURCE_DATA and "not a valid X12 date" in f.message
            for f in result.findings
        )
        # and unreferenced contact/instruction data -> unmapped warning
        assert any(f.category is Category.UNMAPPED_SOURCE for f in result.findings)


@pytest.fixture(scope="module")
def wh945_defects(examples_dir) -> RunResult:
    return _run(examples_dir, "945", "defects")


class Test945ShortShip:
    def test_total_lie_caught(self, wh945_defects):
        defects = wh945_defects
        (finding,) = [f for f in defects.findings if f.source_ref == "recon:w03-shipped-sum"]
        assert finding.status is Status.WARNING
        assert finding.expected == "W0301=80"
        assert finding.actual == "sum(W1203 over LX)=75"

    def test_undeclared_short_ship_caught(self, wh945_defects):
        defects = wh945_defects
        (finding,) = [
            f for f in defects.findings if f.source_ref == "recon:short-ship-declared"
        ]
        assert finding.status is Status.WARNING
        assert finding.expected.endswith("=9")  # ordered 84 - shipped 75
        assert finding.actual == "sum(W1204 over LX)=5"  # only 5 declared

    def test_declared_short_ship_is_silent(self, examples_dir):
        baseline = _run(examples_dir, "945", "baseline")
        assert not [f for f in baseline.findings if f.source_ref.startswith("recon:")]
        # the declared difference maps through
        (finding,) = [f for f in baseline.findings if f.target == "lines[1].qty_difference"]
        assert finding.status is Status.PASS
        assert finding.expected == "5"

    def test_undeclared_difference_skips(self, examples_dir):
        baseline = _run(examples_dir, "945", "baseline")
        (finding,) = [f for f in baseline.findings if f.target == "lines[0].qty_difference"]
        assert finding.status is Status.PASS
        assert "condition" in finding.message  # EXISTS(W1204) false -> SKIP


class TestTransferPair:
    def test_943_total_check(self, examples_dir):
        result = _run(examples_dir, "943", "defects")
        (finding,) = [f for f in result.findings if f.source_ref == "recon:w03-transfer-sum"]
        assert (finding.expected, finding.actual) == ("W0301=70", "sum(W0401 over W04)=64")

    def test_944_total_check(self, examples_dir):
        result = _run(examples_dir, "944", "defects")
        (finding,) = [f for f in result.findings if f.source_ref == "recon:w14-receipt-sum"]
        assert (finding.expected, finding.actual) == ("W1401=60", "sum(W0701 over W07)=64")


class Test947Adjustments:
    def test_signed_quantities_validate(self, examples_dir):
        baseline = _run(examples_dir, "947", "baseline")
        by_target = {f.target: f for f in baseline.findings}
        assert by_target["lines[0].qty"].expected == "-5"
        assert by_target["lines[0].qty"].status is Status.PASS
        assert by_target["lines[1].qty"].expected == "12"

    def test_reason_code_translation(self, examples_dir):
        baseline = _run(examples_dir, "947", "baseline")
        by_target = {f.target: f for f in baseline.findings}
        assert by_target["lines[0].reason"].expected == "DAMAGED"
        assert by_target["lines[2].reason"].expected == "EXPIRED"

    def test_unknown_reason_caught(self, examples_dir):
        result = _run(examples_dir, "947", "defects")
        (finding,) = [f for f in result.findings if f.target == "lines[0].reason"]
        assert finding.status is Status.FAIL
        assert finding.category is Category.SOURCE_DATA
        assert "no entry in code list ADJ_REASON" in finding.message


class Test940:
    def test_unknown_order_status(self, examples_dir):
        result = _run(examples_dir, "940", "defects")
        (finding,) = [f for f in result.findings if f.row_id == "O-001"]
        assert finding.status is Status.FAIL
        assert "ORDER_STATUS" in finding.message

    def test_no_recon_rules_by_design(self):
        assert default_registry.get("940").reconciliation == ()

    def test_conditional_sku_qualifier(self, examples_dir):
        baseline = _run(examples_dir, "940", "baseline")
        (finding,) = [f for f in baseline.findings if f.target == "lines[0].vendor_sku"]
        assert finding.status is Status.PASS
        assert finding.expected == "SKU-1001"
