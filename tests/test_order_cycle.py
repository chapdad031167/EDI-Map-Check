"""Phase 2 tests: the 855 PO Acknowledgment and 810 Invoice.

The 810 brings the first cross-field arithmetic reconciliation (TDS vs
line extensions plus charges minus allowances); the 855 exercises
repeated-segment sums (a line's ACK accept/reject split must still
account for every ordered unit).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapcheck.engine import Category, RunResult, Status, validate_files
from mapcheck.transactions import DefinitionError, default_registry, load_definition


def _run(examples_dir: Path, spec: str, source: str, output: str) -> RunResult:
    return validate_files(
        str(examples_dir / "specs" / spec),
        str(examples_dir / "source" / source),
        str(examples_dir / "output" / output),
    )


@pytest.fixture(scope="module")
def poa_baseline(examples_dir: Path) -> RunResult:
    return _run(examples_dir, "855_reference_spec.xlsx", "855_baseline.edi", "poa_baseline.json")


@pytest.fixture(scope="module")
def poa_defects(examples_dir: Path) -> RunResult:
    return _run(examples_dir, "855_reference_spec.xlsx", "855_defects.edi", "poa_defects.json")


@pytest.fixture(scope="module")
def invoice_baseline(examples_dir: Path) -> RunResult:
    return _run(
        examples_dir, "810_reference_spec.xlsx", "810_baseline.edi", "invoice_baseline.json"
    )


@pytest.fixture(scope="module")
def invoice_defects(examples_dir: Path) -> RunResult:
    return _run(
        examples_dir, "810_reference_spec.xlsx", "810_defects.edi", "invoice_defects.json"
    )


class TestDefinitions:
    def test_registered(self):
        assert default_registry.get("855").functional_group == "PR"
        assert default_registry.get("810").functional_group == "IN"

    def test_810_combine_rule_parsed(self):
        definition = default_registry.get("810")
        (rule,) = [r for r in definition.reconciliation if r.id == "tds-invoice-total"]
        assert rule.left.implied == 2
        assert rule.right.is_combine
        assert rule.right.add[0].sum_expr == ("IT102", "IT104")
        assert rule.right.add[1].sum_loop == "SAC[C]"
        assert rule.right.add[1].implied == 2
        assert rule.right.subtract[0].sum_loop == "SAC[A]"


class Test855:
    def test_baseline_all_pass(self, poa_baseline: RunResult):
        assert poa_baseline.overall is Status.PASS
        counts = poa_baseline.counts
        assert counts[Status.FAIL] == 0
        assert counts[Status.WARNING] == 0  # the split-ACK line balances
        assert poa_baseline.transaction_set == "855"

    def test_split_ack_line_maps_first_ack(self, poa_baseline: RunResult):
        (finding,) = [
            f for f in poa_baseline.findings if f.target == "lines[1].qty_acknowledged"
        ]
        assert finding.status is Status.PASS
        assert finding.expected == "4"  # first ACK of the accept/reject split

    def test_vanished_units_caught(self, poa_defects: RunResult):
        (finding,) = [
            f for f in poa_defects.findings if f.source_ref == "recon:ack-qty-accounted"
        ]
        assert finding.status is Status.WARNING
        assert finding.expected == "sum(ACK02 over PO1)=21"
        assert finding.actual == "sum(PO102 over PO1)=23"

    def test_unknown_ack_status(self, poa_defects: RunResult):
        (finding,) = [f for f in poa_defects.findings if f.row_id == "K-014"
                      and f.target == "lines[2].line_status"]
        assert finding.status is Status.FAIL
        assert finding.category is Category.SOURCE_DATA
        assert "no entry in code list ACK_STATUS" in finding.message

    def test_trusted_ctt_caught_by_loop_count(self, poa_defects: RunResult):
        (finding,) = [f for f in poa_defects.findings if f.row_id == "K-018"]
        assert finding.status is Status.FAIL
        assert (finding.expected, finding.actual) == ("3", "5")

    def test_bad_bak_date(self, poa_defects: RunResult):
        (finding,) = [f for f in poa_defects.findings if f.row_id == "K-004"]
        assert finding.status is Status.FAIL
        assert finding.category is Category.SOURCE_DATA

    def test_unmapped_itd(self, poa_defects: RunResult):
        unmapped = [f for f in poa_defects.findings if f.category is Category.UNMAPPED_SOURCE]
        assert any("ITD" in f.source_ref for f in unmapped)


class Test810:
    def test_baseline_all_pass(self, invoice_baseline: RunResult):
        assert invoice_baseline.overall is Status.PASS
        counts = invoice_baseline.counts
        assert counts[Status.FAIL] == 0
        assert counts[Status.WARNING] == 0
        assert invoice_baseline.transaction_set == "810"

    def test_sac_loop_addressing(self, invoice_baseline: RunResult):
        by_row = {f.row_id: f for f in invoice_baseline.findings if f.row_id}
        assert by_row["V-016"].expected == "15.00"  # SAC[C] implied 2
        assert by_row["V-018"].expected == "8.00"  # SAC[A] implied 2

    def test_missed_allowance_math(self, invoice_defects: RunResult):
        (finding,) = [
            f for f in invoice_defects.findings if f.source_ref == "recon:tds-invoice-total"
        ]
        assert finding.status is Status.WARNING
        assert finding.category is Category.COUNT_MISMATCH
        assert finding.expected == "TDS01=321.00"
        assert "sum(IT102 * IT104 over IT1)=306.0" in finding.actual
        assert "- sum(SAC05 over SAC[A])=8.00" in finding.actual
        assert finding.actual.endswith("=313.00")

    def test_clean_math_is_silent(self, invoice_baseline: RunResult):
        assert not [
            f for f in invoice_baseline.findings if f.source_ref.startswith("recon:")
        ]

    def test_unknown_uom(self, invoice_defects: RunResult):
        (finding,) = [f for f in invoice_defects.findings if f.target == "lines[1].uom"]
        assert finding.status is Status.FAIL
        assert finding.category is Category.SOURCE_DATA

    def test_trusted_ctt_caught_by_loop_count(self, invoice_defects: RunResult):
        (finding,) = [f for f in invoice_defects.findings if f.row_id == "V-020"]
        assert finding.status is Status.FAIL
        assert (finding.expected, finding.actual) == ("3", "4")

    def test_bad_big_date(self, invoice_defects: RunResult):
        (finding,) = [f for f in invoice_defects.findings if f.row_id == "V-001"]
        assert finding.status is Status.FAIL
        assert finding.category is Category.SOURCE_DATA


class TestExprLoaderErrors:
    def _load(self, tmp_path: Path, recon_yaml: str):
        path = tmp_path / "bad.yaml"
        path.write_text(
            f"""
