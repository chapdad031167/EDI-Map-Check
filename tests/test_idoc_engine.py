"""Config-driven IDoc output-adapter engine (design 003).

The load-bearing test is the ORDERS05 retrofit gate: parsing the bundled
ORDERS05 examples through the generic engine must produce byte-identical
canonical data to the hand-coded adapter it replaced (captured as golden
dicts before the refactor). The rest pins the routing grammar, the fixed
and delimited field readers, flat/XML equivalence, and loader errors.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mapcheck.output import MISSING, OutputLoadError, load_output
from mapcheck.output.idoc import (
    DefinitionError,
    OutputFormatRegistry,
    load_idoc_flat,
    parse_definition,
    register_output_definition,
)

GOLDEN = Path(__file__).parent / "golden" / "orders05_parsed.json"


class TestOrders05RetrofitGate:
    @pytest.mark.parametrize(
        "name",
        ["orders05_baseline.txt", "orders05_baseline.xml",
         "orders05_defects.txt", "orders05_defects.xml"],
    )
    def test_data_matches_golden(self, examples_dir, name):
        golden = json.loads(GOLDEN.read_text())[name]
        out = load_output(examples_dir / "output" / name)
        assert out.data == golden["data"]
        assert out.typed is golden["typed"]

    def test_flat_and_xml_still_identical(self, examples_dir):
        flat = load_output(examples_dir / "output" / "orders05_baseline.txt")
        xml = load_output(examples_dir / "output" / "orders05_baseline.xml")
        assert flat.data == xml.data


# ---------------------------------------------------------------------------
# grammar: routing kinds via small inline definitions
# ---------------------------------------------------------------------------

_FIXED_DEF = {
    "format": "test-fixed",
    "basic_type": "TESTIDOC",
    "layout": "fixed",
    "sdata_start": 5,
    "segnam": [0, 4],
    "detect": {"flat": {"control_record": "CTRL"}, "xml": {"root": "TESTIDOC"}},
    "segments": {
        "HDR": {"route": {"kind": "object", "section": "header"},
                "fields": {"A": [0, 3], "B": [3, 3]}},
        "ORG": {"route": {"kind": "keyed", "section": "org",
                          "qualifier": "Q", "value": "V"},
                "fields": {"Q": [0, 3], "V": [3, 5]}},
        "REF": {"route": {"kind": "keyed", "section": "refs",
                          "qualifier": "Q", "values": ["X", "Y"]},
                "fields": {"Q": [0, 3], "X": [3, 3], "Y": [6, 3]}},
        "PTR": {"route": {"kind": "partner", "section": "partners",
                          "qualifier": "P", "values": ["NAME"]},
                "fields": {"P": [0, 2], "NAME": [2, 10]}},
        "ITM": {"route": {"kind": "line"}, "fields": {"QTY": [0, 4]}},
        "ITX": {"route": {"kind": "line_child", "group": "ids",
                          "qualifier": "Q", "values": ["ID"]},
                "fields": {"Q": [0, 3], "ID": [3, 6]}},
    },
}


def _fixed_record(seg: str, sdata: str) -> str:
    return seg.ljust(4) + " " + sdata


def test_all_routing_kinds(tmp_path):
    defn = parse_definition(_FIXED_DEF)
    lines = [
        "CTRL TESTIDOC",
        _fixed_record("HDR", "foobar"),
        _fixed_record("ORG", "012NB   "),
        _fixed_record("REF", "001aaabbb"),
        _fixed_record("PTR", "WEACME      "),
        _fixed_record("ITM", "0012"),
        _fixed_record("ITX", "003UPC123"),
        _fixed_record("ITM", "0034"),
    ]
    path = tmp_path / "f.txt"
    path.write_text("\n".join(lines) + "\n")
    out = load_idoc_flat(path, defn)
    assert out.data["header"] == {"a": "foo", "b": "bar"}
    assert out.data["org"] == {"012": "NB"}
    assert out.data["refs"] == {"001": {"x": "aaa", "y": "bbb"}}
    assert out.data["partners"] == {"we": {"name": "ACME"}}
    assert out.data["lines"][0]["qty"] == "0012"
    assert out.data["lines"][0]["ids"] == {"003": {"id": "UPC123"}}
    assert out.get("lines[].ids.003.id", 1) is MISSING  # second line has no child


def test_line_child_before_line_errors(tmp_path):
    defn = parse_definition(_FIXED_DEF)
    path = tmp_path / "bad.txt"
    path.write_text("CTRL TESTIDOC\n" + _fixed_record("ITX", "003UPC123") + "\n")
    with pytest.raises(OutputLoadError, match="before any line segment"):
        load_idoc_flat(path, defn)


def test_wrong_basic_type_errors(tmp_path):
    defn = parse_definition(_FIXED_DEF)
    path = tmp_path / "wrong.txt"
    path.write_text("CTRL OTHERIDOC\n")
    with pytest.raises(OutputLoadError, match="only TESTIDOC"):
        load_idoc_flat(path, defn)


# ---------------------------------------------------------------------------
# delimited (user format) layout
# ---------------------------------------------------------------------------

_DELIMITED_DEF = {
    "format": "user-csv",
    "layout": "delimited",
    "delimiter": ",",
    "record_id_col": 0,
    "segments": {
        "H": {"route": {"kind": "object", "section": "order"},
              "fields": {"PO": 1, "DATE": 2}},
        "D": {"route": {"kind": "line"}, "fields": {"SKU": 1, "QTY": 2}},
    },
}


def test_delimited_layout(tmp_path):
    defn = parse_definition(_DELIMITED_DEF)
    path = tmp_path / "orders.csv"
    path.write_text("H,PO123,2026-07-01\nD,SKU9,12\nD,SKU8,6\n")
    out = load_idoc_flat(path, defn)
    assert out.data["order"] == {"po": "PO123", "date": "2026-07-01"}
    assert [ln["sku"] for ln in out.data["lines"]] == ["SKU9", "SKU8"]


def test_register_user_definition_and_load(tmp_path):
    # a user onboards a delimited layout with zero Python
    defn_yaml = tmp_path / "mycsv.yaml"
    defn_yaml.write_text(
        "format: my-orders-csv\nlayout: delimited\ndelimiter: '|'\n"
        "record_id_col: 0\nsegments:\n"
        "  H: {route: {kind: object, section: order}, fields: {PO: 1}}\n"
    )
    register_output_definition(defn_yaml)
    data = tmp_path / "o.dat"
    data.write_text("H|PO777\n")
    out = load_output(data, output_format="my-orders-csv")
    assert out.get("order.po") == "PO777"


# ---------------------------------------------------------------------------
# definition validation
# ---------------------------------------------------------------------------


class TestDefinitionErrors:
    def test_unknown_route_kind(self):
        with pytest.raises(DefinitionError, match="route kind"):
            parse_definition({"format": "x", "segments": {
                "S": {"route": {"kind": "bogus"}, "fields": {}}}})

    def test_keyed_needs_value(self):
        with pytest.raises(DefinitionError, match="requires a 'value'"):
            parse_definition({"format": "x", "segments": {
                "S": {"route": {"kind": "keyed", "section": "s", "qualifier": "Q"},
                      "fields": {}}}})

    def test_missing_format(self):
        with pytest.raises(DefinitionError, match="format"):
            parse_definition({"segments": {}})

    def test_unknown_format_lookup(self):
        reg = OutputFormatRegistry()
        with pytest.raises(DefinitionError, match="unknown output format"):
            reg.get("nope")


# ---------------------------------------------------------------------------
# bundled definitions are discoverable
# ---------------------------------------------------------------------------


def test_bundled_formats_registered():
    reg = OutputFormatRegistry()
    formats = {d.format for d in reg.all()}
    assert "idoc-orders05" in formats
