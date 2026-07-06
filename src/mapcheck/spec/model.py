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


class RuleType(str, Enum):
    """How a spec row says the target value is produced."""

    DIRECT = "DIRECT"  # source value lands in target as-is (after format conversion)
    CONDITIONAL = "CONDITIONAL"  # if/then/else mapping
    CODE_LIST = "CODE_LIST"  # source value translated via a lookup table
    CONSTANT = "CONSTANT"  # hardcoded default, no source field
    LOOP_COUNT = "LOOP_COUNT"  # target holds the occurrence count of a source loop


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


def split_source_field(source_field: str) -> tuple[str, int]:
    """Split ``'BEG03'`` into ``('BEG', 3)``; raises ValueError on bad syntax."""
    m = _SOURCE_FIELD_RE.match(source_field.strip())
    if not m:
        raise ValueError(
            f"invalid source field {source_field!r} (expected segment+element, e.g. 'BEG03')"
        )
    return m.group(1), int(m.group(2))


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

    @property
    def is_per_line(self) -> bool:
        """True when the rule runs once per repeating-loop occurrence."""
        return "[]" in self.target_field

    def source_ref(self) -> str:
        """Human-readable source reference for reports, e.g. ``N1[ST] N104``."""
        parts = []
        if self.loop_context:
            parts.append(str(self.loop_context))
        if self.source_field:
            parts.append(self.source_field)
        return " ".join(parts) if parts else "(none)"


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

    @property
    def transaction_set(self) -> str | None:
        return self.meta.get("Transaction Set")

    def rules_for_target(self, target_field: str) -> list[MappingRule]:
        return [r for r in self.rules if r.target_field == target_field]
