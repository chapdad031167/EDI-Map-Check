"""X12 850 file parser.

pyx12's :class:`~pyx12.x12file.X12Reader` does the low-level work —
delimiter detection, segment tokenization, and interchange control checks
(SE counts, control number agreement). This module layers the 850 area and
loop structure on top; pyx12 ships no 850 transaction map (its bundled maps
are HIPAA sets), so the hierarchy rules live here.

Known MVP limitations, by design:

* Only the first ST/SE transaction in the interchange is parsed; extra
  transactions are noted, not validated.
* Composite elements are kept as raw strings (the 850 subset used here has
  none).
* Loop hierarchy covers N1 and PO1 (with PID/PO4/etc. as PO1 members).
"""

from __future__ import annotations

from pathlib import Path

import pyx12.errors
import pyx12.x12file

from mapcheck.x12.model import (
    ENVELOPE_SEGMENTS,
    N1_LOOP_MEMBERS,
    Loop,
    Segment,
    Transaction850,
)


class X12ParseError(Exception):
    """Raised when the file cannot be read as an X12 850 interchange."""


def _raw_segments(path: Path) -> tuple[list[Segment], list[str]]:
    """Tokenize the file with pyx12; return segments and control notes."""
    try:
        reader = pyx12.x12file.X12Reader(str(path))
    except pyx12.errors.X12Error as exc:
        raise X12ParseError(f"{path}: {exc}") from exc

    segments: list[Segment] = []
    notes: list[str] = []
    ele_term = "*"
    seg_term = "~"
    try:
        for seg in reader:
            raw = seg.format()  # e.g. 'BEG*00*SA*PO123**20260615~'
            if raw.startswith("ISA") and len(raw) > 3:
                # ISA fixes the delimiters for the whole interchange.
                ele_term = raw[3]
                seg_term = raw[-1]
            parts = raw.removesuffix(seg_term).split(ele_term)
            segments.append(
                Segment(
                    seg_id=parts[0],
                    elements=tuple(parts[1:]),
                    line_number=getattr(reader, "cur_line", 0),
                )
            )
    except pyx12.errors.X12Error as exc:
        raise X12ParseError(f"{path}: {exc}") from exc

    for err in reader.pop_errors():
        # pyx12 error tuples: (category, code, message, ...)
        message = err[2] if len(err) > 2 else str(err)
        notes.append(str(message))
    return segments, notes


def _capture_envelope(segments: list[Segment]) -> dict[str, str]:
    envelope: dict[str, str] = {}
    for seg in segments:
        if seg.seg_id == "ISA":
            envelope["sender_id"] = (seg.element(6) or "").strip()
            envelope["receiver_id"] = (seg.element(8) or "").strip()
            envelope["interchange_control"] = seg.element(13) or ""
            envelope["usage"] = seg.element(15) or ""
        elif seg.seg_id == "GS":
            envelope["functional_group"] = seg.element(1) or ""
            envelope["version"] = seg.element(8) or ""
        elif seg.seg_id == "ST":
            envelope.setdefault("transaction_set", seg.element(1) or "")
            envelope.setdefault("st_control", seg.element(2) or "")
    return envelope


def parse_850(path: str | Path) -> Transaction850:
    """Parse an X12 file into a :class:`Transaction850`.

    Raises :class:`X12ParseError` when the file is unreadable, contains no
    ST, or the first transaction is not an 850.
    """
    path = Path(path)
    if not path.exists():
        raise X12ParseError(f"source file not found: {path}")

    segments, notes = _raw_segments(path)
    if not any(s.seg_id == "ST" for s in segments):
        raise X12ParseError(f"{path}: no ST segment found — not a valid X12 transaction")

    tx = Transaction850(envelope=_capture_envelope(segments), control_notes=notes)

    in_transaction = False
    transaction_done = False
    area = "heading"
    open_n1: Loop | None = None
    open_po1: Loop | None = None

    for seg in segments:
        if seg.seg_id == "ST":
            if transaction_done:
                tx.control_notes.append(
                    f"line {seg.line_number}: additional transaction "
                    f"(ST*{seg.element(1)}) ignored — MVP validates the first 850 only"
                )
                continue
            if seg.element(1) != "850":
                raise X12ParseError(
                    f"{path}: expected transaction set 850, got {seg.element(1)!r}"
                )
            in_transaction = True
            continue
        if seg.seg_id == "SE":
            if in_transaction:
                in_transaction = False
                transaction_done = True
            continue
        if seg.seg_id in ENVELOPE_SEGMENTS or not in_transaction:
            continue

        if seg.seg_id == "PO1":
            area = "detail"
            open_n1 = None
            open_po1 = Loop(loop_id="PO1", segments=[seg])
            tx.po1_loops.append(open_po1)
            continue
        if seg.seg_id == "CTT":
            # CTT opens the summary area; an AMT before it stays in its PO1 loop.
            area = "summary"
        if area == "summary":
            tx.summary.append(seg)
            continue
        if area == "detail":
            assert open_po1 is not None
            open_po1.segments.append(seg)
            continue

        # heading area
        if seg.seg_id == "N1":
            open_n1 = Loop(loop_id="N1", segments=[seg])
            tx.n1_loops.append(open_n1)
        elif open_n1 is not None and seg.seg_id in N1_LOOP_MEMBERS:
            open_n1.segments.append(seg)
        else:
            open_n1 = None
            tx.heading.append(seg)

    if not transaction_done:
        raise X12ParseError(f"{path}: transaction is not terminated by an SE segment")
    return tx
