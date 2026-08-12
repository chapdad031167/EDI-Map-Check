"""Parser for the templated implementation-guide family (Design 014).

Reads text-extractable PDF and plain-text guide exports in the
SpecBuilder-style layout — segment header blocks (``BEG … Pos: 020
Max: 1``), ``User Option (Usage)`` lines, Element Summary tables
(``Ref / Id / Element Name / Req / Type / Min/Max / Usage``), Code List
Summary blocks, and partner notes — into a
:class:`~mapcheck.guides.profile.GuideProfile`.

The flag-never-guess contract applies at parse time: a line that looks
like data but does not match its grammar lands in the profile's
``review`` list with page context, never in the data. A file that fails
family detection raises :class:`GuideParseError` naming the missing
fingerprints — never a half-parse.
"""

from __future__ import annotations

import re
from pathlib import Path

from mapcheck.guides.profile import (
    GuideCode,
    GuideElement,
    GuideProfile,
    GuideSegment,
)

#: File suffixes the extractor accepts.
_TEXT_SUFFIXES = {".txt"}
_PDF_SUFFIXES = {".pdf"}


class GuideParseError(Exception):
    """The file is not a parseable member of the guide family."""


# --------------------------------------------------------------------------
# Text extraction
# --------------------------------------------------------------------------


def extract_lines(path: str | Path) -> list[tuple[int, str]]:
    """Extract ``(page, line)`` pairs from a guide file.

    ``.txt`` files split on form-feed for pages; ``.pdf`` files extract
    through pdfplumber (the ``guides`` extra). Anything else is rejected.
    """
    path = Path(path)
    if not path.exists():
        raise GuideParseError(f"guide file not found: {path}")
    suffix = path.suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines: list[tuple[int, str]] = []
        for page_number, page in enumerate(text.split("\f"), start=1):
            lines.extend((page_number, line.rstrip()) for line in page.splitlines())
        return lines
    if suffix in _PDF_SUFFIXES:
        try:
            import pdfplumber
        except ImportError as exc:
            raise GuideParseError(
                "PDF guide import needs the 'guides' extra: "
                "pip install \"edi-mapcheck[guides]\""
            ) from exc
        lines = []
        try:
            with pdfplumber.open(str(path)) as pdf:
                for page_number, page in enumerate(pdf.pages, start=1):
                    text = page.extract_text() or ""
                    lines.extend(
                        (page_number, line.rstrip()) for line in text.splitlines()
                    )
        except Exception as exc:  # pdfplumber raises many shapes; fail clean
            raise GuideParseError(f"{path}: could not extract PDF text: {exc}") from exc
        if not any(line for _, line in lines):
            raise GuideParseError(
                f"{path}: no extractable text — scanned/image PDFs are out of "
                "scope (Design 014); export a text PDF or .txt from the "
                "authoring tool"
            )
        return lines
    raise GuideParseError(
        f"{path}: unsupported guide format {suffix!r} (expected .pdf or .txt)"
    )


# --------------------------------------------------------------------------
# Line grammar
# --------------------------------------------------------------------------

#: Segment header: "BEG Beginning Segment for Purchase Order Pos: 020 Max: 1"
_SEGMENT_HEADER = re.compile(
    r"^(?P<id>[A-Z][A-Z0-9]{1,2})\s+(?P<name>.+?)\s+Pos:\s*(?P<pos>\S+)\s+Max:\s*(?P<max>\S+)\s*$"
)
#: Continuation of the header box: "Heading - Mandatory" / "Detail - Optional"
_AREA_LINE = re.compile(r"^(Heading|Detail|Summary)\s*-\s*(Mandatory|Optional)\s*$")
#: "Loop: N/A Elements: 6" or "Loop: PO1 Elements: 9"
_LOOP_LINE = re.compile(r"^Loop:\s*(?P<loop>\S+)(?:\s+Elements:\s*\d+)?\s*$")
#: "User Option (Usage): Must use"
_USAGE_LINE = re.compile(r"^User Option \(Usage\):\s*(?P<usage>.+?)\s*$")
_ELEMENT_SUMMARY = re.compile(r"^Element Summary:?\s*$")
#: "BEG01 353 Transaction Set Purpose Code M ID 2/2 Must use"
_ELEMENT_ROW = re.compile(
    r"^(?P<ref>[A-Z][A-Z0-9]{1,2}\d{2})\s+(?P<id>\d+)\s+(?P<name>.+?)\s+"
    r"(?P<req>[MOCX])\s+(?P<type>[A-Z][A-Z0-9]{0,2})\s+"
    r"(?P<min>\d+)/(?P<max>\d+)\s+(?P<usage>Must use|Used|Not used|Not Used)\s*$"
)
#: Anything that starts like an element row but fails the full grammar.
_ELEMENT_ROW_LOOSE = re.compile(r"^(?P<ref>[A-Z][A-Z0-9]{1,2}\d{2})\b")
_CODE_LIST_HEADER = re.compile(r"^Code List Summary")
_CODE_COLUMNS = re.compile(r"^Code\s+Name\s*$")
#: "00 Original" / "DS Dropship"
_CODE_ROW = re.compile(r"^(?P<code>[A-Z0-9]{1,10})\s+(?P<name>\S.*)$")
#: "Insight Note: ..." / "Partner Note: ..." — any single-word-or-two label
_NOTE_LINE = re.compile(r"^(?P<label>[A-Z][A-Za-z]*(?: [A-Z][A-Za-z]*)?) Note:\s*(?P<note>.+)$")
_DESCRIPTION_LINE = re.compile(r"^Description:\s*")
_EXAMPLE_LINE = re.compile(r"^Example:?\s*$")

_USAGE_VALUES = {
    "must use": "must_use",
    "used": "used",
    "not used": "not_used",
}


