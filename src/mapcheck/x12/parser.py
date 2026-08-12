"""Generic, definition-driven X12 transaction parser.

pyx12's :class:`~pyx12.x12file.X12Reader` does the low-level work —
delimiter detection and segment tokenization. Envelope auditing (SE/GE/IEA
counts, control-number agreement, truncation) is MapCheck's own, in
:mod:`mapcheck.x12.envelope`, with strict severity and precise messages.
This module builds the transaction structure on top, driven entirely by a
:class:`~mapcheck.transactions.schema.TransactionDefinition`: which
segments open which loops, how loops nest, and where the areas begin. The
transaction set is auto-detected from ST01 against the registry unless a
definition is passed explicitly.

:func:`parse_interchange` returns every ST/SE transaction in the file;
:func:`parse_transaction` is a convenience wrapper returning the first.

Known limitations, by design:

* Composite elements are kept as raw strings.
* Segments the definition doesn't know are attached where they appear and
  reported as definition notes (warnings), not errors — real-world files
  are messy, and a validator that dies on the first surprise doesn't run.
* HL-style hierarchical loops parse as flat occurrences for now; tree
  linking (HL01/HL02) lands with the 856.
"""

from __future__ import annotations

from pathlib import Path

import pyx12.errors
import pyx12.x12file

from mapcheck.transactions.registry import (
    TransactionRegistry,
    UnknownTransactionError,
    default_registry,
)
from mapcheck.transactions.schema import AreaDef, LoopDef, TransactionDefinition
from mapcheck.x12.envelope import check_envelope, scan_raw_tail
from mapcheck.x12.model import (
    ENVELOPE_SEGMENTS,
    Interchange,
    Loop,
    Segment,
    TransactionDocument,
)


class X12ParseError(Exception):
    """Raised when the file cannot be read as an X12 interchange."""


def _raw_segments(path: Path) -> list[Segment]:
    """Tokenize the file with pyx12 into :class:`Segment` values.

    Envelope auditing is NOT pyx12's job here — MapCheck's own
    reconciliation (:mod:`mapcheck.x12.envelope`) checks SE/GE/IEA counts,
    control-number agreement, and truncation, with precise messages and
    strict severity.
    """
    try:
        reader = pyx12.x12file.X12Reader(str(path))
    except pyx12.errors.X12Error as exc:
        raise X12ParseError(f"{path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise X12ParseError(
            f"{path}: file is not valid X12 (non-ASCII bytes at position {exc.start})"
        ) from exc

    segments: list[Segment] = []
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
    except UnicodeDecodeError as exc:
        raise X12ParseError(
            f"{path}: file is not valid X12 (non-ASCII bytes at position {exc.start})"
        ) from exc
    return segments


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


