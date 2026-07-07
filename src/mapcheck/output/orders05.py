"""SAP IDoc ORDERS05 output adapters: flat file and IDoc XML.

Both formats fold into the same canonical dict through one shared routine,
so format equivalence is structural rather than coincidental. The fold is
**mechanical**: SAP field names (lowercased) and qualifier values become
dict keys — the adapter never decides what a qualifier *means*. That
opinion lives in the mapping spec, exactly like X12-side ``REF[DP]``
addressing.

Canonical shape (spec Target Field paths address it directly)::

    header    E1EDK01 fields              header.curcy
    org       E1EDK14 QUALF -> ORGID      org.012
    dates     E1EDK03 IDDAT -> DATUM      dates.002
    refs      E1EDK02 by QUALF            refs.001.belnr
    partners  E1EDKA1 by PARVW            partners.we.name1
    lines[]   E1EDP01 + folded children   lines[].menge,
                                          lines[].refs.001.zeile,
                                          lines[].ids.003.idtnr
    summary   E1EDS01 SUMID -> SUMME      summary.001

Scope notes (reviewed design decisions):

* Parsed fields are exactly the validated set below; other fields of
  in-scope segments (POSEX, NETWR, ...) are ignored so SAP-assigned
  values don't produce unmapped-output noise on clean runs.
* E1EDP20 schedule lines are **excluded entirely** — per-schedule
  validation needs multi-list pairing (backlog). E1EDP05 conditions,
  taxes, and all text segments are likewise not parsed.
* Blank fixed-width regions and empty XML elements both mean *absent*
  (the key is omitted, resolving to MISSING). Fixed-width formats cannot
  distinguish empty-but-present, so ``BLANK`` outcomes are not testable
  against IDoc outputs; ``SKIP`` (absence) works fully.

Everything here is built from the public ORDERS05 basic type; the flat
record layout is the standard EDI_DD40 shape (SEGNAM at offset 0 length
30, SDATA from offset 63).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterator

from mapcheck.output.adapter import CanonicalOutput, OutputLoadError

#: EDI_DD40 data-record layout: SEGNAM [0:30], admin fields, SDATA [63:].
_SEGNAM_SLICE = slice(0, 30)
_SDATA_START = 63

#: Per-segment field extraction tables: field -> (offset, length) within
#: SDATA, from the public ORDERS05 segment definitions. Only the fields
#: the reference map validates are listed; everything else is ignored.
_FLAT_FIELDS: dict[str, dict[str, tuple[int, int]]] = {
    # ACTION(3) KZABS(1) CURCY(3) HWAER(3) WKURS(12) ZTERM(17)
    # KUNDEUINR(20) EIGENUINR(20) BSART(4) ...
    "E1EDK01": {"ACTION": (0, 3), "CURCY": (4, 3), "BSART": (79, 4)},
    # QUALF(3) ORGID(35)
    "E1EDK14": {"QUALF": (0, 3), "ORGID": (3, 35)},
    # IDDAT(3) DATUM(8) UZEIT(6)
    "E1EDK03": {"IDDAT": (0, 3), "DATUM": (3, 8)},
    # QUALF(3) BELNR(35) POSNR(6) DATUM(8) UZEIT(6)
    "E1EDK02": {"QUALF": (0, 3), "BELNR": (3, 35), "DATUM": (44, 8)},
    # PARVW(3) PARTN(17) LIFNR(17) NAME1..NAME4(4x35) STRAS(35) STRS2(35)
    # PFACH(35) ORT01(35) COUNC(9) PSTLZ(9) PSTL2(9) LAND1(3) ... REGIO@655(3)
    "E1EDKA1": {
        "PARVW": (0, 3), "PARTN": (3, 17), "NAME1": (37, 35),
        "STRAS": (177, 35), "ORT01": (282, 35), "PSTLZ": (326, 9),
        "REGIO": (655, 3),
    },
    # POSEX(6) ACTION(3) PSTYP(1) KZABS(1) MENGE(15) MENEE(3) BMNG2(15)
    # PMENE(3) ABFTZ(7) VPREI(15) PEINH(9) NETWR(18) ...
    "E1EDP01": {"MENGE": (11, 15), "MENEE": (26, 3), "VPREI": (54, 15)},
    # QUALF(3) BELNR(35) ZEILE(6) DATUM(8) UZEIT(6)
    "E1EDP02": {"QUALF": (0, 3), "ZEILE": (38, 6)},
    # QUALF(3) IDTNR(35) KTEXT(70) ...
    "E1EDP19": {"QUALF": (0, 3), "IDTNR": (3, 35), "KTEXT": (38, 70)},
    # SUMID(3) SUMME(18) SUNIT(3) WAERQ(3)
    "E1EDS01": {"SUMID": (0, 3), "SUMME": (3, 18)},
}

_SEGMENT_TAG_RE = re.compile(r"^E1[A-Z0-9]+$")

#: (segment name, {FIELD: value}) — the stream both parsers emit.
_SegmentStream = Iterator[tuple[str, dict[str, str]]]


# --------------------------------------------------------------------------
# Shared fold: segment stream -> canonical dict
# --------------------------------------------------------------------------


def _fold(segments: _SegmentStream, source: str) -> dict[str, Any]:
    """Fold an in-document-order segment stream into the canonical dict.

    Repeated qualifiers keep their first occurrence. Item children arriving
    before any E1EDP01 are a structural defect and fail the load.
    """
    data: dict[str, Any] = {}
    lines: list[dict[str, Any]] = []

    def qualified(section: dict, key: str, fields: dict[str, str], names: list[str]) -> None:
        entry = {name.lower(): fields[name] for name in names if name in fields}
        if entry:
            section.setdefault(key, entry)

    for seg_name, fields in segments:
        if seg_name == "E1EDK01":
            header = data.setdefault("header", {})
            for name, value in fields.items():
                header.setdefault(name.lower(), value)
        elif seg_name == "E1EDK14" and "QUALF" in fields and "ORGID" in fields:
            data.setdefault("org", {}).setdefault(fields["QUALF"], fields["ORGID"])
        elif seg_name == "E1EDK03" and "IDDAT" in fields and "DATUM" in fields:
            data.setdefault("dates", {}).setdefault(fields["IDDAT"], fields["DATUM"])
        elif seg_name == "E1EDK02" and "QUALF" in fields:
            qualified(data.setdefault("refs", {}), fields["QUALF"], fields, ["BELNR", "DATUM"])
        elif seg_name == "E1EDKA1" and "PARVW" in fields:
            qualified(
                data.setdefault("partners", {}),
                fields["PARVW"].lower(),
                fields,
                ["PARTN", "NAME1", "STRAS", "ORT01", "PSTLZ", "REGIO"],
            )
        elif seg_name == "E1EDP01":
            line = {name.lower(): value for name, value in fields.items()}
            lines.append(line)
        elif seg_name in ("E1EDP02", "E1EDP19"):
            if not lines:
                raise OutputLoadError(
                    f"{source}: {seg_name} item segment appears before any E1EDP01"
                )
            if "QUALF" not in fields:
                continue
            group = "refs" if seg_name == "E1EDP02" else "ids"
            names = ["ZEILE"] if seg_name == "E1EDP02" else ["IDTNR", "KTEXT"]
            qualified(lines[-1].setdefault(group, {}), fields["QUALF"], fields, names)
        elif seg_name == "E1EDS01" and "SUMID" in fields and "SUMME" in fields:
            data.setdefault("summary", {}).setdefault(fields["SUMID"], fields["SUMME"])
        # anything else (E1EDP20, texts, conditions, unknown): not parsed

    if lines:
        data["lines"] = lines
    if not data:
        raise OutputLoadError(f"{source}: no in-scope ORDERS05 segments found")
    return data


# --------------------------------------------------------------------------
# Flat file parser (EDI_DC40 control record + EDI_DD40 data records)
# --------------------------------------------------------------------------


def is_idoc_flat(first_line: str) -> bool:
    """True when a file's first line is an IDoc control record."""
    return first_line.startswith("EDI_DC40")