def _normalize_usage(raw: str) -> str | None:
    return _USAGE_VALUES.get(raw.strip().lower())


def parse_guide(
    path: str | Path, transaction: str, partner: str
) -> GuideProfile:
    """Parse a guide file into a :class:`GuideProfile`.

    ``transaction`` and ``partner`` are supplied by the caller — never
    inferred from the document. Raises :class:`GuideParseError` when the
    file is not a member of the templated family.
    """
    path = Path(path)
    lines = extract_lines(path)

    fingerprints = {
        "segment header block (e.g. 'BEG … Pos: 020 Max: 1')": any(
            _SEGMENT_HEADER.match(line) for _, line in lines
        ),
        "'Element Summary' marker": any(
            _ELEMENT_SUMMARY.match(line) for _, line in lines
        ),
        "element rows (Ref/Req/Type/Min-Max/Usage)": any(
            _ELEMENT_ROW.match(line) for _, line in lines
        ),
    }
    missing = [name for name, found in fingerprints.items() if not found]
    if missing:
        raise GuideParseError(
            f"{path}: not a recognized implementation-guide layout — missing "
            + "; ".join(missing)
            + ". Free-form and scanned guides are out of scope (Design 014)."
        )

    profile = GuideProfile(
        transaction=transaction, partner=partner, source=path.name
    )

    segment: dict | None = None  # mutable accumulator for the open segment
    element: dict | None = None  # mutable accumulator for the last element
    in_element_summary = False
    in_code_list = False

    def close_element() -> None:
        nonlocal element
        if element is not None and segment is not None:
            segment["elements"].append(
                GuideElement(
                    ref=element["ref"],
                    name=element["name"],
                    req=element["req"],
                    type=element["type"],
                    min=element["min"],
                    max=element["max"],
                    usage=element["usage"],
                    codes=tuple(element["codes"]),
                    notes=tuple(element["notes"]),
                )
            )
        element = None

    def close_segment() -> None:
        nonlocal segment, in_element_summary, in_code_list
        close_element()
        if segment is not None:
            profile.segments.append(
                GuideSegment(
                    id=segment["id"],
                    name=segment["name"],
                    pos=segment["pos"],
                    max_use=segment["max"],
                    loop=segment["loop"],
                    usage=segment["usage"],
                    notes=tuple(segment["notes"]),
                    elements=tuple(segment["elements"]),
                )
            )
        segment = None
        in_element_summary = False
        in_code_list = False

    for page, raw_line in lines:
        line = raw_line.strip()
        if not line:
            in_code_list = False
            continue

        if header := _SEGMENT_HEADER.match(line):
            close_segment()
            segment = {
                "id": header["id"],
                "name": header["name"].strip(),
                "pos": header["pos"],
                "max": header["max"],
                "loop": "",
                "usage": "",
                "notes": [],
                "elements": [],
            }
            profile.facts_detected += 1
            profile.facts_confident += 1
            continue

        if segment is None:
            continue  # front matter, page headers, tables of contents

        if _AREA_LINE.match(line) or _EXAMPLE_LINE.match(line):
            in_code_list = False
            continue
        if loop_line := _LOOP_LINE.match(line):
            loop = loop_line["loop"]
            segment["loop"] = "" if loop.upper() == "N/A" else loop
            continue
        if usage_line := _USAGE_LINE.match(line):
            usage = _normalize_usage(usage_line["usage"])
            profile.facts_detected += 1
            if usage is None:
                profile.review.append(
                    f"page {page}: segment {segment['id']}: unrecognized usage "
                    f"{usage_line['usage']!r} — verify by hand"
                )
            else:
                profile.facts_confident += 1
                if in_element_summary and element is not None:
                    element["usage"] = usage
                else:
                    segment["usage"] = usage
            continue
        if _ELEMENT_SUMMARY.match(line):
            in_element_summary = True
            in_code_list = False
            continue
        if _CODE_LIST_HEADER.match(line):
            in_code_list = True
            continue
        if _CODE_COLUMNS.match(line):
            continue
        if _DESCRIPTION_LINE.match(line):
            in_code_list = False
            continue
        if note_line := _NOTE_LINE.match(line):
            note = note_line["note"].strip()
            target = element if element is not None else segment
            target["notes"].append(note)
            continue

        if in_element_summary and (row := _ELEMENT_ROW.match(line)):
            close_element()
            usage = _normalize_usage(row["usage"])
            profile.facts_detected += 1
            if usage is None:  # unreachable via the row grammar, kept honest
                profile.review.append(
                    f"page {page}: {row['ref']}: unrecognized usage "
                    f"{row['usage']!r} — verify by hand"
                )
                continue
            profile.facts_confident += 1
            element = {
                "ref": row["ref"],
                "name": row["name"].strip(),
                "req": row["req"],
                "type": row["type"],
                "min": int(row["min"]),
                "max": int(row["max"]),
                "usage": usage,
                "codes": [],
                "notes": [],
            }
            in_code_list = False
            continue

        if in_element_summary and _ELEMENT_ROW_LOOSE.match(line):
            # Looks like an element row but the grammar did not hold
            # (wrapped name, mangled column): a review fact, never data.
            profile.facts_detected += 1
            profile.review.append(
                f"page {page}: line looks like an element row but did not "
                f"parse — verify by hand: {line!r}"
            )
            continue

        if in_code_list and (code_row := _CODE_ROW.match(line)):
            if element is not None:
                element["codes"].append(
                    GuideCode(code=code_row["code"], name=code_row["name"].strip())
                )
            else:
                profile.review.append(
                    f"page {page}: code row with no open element — verify by "
                    f"hand: {line!r}"
                )
            continue

    close_segment()
    return profile
