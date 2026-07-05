"""Phase 1 tests: the 856 ASN and its HL hierarchy.

The 856 is the architecture stress test — variable-depth HL trees,
ancestor-inherited scopes, nested party loops inside HL levels, and the
sum/count reconciliation grammar. Every planted defect in 856_defects.edi
must be caught with the right root cause; the two clean structures
(pick-and-pack and standard carton) must validate silently.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapcheck.engine import Category, RunResult, Status, validate_files
from mapcheck.spec.model import LoopContext
from mapcheck.x12 import TransactionDocument, parse_transaction


@pytest.fixture(scope="module")
def pickpack_tx(examples_dir: Path) -> TransactionDocument:
    return parse_transaction(examples_dir / "source" / "856_pickpack.edi")


@pytest.fixture(scope="module")
def pickpack_run(examples_dir: Path) -> RunResult:
    return validate_files(
        str(examples_dir / "specs" / "856_reference_spec.xlsx"),
        str(examples_dir / "source" / "856_pickpack.edi"),
        str(examples_dir / "output" / "asn_pickpack.json"),
    )


@pytest.fixture(scope="module")
def standard_run(examples_dir: Path) -> RunResult:
    return validate_files(
        str(examples_dir / "specs" / "856_reference_spec.xlsx"),
        str(examples_dir / "source" / "856_standard.edi"),
        str(examples_dir / "output" / "asn_standard.json"),
    )


@pytest.fixture(scope="module")
def defects_run(examples_dir: Path) -> RunResult:
    return validate_files(
        str(examples_dir / "specs" / "856_reference_spec.xlsx"),
        str(examples_dir / "source" / "856_defects.edi"),
        str(examples_dir / "output" / "asn_defects.json"),
    )


class TestHlTree:
    def test_auto_detected_as_856(self, pickpack_tx: TransactionDocument):
        assert pickpack_tx.definition.set_code == "856"
        assert pickpack_tx.envelope["functional_group"] == "SH"

    def test_occurrences_and_levels(self, pickpack_tx: TransactionDocument):
        loops = pickpack_tx.loops("HL")
        assert len(loops) == 7
        assert [loop.qualifier for loop in loops] == ["S", "O", "P", "I", "I", "P", "I"]
        assert [loop.hl_id for loop in loops] == ["1", "2", "3", "4", "5", "6", "7"]

    def test_parent_links(self, pickpack_tx: TransactionDocument):
        by_id = {loop.hl_id: loop for loop in pickpack_tx.loops("HL")}
        assert by_id["1"].parent is None
        assert by_id["2"].parent is by_id["1"]
        assert by_id["4"].parent is by_id["3"]  # item under first carton
        assert by_id["7"].parent is by_id["6"]  # item under second carton
        assert [a.hl_id for a in by_id["7"].ancestors()] == ["6", "2", "1"]

    def test_clean_tree_has_no_errors(self, pickpack_tx: TransactionDocument):
        assert pickpack_tx.hierarchy_errors == []
        assert pickpack_tx.control_notes == []
        assert pickpack_tx.definition_notes == []

    def test_item_scope_inherits_ancestors(self, pickpack_tx: TransactionDocument):
        scopes = pickpack_tx.scopes(LoopContext.parse("HL[I]"))
        assert len(scopes) == 3
        # first item reads its own SN1, its carton's MAN, its order's PRF
        assert scopes[0].value("SN1", 2) == "12"
        assert scopes[0].value("MAN", 2) == "00061414100734900012"
        assert scopes[0].value("PRF", 1) == "PO4400021"
        # third item sits in the second carton
        assert scopes[2].value("MAN", 2) == "00061414100734900029"

    def test_nested_n1_loop_inside_hl(self, pickpack_tx: TransactionDocument):
        (scope,) = pickpack_tx.scopes(LoopContext.parse("N1[ST]"))
        assert scope.value("N1", 2) == "ALPINE OUTFITTERS DC 12"
        assert scope.value("N4", 1) == "DENVER"


class TestCleanRuns:
    def test_pickpack_all_pass(self, pickpack_run: RunResult):
        assert pickpack_run.overall is Status.PASS
        assert pickpack_run.counts == {
            Status.PASS: 42,  # 24 header/summary + 6 per-line x 3 items
            Status.FAIL: 0,
            Status.WARNING: 0,
            Status.NOT_TESTED: 0,
        }
        assert pickpack_run.transaction_set == "856"

    def test_standard_all_pass(self, standard_run: RunResult):
        assert standard_run.overall is Status.PASS
        counts = standard_run.counts
        assert counts[Status.FAIL] == 0
        assert counts[Status.WARNING] == 0
        assert counts[Status.NOT_TESTED] == 0

    def test_standard_carton_skips_pack_fields(self, standard_run: RunResult):
        # no TD1 and no pack level: packaging/carton/sscc rules PASS as SKIP
        by_target = {
            f.target: f for f in standard_run.findings if f.row_id in ("A-007", "A-008")
        }
        assert all(f.status is Status.PASS for f in by_target.values())
        sscc = [f for f in standard_run.findings if f.row_id == "A-025"]
        assert all(f.status is Status.PASS and "condition" in f.message for f in sscc)


class TestPlantedDefects:
    def _hierarchy_failures(self, run: RunResult) -> list:
        return [
            f
            for f in run.findings
            if f.source_ref == "(hierarchy)" and f.status is Status.FAIL
        ]

    def test_illegal_nesting_caught(self, defects_run: RunResult):
        failures = self._hierarchy_failures(defects_run)
        assert any("'I' is not an allowed child of level 'S'" in f.message for f in failures)

    def test_orphan_caught(self, defects_run: RunResult):
        failures = self._hierarchy_failures(defects_run)
        assert any(
            "parent id '9' does not reference an earlier" in f.message for f in failures
        )

    def test_unknown_level_caught(self, defects_run: RunResult):
        failures = self._hierarchy_failures(defects_run)
        assert any("unknown level code 'X'" in f.message for f in failures)

    def test_hierarchy_failures_are_source_data(self, defects_run: RunResult):
        assert {f.category for f in self._hierarchy_failures(defects_run)} == {
            Category.SOURCE_DATA
        }

    def test_ctt_hl_count_rollup(self, defects_run: RunResult):
        (finding,) = [
            f for f in defects_run.findings if f.source_ref == "recon:ctt-hl-count"
        ]
        assert finding.status is Status.WARNING
        assert finding.expected == "CTT01=9"
        assert finding.actual == "count(HL)=7"

    def test_unit_sum_rollup(self, defects_run: RunResult):
        (finding,) = [
            f for f in defects_run.findings if f.source_ref == "recon:ctt02-unit-sum"
        ]
        assert finding.status is Status.WARNING
        assert "sum(SN102 over HL[I])=96" == finding.actual

    def test_carton_count_rollup(self, defects_run: RunResult):
        (finding,) = [
            f for f in defects_run.findings if f.source_ref == "recon:td1-carton-count"
        ]
        assert finding.expected == "TD102@HL[S]=5"
        assert finding.actual == "count(HL[P])=1"

    def test_loop_count_rule_catches_trusted_ctt(self, defects_run: RunResult):
        (finding,) = [f for f in defects_run.findings if f.row_id == "A-027"]
        assert finding.status is Status.FAIL
        assert finding.category is Category.COUNT_MISMATCH
        assert (finding.expected, finding.actual) == ("7", "9")

    def test_unmapped_definition_segment(self, defects_run: RunResult):
        notes = [f for f in defects_run.findings if f.source_ref == "(structure)"]
        assert any("segment PKG" in f.message for f in notes)

    def test_unmapped_source_data(self, defects_run: RunResult):
        unmapped = [
            f for f in defects_run.findings if f.category is Category.UNMAPPED_SOURCE
        ]
        assert any("REF02='MYSTERY'" in f.message for f in unmapped)

    def test_items_without_order_context_not_tested(self, defects_run: RunResult):
        # the illegally nested and orphaned items have no O ancestor, so
        # their po_number is untestable rather than a false FAIL
        po_findings = [f for f in defects_run.findings if f.row_id == "A-019"]
        statuses = {f.target: f.status for f in po_findings}
        assert statuses["lines[0].po_number"] is Status.NOT_TESTED
        assert statuses["lines[1].po_number"] is Status.PASS
        assert statuses["lines[2].po_number"] is Status.NOT_TESTED

    def test_overall_fails(self, defects_run: RunResult):
        assert defects_run.overall is Status.FAIL
        assert defects_run.exit_code == 1
