"""Phase 4 tests: 846 Inventory Advice, 812 Credit/Debit, 867 Product Transfer.

The 846 exercises the new path Loop Context (``LIN>QTY[QA]``): several
QTY segments per line, each qualifier a distinct output field. The 812
proves signed-amount reconciliation; the 867 combines path addressing
with a header-total rollup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapcheck.engine import Category, RunResult, Status, validate_files
from mapcheck.spec.model import LoopContext
from mapcheck.x12 import parse_transaction

_SETS = {"846": "invinquiry", "812": "creditdebit", "867": "xferreport"}


def _run(examples_dir: Path, set_code: str, kind: str) -> RunResult:
    return validate_files(
        str(examples_dir / "specs" / f"{set_code}_reference_spec.xlsx"),
        str(examples_dir / "source" / f"{set_code}_{kind}.edi"),
        str(examples_dir / "output" / f"{_SETS[set_code]}_{kind}.json"),
    )


class TestPathLoopContext:
    def test_parse_and_roundtrip(self):
        ctx = LoopContext.parse("LIN>QTY[QA]")
        assert (ctx.segment_id, ctx.qualifier) == ("LIN", None)
        assert (ctx.sub_segment_id, ctx.sub_qualifier) == ("QTY", "QA")
        assert str(ctx) == "LIN>QTY[QA]"
        assert ctx.base() == LoopContext.parse("LIN")

    def test_qualified_base_allowed(self):
        ctx = LoopContext.parse("HL[I]>QTY[38]")
        assert ctx.qualifier == "I"
        assert ctx.base() == LoopContext.parse("HL[I]")

    @pytest.mark.parametrize("bad", ["LIN>QTY", "LIN>", ">QTY[QA]", "LIN>QTY[QA]>X[1]"])
    def test_rejects_bad_paths(self, bad):
        with pytest.raises(ValueError):
            LoopContext.parse(bad)

    def test_narrowed_scopes_keep_line_alignment(self, examples_dir):
        tx = parse_transaction(examples_dir / "source" / "846_defects.edi")
        scopes = tx.scopes(LoopContext.parse("LIN>QTY[QC]"))
        # line 1 has no QC bucket: the scope survives, empty, so per-line
        # index pairing holds
        assert len(scopes) == 2
        assert scopes[0].segments == ()
        assert scopes[1].value("QTY", 2) == "75"

    def test_narrowing_selects_by_qualifier(self, examples_dir):
        tx = parse_transaction(examples_dir / "source" / "846_baseline.edi")
        qa = tx.scopes(LoopContext.parse("LIN>QTY[QA]"))
        qo = tx.scopes(LoopContext.parse("LIN>QTY[QO]"))
        assert [s.value("QTY", 2) for s in qa] == ["500", "1200"]
        assert [s.value("QTY", 2) for s in qo] == ["200", "0"]


class Test846:
    def test_baseline_all_pass(self, examples_dir):
        result = _run(examples_dir, "846", "baseline")
        assert result.overall is Status.PASS
        counts = result.counts
        assert counts[Status.FAIL] == 0 and counts[Status.WARNING] == 0
        assert counts[Status.NOT_TESTED] == 0

    def test_quantity_buckets_map_distinctly(self, examples_dir):
        result = _run(examples_dir, "846", "baseline")
        by_target = {f.target: f for f in result.findings}
        assert by_target["lines[0].qty_available"].expected == "500"
        assert by_target["lines[0].qty_on_order"].expected == "200"
        assert by_target["lines[0].qty_committed"].expected == "50"
        assert by_target["lines[1].qty_on_order"].expected == "0"

    def test_mystery_bucket_flagged(self, examples_dir):
        result = _run(examples_dir, "846", "defects")
        unmapped = [f for f in result.findings if f.category is Category.UNMAPPED_SOURCE]
        assert any("QTY01='ZZ'" in f.message for f in unmapped)

    def test_missing_bucket_not_tested(self, examples_dir):
        result = _run(examples_dir, "846", "defects")
        (finding,) = [f for f in result.findings if f.target == "lines[0].qty_committed"]
        assert finding.status is Status.NOT_TESTED
        assert "LIN>QTY[QC]" in finding.message

    def test_uom_on_bucket_translates(self, examples_dir):
        result = _run(examples_dir, "846", "defects")
        (finding,) = [f for f in result.findings if f.target == "lines[0].uom"]
        assert finding.status is Status.FAIL
        assert finding.category is Category.SOURCE_DATA


class Test812:
    def test_baseline_signed_math_silent(self, examples_dir):
        result = _run(examples_dir, "812", "baseline")
        assert result.overall is Status.PASS
        assert not [f for f in result.findings if f.source_ref.startswith("recon:")]
        by_target = {f.target: f for f in result.findings}
        assert by_target["lines[0].amount"].expected == "-25.00"
        assert by_target["adjustment.total_amount"].expected == "15.00"

    def test_backwards_key_signature(self, examples_dir):
        result = _run(examples_dir, "812", "defects")
        (finding,) = [f for f in result.findings if f.source_ref == "recon:bcd-total-foots"]
        assert finding.status is Status.WARNING
        assert finding.expected == "BCD04=15.00"
        assert finding.actual == "sum(CDD04 over CDD)=65.00"  # gap = 2x the credit

    def test_unknown_reason_code(self, examples_dir):
        result = _run(examples_dir, "812", "defects")
        (finding,) = [f for f in result.findings if f.target == "lines[0].reason"]
        assert finding.status is Status.FAIL
        assert "ADJ_REASON_812" in finding.message


class Test867:
    def test_baseline_all_pass(self, examples_dir):
        result = _run(examples_dir, "867", "baseline")
        assert result.overall is Status.PASS
        counts = result.counts
        assert counts[Status.FAIL] == 0 and counts[Status.WARNING] == 0
        by_target = {f.target: f for f in result.findings}
        assert by_target["lines[0].qty"].expected == "100"
        assert by_target["lines[0].resale_price"].expected == "8.99"
        assert by_target["report.total_quantity"].expected == "175"

    def test_header_total_rollup(self, examples_dir):
        result = _run(examples_dir, "867", "defects")
        (finding,) = [f for f in result.findings if f.source_ref == "recon:total-qty"]
        assert finding.status is Status.WARNING
        assert finding.expected == "QTY02@QTY[TO]=200"
        assert finding.actual == "sum(QTY02 over PTD)=175"

    def test_trusted_ctt_caught_by_loop_count(self, examples_dir):
        result = _run(examples_dir, "867", "defects")
        (finding,) = [f for f in result.findings if f.row_id == "P-018"]
        assert finding.status is Status.FAIL
        assert (finding.expected, finding.actual) == ("2", "3")

    def test_defects_fail_overall(self, examples_dir):
        result = _run(examples_dir, "867", "defects")
        assert result.overall is Status.FAIL
        assert any(
            f.category is Category.SOURCE_DATA and "not a valid X12 date" in f.message
            for f in result.findings
        )
