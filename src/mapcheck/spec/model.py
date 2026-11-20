"""Data model for EDI MapCheck mapping specifications.

A mapping spec is loaded from the Excel template into these frozen
dataclasses. The validation engine consumes only this model; nothing
downstream touches openpyxl.

Addressing conventions (chosen for vendor neutrality):

* **Source Field** is plain segment+element notation: ``BEG03``, ``N104``,
  ``PO102``. Which occurrence of a repeating segment/loop is meant lives in
  the separate **Loop Context** column.
* **Loop Context** is either empty (header/summary area, first occurrence),
  a segment/loop id (``PO1`` = each occurrence of the PO1 loop), or a
  qualified occurrence ``SEG[QQ]`` (``N1[ST]`` = the N1 loop whose N101 is
  ``ST``; ``REF[DP]`` = the REF segment whose REF01 is ``DP``). The
  qualifier always matches element 01 of the context segment.
* **Target Field** is a dot path into the canonical output model:
  ``order.po_number``, ``ship_to.name``, ``lines[].qty``,
  ``summary.line_count``. ``lines[]`` pairs each PO1 loop occurrence with
  the output line at the same position.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class Direction(str, Enum):
    """Which way the spec maps (Meta sheet ``Direction`` key).

    Inbound (the default) validates X12 → internal: expected values derive
    from the X12 source, actuals resolve from the canonical output model.
    Outbound swaps the roles: Source Field holds a canonical path into the
    internal document, Target Field holds an X12 element (``BAK03``), and
    Loop Context qualifies the X12 target side.
    """

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class RuleType(str, Enum):
    """How a spec row says the target value is produced."""

    DIRECT = "DIRECT"  # source value lands in target as-is (after format conversion)
    CONDITIONAL = "CONDITIONAL"  # if/then/else mapping
    CODE_LIST = "CODE_LIST"  # source value translated via a lookup table
    CONSTANT = "CONSTANT"  # hardcoded default, no source field
    LOOP_COUNT = "LOOP_COUNT"  # target holds the occurrence count of a source loop
    TODO = "TODO"  # draft placeholder: mapping not decided yet (reports NOT TESTED)


class DataType(str, Enum):
    """Expected data type of the target field (drives rule-5 checks)."""

    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE = "date"
    TIME = "time"


class OutcomeKind(str, Enum):
    """What a conditional rule's Then/Else column resolves to."""

    SOURCE = "SOURCE"  # map the source element's value
    LITERAL = "LITERAL"  # map a quoted literal
    SKIP = "SKIP"  # target field must be absent
    BLANK = "BLANK"  # target field present but empty
    NEXT = "NEXT"  # Else only: the next Mapping row decides (Design 022)


@dataclass(frozen=True)
class Outcome:
    """A resolved Then/Else outcome."""

    kind: OutcomeKind
    literal: str | None = None

    def __str__(self) -> str:
        if self.kind is OutcomeKind.LITERAL:
            return f"'{self.literal}'"
        return self.kind.value


@dataclass(frozen=True)
class Predicate:
    """A single coded comparison, e.g. ``N101 = 'ST'`` or ``EXISTS(REF02)``."""

    field: str
    op: str  # '=', '!=', 'IN', 'EXISTS'
    values: tuple[str, ...] = ()

    def __str__(self) -> str:
        if self.op == "EXISTS":
            return f"EXISTS({self.field})"
        if self.op == "IN":
            vals = ", ".join(f"'{v}'" for v in self.values)
            return f"{self.field} IN ({vals})"
        return f"{self.field} {self.op} '{self.values[0]}'"


@dataclass(frozen=True)
class Condition:
    """AND-joined predicates parsed from the coded condition column."""

    predicates: tuple[Predicate, ...]
    raw: str

    def __str__(self) -> str:
        return self.raw


_CONTEXT_RE = re.compile(
    r"^([A-Z][A-Z0-9]{1,2})(?:\[([^\]]+)\])?"  # base loop/segment, optional qualifier
    r"(?:>([A-Z][A-Z0-9]{1,2})\[([^\]]+)\])?$"  # optional qualified segment within it
)