class _StructureWalker:
    """Places each business segment into areas and loops per the definition."""

    def __init__(self, doc: TransactionDocument) -> None:
        self.doc = doc
        self.definition = doc.definition
        self.area_index = 0
        #: Stack of (loop definition, open occurrence), innermost last.
        self.stack: list[tuple[LoopDef, Loop]] = []
        self._unknown_reported: set[str] = set()
        #: Per hierarchical loop id: HL id -> occurrence, for parent linking.
        self._hl_index: dict[str, dict[str, Loop]] = {}

    @property
    def area(self) -> AreaDef:
        return self.definition.areas[self.area_index]

    def _advance_area(self, seg_id: str) -> None:
        for index in range(self.area_index + 1, len(self.definition.areas)):
            if seg_id in self.definition.areas[index].opens_with:
                self.area_index = index
                self.stack.clear()
                return

    def _open_loop(self, loop_def: LoopDef, depth: int, seg: Segment) -> None:
        del self.stack[depth:]
        occurrence = Loop(
            loop_id=loop_def.id,
            segments=[seg],
            qualifier_element=loop_def.qualifier,
        )
        occurrences = self.doc.loop_occurrences.setdefault(loop_def.id, [])
        occurrences.append(occurrence)
        if loop_def.max_repeats is not None and len(occurrences) == loop_def.max_repeats + 1:
            self.doc.definition_notes.append(
                f"loop {loop_def.id} exceeds max_repeats={loop_def.max_repeats}"
            )
        if loop_def.is_hierarchical:
            self._link_hierarchy(loop_def, occurrence, seg)
        self.stack.append((loop_def, occurrence))

    def _link_hierarchy(self, loop_def: LoopDef, occurrence: Loop, seg: Segment) -> None:
        """Record the occurrence's HL id and link it to its parent.

        Structural problems (duplicate ids, orphaned parents, unknown level
        codes, illegal nesting) go to ``hierarchy_errors`` — the tree still
        builds as well as it can so the rest of the run stays useful.
        """
        assert loop_def.hierarchy is not None
        hierarchy = loop_def.hierarchy
        err = self.doc.hierarchy_errors.append
        where = f"{loop_def.trigger} at line {seg.line_number}"

        hl_id = seg.element(hierarchy.id_element)
        parent_id = seg.element(hierarchy.parent_element)
        level_code = seg.element(hierarchy.level_element)
        occurrence.hl_id = hl_id

        index = self._hl_index.setdefault(loop_def.id, {})
        if hl_id is None:
            err(f"{where}: missing hierarchical id ({seg.ref(hierarchy.id_element)})")
        elif hl_id in index:
            err(f"{where}: duplicate hierarchical id {hl_id!r}")
        else:
            index[hl_id] = occurrence

        level = loop_def.level(level_code) if level_code else None
        if level_code is None:
            err(f"{where}: missing level code ({seg.ref(hierarchy.level_element)})")
        elif level is None:
            allowed = ", ".join(lv.code for lv in loop_def.levels)
            err(f"{where}: unknown level code {level_code!r} (allowed: {allowed})")

        if parent_id is None:
            return  # a root (e.g. the shipment level)
        parent = index.get(parent_id)
        if parent is None or parent is occurrence:
            err(
                f"{where}: parent id {parent_id!r} does not reference an "
                "earlier hierarchical loop (orphan)"
            )
            return
        occurrence.parent = parent
        parent_level_code = parent.trigger.element(hierarchy.level_element)
        parent_level = loop_def.level(parent_level_code) if parent_level_code else None
        if (
            level_code is not None
            and parent_level is not None
            and level_code not in parent_level.children
        ):
            err(
                f"{where}: level {level_code!r} is not an allowed child of "
                f"level {parent_level_code!r} "
                f"(allowed children: {', '.join(parent_level.children) or 'none'})"
            )

    def _loops_at(self, depth: int) -> tuple[LoopDef, ...]:
        """Child loop definitions available at a stack depth (0 = area level)."""
        if depth == 0:
            return self.area.loops
        return self.stack[depth - 1][0].loops

    def place(self, seg: Segment) -> None:
        """Find the segment's home, preferring the deepest open context."""
        self._advance_area(seg.seg_id)

        for depth in range(len(self.stack), -1, -1):
            for loop_def in self._loops_at(depth):
                if seg.seg_id == loop_def.trigger:
                    self._open_loop(loop_def, depth, seg)
                    return
            if depth > 0:
                loop_def, occurrence = self.stack[depth - 1]
                if seg.seg_id in loop_def.segments or (
                    loop_def.is_hierarchical and self._in_level_segments(loop_def, seg)
                ):
                    del self.stack[depth:]
                    occurrence.segments.append(seg)
                    return
            elif seg.seg_id in self.area.segments:
                self.stack.clear()
                self.doc.area_segments.setdefault(self.area.id, []).append(seg)
                return

        # Unknown segment: keep it where it appeared (innermost open context)
        # and note the deviation once per segment id.
        if seg.seg_id not in self._unknown_reported:
            self._unknown_reported.add(seg.seg_id)
            self.doc.definition_notes.append(
                f"segment {seg.seg_id} (line {seg.line_number}) is not in the "
                f"{self.definition.set_code} definition"
            )
        if self.stack:
            self.stack[-1][1].segments.append(seg)
        else:
            self.doc.area_segments.setdefault(self.area.id, []).append(seg)

    def _in_level_segments(self, loop_def: LoopDef, seg: Segment) -> bool:
        """For hierarchical loops, membership can be declared per level."""
        return any(seg.seg_id in level.segments for level in loop_def.levels)


