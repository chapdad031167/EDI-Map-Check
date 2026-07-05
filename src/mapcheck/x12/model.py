"""Queryable structure for a parsed X12 850 transaction.

The 850 is modeled as three areas (heading, detail, summary) with two
explicit loops — N1 (party) and PO1 (line item). Loop members are kept as
flat segment lists inside their loop; nested detail loops (e.g. PID inside
PO1) are members of the PO1 loop, which is as deep as the MVP needs.

Resolution against spec addressing happens through :meth:`Transaction850.scopes`:
a :class:`Scope` is the list of segments a rule's Loop Context selects, and
plain ``SEGnn`` source fields are read from the first matching segment in
that scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from mapcheck.spec.model import LoopContext

#: Loop trigger segments the 850 layer knows about.
LOOP_TRIGGERS = frozenset({"N1", "PO1"})

#: Segments that belong to an open N1 loop rather than closing it.
N1_LOOP_MEMBERS = frozenset({"N2", "N3", "N4", "REF", "PER", "FOB", "TD5"})

#: Envelope/control segments excluded from business-data checks.
ENVELOPE_SEGMENTS = frozenset({"ISA", "GS", "ST", "SE", "GE", "IEA", "TA1"})


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
    """A loop occurrence: trigger segment plus member segments, in order."""

    loop_id: str
    segments: list[Segment] = field(default_factory=list)

    @property
    def trigger(self) -> Segment:
        return self.segments[0]

    @property
    def qualifier(self) -> str | None:
        """Element 01 of the trigger segment (N101, PO101, ...)."""
        return self.trigger.element(1)


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
class Transaction850:
    """A parsed 850: areas, loops, envelope metadata, and control notes."""

    heading: list[Segment] = field(default_factory=list)
    n1_loops: list[Loop] = field(default_factory=list)
    po1_loops: list[Loop] = field(default_factory=list)
    summary: list[Segment] = field(default_factory=list)
    envelope: dict[str, str] = field(default_factory=dict)
    #: Structural/control problems reported by pyx12 (SE counts, control
    #: number mismatches, ...). Surfaced as warnings by the engine.
    control_notes: list[str] = field(default_factory=list)

    # -- addressing ---------------------------------------------------------

    def flat_scope(self) -> Scope:
        """Heading + summary segments outside any loop (empty Loop Context)."""
        return Scope(label="header", segments=(*self.heading, *self.summary))

    def loops(self, loop_id: str) -> list[Loop]:
        if loop_id == "N1":
            return self.n1_loops
        if loop_id == "PO1":
            return self.po1_loops
        return []

    def scopes(self, context: LoopContext | None) -> list[Scope]:
        """Resolve a spec Loop Context to the scopes it selects.

        * ``None`` — one scope: the flat heading/summary area.
        * qualified loop trigger (``N1[ST]``) — each matching loop occurrence.
        * bare loop trigger (``PO1``) — one scope per loop occurrence.
        * qualified plain segment (``REF[DP]``) — each matching segment in
          the flat area, one single-segment scope apiece.

        Returns an empty list when nothing matches (the caller decides
        whether that means NOT TESTED, a failed condition, or a defect).
        """
        if context is None:
            return [self.flat_scope()]
        if context.segment_id in LOOP_TRIGGERS:
            matches = [
                loop
                for loop in self.loops(context.segment_id)
                if context.qualifier is None or loop.qualifier == context.qualifier
            ]
            return [
                Scope(label=str(context), segments=tuple(loop.segments)) for loop in matches
            ]
        return [
            Scope(label=str(context), segments=(seg,))
            for seg in self.flat_scope().segments
            if seg.seg_id == context.segment_id
            and (context.qualifier is None or seg.element(1) == context.qualifier)
        ]

    # -- iteration ----------------------------------------------------------

    def business_segments(self) -> Iterator[tuple[str, Segment]]:
        """Yield ``(context_label, segment)`` for every business segment."""
        for seg in self.heading:
            yield "header", seg
        for loop in self.n1_loops:
            label = f"N1[{loop.qualifier or '?'}]"
            for seg in loop.segments:
                yield label, seg
        for index, loop in enumerate(self.po1_loops, start=1):
            for seg in loop.segments:
                yield f"PO1 #{index}", seg
        for seg in self.summary:
            yield "summary", seg