@dataclass(frozen=True)
class LoopContext:
    """Parsed Loop Context cell: which occurrence of a segment/loop to use.

    ``qualifier`` matches element 01 of the context segment (``N1[ST]``,
    ``REF[DP]``, ``DTM[002]``). A bare id (``PO1``) means *each* occurrence
    — the rule is evaluated once per loop instance.

    A path form narrows to a qualified segment *within* the loop:
    ``LIN>QTY[QA]`` pairs per-line on the LIN loop but resolves source
    fields from the QTY segment whose QTY01 is ``QA`` — how an 846 maps
    available/on-order/committed quantities to distinct fields. The
    sub-segment's qualifier always matches its element 01, and the rule's
    source/condition fields see only the narrowed segment(s).
    """

    segment_id: str
    qualifier: str | None = None
    sub_segment_id: str | None = None
    sub_qualifier: str | None = None

    @classmethod
    def parse(cls, text: str) -> "LoopContext":
        """Parse a Loop Context cell value; raises ValueError on bad syntax."""
        m = _CONTEXT_RE.match(text.strip())
        if not m:
            raise ValueError(
                f"invalid loop context {text!r} "
                "(expected e.g. 'PO1', 'N1[ST]', 'REF[DP]', or 'LIN>QTY[QA]')"
            )
        return cls(
            segment_id=m.group(1),
            qualifier=m.group(2),
            sub_segment_id=m.group(3),
            sub_qualifier=m.group(4),
        )

    def base(self) -> "LoopContext":
        """The context without its sub-segment path (for loop pairing)."""
        if self.sub_segment_id is None:
            return self
        return LoopContext(segment_id=self.segment_id, qualifier=self.qualifier)

    def __str__(self) -> str:
        text = f"{self.segment_id}[{self.qualifier}]" if self.qualifier else self.segment_id
        if self.sub_segment_id is not None:
            text += f">{self.sub_segment_id}[{self.sub_qualifier}]"
        return text


_SOURCE_FIELD_RE = re.compile(r"^([A-Z][A-Z0-9]{1,2})(\d{2})$")

#: Canonical path notation: dot-separated keys, ``[]`` marking the
#: repeating list (``order.po_number``, ``lines[].qty``, ``refs.001.belnr``).
_CANONICAL_PATH_RE = re.compile(
    r"^[A-Za-z0-9_]+(?:\[\])?(?:\.[A-Za-z0-9_]+(?:\[\])?)*$"
)


def split_source_field(source_field: str) -> tuple[str, int]:
    """Split ``'BEG03'`` into ``('BEG', 3)``; raises ValueError on bad syntax."""
    m = _SOURCE_FIELD_RE.match(source_field.strip())
    if not m:
        raise ValueError(
            f"invalid source field {source_field!r} (expected segment+element, e.g. 'BEG03')"
        )
    return m.group(1), int(m.group(2))


def is_element_ref(text: str) -> bool:
    """True when ``text`` is segment+element notation (``BEG03``)."""
    return _SOURCE_FIELD_RE.match(text.strip().upper()) is not None


def is_canonical_path(text: str) -> bool:
    """True when ``text`` is canonical dot-path notation (``lines[].qty``)."""
    text = text.strip()
    return bool(_CANONICAL_PATH_RE.match(text)) and not is_element_ref(text)


@dataclass(frozen=True)
class MappingRule:
    """One row of the Mapping sheet."""

    row_id: str
    sheet_row: int  # 1-based Excel row, for error/report references
    target_field: str
    rule_type: RuleType
    source_field: str | None = None
    loop_context: LoopContext | None = None
    condition_text: str | None = None
    condition: Condition | None = None
    then_outcome: Outcome | None = None
    else_outcome: Outcome | None = None
    default_value: str | None = None
    code_list_ref: str | None = None
    data_type: DataType | None = None
    format: str | None = None
    notes: str | None = None
    direction: Direction = Direction.INBOUND
    #: Where this rule came from after any partner-override merge: "base",
    #: or a partner label like "partner:acme". Default keeps every
    #: non-overridden spec and test unaffected.
    origin: str = "base"

    @property
    def is_per_line(self) -> bool:
        """True when the rule runs once per repeating-loop occurrence.

        Inbound, the ``lines[]`` target marks it; outbound the target is an
        X12 element, so a bare (unqualified) Loop Context — *each*
        occurrence of the loop — is the marker instead.
        """
        if self.direction is Direction.OUTBOUND:
            return self.loop_context is not None and self.loop_context.qualifier is None
        return "[]" in self.target_field

    @property
    def passes_on(self) -> bool:
        """True when this row's Else hands the decision to the next row
        (Design 022), making it a link in an if / else-if chain."""
        return (
            self.rule_type is RuleType.CONDITIONAL
            and self.else_outcome is not None
            and self.else_outcome.kind is OutcomeKind.NEXT
        )

    def source_ref(self) -> str:
        """Human-readable source reference for reports, e.g. ``N1[ST] N104``.

        Outbound the source is a canonical path and Loop Context belongs to
        the X12 target side, so only the path is shown.
        """
        if self.direction is Direction.OUTBOUND:
            return self.source_field or "(none)"
        parts = []
        if self.loop_context:
            parts.append(str(self.loop_context))
        if self.source_field:
            parts.append(self.source_field)
        return " ".join(parts) if parts else "(none)"

    def target_ref(self) -> str:
        """Human-readable target reference for reports.

        Inbound targets are self-describing paths; outbound ones gain their
        Loop Context, e.g. ``N1[SE] N102``.
        """
        if self.direction is Direction.OUTBOUND and self.loop_context:
            return f"{self.loop_context} {self.target_field}"
        return self.target_field


