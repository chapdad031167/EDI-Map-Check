"""Phase 5 tests: the pharma contract & chargeback set — 844, 845, 849, 854.

The 844/849 pair carries the chargeback money story (request total vs
line debits, approved total vs line approvals); the 845 exercises the
new ``not_after`` date-range check; the 854 is the discrepancy
reason-code showcase.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapcheck.engine import Category, RunResult, Status, validate_files
from mapcheck.transactions import DefinitionError, default_registry, load_definition

_SETS = {"844": "chargeback", "845": "priceauth", "849": "cbresponse", "854": "discrepancy"}


def _run(examples_dir: Path, set_code: str, kind: str) -> RunResult:
    return validate_files(
        str(examples_dir / "specs" / f"{set_code}_reference_spec.xlsx"),
        str(examples_dir / "source" / f"{set_code}_{kind}.edi"),
        str(examples_dir / "output" / f"{_SETS[set_code]}_{kind}.json"),
    )


class TestFamily:
    @pytest.mark.parametrize("set_code", sorted(_SETS))
    def test_registered(self, set_code):
        assert default_registry.get(set_code).set_code == set_code

    @pytest.mark.parametrize("set_code", sorted(_SETS))
    def test_baseline_all_pass(self, examples_dir, set_code):
        result = _run(examples_dir, set_code, "baseline")
        assert result.overall is Status.PASS, result.sorted_findings()[:5]
        counts = result.counts
        assert counts[Status.FAIL] == 0
        assert counts[Status.WARNING] == 0
        assert counts[Status.NOT_TESTED] == 0

    @pytest.mark.parametrize("set_code", sorted(_SETS))
    def test_defects_fail(self, examples_dir, set_code):
        result = _run(examples_dir, set_code, "defects")
        assert result.overall is Status.FAIL
        assert any(
            f.category is Category.SOURCE_DATA and "not a valid X12 date" in f.message
            for f in result.findings
        )
        assert any(f.category is Category.UNMAPPED_SOURCE for f in result.findings)


class Test844Chargeback:
    def test_baseline_money_maps(self, examples_dir):
        result = _run(examples_dir, "844", "baseline")
        by_target = {f.target: f for f in result.findings}
        assert by_target["lines[0].wac"].expected == "5.85"
        assert by_target["lines[0].contract_price"].expected == "4.10"
        assert by_target["lines[0].debit_amount"].expected == "70.00"
        assert by_target["request.contract_number"].expected == "CTR-2026-0142"

    def test_disputed_total(self, examples_dir):
        result = _run(examples_dir, "844", "defects")
        (finding,) = [f for f in result.findings if f.source_ref == "recon:request-total"]
        assert finding.status is Status.WARNING
        assert finding.expected == "AMT02@AMT[TT]=350.00"
        assert finding.actual == "sum(AMT02 over LIN)=320.00"

    def test_stale_contract_number(self, examples_dir):
        result = _run(examples_dir, "844", "defects")
        (finding,) = [f for f in result.findings if f.row_id == "G-004"]
        assert finding.status is Status.FAIL
        assert finding.category is Category.UNEXPECTED_OUTPUT
        assert "REF[CT] not present" in finding.message


class Test845DateWindow:
    def test_not_after_check_parsed(self):
        definition = default_registry.get("845")
        (rule,) = [r for r in definition.reconciliation if r.id == "auth-window-sane"]
        assert rule.check == "not_after"

    def test_valid_window_silent(self, examples_dir):
        result = _run(examples_dir, "845", "baseline")
        assert not [f for f in result.findings if f.source_ref.startswith("recon:")]

    def test_inverted_window_caught(self, examples_dir):
        result = _run(examples_dir, "845", "defects")
        (finding,) = [f for f in result.findings if f.source_ref == "recon:auth-window-sane"]
        assert finding.status is Status.WARNING
        assert "must not be after" in finding.message
        assert finding.expected == "DTM02@DTM[007]=20270101"
        assert finding.actual == "DTM02@DTM[036]=20260630"

    def test_missing_price_not_tested(self, examples_dir):
        result = _run(examples_dir, "845", "defects")
        (finding,) = [
            f for f in result.findings if f.target == "lines[1].authorized_price"
        ]
        assert finding.status is Status.NOT_TESTED

    def test_not_after_rejected_on_bad_kind(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(
            """
transaction: {set: "998", name: X, functional_group: ZZ}
structure:
  - {area: header, segments: [XA]}
reconciliation:
  - {id: r, left: {value: XA01}, right: {value: XA02}, check: before}
"""
        )
        with pytest.raises(DefinitionError, match="unsupported check 'before'"):
            load_definition(path)


class Test849Response:
    def test_status_codes_translate(self, examples_dir):
        result = _run(examples_dir, "849", "baseline")
        by_target = {f.target: f for f in result.findings}
        assert by_target["lines[0].line_status"].expected == "APPROVED"
        assert by_target["lines[1].line_status"].expected == "PARTIAL_APPROVAL"
        assert by_target["response.original_request_number"].expected == "CBR20260815001"

    def test_unknown_status(self, examples_dir):
        result = _run(examples_dir, "849", "defects")
        (finding,) = [f for f in result.findings if f.target == "lines[0].line_status"]
        assert finding.status is Status.FAIL
        assert "RESP_STATUS" in finding.message

    def test_approved_total_disagrees(self, examples_dir):
        result = _run(examples_dir, "849", "defects")
        (finding,) = [f for f in result.findings if f.source_ref == "recon:approved-total"]
        assert finding.expected == "AMT02@AMT[TT]=300.00"
        assert finding.actual == "sum(AMT02 over LIN)=270.00"


class Test854Discrepancy:
    def test_reason_codes_translate(self, examples_dir):
        result = _run(examples_dir, "854", "baseline")
        by_target = {f.target: f for f in result.findings}
        assert by_target["lines[0].reason"].expected == "SHORTAGE"
        assert by_target["lines[1].reason"].expected == "DAMAGED"
        assert by_target["carrier.scac"].expected == "RDWY"

    def test_unknown_reason(self, examples_dir):
        result = _run(examples_dir, "854", "defects")
        (finding,) = [f for f in result.findings if f.target == "lines[0].reason"]
        assert finding.status is Status.FAIL
        assert "DISCREPANCY" in finding.message

    def test_trusted_ctt_caught(self, examples_dir):
        result = _run(examples_dir, "854", "defects")
        (finding,) = [f for f in result.findings if f.row_id == "F-015"]
        assert finding.status is Status.FAIL
        assert (finding.expected, finding.actual) == ("2", "4")
