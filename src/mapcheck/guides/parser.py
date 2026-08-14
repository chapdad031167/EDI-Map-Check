"""Parsers for the known implementation-guide layout families.

Two families, one output. :func:`parse_guide` extracts the text once,
fingerprints it against each known family, and delegates to that
family's line grammar; both grammars build the same
:class:`~mapcheck.guides.profile.GuideProfile`, so everything
downstream — overlays, drafts, CLI, UI — is family-agnostic.

* **templated** (Design 014): the SpecBuilder-style layout — segment
  header blocks (``BEG … Pos: 020 Max: 1``, one-line or split),
  ``User Option (Usage)`` lines, ``Element Summary`` tables with
  ``Must use``/``Used``/``Not used`` wording, ``Code List Summary``
  blocks, and labeled partner notes.
* **tabular** (Design 017): the Gentran/EDI-Notepad-style
  ``Data Element Summary`` layout — keyed multi-line segment headers
  (``Segment:`` / ``Position:`` / ``Usage:``), dual Base/User attribute
  element rows (the User column overrides only when present, else the
  base/X12 default applies), bare-indented code subsets, and a front
  index table that is cross-checked against the detail pages.

The flag-never-guess contract applies at parse time in both grammars: a
line that looks like data but does not match lands in the profile's
``review`` list with page context, never in the data. A file matching
no family raises :class:`GuideParseError` naming every family's missing
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
    element_position,
)

#: File suffixes the extractor accepts.
_TEXT_SUFFIXES = {".txt"}
_PDF_SUFFIXES = {".pdf"}

#: Family labels recorded on the profile (Designs 017, 019).
FAMILY_TEMPLATED = "templated"
FAMILY_TABULAR = "tabular"
FAMILY_TERSE = "terse"

#: Display names for messages.
FAMILY_NAMES = {
    FAMILY_TEMPLATED: "templated (Element Summary layout)",
    FAMILY_TABULAR: "tabular (Data Element Summary layout)",
    FAMILY_TERSE: "terse (EDI Specifications User Guide layout)",
}


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
                    # Bold text in these guides is printed as overstruck
                    # duplicate glyphs ("IInnssiigghhtt"); dedupe restores it.
                    text = page.dedupe_chars().extract_text() or ""
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

#: Segment header, one-line form: "BEG Beginning Segment ... Pos: 020 Max: 1"
_SEGMENT_HEADER = re.compile(
    r"^(?P<id>[A-Z][A-Z0-9]{1,2})\s+(?P<name>.+?)\s+Pos:\s*(?P<pos>\S+)\s+Max:\s*(?P<max>\S+)\s*$"
)
#: Split form: real PDFs render the header box as two columns that extract
#: as "Pos: 020 Max: 1" on its own line, then "BEG Beginning Segment for"
#: (name possibly wrapping onto the Loop line).
_POS_MAX_LINE = re.compile(r"^Pos:\s*(?P<pos>\S+)\s+Max:\s*(?P<max>\S+)\s*$")
_SEGMENT_NAME_LINE = re.compile(r"^(?P<id>[A-Z][A-Z0-9]{1,2})\s+(?P<name>[A-Z(].*?)\s*$")
#: Continuation of the header box: "Heading - Mandatory" / "Detail - Optional"
_AREA_LINE = re.compile(r"^(Heading|Detail|Summary)\s*-\s*(Mandatory|Optional)\s*$")
#: "Loop: N/A Elements: 6" — a split-form segment's wrapped name may extract
#: as a prefix on this line ("Sequence/Transit Time) Loop: N/A Elements: 5").
_LOOP_LINE = re.compile(
    r"^(?P<prefix>.*?)\s*Loop:\s*(?P<loop>\S+)(?:\s+Elements:\s*\d+)?\s*$"
)
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


def _attach_element(profile: GuideProfile, segment: dict, element: dict) -> None:
    """Append a finished element row to the segment block it was read in.

    An element row naming another segment — a ``REF02`` row still inside
    an open ``N1`` block, from a page break or a mangled column — matches
    the row grammar but contradicts the layout around it. It is a review
    fact, never data: downstream numbers an element by stripping the
    segment id off its ref, which a foreign ref does not survive. The row
    stops counting as a confident fact, so parse coverage shows the doubt.
    """
    if element_position(element["ref"], segment["id"]) is None:
        profile.facts_confident -= 1
        profile.review.append(
            f"segment {segment['id']}: element row {element['ref']} names a "
            "different segment — verify by hand"
        )
        return
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


def _templated_fingerprints(lines: list[tuple[int, str]]) -> dict[str, bool]:
    return {
        "segment header block (e.g. 'BEG … Pos: 020 Max: 1')": any(
            _SEGMENT_HEADER.match(line) or _POS_MAX_LINE.match(line)
            for _, line in lines
        ),
        "'Element Summary' marker": any(
            _ELEMENT_SUMMARY.match(line) for _, line in lines
        ),
        "element rows (Ref/Req/Type/Min-Max/Usage)": any(
            _ELEMENT_ROW.match(line) for _, line in lines
        ),
    }


def parse_guide(
    path: str | Path, transaction: str, partner: str
) -> GuideProfile:
    """Parse a guide file into a :class:`GuideProfile`.

    ``transaction`` and ``partner`` are supplied by the caller — never
    inferred from the document. The layout family is detected by
    fingerprinting and recorded on the profile; a file matching no known
    family raises :class:`GuideParseError` naming what each family was
    missing, and a file matching more than one is a defined error rather
    than a coin flip.
    """
    path = Path(path)
    lines = extract_lines(path)

    # (family label, fingerprint fn, parse fn) — a new family is one row.
    families = (
        (FAMILY_TEMPLATED, _templated_fingerprints, _parse_templated),
        (FAMILY_TABULAR, _tabular_fingerprints, _parse_tabular),
        (FAMILY_TERSE, _terse_fingerprints, _parse_terse),
    )
    prints = {label: fp(lines) for label, fp, _ in families}
    matched = [label for label, fp, _ in families if all(prints[label].values())]

    if len(matched) > 1:
        raise GuideParseError(
            f"{path}: matches guide layout families "
            f"{', '.join(FAMILY_NAMES[m] for m in matched)} at once — cannot "
            "choose a grammar safely; split or clean the file"
        )
    if not matched:
        detail = ". ".join(
            f"{FAMILY_NAMES[label]}: missing "
            + "; ".join(name for name, found in prints[label].items() if not found)
            for label, _, _ in families
        )
        raise GuideParseError(
            f"{path}: not a recognized implementation-guide layout. {detail}. "
            "Free-form and scanned guides are out of scope (Designs 014/017/019)."
        )

    family = matched[0]
    profile = GuideProfile(
        transaction=transaction, partner=partner, source=path.name, family=family
    )
    parse_fn = next(fn for label, _, fn in families if label == family)
    return parse_fn(lines, profile)


def _parse_templated(
    lines: list[tuple[int, str]], profile: GuideProfile
) -> GuideProfile:
    """The Design 014 grammar: SpecBuilder-style templated guides."""
    segment: dict | None = None  # mutable accumulator for the open segment
    element: dict | None = None  # mutable accumulator for the last element
    in_element_summary = False
    in_code_list = False
    #: A "Pos: … Max: …" line waiting for its segment-name line (split form).
    pending_header: tuple[str, str, int] | None = None

    def close_element() -> None:
        nonlocal element
        if element is not None and segment is not None:
            _attach_element(profile, segment, element)
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
            pending_header = None
            segment = {
                "id": header["id"],
                "name": header["name"].strip(),
                "pos": header["pos"],
                "max": header["max"],
                "loop": "",
                "usage": "",
                "notes": [],
                "elements": [],
                "split_header": False,
            }
            profile.facts_detected += 1
            profile.facts_confident += 1
            continue

        if pos_max := _POS_MAX_LINE.match(line):
            if pending_header is not None:
                profile.review.append(
                    f"page {pending_header[2]}: 'Pos: {pending_header[0]} "
                    f"Max: {pending_header[1]}' was not followed by a segment "
                    "name line — verify by hand"
                )
                profile.facts_detected += 1
            pending_header = (pos_max["pos"], pos_max["max"], page)
            continue

        if pending_header is not None:
            pos, max_use, header_page = pending_header
            pending_header = None
            profile.facts_detected += 1
            if name_line := _SEGMENT_NAME_LINE.match(line):
                close_segment()
                segment = {
                    "id": name_line["id"],
                    "name": name_line["name"].strip(),
                    "pos": pos,
                    "max": max_use,
                    "loop": "",
                    "usage": "",
                    "notes": [],
                    "elements": [],
                    "split_header": True,
                }
                profile.facts_confident += 1
                continue
            profile.review.append(
                f"page {header_page}: 'Pos: {pos} Max: {max_use}' was not "
                f"followed by a segment name line — verify by hand: {line!r}"
            )
            # fall through: the line may still be meaningful on its own

        if segment is None:
            continue  # front matter, page headers, tables of contents

        if _AREA_LINE.match(line) or _EXAMPLE_LINE.match(line):
            in_code_list = False
            continue
        if loop_line := _LOOP_LINE.match(line):
            loop = loop_line["loop"]
            segment["loop"] = "" if loop.upper() == "N/A" else loop
            prefix = loop_line["prefix"].strip()
            if prefix:
                if segment.get("split_header"):
                    # the wrapped tail of the segment name (two-column layout)
                    segment["name"] = f"{segment['name']} {prefix}"
                else:
                    profile.review.append(
                        f"page {page}: segment {segment['id']}: unexpected text "
                        f"before 'Loop:' — verify by hand: {prefix!r}"
                    )
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


# --------------------------------------------------------------------------
# The tabular family (Design 017): Gentran-style "Data Element Summary"
# --------------------------------------------------------------------------

#: "Segment: Beginning Segment for Purchase Order" — the partner's name.
_B_SEGMENT = re.compile(r"^Segment:\s*(?P<name>.*\S)\s*$")
#: The bare segment id printed above the Segment: line ("BEG").
_B_BARE_ID = re.compile(r"^(?P<id>[A-Z][A-Z0-9]{1,2})\s*$")
_B_POSITION = re.compile(r"^Position:\s*(?P<pos>\S+)\s*$")
#: "Loop:" (empty), or "Loop: N1 Mandatory" — the loop id, usage ignored.
_B_LOOP = re.compile(r"^Loop:\s*(?P<loop>[A-Z][A-Z0-9]{0,2})?(?:\s+\S.*)?$")
_B_LEVEL = re.compile(r"^Level:\s*(Heading|Detail|Summary)\s*$")
_B_USAGE = re.compile(r"^Usage:\s*(?P<usage>.+?)\s*$")
_B_MAX_USE = re.compile(r"^Max Use:\s*(?P<max>\S+)\s*$")
_B_NOTES = re.compile(r"^Notes:\s*(?P<note>.*)$")
#: Keyed prose blocks that are standard-text, not partner facts.
_B_SKIP_KEYED = re.compile(r"^(Purpose|Syntax Notes|Comments):")
_B_TABLE_MARKER = re.compile(r"^Data Element Summary\s*$")
#: The two-line column header of the element table.
_B_TABLE_HEADER = re.compile(r"^(Ref\.|Des\.)\s")
#: "BEG01 353 Transaction Set Purpose Code M ID 2/2 M" — base attributes
#: always present, the trailing User requirement optional (Design 017:
#: absent User column = no partner override, base applies).
_B_ELEMENT_ROW = re.compile(
    r"^(?P<ref>[A-Z][A-Z0-9]{1,2}\d{2})\s+(?P<num>\d+)\s+(?P<name>.+?)\s+"
    r"(?P<breq>[MOCX])\s+(?P<type>[A-Z][A-Z0-9]{0,2})\s+"
    r"(?P<min>\d+)/(?P<max>\d+)(?:\s+(?P<ureq>[MOCX]))?\s*$"
)
#: Index-table row: "10 300 N1 ABC Division Name M M 1".
_B_INDEX_ROW = re.compile(
    r"^(?P<page>\d{1,3})\s+(?P<pos>\d{2,4})\s+"
    r"(?P<seg>[A-Z][A-Z0-9]{1,2})\s+(?P<rest>.+)$"
)
_B_INDEX_HEADER = re.compile(r"^(Page\s+Pos\.|No\.\s+No\.|LOOP ID\b|Heading:|Detail:|Summary:)")
#: Page furniture: a page's last line ending in a "Month D, YYYY" date
#: (title-page#-date footers) or a bare page number.
_B_FOOTER = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4}\s*$|^Page \d+( of \d+)?\s*$)")
#: A raw EDI sample inside a Notes block ("ST|850|008123456~").
_B_RAW_SAMPLE = re.compile(r"[A-Z][A-Z0-9]{1,2}[|*][^ ]")

#: Requirement letter -> normalized usage. The effective letter is the
#: User attribute when present, else the Base attribute (X12 default) —
#: maintainer-confirmed reading of the dual-column layout.
_B_REQ_USAGE = {"M": "must_use", "O": "used", "C": "used", "X": "used"}
_B_USAGE_WORDS = {
    "mandatory": "must_use",
    "optional": "used",
    "conditional": "used",
    "not used": "not_used",
}


def _tabular_fingerprints(lines: list[tuple[int, str]]) -> dict[str, bool]:
    return {
        "'Data Element Summary' marker": any(
            _B_TABLE_MARKER.match(line.strip()) for _, line in lines
        ),
        "'Segment:'/'Usage:' keyed header lines": any(
            _B_SEGMENT.match(line.strip()) for _, line in lines
        )
        and any(_B_USAGE.match(line.strip()) for _, line in lines),
        "element rows (Ref/Num/Name/Base-Attributes)": any(
            _B_ELEMENT_ROW.match(line.strip()) for _, line in lines
        ),
    }


#: Tabular structural lines, protected from furniture stripping.
_TABULAR_STRUCTURAL = (
    _B_SEGMENT, _B_TABLE_MARKER, _B_TABLE_HEADER, _B_ELEMENT_ROW,
    _B_INDEX_ROW, _B_INDEX_HEADER, _B_POSITION, _B_USAGE, _B_MAX_USE,
    _B_NOTES, _B_SKIP_KEYED, _B_LOOP, _B_LEVEL,
)


def _strip_page_furniture(
    lines: list[tuple[int, str]],
    structural: tuple = _TABULAR_STRUCTURAL,
    footer=_B_FOOTER,
) -> list[tuple[int, str]]:
    """Drop running headers and footers before parsing (families two, three).

    Footers: each page's last line when it matches ``footer`` (a written-out
    date, a bare page number, a ``- N -`` marker). Headers: a verbatim line
    repeating on at least half the pages (minimum 3) that matches no
    ``structural`` grammar — the partner's letterhead, not data. Structural
    lines (segment/table markers, column headers, element rows) repeat
    legitimately and are protected.
    """
    total_pages = max((p for p, _ in lines), default=0)
    last_line_index: dict[int, int] = {}
    for index, (page, line) in enumerate(lines):
        if line.strip():
            last_line_index[page] = index

    pages_of: dict[str, set[int]] = {}
    for page, line in lines:
        text = line.strip()
        if text:
            pages_of.setdefault(text, set()).add(page)
    threshold = max(3, total_pages // 2)
    repeated_furniture = {
        text
        for text, pages in pages_of.items()
        if total_pages >= 4
        and len(pages) >= threshold
        and not any(rx.match(text) for rx in structural)
    }

    kept: list[tuple[int, str]] = []
    for index, (page, line) in enumerate(lines):
        text = line.strip()
        if text in repeated_furniture:
            continue
        if index == last_line_index.get(page) and footer.search(text):
            continue
        kept.append((page, line))
    return kept


def _parse_index_rest(rest: str) -> tuple[str, str | None, str | None]:
    """Split an index row's tail into (name, base_req, user_req).

    The tail reads name + Base [+ User] + Max.Use; requirements are
    single ``M/O/C/X`` letters and Max.Use is a count like ``1``/``>1``.
    Returns (rest, None, None) when the tail does not end that way.
    """
    tokens = rest.split()
    if len(tokens) < 3 or not re.fullmatch(r">?\d+", tokens[-1]):
        return rest, None, None
    base = user = None
    cut = -1
    if tokens[-2] in _B_REQ_USAGE:
        if len(tokens) >= 4 and tokens[-3] in _B_REQ_USAGE:
            base, user, cut = tokens[-3], tokens[-2], -3
        else:
            base, cut = tokens[-2], -2
    if base is None:
        return rest, None, None
    return " ".join(tokens[:cut]), base, user


def _parse_tabular(
    lines: list[tuple[int, str]], profile: GuideProfile
) -> GuideProfile:
    """The Design 017 grammar: Gentran-style tabular guides."""
    lines = _strip_page_furniture(lines)

    #: (seg, pos) -> usages from the front index table, for cross-check.
    index_entries: list[tuple[str, str, str, int]] = []  # seg, pos, usage, page

    segment: dict | None = None
    element: dict | None = None
    pending_id: str | None = None
    in_table = False
    in_notes = False
    note_lines: list[str] = []
    seen_detail = False  # index rows only count before the first Segment:

    def close_element() -> None:
        nonlocal element
        if element is not None and segment is not None:
            _attach_element(profile, segment, element)
        element = None

    def flush_notes() -> None:
        nonlocal in_notes, note_lines
        if in_notes and segment is not None:
            kept = [
                text for text in note_lines
                if text
                and not text.lower().startswith("example")
                and not _B_RAW_SAMPLE.search(text)
            ]
            if kept:
                segment["notes"].append(" ".join(kept))
        in_notes = False
        note_lines = []

    def close_segment() -> None:
        nonlocal segment, in_table
        flush_notes()
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
        in_table = False

    for page, raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if header := _B_SEGMENT.match(line):
            close_segment()
            seen_detail = True
            profile.facts_detected += 1
            if pending_id is None:
                profile.review.append(
                    f"page {page}: 'Segment:' block with no segment id line "
                    f"above it — skipped; verify by hand: {line!r}"
                )
                continue
            profile.facts_confident += 1
            segment = {
                "id": pending_id,
                "name": header["name"].strip(),
                "pos": "",
                "max": "",
                "loop": "",
                "usage": "",
                "notes": [],
                "elements": [],
            }
            pending_id = None
            continue

        if bare := _B_BARE_ID.match(line):
            flush_notes()
            pending_id = bare["id"]
            continue

        if not seen_detail:
            # front matter: the summary index table, parsed for cross-check
            if _B_INDEX_HEADER.match(line):
                continue
            if index_row := _B_INDEX_ROW.match(line):
                _, base, user = _parse_index_rest(index_row["rest"])
                if base is not None:
                    effective = user or base
                    index_entries.append(
                        (
                            index_row["seg"],
                            index_row["pos"],
                            _B_REQ_USAGE.get(effective, "used"),
                            page,
                        )
                    )
                continue
            continue

        if segment is None:
            continue

        if position := _B_POSITION.match(line):
            flush_notes()
            segment["pos"] = position["pos"]
            continue
        if _B_LEVEL.match(line):
            flush_notes()
            continue
        if loop_line := _B_LOOP.match(line):
            flush_notes()
            segment["loop"] = loop_line["loop"] or ""
            continue
        if usage_line := _B_USAGE.match(line):
            flush_notes()
            profile.facts_detected += 1
            usage = _B_USAGE_WORDS.get(usage_line["usage"].strip().lower())
            if usage is None:
                profile.review.append(
                    f"page {page}: segment {segment['id']}: unrecognized "
                    f"usage {usage_line['usage']!r} — verify by hand"
                )
            else:
                profile.facts_confident += 1
                segment["usage"] = usage
            continue
        if max_use := _B_MAX_USE.match(line):
            flush_notes()
            segment["max"] = max_use["max"]
            continue
        if _B_SKIP_KEYED.match(line):
            flush_notes()
            continue
        if note := _B_NOTES.match(line):
            flush_notes()
            in_notes = True
            if note["note"].strip():
                note_lines.append(note["note"].strip())
            continue
        if _B_TABLE_MARKER.match(line):
            flush_notes()
            in_table = True
            continue
        if in_notes:
            note_lines.append(line)
            continue
        if not in_table:
            continue  # Purpose/Comments continuation prose
        if _B_TABLE_HEADER.match(line):
            continue

        if row := _B_ELEMENT_ROW.match(line):
            close_element()
            profile.facts_detected += 1
            profile.facts_confident += 1
            effective = row["ureq"] or row["breq"]
            element = {
                "ref": row["ref"],
                "name": row["name"].strip(),
                "req": effective,
                "type": row["type"],
                "min": int(row["min"]),
                "max": int(row["max"]),
                "usage": _B_REQ_USAGE.get(effective, "used"),
                "codes": [],
                "notes": [],
                "described": False,  # first prose line = X12 description
            }
            continue

        if _ELEMENT_ROW_LOOSE.match(line):
            profile.facts_detected += 1
            profile.review.append(
                f"page {page}: line looks like an element row but did not "
                f"parse — verify by hand: {line!r}"
            )
            close_element()
            continue

        if element is not None:
            is_code_shaped = bool(code_row := _CODE_ROW.match(line))
            if element["type"] == "ID":
                if is_code_shaped:
                    element["codes"].append(
                        GuideCode(
                            code=code_row["code"], name=code_row["name"].strip()
                        )
                    )
                elif element["codes"]:
                    # a wrapped code name continues on the next line
                    last = element["codes"][-1]
                    element["codes"][-1] = GuideCode(
                        code=last.code, name=f"{last.name} {line}".strip()
                    )
                # else: the X12 description before the first code — skipped
            elif is_code_shaped and element["described"]:
                profile.review.append(
                    f"page {page}: {element['ref']}: code-shaped line under a "
                    f"non-ID element — verify by hand: {line!r}"
                )
            else:
                element["described"] = True  # description prose — skipped
            continue

    close_segment()

    if index_entries:
        _cross_check_index(profile, index_entries)
    return profile


def _cross_check_index(
    profile: GuideProfile, index_entries: list[tuple[str, str, str, int]]
) -> None:
    """Compare the front index table against the detail pages (Design 017).

    Disagreements surface questions up front, before a mapping session:
    a listed segment with no detail page (or the reverse), occurrence
    counts that differ for a per-qualifier repeat, and effective-usage
    conflicts all become review facts.
    """
    index_map: dict[tuple[str, str], list[str]] = {}
    for seg, pos, usage, _ in index_entries:
        index_map.setdefault((seg, pos), []).append(usage)
    detail_map: dict[tuple[str, str], list[str]] = {}
    for seg in profile.segments:
        detail_map.setdefault((seg.id, seg.pos), []).append(seg.usage)

    for key in sorted(set(index_map) | set(detail_map)):
        seg, pos = key
        from_index = sorted(index_map.get(key, []))
        from_detail = sorted(detail_map.get(key, []))
        if not from_detail:
            profile.review.append(
                f"index table lists {seg} at position {pos} "
                f"({len(from_index)} occurrence(s)) but no detail page "
                "defines it — verify with the partner"
            )
        elif not from_index:
            profile.review.append(
                f"detail pages define {seg} at position {pos} but the index "
                "table does not list it — verify with the partner"
            )
        elif len(from_index) != len(from_detail):
            profile.review.append(
                f"{seg} at position {pos}: index table shows "
                f"{len(from_index)} occurrence(s) but the detail pages show "
                f"{len(from_detail)} — verify with the partner"
            )
        elif from_index != from_detail:
            profile.review.append(
                f"{seg} at position {pos}: index table says "
                f"{'/'.join(from_index)} but the detail page says "
                f"{'/'.join(from_detail)} — verify with the partner"
            )


# --------------------------------------------------------------------------
# The terse family (Design 019): the "EDI Specifications User Guide" layout
# --------------------------------------------------------------------------

#: "Segment BEG – Beginning Segment for Purchase Order" (en-dash or hyphen).
_T_SEGMENT = re.compile(
    r"^Segment\s+(?P<id>[A-Z][A-Z0-9]{1,2})\s*[–—-]\s*(?P<name>.+?)\s*$"
)
_T_LEVEL = re.compile(r"^Level\s+(?P<level>Heading|Detail|Summary)\s*$")
_T_MAX_USE = re.compile(r"^Max\.?\s*Use\s+(?P<max>\S+)")
#: Keyed prose blocks in the detail header.
_T_PURPOSE = re.compile(r"^(Purpose|Syntax Notes)\b")
_T_COMMENTS = re.compile(r"^Comments\b\s*(?P<note>.*)$")
_T_EXAMPLE = re.compile(r"^Examples?\b")
#: The element table column header: "ID ELEMENT NAME FEATURES COMMENTS".
_T_ELEMENT_HEADER = re.compile(r"^ID\s+ELEMENT\s+NAME\s+FEATURES\s+COMMENTS\s*$")
#: Element row: "N101 Entity Identifier Code M ID 2/3 comments" — no element
#: number, one requiredness letter, TYPE MIN/MAX optional (absent for N rows).
_T_ELEMENT_ROW = re.compile(
    r"^(?P<ref>[A-Z][A-Z0-9]{1,2}\d{2})\s+(?P<name>.+?)\s+(?P<req>[MONCX])"
    r"(?:\s+(?P<type>[A-Z][A-Z0-9]{0,2})\s+(?P<min>\d+)/(?P<max>\d+))?"
    r"(?:\s+(?P<rest>.*\S))?\s*$"
)
#: The front index area header and its two-line column header.
_T_INDEX_AREA = re.compile(r"^Data Segment Sequence for\b")
_T_INDEX_HEADER = re.compile(r"^(Seg\.|ID\s+Use|GLOSSARY\b)")
#: An index row: "N1 Name O 1 N1 / 3" — seg id is 2-3 chars (never a bare
#: glossary letter M/O/C).
_T_INDEX_ROW = re.compile(r"^(?P<seg>[A-Z][A-Z0-9]{1,2})\s+(?P<rest>\S.*)$")
#: "- 4 -" page-number footer.
_T_FOOTER = re.compile(r"(^-\s*\d+\s*-\s*$|[A-Z][a-z]+ \d{1,2}, \d{4}\s*$|^Page \d+)")
#: A code definition inside prose: "BY" = name / "EA" – Each / 00 = Original,
#: possibly several per line. The name runs to the next code token or line end.
_T_CODE = re.compile(
    r'[“”"]?(?P<code>[A-Z0-9]{1,4})[“”"]?\s*[=–—-]\s*'
    r'(?P<name>.+?)'
    r'(?=\s+[“”"]?[A-Z0-9]{1,4}[“”"]?\s*[=–—-]\s|$)'
)
#: A line that *starts* like a code definition (so it is codes, not prose).
_T_CODE_LINE = re.compile(r'^[“”"]?[A-Z0-9]{1,4}[“”"]?\s*[=–—-]\s')

_T_REQ_USAGE = {"M": "must_use", "O": "used", "C": "used", "X": "used", "N": "not_used"}

_T_STRUCTURAL = (
    _T_SEGMENT, _T_LEVEL, _T_MAX_USE, _T_ELEMENT_HEADER, _T_ELEMENT_ROW,
    _T_INDEX_AREA, _T_INDEX_HEADER, _T_PURPOSE, _T_COMMENTS, _T_EXAMPLE,
)


def _terse_fingerprints(lines: list[tuple[int, str]]) -> dict[str, bool]:
    return {
        "'Data Segment Sequence' index table": any(
            _T_INDEX_AREA.match(line.strip()) for _, line in lines
        ),
        "'Segment X - name' headers": any(
            _T_SEGMENT.match(line.strip()) for _, line in lines
        ),
        "'ID ELEMENT NAME FEATURES COMMENTS' element tables": any(
            _T_ELEMENT_HEADER.match(line.strip()) for _, line in lines
        ),
    }


def _parse_terse_index_rest(rest: str) -> tuple[str | None, str]:
    """Split an index row's tail into (usage, loop).

    Tail reads: name… USAGE maxuse [loopid / repeat]. USAGE is one of
    M/O/C, maxuse a count, and the optional loop is 'N1 / 3'. Returns
    (None, "") when no usage letter is found.
    """
    tokens = rest.split()
    for i, tok in enumerate(tokens):
        if tok in ("M", "O", "C") and i + 1 < len(tokens) and re.fullmatch(r">?\d+", tokens[i + 1]):
            loop = ""
            tail = tokens[i + 2:]
            if tail and re.fullmatch(r"[A-Z][A-Z0-9]{0,2}", tail[0]):
                loop = tail[0]
            return tok, loop
    return None, ""


def _extract_terse_codes(line: str) -> list[GuideCode]:
    return [
        GuideCode(code=m["code"], name=m["name"].strip())
        for m in _T_CODE.finditer(line)
    ]


def _parse_terse(
    lines: list[tuple[int, str]], profile: GuideProfile
) -> GuideProfile:
    """The Design 019 grammar: the terse EDI-Specifications-Guide layout.

    Two complementary regions, joined by segment id: the front
    ``Data Segment Sequence`` index gives segment usage and loop, the
    detail pages give elements, requiredness, and (freeform) codes.
    """
    lines = _strip_page_furniture(lines, structural=_T_STRUCTURAL, footer=_T_FOOTER)

    index_usage: dict[str, str] = {}
    index_loop: dict[str, str] = {}
    in_detail = False

    segment: dict | None = None
    element: dict | None = None
    in_elements = False
    in_comments = False
    comment_lines: list[str] = []

    def flush_comments() -> None:
        nonlocal in_comments, comment_lines
        if in_comments and segment is not None:
            kept = [
                t for t in comment_lines
                if t and not t.lower().startswith("example")
                and not _B_RAW_SAMPLE.search(t)
            ]
            if kept:
                segment["notes"].append(" ".join(kept))
        in_comments = False
        comment_lines = []

    def close_element() -> None:
        nonlocal element
        if element is not None and segment is not None:
            _attach_element(profile, segment, element)
        element = None

    def close_segment() -> None:
        nonlocal segment, in_elements
        flush_comments()
        close_element()
        if segment is not None:
            usage = index_usage.get(segment["id"], "")
            loop = index_loop.get(segment["id"], "")
            if segment["id"] not in index_usage:
                profile.review.append(
                    f"segment {segment['id']} has a detail page but no row in the "
                    "Data Segment Sequence index — usage unknown, verify by hand"
                )
            profile.segments.append(
                GuideSegment(
                    id=segment["id"], name=segment["name"], pos="",
                    max_use=segment["max"], loop=loop, usage=usage,
                    notes=tuple(segment["notes"]), elements=tuple(segment["elements"]),
                )
            )
        segment = None
        in_elements = False

    for page, raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if header := _T_SEGMENT.match(line):
            close_segment()
            in_detail = True
            profile.facts_detected += 1
            profile.facts_confident += 1
            segment = {
                "id": header["id"], "name": header["name"].strip(),
                "max": "", "notes": [], "elements": [],
            }
            continue

        if not in_detail:
            # front matter: the Data Segment Sequence index
            if _T_INDEX_AREA.match(line) or _T_INDEX_HEADER.match(line):
                continue
            if row := _T_INDEX_ROW.match(line):
                usage, loop = _parse_terse_index_rest(row["rest"])
                if usage is not None:
                    seg_id = row["seg"]
                    profile.facts_detected += 1
                    profile.facts_confident += 1
                    index_usage[seg_id] = _T_REQ_USAGE.get(usage, "used")
                    if loop and loop != seg_id:
                        index_loop[seg_id] = loop
                    elif loop:
                        index_loop[seg_id] = loop
            continue

        if segment is None:
            continue

        if _T_LEVEL.match(line):
            flush_comments()
            continue
        if max_use := _T_MAX_USE.match(line):
            flush_comments()
            segment["max"] = max_use["max"]
            continue
        if _T_ELEMENT_HEADER.match(line):
            flush_comments()
            in_elements = True
            continue
        if comment := _T_COMMENTS.match(line):
            flush_comments()
            in_comments = True
            if comment["note"].strip():
                comment_lines.append(comment["note"].strip())
            continue
        if _T_PURPOSE.match(line) or _T_EXAMPLE.match(line):
            flush_comments()
            in_comments = False
            continue
        if in_comments and not in_elements:
            comment_lines.append(line)
            continue
        if not in_elements:
            continue

        if row := _T_ELEMENT_ROW.match(line):
            close_element()
            profile.facts_detected += 1
            profile.facts_confident += 1
            req = row["req"]
            element = {
                "ref": row["ref"], "name": row["name"].strip(), "req": req,
                "type": row["type"] or "",
                "min": int(row["min"]) if row["min"] else None,
                "max": int(row["max"]) if row["max"] else None,
                "usage": _T_REQ_USAGE.get(req, "used"),
                "codes": [], "notes": [], "described": False,
            }
            # a code definition may ride on the element row's comment tail
            rest = row["rest"] or ""
            if element["type"] == "ID" and _T_CODE_LINE.match(rest):
                element["codes"].extend(_extract_terse_codes(rest))
            continue

        if _ELEMENT_ROW_LOOSE.match(line):
            profile.facts_detected += 1
            profile.review.append(
                f"page {page}: line looks like an element row but did not parse "
                f"— verify by hand: {line!r}"
            )
            close_element()
            continue

        if element is not None:
            if element["type"] == "ID" and _T_CODE_LINE.match(line):
                found = _extract_terse_codes(line)
                if found:
                    element["codes"].extend(found)
                else:
                    profile.review.append(
                        f"page {page}: {element['ref']}: line looks like a code "
                        f"list but did not parse — verify by hand: {line!r}"
                    )
            # else: description / comment prose under the element — skipped
            continue

    close_segment()
    return profile
