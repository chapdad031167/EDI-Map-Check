"""Schema for declarative transaction definitions.

A transaction definition tells the generic X12 parser and the validation
engine everything transaction-specific: which segments belong where, which
segments open loops (including HL-style hierarchical trees), what the
envelope must say, how spec ``lines[]`` targets pair with a source loop,
and which source-side reconciliation checks to run.

Definitions normally live as YAML files under
``mapcheck/transactions/definitions/`` (see :mod:`mapcheck.transactions.loader`),
so adding a transaction set is adding a data file, not writing parser code.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def unquoted_code_error(value: object) -> str:
    """Why a bare YAML scalar cannot stand in for a qualifier code.

    An EDI code is text that happens to look numeric, and YAML reads the
    number instead: ``002`` arrives as ``2``, and a leading zero means
    octal, so ``010`` arrives as ``8``. Either way the rule quietly stops
    matching the segment it was written for, which is the one failure a
    validation tool must not have. Both loaders reject the bare scalar
    and say how to write it instead.
    """
    return (
        f"expected a quoted code, got {type(value).__name__} {value!r} — an "
        "unquoted YAML code loses leading zeros and reads a leading 0 as "
        "octal (002 arrives as 2, 010 as 8); quote it exactly as the guide "
        "prints it"
    )


@dataclass(frozen=True)
class HierarchyDef:
    """HL-style variable-depth tree configuration for a loop.

    ``id_element`` / ``parent_element`` are the 1-based elements carrying
    the occurrence id and parent id (HL01/HL02). ``level_element`` carries
    the level code (HL03) and doubles as the loop's qualifier element for
    spec Loop Context addressing (``HL[S]``, ``HL[I]``).
    """

    id_element: int
    parent_element: int
    level_element: int


@dataclass(frozen=True)
class LevelDef:
    """One allowed level of a hierarchical loop (e.g. HL03 = ``S``)."""

    code: str
    children: tuple[str, ...] = ()
    segments: tuple[str, ...] = ()


@dataclass(frozen=True)
class LoopDef:
    """A loop: trigger segment, member segments, optional nesting/hierarchy."""

    id: str
    trigger: str
    #: 1-based element of the trigger used as the ``[qualifier]`` in spec
    #: Loop Context addressing. For hierarchical loops this is
    #: ``hierarchy.level_element``.
    qualifier: int = 1
    segments: tuple[str, ...] = ()
    loops: tuple["LoopDef", ...] = ()
    max_repeats: int | None = None
    hierarchy: HierarchyDef | None = None
    levels: tuple[LevelDef, ...] = ()

    @property
    def is_hierarchical(self) -> bool:
        return self.hierarchy is not None

    def level(self, code: str) -> LevelDef | None:
        for level in self.levels:
            if level.code == code:
                return level
        return None


@dataclass(frozen=True)
class AreaDef:
    """One transaction area (heading/detail/summary), in order."""

    id: str
    #: Segments that switch the parser into this area on first sight.
    #: Empty for the first area.
    opens_with: tuple[str, ...] = ()
    segments: tuple[str, ...] = ()
    loops: tuple[LoopDef, ...] = ()


@dataclass(frozen=True)
class OutputPairing:
    """Which source loop the spec's repeating ``lines[]`` targets pair with."""

    list_path: str
    loop: str


@dataclass(frozen=True)
class Operand:
    """One side of a reconciliation check.

    Exactly one of these is set:

    * ``value`` — an element reference like ``CTT01``, read from the flat
      (non-loop) scope, or from ``context`` (a Loop Context string like
      ``HL[S]``) when given.
    * ``count`` — a loop id, optionally qualifier/level-filtered
      (``PO1``, ``HL``, ``HL[I]``).
    * ``sum_loop`` + (``sum_value`` | ``sum_expr``) — sum across a loop
      reference (``HL[I]``, ``SAC[C]``). A ``sum_value`` element
      (``ACK02``) is summed over **every** matching segment in each
      occurrence (repeats included); a ``sum_expr`` product
      (``"IT102 * IT104"``, parsed into element refs — no eval) is
      evaluated once per occurrence.
    * ``add`` / ``subtract`` — a combine operand: the sum of the ``add``
      sub-operands minus the sum of the ``subtract`` ones (invoice math:
      lines + charges − allowances).

    ``implied`` shifts a numeric operand's decimal point, matching the
    spec Format grammar.
    """

    value: str | None = None
    context: str | None = None
    count: str | None = None
    sum_loop: str | None = None
    sum_value: str | None = None
    sum_expr: tuple[str, ...] = ()  # element refs multiplied together
    add: tuple["Operand", ...] = ()
    subtract: tuple["Operand", ...] = ()
    implied: int | None = None

    @property
    def is_combine(self) -> bool:
        return bool(self.add or self.subtract)


