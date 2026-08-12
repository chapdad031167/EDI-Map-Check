"""MapCheck-native X12 envelope reconciliation.

pyx12 tokenizes the file; this module audits the envelope itself:

* SE01 segment counts and SE02 ↔ ST02 agreement per transaction,
* GE01 transaction counts and GE02 ↔ GS06 agreement per functional group,
* IEA01 group counts and IEA02 ↔ ISA13 agreement per interchange,
* truncation — missing SE/GE/IEA trailers and an unterminated final
  segment left behind by a dropped transfer.

The checks are native (not pyx12's) so every failure carries a precise
expected-vs-actual message and strict severity: a broken envelope fails
the run. A truncation that leaves a transaction without its SE is fatal —
the document cannot be trusted enough to validate — and is reported via
``EnvelopeReport.fatal`` for the parser to raise gracefully.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mapcheck.x12.model import ControlIssue, Segment

#: How much of an unterminated trailing fragment to show in messages.
_TAIL_DISPLAY_LIMIT = 60


@dataclass(frozen=True)
class EnvelopeReport:
    """Everything the envelope walk found."""

    issues: tuple[ControlIssue, ...] = ()
    #: A truncation that prevents validation (a transaction with no SE),
    #: phrased for the user; None when the file can still be validated.
    fatal: str | None = None


def scan_raw_tail(path: str | Path) -> str | None:
    """Return unterminated content after the file's last segment terminator.

    The segment terminator is read from the ISA's fixed byte position
    (offset 105; the element separator sits at offset 3) — real files
    declare their delimiters in the ISA, so nothing is assumed. Returns
    None for a cleanly terminated file, or when the file is too short to
    carry a conforming ISA (the parser reports that separately).
    """
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if text.startswith("﻿"):  # tolerate a UTF-8 BOM in the scan
        text = text[1:]
    if not text.startswith("ISA") or len(text) < 106:
        return None
    seg_term = text[105]
    tail = text.rsplit(seg_term, 1)[-1].strip()
    if not tail:
        return None
    if len(tail) > _TAIL_DISPLAY_LIMIT:
        tail = tail[: _TAIL_DISPLAY_LIMIT] + "..."
    return tail


def _num(value: str | None) -> int | None:
    if value is None or not value.isdigit():
        return None
    return int(value)


def _ids_match(a: str | None, b: str | None) -> bool:
    """Control numbers agree; numeric values compare ignoring zero-padding."""
    if a is None or b is None:
        return a == b
    if a.isdigit() and b.isdigit():
        return int(a) == int(b)
    return a == b


def _show(value: str | None) -> str:
    return value if value else "(empty)"


def check_envelope(
    segments: list[Segment], unterminated_tail: str | None
) -> EnvelopeReport:
    """Reconcile the envelope of a tokenized interchange.

    ``unterminated_tail`` is :func:`scan_raw_tail`'s finding for the same
    file, folded into truncation messages. Structural states the parser
    itself rejects (SE with no open ST, nested ST) are skipped here — the
    parser's fatal error names them.
    """
    issues: list[ControlIssue] = []
    isa: Segment | None = None
    gs: Segment | None = None
    open_st: Segment | None = None
    segments_since_st = 0
    groups_seen = 0
    transactions_in_group = 0
    iea_seen = False

    for seg in segments:
        if open_st is not None:
            segments_since_st += 1
        if seg.seg_id == "ISA":
            isa = seg
        elif seg.seg_id == "GS":
            gs = seg
            groups_seen += 1
            transactions_in_group = 0
        elif seg.seg_id == "ST":
            open_st = seg
            segments_since_st = 1
            transactions_in_group += 1
        elif seg.seg_id == "SE":
            if open_st is None:
                continue  # parser reports the orphan SE as fatal
            st02 = open_st.element(2)
            claimed = _num(seg.element(1))
            if claimed is None:
                issues.append(
                    ControlIssue(
                        message=(
                            f"SE01 segment count {_show(seg.element(1))!r} is not "
                            f"a number (transaction {_show(st02)})"
                        ),
                        expected=str(segments_since_st),
                        actual=_show(seg.element(1)),
                    )
                )
            elif claimed != segments_since_st:
                issues.append(
                    ControlIssue(
                        message=(
                            f"SE01 segment count mismatch: SE claims {claimed} "
                            f"segments but transaction {_show(st02)} contains "
                            f"{segments_since_st} (ST through SE)"
                        ),
                        expected=str(segments_since_st),
                        actual=str(claimed),
                    )
                )
            if not _ids_match(seg.element(2), st02):
                issues.append(
                    ControlIssue(
                        message=(
                            f"SE02 control number mismatch: SE02 is "
                            f"{_show(seg.element(2))} but its ST02 is {_show(st02)}"
                        ),
                        expected=st02,
                        actual=_show(seg.element(2)),
                    )
                )
            open_st = None
            segments_since_st = 0
        elif seg.seg_id == "GE":
            if gs is None:
                continue
            gs06 = gs.element(6)
            claimed = _num(seg.element(1))
            if claimed is None:
                issues.append(
                    ControlIssue(
                        message=(
                            f"GE01 transaction count {_show(seg.element(1))!r} is "
                            f"not a number (functional group {_show(gs06)})"
                        ),
                        expected=str(transactions_in_group),
                        actual=_show(seg.element(1)),
                    )
                )
            elif claimed != transactions_in_group:
                issues.append(
                    ControlIssue(
                        message=(
                            f"GE01 transaction count mismatch: GE claims {claimed} "
                            f"transaction set(s) but functional group {_show(gs06)} "
                            f"contains {transactions_in_group}"
                        ),
                        expected=str(transactions_in_group),
                        actual=str(claimed),
                    )
                )
            if not _ids_match(seg.element(2), gs06):
                issues.append(
                    ControlIssue(
                        message=(
                            f"GE02 control number mismatch: GE02 is "
                            f"{_show(seg.element(2))} but its GS06 is {_show(gs06)}"
                        ),
                        expected=gs06,
                        actual=_show(seg.element(2)),
                    )
                )
            gs = None
        elif seg.seg_id == "IEA":
            iea_seen = True
            if isa is None:
                continue
            isa13 = isa.element(13)
            claimed = _num(seg.element(1))
            if claimed is not None and claimed != groups_seen:
                issues.append(
                    ControlIssue(
                        message=(
                            f"IEA01 group count mismatch: IEA claims {claimed} "
                            f"functional group(s) but the interchange contains "
                            f"{groups_seen}"
                        ),
                        expected=str(groups_seen),
                        actual=str(claimed),
                    )
                )
            if not _ids_match(seg.element(2), isa13):
                issues.append(
                    ControlIssue(
                        message=(
                            f"IEA02 control number mismatch: IEA02 is "
                            f"{_show(seg.element(2))} but ISA13 is {_show(isa13)}"
                        ),
                        expected=isa13,
                        actual=_show(seg.element(2)),
                    )
                )

    last = segments[-1] if segments else None
    where = (
        f"last complete segment is {last.seg_id} at line {last.line_number}"
        if last is not None
        else "no complete segments were read"
    )
    tail_note = (
        f"; the file ends with an unterminated segment {unterminated_tail!r}"
        if unterminated_tail
        else ""
    )

    if open_st is not None:
        missing = ["SE"]
        if gs is not None:
            missing.append("GE")
        if isa is not None and not iea_seen:
            missing.append("IEA")
        fatal = (
            f"interchange truncated: transaction {_show(open_st.element(2))} "
            f"(ST at line {open_st.line_number}) is missing its "
            f"{'/'.join(missing)} trailer{'s' if len(missing) > 1 else ''}; "
            f"{where}{tail_note}"
        )
        return EnvelopeReport(issues=tuple(issues), fatal=fatal)

    missing = []
    if gs is not None:
        missing.append("GE")
    if isa is not None and not iea_seen:
        missing.append("IEA")
    if missing:
        issues.append(
            ControlIssue(
                message=(
                    f"interchange truncated: {' and '.join(missing)} "
                    f"trailer{'s are' if len(missing) > 1 else ' is'} missing; "
                    f"{where}{tail_note}"
                )
            )
        )
    elif unterminated_tail:
        issues.append(
            ControlIssue(
                message=(
                    "file ends with an unterminated segment "
                    f"{unterminated_tail!r} after the interchange trailer"
                )
            )
        )
    return EnvelopeReport(issues=tuple(issues))