transaction: {{set: "998", name: X, functional_group: ZZ}}
structure:
  - area: header
    segments: [XA]
    loops:
      - {{id: LD, trigger: LD, segments: [XN]}}
reconciliation:
{recon_yaml}
"""
        )
        return load_definition(path)

    def test_bad_expr_rejected(self, tmp_path):
        with pytest.raises(DefinitionError, match="invalid expression"):
            self._load(
                tmp_path,
                '  - {id: r, left: {value: XA01}, '
                'right: {sum: {loop: LD, expr: "XN01 + XN02"}}}',
            )

    def test_sum_needs_value_or_expr(self, tmp_path):
        with pytest.raises(DefinitionError, match="expected .loop"):
            self._load(
                tmp_path,
                "  - {id: r, left: {value: XA01}, right: {sum: {loop: LD}}}",
            )

    def test_empty_combine_rejected(self, tmp_path):
        with pytest.raises(DefinitionError, match="combine"):
            self._load(
                tmp_path,
                "  - {id: r, left: {value: XA01}, right: {combine: {}}}",
            )

    def test_combine_loop_refs_validated(self, tmp_path):
        with pytest.raises(DefinitionError, match="undeclared loop"):
            self._load(
                tmp_path,
                "  - {id: r, left: {value: XA01}, "
                "right: {combine: {add: [{sum: {loop: NOPE, value: XN01}}]}}}",
            )
