"""Multi-transaction interchange validation (design 002).

Covers parse_interchange, the JSON-array output loader, document pairing
(exact key, positional fallback, keyless-multidoc error, duplicates,
orphans), history parent/child rows, and the three-850 reference scenario.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mapcheck.engine import (
    Category,
    InterchangeResult,
    Status,
    validate_files,
    validate_interchange_files,
)
from mapcheck.output import load_output, load_output_documents
from mapcheck.output.adapter import OutputLoadError
from mapcheck.report.history import RunHistory
from mapcheck.spec.parser import SpecLoadError
from mapcheck.x12.parser import parse_interchange, parse_transaction

SPEC = "850_multi_reference_spec.xlsx"


def _spec(examples_dir: Path) -> str:
    return str(examples_dir / "specs" / SPEC)


def _run(examples_dir: Path, source: str, output: str) -> InterchangeResult:
    return validate_interchange_files(
        _spec(examples_dir),
        str(examples_dir / "source" / source),
        str(examples_dir / "output" / output),
    )


@pytest.fixture(scope="module")
def baseline(examples_dir: Path) -> InterchangeResult:
    return _run(examples_dir, "850_multi_baseline.edi", "orders_multi_baseline.json")


@pytest.fixture(scope="module")
def defects(examples_dir: Path) -> InterchangeResult:
    return _run(examples_dir, "850_multi_defects.edi", "orders_multi_defects.json")


def _one(items, **attrs):
    matches = [
        f for f in items
        if all(getattr(f, name) == value for name, value in attrs.items())
    ]
    assert len(matches) == 1, f"{attrs} matched {len(matches)}"
    return matches[0]


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------


class TestParseInterchange:
    def test_returns_every_transaction(self, examples_dir):
        interchange = parse_interchange(
            str(examples_dir / "source" / "850_multi_baseline.edi")
        )
        assert len(interchange.documents) == 3
        assert [d.envelope["st_control"] for d in interchange.documents] == [
            "0001", "0002", "0003",
        ]
        assert all(d.definition.set_code == "850" for d in interchange.documents)

    def test_single_transaction_wrapper_unchanged(self, examples_dir):
        # parse_transaction still returns the first document of a single-txn file
        doc = parse_transaction(str(examples_dir / "source" / "850_baseline.edi"))
        assert doc.definition.set_code == "850"
        assert doc.envelope["st_control"]

    def test_json_array_loads_many_documents(self, examples_dir):
        docs = load_output_documents(
            str(examples_dir / "output" / "orders_multi_baseline.json")
        )
        assert len(docs) == 3
        assert docs[0].get("order.po_number") == "PO7700001"

    def test_single_json_stays_one_document(self, examples_dir):
        docs = load_output_documents(
            str(examples_dir / "output" / "po_baseline.json")
        )
        assert len(docs) == 1

    def test_empty_array_rejected(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text("[]")
        with pytest.raises(OutputLoadError, match="empty"):
            load_output_documents(path)


# ---------------------------------------------------------------------------
# baseline
# ---------------------------------------------------------------------------


class TestBaseline:
    def test_all_documents_pass(self, baseline):
        assert baseline.overall is Status.PASS
        assert len(baseline.documents) == 3
        assert not baseline.file_findings
        counts = baseline.counts
        assert counts[Status.FAIL] == 0
        assert counts[Status.WARNING] == 0

    def test_paired_by_po_number(self, baseline):
        assert [d.key for d in baseline.documents] == [
            "PO7700001", "PO7700002", "PO7700003",
        ]


# ---------------------------------------------------------------------------
# planted defects
# ---------------------------------------------------------------------------


class TestPlantedDefects:
    def test_overall_fail(self, defects):
        assert defects.overall is Status.FAIL

    def test_per_document_defect_still_fires(self, defects):
        doc = _one(defects.documents, key="PO7700002")
        finding = _one(doc.result.findings, row_id="X-005")
        assert finding.status is Status.FAIL
        assert finding.category is Category.VALUE_MISMATCH
        assert (finding.expected, finding.actual) == ("DENVER", "COLORADO SPRINGS")

    def test_other_documents_still_pass(self, defects):
        assert _one(defects.documents, key="PO7700001").result.overall is Status.PASS
        assert _one(defects.documents, key="PO7700003").result.overall is Status.PASS

    def test_source_orphan_is_missing_output(self, defects):
        f = _one(defects.file_findings, category=Category.MISSING_OUTPUT)
        assert f.status is Status.FAIL
        assert "PO7700004" in f.message

    def test_output_orphan_is_unexpected_output(self, defects):
        f = _one(defects.file_findings, category=Category.UNEXPECTED_OUTPUT)
        assert f.status is Status.FAIL
        assert "PO7700009" in f.message

    def test_duplicate_key_is_count_mismatch(self, defects):
        f = _one(defects.file_findings, category=Category.COUNT_MISMATCH)
        assert f.status is Status.FAIL
        assert "PO7700001" in f.message

    def test_rollup_categories(self, defects):
        cats = defects.category_counts
        assert cats[Category.MISSING_OUTPUT] == 1
        assert cats[Category.UNEXPECTED_OUTPUT] == 1
        assert cats[Category.COUNT_MISMATCH] == 1
        assert cats[Category.VALUE_MISMATCH] == 1


# ---------------------------------------------------------------------------
# pairing edge cases
# ---------------------------------------------------------------------------


class TestPairingEdges:
    def test_single_document_positional_fallback(self, examples_dir):
        # the plain 850 spec has no Pairing Key; a single-txn file still runs
        result = validate_interchange_files(
            str(examples_dir / "specs" / "850_reference_spec.xlsx"),
            str(examples_dir / "source" / "850_baseline.edi"),
            str(examples_dir / "output" / "po_baseline.json"),
        )
        assert len(result.documents) == 1
        assert result.documents[0].key == "#1"
        assert result.overall is Status.PASS

    def test_keyless_multidoc_is_hard_error(self, examples_dir, tmp_path):
        # the plain 850 spec declares no Pairing Key; a 3-transaction file
        # cannot be paired positionally
        array = json.dumps([{"order": {}}, {"order": {}}, {"order": {}}])
        out = tmp_path / "arr.json"
        out.write_text(array)
        with pytest.raises(SpecLoadError, match="no.*Pairing Key"):
            validate_interchange_files(
                str(examples_dir / "specs" / "850_reference_spec.xlsx"),
                str(examples_dir / "source" / "850_multi_baseline.edi"),
                str(out),
            )


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


class TestHistory:
    def test_parent_and_child_rows(self, defects, tmp_path):
        db = tmp_path / "hist.db"
        with RunHistory(db) as history:
            parent_id = history.record_interchange(defects)
            rows = history.recent_runs(20)
        parent = next(r for r in rows if r["id"] == parent_id)
        assert parent["interchange_id"] is None
        assert parent["document_key"] is None
        # aggregate rollup on the parent
        assert parent["failed"] == defects.counts[Status.FAIL]
        children = [r for r in rows if r["interchange_id"] == parent_id]
        assert len(children) == 3
        assert {r["document_key"] for r in children} == {
            "PO7700001", "PO7700002", "PO7700003",
        }

    def test_migration_on_legacy_db(self, tmp_path, examples_dir):
        # a db created without the new columns still records single runs
        db = tmp_path / "legacy.db"
        import sqlite3

        conn = sqlite3.connect(db)
        conn.executescript(
            "CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, run_at TEXT,"
            " spec_file TEXT, source_file TEXT, output_file TEXT, result TEXT,"
            " passed INT, failed INT, warnings INT, not_tested INT);"
            "CREATE TABLE findings (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INT,"
            " row_id TEXT, source_ref TEXT, target TEXT, status TEXT, category TEXT,"
            " expected TEXT, actual TEXT, message TEXT);"
        )
        conn.commit()
        conn.close()
        run = validate_files(
            str(examples_dir / "specs" / "850_reference_spec.xlsx"),
            str(examples_dir / "source" / "850_baseline.edi"),
            str(examples_dir / "output" / "po_baseline.json"),
        )
        with RunHistory(db) as history:
            run_id = history.record(run)
            rows = history.recent_runs(5)
        assert next(r for r in rows if r["id"] == run_id)["document_key"] is None