def _build_document(
    st_seg: Segment,
    body: list[Segment],
    shared_envelope: dict[str, str],
    definition: TransactionDefinition | None,
    registry: TransactionRegistry | None,
    path: Path,
) -> TransactionDocument:
    """Resolve one ST/SE group's definition and walk its segments."""
    st01 = st_seg.element(1) or ""
    if definition is not None:
        if st01 != definition.set_code:
            raise X12ParseError(
                f"{path}: expected transaction set {definition.set_code}, got {st01!r}"
            )
        doc_definition = definition
    else:
        try:
            doc_definition = (registry or default_registry).get(st01)
        except UnknownTransactionError as exc:
            raise X12ParseError(f"{path}: {exc.args[0]}") from exc

    envelope = dict(shared_envelope)
    envelope["transaction_set"] = st01
    envelope["st_control"] = st_seg.element(2) or ""

    doc = TransactionDocument(definition=doc_definition, envelope=envelope)
    group = envelope.get("functional_group")
    if group and group != doc_definition.functional_group:
        doc.control_notes.append(
            f"functional group {group!r} does not match the "
            f"{doc_definition.set_code} definition ({doc_definition.functional_group!r})"
        )
    # Version drift is common in the wild (e.g. 5010 traffic against a 4010
    # definition): call it out, but keep validating against the definition.
    declared = envelope.get("version")
    if (
        declared
        and doc_definition.version
        and not declared.startswith(doc_definition.version)
    ):
        doc.control_notes.append(
            f"file declares version {declared} (GS08) but the "
            f"{doc_definition.set_code} definition is {doc_definition.version} — "
            f"validated against the {doc_definition.version} structure"
        )

    walker = _StructureWalker(doc)
    for seg in body:
        if seg.seg_id in ENVELOPE_SEGMENTS:
            continue
        walker.place(seg)
    return doc


def parse_interchange(
    path: str | Path,
    definition: TransactionDefinition | None = None,
    registry: TransactionRegistry | None = None,
) -> Interchange:
    """Parse every ST/SE transaction in an X12 file into an :class:`Interchange`.

    Each transaction resolves its own definition from its ST01 (mixed
    transaction sets in one interchange are allowed) unless ``definition``
    forces one for all of them. Raises :class:`X12ParseError` when the file
    is unreadable, contains no ST, a set is unknown, a forced definition
    doesn't match, or a transaction is not terminated by an SE.
    """
    path = Path(path)
    if not path.exists():
        raise X12ParseError(f"source file not found: {path}")

    segments = _raw_segments(path)
    envelope_report = check_envelope(segments, scan_raw_tail(path))
    if envelope_report.fatal:
        raise X12ParseError(f"{path}: {envelope_report.fatal}")
    shared_envelope = _capture_envelope(segments)

    documents: list[TransactionDocument] = []
    st_seg: Segment | None = None
    body: list[Segment] = []
    for seg in segments:
        if seg.seg_id == "ST":
            if st_seg is not None:
                raise X12ParseError(
                    f"{path}: line {seg.line_number}: ST segment before the previous "
                    "transaction was terminated by an SE"
                )
            st_seg = seg
            body = []
        elif seg.seg_id == "SE":
            if st_seg is None:
                raise X12ParseError(
                    f"{path}: line {seg.line_number}: SE segment with no open transaction"
                )
            documents.append(
                _build_document(st_seg, body, shared_envelope, definition, registry, path)
            )
            st_seg = None
        elif st_seg is not None:
            body.append(seg)

    if st_seg is not None:
        # Defensive: check_envelope reports open transactions as fatal first.
        raise X12ParseError(f"{path}: transaction is not terminated by an SE segment")
    if not documents:
        raise X12ParseError(f"{path}: no ST segment found — not a valid X12 transaction")

    return Interchange(
        documents=documents,
        envelope=shared_envelope,
        control_errors=list(envelope_report.issues),
    )


def parse_transaction(
    path: str | Path,
    definition: TransactionDefinition | None = None,
    registry: TransactionRegistry | None = None,
) -> TransactionDocument:
    """Parse the first ST/SE transaction of an X12 file.

    Convenience wrapper over :func:`parse_interchange` for callers that
    expect a single transaction; the interchange's file-level control notes
    are carried on the returned document so behavior matches a
    single-transaction validation exactly.
    """
    interchange = parse_interchange(path, definition=definition, registry=registry)
    doc = interchange.documents[0]
    doc.control_notes = interchange.control_notes + doc.control_notes
    doc.control_errors = interchange.control_errors + doc.control_errors
    if len(interchange.documents) > 1:
        extra = interchange.documents[1]
        doc.control_notes.append(
            f"additional transaction (ST*{extra.envelope.get('transaction_set')}) "
            "present — only the first transaction is validated"
        )
    return doc


def parse_850(path: str | Path) -> TransactionDocument:
    """Parse an X12 850 file. Backward-compatible wrapper around
    :func:`parse_transaction` that requires the 850 definition."""
    return parse_transaction(path, definition=default_registry.get("850"))