def _flat_segments(text: str, source: str) -> _SegmentStream:
    lines = text.splitlines()
    if not lines or not is_idoc_flat(lines[0]):
        raise OutputLoadError(f"{source}: missing EDI_DC40 control record")
    if "ORDERS05" not in lines[0]:
        raise OutputLoadError(
            f"{source}: control record does not name basic type ORDERS05 — "
            "only ORDERS05 IDocs are supported"
        )
    for line in lines[1:]:
        if not line.strip():
            continue
        seg_name = line[_SEGNAM_SLICE].strip()
        table = _FLAT_FIELDS.get(seg_name)
        if table is None:
            continue  # out-of-scope or unknown segment
        sdata = line[_SDATA_START:]
        fields = {}
        for name, (offset, length) in table.items():
            value = sdata[offset : offset + length].strip()
            if value:
                fields[name] = value
        yield seg_name, fields


def load_orders05_flat(path: Path) -> CanonicalOutput:
    """Parse an ORDERS05 IDoc flat file into the canonical model."""
    text = path.read_text(encoding="utf-8")
    data = _fold(_flat_segments(text, str(path)), str(path))
    return CanonicalOutput(
        data=data, typed=False, source_path=str(path), format_name="idoc-flat"
    )


# --------------------------------------------------------------------------
# IDoc XML parser
# --------------------------------------------------------------------------


def _xml_segments(element: ET.Element) -> _SegmentStream:
    """Preorder walk emitting segments; nesting becomes document order."""
    for child in element:
        if not _SEGMENT_TAG_RE.match(child.tag):
            continue
        fields = {}
        for sub in child:
            if _SEGMENT_TAG_RE.match(sub.tag):
                continue  # nested segment, handled by recursion below
            value = (sub.text or "").strip()
            if value:
                fields[sub.tag.upper()] = value
        # only keep fields the flat layout also extracts, so the two
        # formats stay byte-identical in the canonical dict
        table = _FLAT_FIELDS.get(child.tag)
        if table is not None:
            yield child.tag, {k: v for k, v in fields.items() if k in table}
        yield from _xml_segments(child)


def load_orders05_xml(path: Path) -> CanonicalOutput:
    """Parse a standard SAP ORDERS05 IDoc XML file into the canonical model."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise OutputLoadError(f"{path}: not valid XML — {exc}") from exc
    if root.tag != "ORDERS05":
        raise OutputLoadError(
            f"{path}: expected an ORDERS05 IDoc XML root, found <{root.tag}>"
        )
    idoc = root.find("IDOC")
    if idoc is None:
        raise OutputLoadError(f"{path}: no IDOC element under the ORDERS05 root")
    control = idoc.find("EDI_DC40")
    if control is not None:
        idoctyp = control.findtext("IDOCTYP", "").strip()
        if idoctyp and idoctyp != "ORDERS05":
            raise OutputLoadError(
                f"{path}: control record names basic type {idoctyp!r} — "
                "only ORDERS05 IDocs are supported"
            )
    data = _fold(_xml_segments(idoc), str(path))
    return CanonicalOutput(
        data=data, typed=False, source_path=str(path), format_name="idoc-xml"
    )
