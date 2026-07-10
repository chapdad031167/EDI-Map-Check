"""Unit tests for the ORDERS05 IDoc output adapters (flat + XML).

These use small inline fixtures to pin parser behavior; the full
850-to-ORDERS05 validation scenario package lives in test_orders05_scenario
(Task 3).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapcheck.output import MISSING, OutputLoadError, load_output
from mapcheck.output.orders05 import _FLAT_FIELDS

# ---------------------------------------------------------------------------
# fixture builders
# ---------------------------------------------------------------------------

_SDATA_START = 63


def flat_record(seg_name: str, **fields: str) -> str:
    """Render one EDI_DD40 data record with fields at their SDATA offsets."""
    table = _FLAT_FIELDS[seg_name]
    end = max(offset + length for offset, length in table.values())
    sdata = [" "] * end
    for name, value in fields.items():
        offset, length = table[name.upper()]
        assert len(value) <= length, f"{name} too long for its field"
        sdata[offset : offset + len(value)] = value
    return seg_name.ljust(30) + " " * (_SDATA_START - 30) + "".join(sdata)


def control_record(idoctyp: str = "ORDERS05") -> str:
    return "EDI_DC40".ljust(30) + " " * 20 + idoctyp


def xml_doc(idoc_body: str, root: str = "ORDERS05", idoctyp: str = "ORDERS05") -> str:
    return (
        f"<{root}><IDOC BEGIN=\"1\">"
        f"<EDI_DC40 SEGMENT=\"1\"><IDOCTYP>{idoctyp}</IDOCTYP></EDI_DC40>"
        f"{idoc_body}</IDOC></{root}>"
    )


BASIC_FLAT_RECORDS = [
    control_record(),
    flat_record("E1EDK01", action="000", curcy="USD", bsart="NB"),
    flat_record("E1EDK14", qualf="012", orgid="NB"),
    flat_record("E1EDK03", iddat="002", datum="20260701"),
    flat_record("E1EDK02", qualf="001", belnr="PO4400021", datum="20260615"),
    flat_record("E1EDKA1", parvw="WE", partn="0118",
                name1="ALPINE OUTFITTERS STORE 118", stras="4501 CASCADE AVE",
                ort01="BOULDER", pstlz="80301", regio="CO"),
    flat_record("E1EDP01", menge="12.000", menee="ST", vprei="8.50"),
    flat_record("E1EDP02", qualf="001", zeile="1"),
    flat_record("E1EDP19", qualf="003", idtnr="614141007349", ktext="TRAIL MIX 12OZ"),
    flat_record("E1EDP01", menge="6.000", menee="KAR", vprei="24.00"),
    flat_record("E1EDP02", qualf="001", zeile="2"),
    flat_record("E1EDS01", sumid="001", summe="2"),
]

BASIC_XML_BODY = """
<E1EDK01 SEGMENT="1"><ACTION>000</ACTION><CURCY>USD</CURCY><BSART>NB</BSART></E1EDK01>
<E1EDK14 SEGMENT="1"><QUALF>012</QUALF><ORGID>NB</ORGID></E1EDK14>
<E1EDK03 SEGMENT="1"><IDDAT>002</IDDAT><DATUM>20260701</DATUM></E1EDK03>
<E1EDK02 SEGMENT="1"><QUALF>001</QUALF><BELNR>PO4400021</BELNR><DATUM>20260615</DATUM></E1EDK02>
<E1EDKA1 SEGMENT="1"><PARVW>WE</PARVW><PARTN>0118</PARTN>
  <NAME1>ALPINE OUTFITTERS STORE 118</NAME1><STRAS>4501 CASCADE AVE</STRAS>
  <ORT01>BOULDER</ORT01><PSTLZ>80301</PSTLZ><REGIO>CO</REGIO></E1EDKA1>
<E1EDP01 SEGMENT="1"><MENGE>12.000</MENGE><MENEE>ST</MENEE><VPREI>8.50</VPREI>
  <E1EDP02 SEGMENT="1"><QUALF>001</QUALF><ZEILE>1</ZEILE></E1EDP02>
  <E1EDP19 SEGMENT="1"><QUALF>003</QUALF><IDTNR>614141007349</IDTNR>
    <KTEXT>TRAIL MIX 12OZ</KTEXT></E1EDP19>
</E1EDP01>
<E1EDP01 SEGMENT="1"><MENGE>6.000</MENGE><MENEE>KAR</MENEE><VPREI>24.00</VPREI>
  <E1EDP02 SEGMENT="1"><QUALF>001</QUALF><ZEILE>2</ZEILE></E1EDP02>