@dataclass(frozen=True)
class RequiredElementDef:
    """A base-standard mandatory element, checked on every occurrence.

    ``segment`` is the segment id and ``element`` the 1-based position that
    must carry a value in every occurrence of that segment. ``name`` is the
    human name used in messages ("PO number"). With ``when_present`` set
    (another 1-based element of the same segment), the element is required
    only in occurrences where that other element has a value — X12
    relational conditions, e.g. the 850's C0302 (if PO103 then PO102);
    ``when_name`` names it for messages.

    Base-standard requiredness is spec-independent: it lives here in the
    transaction definition, not in any mapping spec, and an empty required
    element is a FAILURE, never NOT TESTED.

    With ``qualifier`` set (Design 015), only occurrences whose
    ``qualifier_element`` equals that code are checked — "REF02 is
    required in REF*IA occurrences" — so a partner rule about one
    qualified occurrence never flags the others. ``qualifiers`` (Design
    018) is the code-*set* form: an occurrence matches when its qualifier
    element is any of the codes ("REF02 in REF*{IA|DP}"); it takes
    precedence over ``qualifier`` and the two are never both set.

    ``loop`` (Design 018) scopes the check to occurrences inside a loop
    context — a bare loop id (``N1``) matches any occurrence of it, a
    qualified context (``N1[ST]``) only that one — so "PER02 required
    within the N1 loop" ignores a heading PER.

    ``origin`` is empty for base-standard rules; a partner-rules overlay
    (Design 014) sets it to the partner name so findings say whose rule
    failed.
    """

    segment: str
    element: int
    name: str = ""
    when_present: int | None = None
    when_name: str = ""
    qualifier: str | None = None
    qualifiers: tuple[str, ...] = ()
    qualifier_element: int = 1
    loop: str = ""
    origin: str = ""

    def match_codes(self) -> tuple[str, ...]:
        """The qualifier codes this rule matches (empty = unqualified)."""
        if self.qualifiers:
            return self.qualifiers
        return (self.qualifier,) if self.qualifier is not None else ()


@dataclass(frozen=True)
class RequiredPairDef:
    """A qualifier/value pair required in every occurrence of a segment.

    X12 product-ID pairs are positional but code-keyed: PO106/PO107 and
    PO108/PO109 both carry (qualifier, value), and a sender may put a
    given qualifier in either slot. This rule is the semantic form —
    "every PO1 must carry a UP pair" — checked by scanning the qualifier
    positions ``first_element, first_element + step, …, last_element``
    for ``code`` with a non-empty companion value at the next position.

    ``name`` is the code's human name for messages ("UPC Consumer
    Package Code"); ``origin`` names the partner whose rule this is.
    """

    segment: str
    code: str
    first_element: int = 6
    last_element: int = 24
    step: int = 2
    name: str = ""
    origin: str = ""


@dataclass(frozen=True)
class RequiredSegmentDef:
    """A segment that must appear at least once in the transaction.

    With ``qualifier`` set, only occurrences whose ``qualifier_element``
    (1-based, element 01 by default) equals the qualifier count — the shape
    of X12 qualified families like ``DTM*002`` or ``REF*IA``. ``qualifiers``
    (Design 018) is the code-*set* form: at least one occurrence whose
    qualifier element is any of the codes ("a REF whose REF01 ∈ {IA, DP}");
    it takes precedence over ``qualifier`` and the two are never both set.

    ``loop`` (Design 018) scopes the presence check to a loop context — a
    bare loop id (``N1``) matches any occurrence of it, a qualified context
    (``N1[ST]``) only that one — so "PER required within the N1 loop"
    ignores a heading PER. ``name`` is the human name for messages
    ("Requested Delivery"). ``origin`` names the partner whose rules
    require it (empty for base-standard rules).

    The base 004010 standard makes almost no business segment mandatory
    beyond ST/BEG-class openers the parser already enforces, so in practice
    these come from partner-rules overlays (Design 014).
    """

    segment: str
    qualifier: str | None = None
    qualifiers: tuple[str, ...] = ()
    qualifier_element: int = 1
    loop: str = ""
    name: str = ""
    origin: str = ""

    def match_codes(self) -> tuple[str, ...]:
        """The qualifier codes this rule matches (empty = unqualified)."""
        if self.qualifiers:
            return self.qualifiers
        return (self.qualifier,) if self.qualifier is not None else ()


@dataclass(frozen=True)
class ReconRule:
    """A declarative source-side reconciliation check."""

    id: str
    left: Operand
    right: Operand
    check: str = "equals"  # only comparison supported so far
    when_exists: str | None = None  # skip silently unless this element exists
    when_context: str | None = None  # Loop Context the when-element lives in
    severity: str = "warning"  # 'warning' (default) or 'error'
    description: str = ""


@dataclass(frozen=True)
class TransactionDefinition:
    """A complete transaction definition."""

    set_code: str  # ST01, e.g. "850"
    name: str
    functional_group: str  # GS01
    version: str | None = None
    areas: tuple[AreaDef, ...] = ()
    output_pairing: OutputPairing | None = None
    reconciliation: tuple[ReconRule, ...] = ()
    required_elements: tuple[RequiredElementDef, ...] = ()
    required_segments: tuple[RequiredSegmentDef, ...] = ()
    required_pairs: tuple[RequiredPairDef, ...] = ()
    #: Element dictionary for draft-spec's source walk (Design 012):
    #: segment id -> element names in positional order (element 01 first).
    #: Covers the commonly used commercial subset, not the exhaustive
    #: standard; segments without an entry simply don't enumerate.
    elements: dict[str, tuple[str, ...]] = field(default_factory=dict)
    source: str = ""  # where this definition was loaded from, for messages

    def all_loops(self) -> list[LoopDef]:
        """Every loop in the definition, including nested ones, in order."""
        found: list[LoopDef] = []

        def walk(loops: tuple[LoopDef, ...]) -> None:
            for loop in loops:
                found.append(loop)
                walk(loop.loops)

        for area in self.areas:
            walk(area.loops)
        return found

    def loop(self, loop_id: str) -> LoopDef | None:
        for candidate in self.all_loops():
            if candidate.id == loop_id:
                return candidate
        return None

    def area(self, area_id: str) -> AreaDef | None:
        for candidate in self.areas:
            if candidate.id == area_id:
                return candidate
        return None
