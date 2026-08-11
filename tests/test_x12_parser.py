"""Tests for the pyx12-backed X12 850 parser and addressing model."""

from __future__ import annotations

from pathlib import Path

import pytest

from mapcheck.spec.model import LoopContext
from mapcheck.x12 import Transaction850, X12ParseError, parse_850


@pytest.fixture(scope="module")
def baseline(examples_dir: Path) -> Transaction850:
    return parse_850(examples_dir / "source" / "850_baseline.edi")


@pytest.fixture(scope="module")
def defects(examples_dir: Path) -> Transaction850:
    return parse_850(examples_dir / "source" / "850_defects.edi")


class TestStructure:
    def test_envelope(self, baseline: Transaction850):
        assert baseline.envelope["sender_id"] == "MAPCHECKSND"
        assert baseline.envelope["transaction_set"] == "850"
        assert baseline.envelope["version"] == "004010"

    def test_areas(self, baseline: Transaction850):
        heading_ids = [s.seg_id for s in baseline.heading]
        assert heading_ids == ["BEG", "CUR", "REF", "REF", "REF", "DTM", "DTM", "SAC"]
        assert [s.seg_id for s in baseline.summary] == ["CTT", "AMT"]

    def test_n1_loops(self, baseline: Transaction850):
        assert [loop.qualifier for loop in baseline.n1_loops] == ["ST", "BT"]
        st_loop = baseline.n1_loops[0]
        assert [s.seg_id for s in st_loop.segments] == ["N1", "N3", "N4"]

    def test_po1_loops(self, baseline: Transaction850):
        assert len(baseline.po1_loops) == 3
        for loop in baseline.po1_loops:
            assert [s.seg_id for s in loop.segments] == ["PO1", "PID"]
        assert baseline.po1_loops[1].trigger.element(2) == "6"

    def test_clean_file_has_no_control_notes(self, baseline: Transaction850):
        assert baseline.control_notes == []
        assert baseline.control_errors == []

    def test_element_access(self, baseline: Transaction850):
        beg = baseline.heading[0]
        assert beg.element(3) == "PO4400021"
        assert beg.element(4) is None  # empty element
        assert beg.element(99) is None  # beyond segment length
        assert beg.ref(3) == "BEG03"


class TestScopes:
    def test_flat_scope(self, baseline: Transaction850):
        scope = baseline.flat_scope()
        assert scope.value("BEG", 3) == "PO4400021"
        assert scope.value("CTT", 1) == "3"
        assert scope.value("ZZZ", 1) is None

    def test_qualified_loop_context(self, baseline: Transaction850):
        (scope,) = baseline.scopes(LoopContext.parse("N1[ST]"))
        assert scope.value("N1", 2) == "ALPINE OUTFITTERS STORE 118"
        assert scope.value("N3", 1) == "4501 CASCADE AVE"
        assert scope.value("N4", 2) == "CO"

    def test_qualified_segment_context(self, baseline: Transaction850):
        (scope,) = baseline.scopes(LoopContext.parse("REF[IA]"))
        assert scope.value("REF", 2) == "VEND8821"
        (scope,) = baseline.scopes(LoopContext.parse("DTM[002]"))
        assert scope.value("DTM", 2) == "20260701"
        (scope,) = baseline.scopes(LoopContext.parse("AMT[TT]"))
        assert scope.value("AMT", 2) == "306"

    def test_repeating_loop_context(self, baseline: Transaction850):
        scopes = baseline.scopes(LoopContext.parse("PO1"))
        assert len(scopes) == 3
        assert [s.value("PO1", 1) for s in scopes] == ["1", "2", "3"]
        assert scopes[0].value("PID", 5) == "TRAIL MIX 12OZ"

    def test_unmatched_context_returns_empty(self, baseline: Transaction850):
        assert baseline.scopes(LoopContext.parse("N1[SF]")) == []
        assert baseline.scopes(LoopContext.parse("REF[ZZ]")) == []

    def test_business_segments_labels(self, baseline: Transaction850):
        labels = {label for label, _ in baseline.business_segments()}
        assert {"header", "N1[ST]", "N1[BT]", "PO1 #1", "PO1 #3", "summary"} <= labels
        seg_ids = [s.seg_id for _, s in baseline.business_segments()]
        assert "ISA" not in seg_ids and "SE" not in seg_ids


class TestDefectiveFile:
    def test_control_errors_catch_bad_se_count(self, defects: Transaction850):
        issues = defects.control_errors
        assert len(issues) == 1
        assert "SE01 segment count mismatch" in issues[0].message
        assert "claims 24" in issues[0].message and "contains 22" in issues[0].message
        assert issues[0].expected == "22" and issues[0].actual == "24"

    def test_structure_still_parses(self, defects: Transaction850):
        assert len(defects.po1_loops) == 3
        assert defects.flat_scope().value("CTT", 1) == "5"
        assert [loop.qualifier for loop in defects.n1_loops] == ["ST"]

    def test_unknown_uom_is_readable(self, defects: Transaction850):
        assert defects.po1_loops[1].trigger.element(3) == "XX"


class TestParseErrors:
    def test_missing_file(self, tmp_path: Path):
        with pytest.raises(X12ParseError, match="not found"):
            parse_850(tmp_path / "nope.edi")

    def test_not_x12(self, tmp_path: Path):
        bad = tmp_path / "notx12.edi"
        bad.write_text("this is not an EDI file\n")
        with pytest.raises(X12ParseError):
            parse_850(bad)

    def test_wrong_transaction_set(self, tmp_path: Path):
        content = (
            "ISA*00*          *00*          *ZZ*A              *ZZ*B              "
            "*260615*1200*U*00401*000000001*0*T*>~"
            "GS*IN*A*B*20260615*1200*1*X*004010~"
            "ST*810*0001~BIG*20260615*INV1~SE*3*0001~GE*1*1~IEA*1*000000001~"
        )
        bad = tmp_path / "810.edi"
        bad.write_text(content)
        with pytest.raises(X12ParseError, match="expected transaction set 850"):
            parse_850(bad)

    def test_minimal_parses(self, examples_dir: Path):
        tx = parse_850(examples_dir / "source" / "850_minimal.edi")
        assert len(tx.po1_loops) == 1
        assert tx.scopes(LoopContext.parse("REF[DP]")) == []
        assert tx.flat_scope().value("BEG", 4) is None