def group_units(rules: tuple[MappingRule, ...] | list[MappingRule]) -> list[tuple[MappingRule, ...]]:
    """Group rules into the units the engine evaluates (Design 022).

    A unit is one rule, or a chain: consecutive rows each of whose Else is
    ``NEXT``, plus the row that ends it (the tail). The grouping itself
    does not judge whether a chain is well formed; :func:`chain_errors`
    does, and the loader refuses a spec that fails it.
    """
    units: list[tuple[MappingRule, ...]] = []
    current: list[MappingRule] = []
    for rule in rules:
        current.append(rule)
        if not rule.passes_on:
            units.append(tuple(current))
            current = []
    if current:  # a trailing row that passes on to nothing
        units.append(tuple(current))
    return units


def _same_target(a: MappingRule, b: MappingRule) -> bool:
    """Do two rows decide the same target? Outbound, the X12 element alone
    is not enough: Loop Context says which occurrence, so it must agree."""
    if a.target_field != b.target_field:
        return False
    if a.direction is Direction.OUTBOUND:
        return a.loop_context == b.loop_context
    return True


def chain_errors(rules: tuple[MappingRule, ...] | list[MappingRule]) -> list[str]:
    """Everything wrong with the chains in ``rules``, one message each.

    Checked at load so a malformed chain is a spec error naming its rows,
    never a strange finding in a report.
    """

    def name(rule: MappingRule) -> str:
        return f"Mapping row {rule.sheet_row} ({rule.row_id})"

    errors: list[str] = []
    for unit in group_units(rules):
        last = unit[-1]
        if last.passes_on:
            errors.append(
                f"{name(last)}: Else is NEXT but there is no next row to "
                "pass the decision to"
            )
            continue
        if len(unit) == 1:
            continue
        head = unit[0]
        for prev, row in zip(unit, unit[1:]):
            if not _same_target(prev, row):
                errors.append(
                    f"{name(prev)}: Else is NEXT, so the next row must decide the "
                    f"same target ({prev.target_ref()}), but {name(row)} targets "
                    f"{row.target_ref()}"
                )
        scopes = {
            (r.is_per_line, r.loop_context.base() if r.is_per_line and r.loop_context else None)
            for r in unit
        }
        if len(scopes) > 1:
            errors.append(
                f"{name(head)}: the rows of a chain must all be per-line on the "
                "same loop, or all header-level; this one mixes them"
            )
    return errors


@dataclass(frozen=True)
class CodeList:
    """A named lookup table from the CodeLists sheet."""

    name: str
    entries: dict[str, str]  # source value -> target value
    descriptions: dict[str, str] = field(default_factory=dict)

    def translate(self, source_value: str) -> str | None:
        """Return the target value for a source value, or None if unlisted."""
        return self.entries.get(source_value)


@dataclass(frozen=True)
class MappingSpec:
    """A fully loaded, validated mapping specification."""

    meta: dict[str, str]
    rules: tuple[MappingRule, ...]
    code_lists: dict[str, CodeList]
    source_path: str | None = None
    direction: Direction = Direction.INBOUND
    #: Non-fatal loader observations (e.g. BLANK outcomes in an outbound
    #: spec); surfaced as warnings by the engine.
    load_notes: tuple[str, ...] = ()

    @property
    def transaction_set(self) -> str | None:
        return self.meta.get("Transaction Set")

    def rules_for_target(self, target_field: str) -> list[MappingRule]:
        return [r for r in self.rules if r.target_field == target_field]

    def units(self) -> list[tuple[MappingRule, ...]]:
        """The rules as the engine evaluates them: single rows, and chains
        of rows linked by an Else of ``NEXT`` (Design 022)."""
        return group_units(self.rules)
