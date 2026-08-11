"""Queryable structure for a parsed X12 transaction.

The document layout — areas, loops, nesting — comes entirely from a
:class:`~mapcheck.transactions.schema.TransactionDefinition`; nothing in
this module is specific to any transaction set. The 850 shape (header /
detail with PO1 loops / summary) is just what its definition file declares.

Resolution against spec addressing happens through
:meth:`TransactionDocument.scopes`: a :class:`Scope` is the list of segments
a rule's Loop Context selects, and plain ``SEGnn`` source fields are read
from the first matching segment in that scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from mapcheck.spec.model import LoopContext
from mapcheck.transactions.schema import TransactionDefinition

#: Envelope/control segments excluded from business-data checks.
ENVELOPE_SEGMENTS = frozenset({"ISA", "GS", "ST", "SE", "GE", "IEA", "TA1"})


@dataclass(frozen=True)
class ControlIssue:
    """One strict envelope-control failure (native reconciliation).

    ``expected`` is what the envelope should say, ``actual`` what it does
    say — both optional display strings for the report's columns.
    """

    message: str
    expected: str | None = None
    actual: str | None = None


@dataclass(frozen=True)
class Segment:
    """One X12 segment: id plus positional elements (element 1 first)."""

    seg_id: str
    elements: tuple[str, ...]
    line_number: int

    def element(self, index: int) -> str | None:
        """Return element ``index`` (1-based), or None when empty/absent."""
        if index < 1 or index > len(self.elements):
            return None
        value = self.elements[index - 1]
        return value if value != "" else None

    def ref(self, index: int) -> str:
        """Reference designator for reports, e.g. ``BEG03``."""
        return f"{self.seg_id}{index:02d}"

    def __str__(self) -> str:
        return f"{self.seg_id}*" + "*".join(self.elements)


@dataclass
class Loop:
    """A loop occurrence: trigger segment plus member segments, in order.

    ``qualifier_element`` comes from the loop's definition (element 01 for
    conventional loops, the level element for HL-style loops). Hierarchical
    occurrences additionally carry their ``hl_id`` and a ``parent`` link.
    """

    loop_id: str
    segments: list[Segment] = field(default_factory=list)
    qualifier_element: int = 1
    hl_id: str | None = None
    parent: "Loop | None" = None

    @property
    def trigger(self) -> Segment:
        return self.segments[0]

    @property
    def qualifier(self) -> str | None:
        """The trigger element used for ``LOOP[qualifier]`` addressing."""
        return self.trigger.element(self.qualifier_element)

    def ancestors(self) -> Iterator["Loop"]:
        """Walk up the hierarchy, nearest ancestor first."""
        node = self.parent
        while node is not None:
            yield node
            node = node.parent


@dataclass(frozen=True)
class Scope:
    """The segments a Loop Context resolves to, with a label for reports."""

    label: str
    segments: tuple[Segment, ...]

    def first(self, seg_id: str) -> Segment | None:
        """First segment with ``seg_id`` in this scope, or None."""
        for seg in self.segments:
            if seg.seg_id == seg_id:
                return seg
        return None

    def value(self, seg_id: str, element: int) -> str | None:
        """Value of ``SEGnn`` within this scope, or None when absent/empty."""
        seg = self.first(seg_id)
        return seg.element(element) if seg is not None else None


@dataclass
class TransactionDocument:
    """A parsed transaction: areas, loops, envelope metadata, and notes."""

    definition: TransactionDefinition
    #: Flat (non-loop) segments per area id, in document order.
    area_segments: dict[str, list[Segment]] = field(default_factory=dict)
    #: Loop occurrences per loop id, in document order.
    loop_occurrences: dict[str, list[Loop]] = field(default_factory=dict)
    envelope: dict[str, str] = field(default_factory=dict)
    #: Advisory control observations (functional-group mismatch, additional
    #: transactions present, ...). Surfaced as warnings by the engine.
    control_notes: list[str] = field(default_factory=list)
    #: Strict envelope-control failures from MapCheck's native envelope
    #: reconciliation (SE/GE/IEA counts, control-number agreement,
    #: truncation). Surfaced as FAILURES by the engine.
    control_errors: list[ControlIssue] = field(default_factory=list)
    #: Deviations from the transaction definition (unknown segments,
    #: repeat limits). Surfaced as source-data warnings by the engine.
    definition_notes: list[str] = field(default_factory=list)
    #: Structural corruption in hierarchical (HL) loops: orphaned parents,
    #: illegal nesting, duplicate or unknown level codes. Surfaced as
    #: source-data FAILURES by the engine — a broken tree is never OK.
    hierarchy_errors: list[str] = field(default_factory=list)

    # -- area conveniences ---------------------------------------------------

    def area(self, area_id: str) -> list[Segment]:
        return self.area_segments.get(area_id, [])

    @property
    def heading(self) -> list[Segment]:
        """Flat segments of the first area."""
        if not self.definition.areas:
            return []
        return self.area(self.definition.areas[0].id)

    @property
    def summary(self) -> list[Segment]:
        """Flat segments of the last area (when there is more than one)."""
        if len(self.definition.areas) < 2:
            return []
        return self.area(self.definition.areas[-1].id)

    # -- loop conveniences ----------------------------------------------------

    def loops(self, loop_id: str) -> list[Loop]:
        return self.loop_occurrences.get(loop_id, [])

    @property
    def n1_loops(self) -> list[Loop]:  # backward-compatible convenience
        return self.loops("N1")

    @property
    def po1_loops(self) -> list[Loop]:  # backward-compatible convenience
        return self.loops("PO1")

    @property
    def line_loop_id(self) -> str | None:
        """The loop paired with the spec's ``lines[]`` targets, if declared."""
        pairing = self.definition.output_pairing
        return pairing.loop if pairing else None

    # -- addressing ---------------------------------------------------------

    def flat_scope(self) -> Scope:
        """All non-loop segments across the areas (empty Loop Context)."""
        segments: list[Segment] = []
        for area in self.definition.areas:
            segments.extend(self.area(area.id))
        return Scope(label="header", segments=tuple(segments))

    def scopes(self, context: LoopContext | None) -> list[Scope]:
        """Resolve a spec Loop Context to the scopes it selects.

        * ``None`` — one scope: the flat (non-loop) segments.
        * qualified loop (``N1[ST]``, ``HL[I]``) — each loop occurrence
          whose qualifier element (from the definition) matches. For
          hierarchical loops the scope also includes the occurrence's
          ancestors' segments, nearest first — an item-level rule can read
          its order's PRF or its carton's MAN without new spec syntax.
        * bare loop (``PO1``) — one scope per loop occurrence.
        * qualified plain segment (``REF[DP]``) — each matching flat
          segment, one single-segment scope apiece; the qualifier always
          matches element 01.

        A path context (``LIN>QTY[QA]``) yields one scope per base
        occurrence — kept even when empty, so per-line index pairing holds —
        narrowed to the sub-segments whose element 01 matches.

        Returns an empty list when nothing matches (the caller decides
        whether that means NOT TESTED, a failed condition, or a defect).
        """
        if context is None:
            return [self.flat_scope()]

        def narrow(segments: tuple[Segment, ...]) -> tuple[Segment, ...]:
            if context.sub_segment_id is None:
                return segments
            return tuple(
                seg
                for seg in segments
                if seg.seg_id == context.sub_segment_id
                and seg.element(1) == context.sub_qualifier
            )

        loop_def = self.definition.loop(context.segment_id)
        if loop_def is not None:
            matches = [
                loop
                for loop in self.loops(context.segment_id)
                if context.qualifier is None or loop.qualifier == context.qualifier
            ]
            def scope_segments(loop: Loop) -> tuple[Segment, ...]:
                segments = list(loop.segments)
                if loop_def.is_hierarchical:
                    for ancestor in loop.ancestors():
                        segments.extend(ancestor.segments)
                return narrow(tuple(segments))

            return [
                Scope(label=str(context), segments=scope_segments(loop)) for loop in matches
            ]
        if context.sub_segment_id is not None:
            # a path only makes sense inside a loop; a plain flat segment
            # has no interior to narrow into
            return []
        return [
            Scope(label=str(context), segments=(seg,))
            for seg in self.flat_scope().segments
            if seg.seg_id == context.segment_id
            and (context.qualifier is None or seg.element(1) == context.qualifier)
        ]

    # -- iteration ----------------------------------------------------------

    def _loop_label(self, loop_id: str, index: int, loop: Loop) -> str:
        if loop_id == self.line_loop_id:
            return f"{loop_id} #{index}"
        return f"{loop_id}[{loop.qualifier or '?'}]"

    def business_segments(self) -> Iterator[tuple[str, Segment]]:
        """Yield ``(context_label, segment)`` for every business segment.

        Flat segments are labeled with their area id; loop segments with
        ``LOOP[qualifier]`` (or ``LOOP #n`` for the line loop).
        """
        emitted_loops: set[int] = set()
        for area_def in self.definition.areas:
            for seg in self.area(area_def.id):
                yield area_def.id, seg
            for loop_def in area_def.loops:
                yield from self._walk_loops(loop_def.id, emitted_loops)

    def _walk_loops(self, loop_id: str, emitted: set[int]) -> Iterator[tuple[str, Segment]]:
        for index, loop in enumerate(self.loops(loop_id), start=1):
            if id(loop) in emitted:
                continue
            emitted.add(id(loop))
            label = self._loop_label(loop_id, index, loop)
            for seg in loop.segments:
                yield label, seg
        loop_def = self.definition.loop(loop_id)
        if loop_def:
            for child in loop_def.loops:
                yield from self._walk_loops(child.id, emitted)


@dataclass
class Interchange:
    """A parsed X12 interchange: every ST/SE transaction plus shared control.

    ``documents`` holds one :class:`TransactionDocument` per ST/SE in file
    order. ``control_errors`` are the interchange-level envelope failures
    (SE/GE/IEA counts, control-number agreement, truncation) from MapCheck's
    native reconciliation — they belong to the file, not any one
    transaction; ``control_notes`` are advisory observations. A
    single-transaction file is just an interchange whose ``documents`` has
    length one.
    """

    documents: list[TransactionDocument] = field(default_factory=list)
    envelope: dict[str, str] = field(default_factory=dict)
    control_notes: list[str] = field(default_factory=list)
    control_errors: list[ControlIssue] = field(default_factory=list)


#: Backward-compatible alias: the 850 was the first (and once only) document.
Transaction850 = TransactionDocument
