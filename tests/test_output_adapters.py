"""Tests for the JSON and keyed-flat output adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from mapcheck.output import MISSING, OutputLoadError, load_output


class TestJsonAdapter:
    def test_load_baseline(self, examples_dir: Path):
        out = load_output(examples_dir / "output" / "po_baseline.json")
        assert out.typed is True
        assert out.format_name == "json"
        assert out.get("order.po_number") == "PO4400021"
        assert out.get("ship_to.zip") == "80301"
        assert out.get("lines[].qty", line_index=1) == 6
        assert out.line_count() == 3

    def test_missing_paths(self, examples_dir: Path):
        out = load_output(examples_dir / "output" / "po_baseline.json")
        assert out.get("order.nope") is MISSING
        assert out.get("nope.nope") is MISSING
        assert out.get("lines[].qty", line_index=99) is MISSING

    def test_line_index_required(self, examples_dir: Path):
        out = load_output(examples_dir / "output" / "po_baseline.json")
        with pytest.raises(ValueError, match="requires a line index"):
            out.get("lines[].qty")

    def test_walk_paths(self, examples_dir: Path):
        out = load_output(examples_dir / "output" / "po_baseline.json")
        paths = {norm for norm, _, _ in out.walk_paths()}
        assert "order.po_number" in paths
        assert "lines[].uom" in paths
        concrete = {c for _, c, _ in out.walk_paths()}
        assert "lines[2].uom" in concrete

    def test_invalid_json(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        with pytest.raises(OutputLoadError, match="not valid JSON"):
            load_output(bad)

    def test_non_object_top_level(self, tmp_path: Path):
        bad = tmp_path / "scalar.json"
        bad.write_text("42")
        with pytest.raises(OutputLoadError, match="must be an object"):
            load_output(bad)

    def test_array_top_level_points_to_interchange(self, tmp_path: Path):
        bad = tmp_path / "list.json"
        bad.write_text("[{}, {}]")
        with pytest.raises(OutputLoadError, match="interchange validation"):
            load_output(bad)


class TestFlatAdapter:
    def test_load_baseline_flat(self, examples_dir: Path):
        out = load_output(examples_dir / "output" / "po_baseline.flat")
        assert out.typed is False
        assert out.format_name == "flat"
        assert out.get("order.po_number") == "PO4400021"
        assert out.get("ship_to.name") == "ALPINE OUTFITTERS STORE 118"
        assert out.get("bill_to.id") == "0001"
        assert out.get("lines[].unit_price", line_index=0) == "8.50"
        assert out.line_count() == 3
        assert out.get("summary.line_count") == "3"

    def test_comments_and_blanks_ignored(self, tmp_path: Path):
        flat = tmp_path / "out.flat"
        flat.write_text("# comment\n\nH|po_number=X\n\nS|line_count=0\n")
        out = load_output(flat)
        assert out.get("order.po_number") == "X"

    def test_unknown_record_code(self, tmp_path: Path):
        flat = tmp_path / "out.flat"
        flat.write_text("Z|foo=bar\n")
        with pytest.raises(OutputLoadError, match="unknown record code 'Z'"):
            load_output(flat)

    def test_a_record_requires_role(self, tmp_path: Path):
        flat = tmp_path / "out.flat"
        flat.write_text("A|name=X\n")
        with pytest.raises(OutputLoadError, match="requires a role"):
            load_output(flat)

    def test_malformed_field(self, tmp_path: Path):
        flat = tmp_path / "out.flat"
        flat.write_text("H|justakey\n")
        with pytest.raises(OutputLoadError, match="malformed field"):
            load_output(flat)

    def test_missing_file(self, tmp_path: Path):
        with pytest.raises(OutputLoadError, match="not found"):
            load_output(tmp_path / "nope.flat")
