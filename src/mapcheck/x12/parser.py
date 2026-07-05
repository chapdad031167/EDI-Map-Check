"""Generic, definition-driven X12 transaction parser.

pyx12's :class:`~pyx12.x12file.X12Reader` does the low-level work —
delimiter detection, segment tokenization, and interchange control checks
(SE counts, control number agreement). This module builds the transaction
structure on top, driven entirely by a
:class:`~mapcheck.transactions.schema.TransactionDefinition`: which
segments open which loops, how loops nest, and where the areas begin. The
transaction set is auto-detected from ST01 against the registry unless a
definition is passed explicitly.

Known limitations, by design:

* Only the first ST/SE transaction in the interchange is parsed; extra
  transactions are noted, not validated.
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
from mapcheck.x12.model import (
    ENVELOPE_SEGMENTS,
    Loop,
    Segment,
    TransactionDocument,
)


class X12ParseError(Exception):
    """Raised when the file cannot be read as an X12 interchange."""


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


def parse_transaction(
    path: str | Path,
    definition: TransactionDefinition | None = None,
    registry: TransactionRegistry | None = None,
) -> TransactionDocument:
    """Parse an X12 file into a :class:`TransactionDocument`.

    When ``definition`` is None the transaction set is auto-detected from
    ST01 and resolved against the registry. Raises :class:`X12ParseError`
    when the file is unreadable, contains no ST, the set is unknown, or a
    forced definition doesn't match the file.
    """
    path = Path(path)
    if not path.exists():
        raise X12ParseError(f"source file not found: {path}")

    segments, control_notes = _raw_segments(path)
    st = next((s for s in segments if s.seg_id == "ST"), None)
    if st is None:
        raise X12ParseError(f"{path}: no ST segment found — not a valid X12 transaction")
    st01 = st.element(1) or ""

    if definition is not None:
        if st01 != definition.set_code:
            raise X12ParseError(
                f"{path}: expected transaction set {definition.set_code}, got {st01!r}"
            )
    else:
        try:
            definition = (registry or default_registry).get(st01)
        except UnknownTransactionError as exc:
            raise X12ParseError(f"{path}: {exc.args[0]}") from exc

    doc = TransactionDocument(
        definition=definition,
        envelope=_capture_envelope(segments),
        control_notes=control_notes,
    )
    group = doc.envelope.get("functional_group")
    if group and group != definition.functional_group:
        doc.control_notes.append(
            f"functional group {group!r} does not match the "
            f"{definition.set_code} definition ({definition.functional_group!r})"
        )

    walker = _StructureWalker(doc)
    in_transaction = False
    transaction_done = False
    for seg in segments:
        if seg.seg_id == "ST":
            if transaction_done:
                doc.control_notes.append(
                    f"line {seg.line_number}: additional transaction "
                    f"(ST*{seg.element(1)}) ignored — only the first transaction is validated"
                )
                continue
            in_transaction = True
            continue
        if seg.seg_id == "SE":
            if in_transaction:
                in_transaction = False
                transaction_done = True
            continue
        if seg.seg_id in ENVELOPE_SEGMENTS or not in_transaction:
            continue
        walker.place(seg)

    if not transaction_done:
        raise X12ParseError(f"{path}: transaction is not terminated by an SE segment")
    return doc


def parse_850(path: str | Path) -> TransactionDocument:
    """Parse an X12 850 file. Backward-compatible wrapper around
    :func:`parse_transaction` that requires the 850 definition."""
    return parse_transaction(path, definition=default_registry.get("850"))