</E1EDP01>
<E1EDS01 SEGMENT="1"><SUMID>001</SUMID><SUMME>2</SUMME></E1EDS01>
"""


@pytest.fixture()
def flat_path(tmp_path: Path) -> Path:
    path = tmp_path / "orders05.txt"
    path.write_text("\n".join(BASIC_FLAT_RECORDS) + "\n")
    return path


@pytest.fixture()
def xml_path(tmp_path: Path) -> Path:
    path = tmp_path / "orders05.xml"
    path.write_text(xml_doc(BASIC_XML_BODY))
    return path


# ---------------------------------------------------------------------------
# structure
# ---------------------------------------------------------------------------


class TestFlatParsing:
    def test_detected_and_typed(self, flat_path):
        out = load_output(flat_path)
        assert out.format_name == "idoc-orders05"
        assert out.typed is False

    def test_sections(self, flat_path):
        out = load_output(flat_path)
        assert out.get("header.curcy") == "USD"
        assert out.get("header.bsart") == "NB"
        assert out.get("org.012") == "NB"
        assert out.get("dates.002") == "20260701"
        assert out.get("refs.001.belnr") == "PO4400021"
        assert out.get("refs.001.datum") == "20260615"
        assert out.get("partners.we.name1") == "ALPINE OUTFITTERS STORE 118"
        assert out.get("partners.we.regio") == "CO"

    def test_lines_and_folded_children(self, flat_path):
        out = load_output(flat_path)
        assert out.line_count() == 2
        assert out.get("lines[].menge", 0) == "12.000"
        assert out.get("lines[].refs.001.zeile", 0) == "1"
        assert out.get("lines[].ids.003.idtnr", 0) == "614141007349"
        assert out.get("lines[].menee", 1) == "KAR"
        assert out.get("summary.001") == "2"

    def test_missing_semantics(self, flat_path):
        out = load_output(flat_path)
        # line 2 has no E1EDP19: the ids group is absent, not empty
        assert out.get("lines[].ids.003.idtnr", 1) is MISSING
        # blank fixed-width field (no DATUM on E1EDK03 wasn't blank; use header)
        assert out.get("header.zterm") is MISSING

    def test_out_of_scope_segments_ignored(self, tmp_path):
        records = [
            control_record(),
            flat_record("E1EDK01", curcy="USD"),
            flat_record("E1EDP01", menge="5.000"),
            # E1EDP20 schedule line and an unknown segment: both skipped
            "E1EDP20".ljust(30) + " " * 33 + "005.000       20260701",
            "E1EDPT1".ljust(30) + " " * 33 + "TEXTID",
            flat_record("E1EDS01", sumid="001", summe="1"),
        ]
        path = tmp_path / "sched.txt"
        path.write_text("\n".join(records) + "\n")
        out = load_output(path)
        assert out.line_count() == 1
        assert out.get("lines[].schedule", 0) is MISSING
        assert out.get("summary.001") == "1"


class TestXmlParsing:
    def test_detected_and_sections(self, xml_path):
        out = load_output(xml_path)
        assert out.format_name == "idoc-orders05"
        assert out.typed is False
        assert out.get("refs.001.belnr") == "PO4400021"
        assert out.get("lines[].ids.003.ktext", 0) == "TRAIL MIX 12OZ"

    def test_empty_elements_are_absent(self, tmp_path):
        body = "<E1EDK01><CURCY>USD</CURCY><ZTERM>  </ZTERM></E1EDK01>"
        path = tmp_path / "empty.xml"
        path.write_text(xml_doc(body))
        out = load_output(path)
        assert out.get("header.zterm") is MISSING

    def test_unscoped_xml_fields_ignored(self, tmp_path):
        # POSEX exists in the file but is not in the extraction table, so
        # both formats agree it is absent from the canonical dict
        body = "<E1EDP01><POSEX>000010</POSEX><MENGE>1.000</MENGE></E1EDP01>"
        path = tmp_path / "posex.xml"
        path.write_text(xml_doc(body))
        out = load_output(path)
        assert out.get("lines[].posex", 0) is MISSING
        assert out.get("lines[].menge", 0) == "1.000"


class TestFormatEquivalence:
    def test_identical_canonical_dicts(self, flat_path, xml_path):
        assert load_output(flat_path).data == load_output(xml_path).data


class TestLoaderErrors:
    def test_wrong_basic_type_flat(self, tmp_path):
        # the ORDERS05 shim rejects a control record naming another basic type
        from mapcheck.output.orders05 import load_orders05_flat

        path = tmp_path / "other.txt"
        path.write_text(control_record("XXXXXX01") + "\n")
        with pytest.raises(OutputLoadError, match="only ORDERS05"):
            load_orders05_flat(path)

    def test_unregistered_xml_root(self, tmp_path):
        path = tmp_path / "other.xml"
        path.write_text("<UNKNOWN99><IDOC></IDOC></UNKNOWN99>")
        with pytest.raises(OutputLoadError, match="no registered IDoc XML format"):
            load_output(path)

    def test_wrong_xml_root_direct(self, tmp_path):
        from mapcheck.output.orders05 import load_orders05_xml

        path = tmp_path / "other.xml"
        path.write_text("<DESADV01><IDOC></IDOC></DESADV01>")
        with pytest.raises(OutputLoadError, match="expected a ORDERS05"):
            load_orders05_xml(path)

    def test_wrong_basic_type_xml_control(self, tmp_path):
        path = tmp_path / "ctl.xml"
        path.write_text(xml_doc("<E1EDK01><CURCY>USD</CURCY></E1EDK01>", idoctyp="ORDERS01"))
        with pytest.raises(OutputLoadError, match="ORDERS01"):
            load_output(path)

    def test_item_child_before_line(self, tmp_path):
        records = [
            control_record(),
            flat_record("E1EDP19", qualf="003", idtnr="614141007349"),
        ]
        path = tmp_path / "orphan.txt"
        path.write_text("\n".join(records) + "\n")
        with pytest.raises(OutputLoadError, match="before any line segment"):
            load_output(path)

    def test_invalid_xml(self, tmp_path):
        path = tmp_path / "broken.xml"
        path.write_text("<ORDERS05><IDOC>")
        with pytest.raises(OutputLoadError, match="not valid XML"):
            load_output(path)

    def test_keyed_flat_still_routes_correctly(self, examples_dir):
        # regression: the EDI_DC40 sniff must not hijack the keyed flat format
        out = load_output(examples_dir / "output" / "po_baseline.flat")
        assert out.format_name == "flat"
