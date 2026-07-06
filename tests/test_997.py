"""Phase 6 tests: the 997 Functional Acknowledgment — and the roadmap DoD."""

from __future__ import annotations

from pathlib import Path

import pytest

from mapcheck.engine import Category, RunResult, Status, validate_files
from mapcheck.transactions import default_registry

ROADMAP_SETS = {
    "810", "812", "844", "845", "846", "849", "850", "854", "855", "856",
    "867", "940", "943", "944", "945", "947", "997",
}


def _run(examples_dir: Path, kind: str) -> RunResult:
    return validate_files(
        str(examples_dir / "specs" / "997_reference_spec.xlsx"),
        str(examples_dir / "source" / f"997_{kind}.edi"),
        str(examples_dir / "output" / f"funcack_{kind}.json"),
    )


class Test997:
    def test_registered_under_fa(self):
        definition = default_registry.get("997")
        assert definition.functional_group == "FA"
        assert [rule.check for rule in definition.reconciliation] == [
            "not_greater", "not_greater",
        ]

    def test_baseline_all_pass(self, examples_dir):
        result = _run(examples_dir, "baseline")
        assert result.overall is Status.PASS
        counts = result.counts
        assert counts[Status.FAIL] == 0
        assert counts[Status.WARNING] == 0
        by_target = {f.target: f for f in result.findings}
        assert by_target["ack.group_status"].expected == "PARTIALLY_ACCEPTED"
        assert by_target["lines[1].status"].expected == "REJECTED"
        assert by_target["lines[0].control_number"].expected == "0001"

    def test_impossible_counts_caught(self, examples_dir):
        result = _run(examples_dir, "defects")
        (finding,) = [
            f for f in result.findings if f.source_ref == "recon:accepted-lte-received"
        ]
        assert finding.status is Status.WARNING
        assert "AK904=3 must not exceed AK903=2" in finding.message

    def test_unknown_ack_code(self, examples_dir):
        result = _run(examples_dir, "defects")
        (finding,) = [f for f in result.findings if f.target == "lines[0].status"]
        assert finding.status is Status.FAIL
        assert finding.category is Category.SOURCE_DATA

    def test_unmapped_error_detail(self, examples_dir):
        result = _run(examples_dir, "defects")
        unmapped = [f for f in result.findings if f.category is Category.UNMAPPED_SOURCE]
        assert any("AK3" in f.source_ref for f in unmapped)
        assert any("AK4" in f.source_ref for f in unmapped)


class TestRoadmapDefinitionOfDone:
    def test_all_seventeen_sets_registered(self):
        registered = {d.set_code for d in default_registry.all()}
        assert registered == ROADMAP_SETS
        assert len(registered) == 17

    @pytest.mark.parametrize("set_code", sorted(ROADMAP_SETS))
    def test_every_set_has_a_reference_spec(self, examples_dir, set_code):
        assert (examples_dir / "specs" / f"{set_code}_reference_spec.xlsx").exists()
