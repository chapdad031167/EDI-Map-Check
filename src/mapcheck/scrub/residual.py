"""Residual-risk scan (Design 020): what a scrub left in the clear.

A scrub profile is a list of positions somebody thought of. This module
looks at everything else. After masking, every element the scrubber did
not touch is checked for the shapes identifiers take (postal code, phone,
UPC, DEA, NDC, email, account-style tokens), for free text, for a position
the profile masks elsewhere in the same file, and for an identifier left
beside a masked name.

It is a pattern check, so it errs toward speaking up: a harmless value
flagged costs the reader ten seconds, a real one missed costs a
disclosure. What keeps it from being noise is :class:`Positions`, the
table of positions known to hold control numbers, codes or arithmetic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources

import yaml

ENVELOPE_SEGMENTS = frozenset({"ISA", "GS", "ST", "SE", "GE", "IEA"})

#: Trading-partner IDs, masked by a profile's ``envelope: true``.
ENVELOPE_IDS = frozenset({("ISA", 6), ("ISA", 8), ("GS", 2), ("GS", 3)})

#: ISA02 / ISA04: authorization and security information. Blank in most
#: interchanges, a password in some.
ENVELOPE_SECRETS = frozenset({("ISA", 2), ("ISA", 4)})

#: A value this short is a code, a unit or a small count.
SHORT_CODE = 3

Position = tuple[str, int]

_ELEMENT_REF = re.compile(r"^([A-Z][A-Z0-9]{1,2})(\d{2})$")
_NDC = re.compile(r"\d{4,5}-\d{3,4}-\d{1,2}")
_DEA = re.compile(r"[A-Za-z]{2}\d{7}")
_ZIP_PLUS4 = re.compile(r"\d{5}-\d{4}")
_PHONE_FORMATTED = re.compile(r"\+?[\d\s\-().]+")
_DECIMAL = re.compile(r"-?\d*\.\d+|-?\d+\.\d*")


def parse_element_ref(ref: str) -> Position | None:
    """``CTT01`` -> ``("CTT", 1)``, ``W0301`` -> ``("W03", 1)``."""
    match = _ELEMENT_REF.match(ref.strip())
    if not match:
        return None
    return match.group(1), int(match.group(2))


def is_decimal(value: str) -> bool:
    """A number written with a decimal point: a price or a quantity, never
    a postal code, a phone number or a UPC."""
    return bool(_DECIMAL.fullmatch(value.strip()))


def is_date(value: str) -> bool:
    """Eight digits that read as a plausible CCYYMMDD date."""
    v = value.strip()
    if len(v) != 8 or not v.isdigit():
        return False
    year, month, day = int(v[:4]), int(v[4:6]), int(v[6:])
    return 1900 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31


def classify(value: str) -> str | None:
    """Name the identifier shape ``value`` has, or None when it has none."""
    v = value.strip()
    if not v:
        return None
    if "@" in v:
        return "email address"
    tokens = [t.strip(",;:") for t in v.split()]
    for token in tokens:
        if _NDC.fullmatch(token):
            return "NDC shape"
    for token in tokens:
        if _DEA.fullmatch(token):
            return "DEA-number shape"
    for token in tokens:
        if token.isdigit() and 12 <= len(token) <= 14:
            return "UPC/GTIN shape"
    for token in tokens:
        if token.isdigit() and 10 <= len(token) <= 11:
            return "phone-number shape"
    if not v.isdigit() and _PHONE_FORMATTED.fullmatch(v):
        if 10 <= sum(ch.isdigit() for ch in v) <= 11:
            return "phone-number shape"
    for token in tokens:
        if (token.isdigit() and len(token) in (5, 9)) or _ZIP_PLUS4.fullmatch(token):
            return "postal-code shape"
    for token in tokens:
        core = token.strip(".,;:()[]#/")
        if (
            len(core) >= 6
            and any(ch.isalpha() for ch in core)
            and any(ch.isdigit() for ch in core)
        ):
            return "account or reference shape"
    return None


def _positions(raw: object, label: str) -> set[Position]:
    if raw is None:
        return set()
    if not isinstance(raw, dict):
        raise ValueError(f"positions table: '{label}' must be a mapping")
    found: set[Position] = set()
    for seg, elements in raw.items():
        for element in elements or ():
            found.add((str(seg), int(element)))
    return found


@dataclass
class Positions:
    """Which element positions hold control numbers, codes, math, an
    identifier, or free text."""

    control: set[Position] = field(default_factory=set)
    structure: set[Position] = field(default_factory=set)
    code: set[Position] = field(default_factory=set)
    math: set[Position] = field(default_factory=set)
    identifier: set[Position] = field(default_factory=set)
    free_text: set[Position] = field(default_factory=set)

    @classmethod
    def bundled(cls) -> "Positions":
        text = (resources.files("mapcheck.scrub") / "positions.yaml").read_text(
            encoding="utf-8"
        )
        data = yaml.safe_load(text) or {}
        return cls(
            control=_positions(data.get("control"), "control"),
            structure=_positions(data.get("structure"), "structure"),
            code=_positions(data.get("code"), "code"),
            math=_positions(data.get("math"), "math"),
            identifier=_positions(data.get("identifier"), "identifier"),
            free_text=_positions(data.get("free_text"), "free_text"),
        )

    @classmethod
    def for_transactions(cls, set_codes: set[str]) -> "Positions":
        """The bundled table, widened from the definitions of the
        transaction sets present in the file."""
        positions = cls.bundled()
        if not set_codes:
            return positions
        from mapcheck.transactions.registry import default_registry

        for definition in default_registry.all():
            if definition.set_code in set_codes:
                positions._learn(definition)
        return positions

    def _learn(self, definition) -> None:
        def operand(op) -> None:
            if op is None:
                return
            for ref in (op.value, op.sum_value, *op.sum_expr):
                pos = parse_element_ref(ref) if ref else None
                if pos and pos not in self.control:
                    self.math.add(pos)
            for child in (*op.add, *op.subtract):
                operand(child)

        for rule in definition.reconciliation:
            operand(rule.left)
            operand(rule.right)
        for loop in definition.all_loops():
            self.code.add((loop.trigger, loop.qualifier))
        for rule in (*definition.required_elements, *definition.required_segments):
            if rule.match_codes():
                self.code.add((rule.segment, rule.qualifier_element))
        for seg, names in definition.elements.items():
            for number, name in enumerate(names, start=1):
                kind = _kind_from_name(name)
                if kind == "code":
                    self.code.add((seg, number))
                elif kind == "math" and (seg, number) not in self.control:
                    self.math.add((seg, number))

    def is_quiet(self, pos: Position) -> bool:
        """Nothing to report here: a control number, a code, or math."""
        return (
            pos in self.control
            or pos in self.structure
            or pos in self.code
            or pos in self.math
        )


#: Element names that end in "Code" but hold an identifier or an address.
_NOT_CODES = {"Identification Code", "Postal Code", "State or Province Code"}
_MATH_WORDS = ("Quantity", "Price", "Amount", "Date", "Hash Total")


def _kind_from_name(name: str) -> str | None:
    """Classify a definition's element name (Design 012's dictionary)."""
    if "Qualifier" in name:
        return "code"
    if name in _NOT_CODES:
        return None
    if name.endswith(("Code", "Indicator", " Type")):
        return "code"
    if any(word in name for word in _MATH_WORDS):
        return "math"
    return None


@dataclass
class Residual:
    """One position holding unmasked values that look like they matter."""

    position: str
    reason: str
    values: list[str] = field(default_factory=list)
    occurrences: int = 0

    def shown(self, limit: int = 3, width: int = 32) -> str:
        parts = [v if len(v) <= width else v[: width - 3] + "..." for v in self.values[:limit]]
        extra = len(self.values) - limit
        if extra > 0:
            parts.append(f"+{extra} more")
        return ", ".join(parts)


def _label(pos: Position) -> str:
    return f"{pos[0]}{pos[1]:02d}"


class ResidualScan:
    """Collects residual findings across one scrub."""

    def __init__(self, positions: Positions, deny_by_default: bool = False) -> None:
        self.positions = positions
        self.deny_by_default = deny_by_default
        self._found: dict[tuple[str, str], Residual] = {}
        self._masked_positions: set[Position] = set()
        self._unflagged: list[tuple[Position, str]] = []

    def _flag(self, pos: Position, reason: str, value: str) -> None:
        key = (_label(pos), reason)
        entry = self._found.setdefault(key, Residual(_label(pos), reason))
        entry.occurrences += 1
        shown = value.strip()
        if shown not in entry.values:
            entry.values.append(shown)

    def segment(
        self,
        seg_id: str,
        elements: list[str],
        handled: set[int],
        masked_names: list[int],
    ) -> None:
        """Look at one segment occurrence.

        ``elements`` are the original values, ``handled`` the indexes a
        rule (or the deny-by-default pass) took care of, ``masked_names``
        the indexes masked by a ``name`` rule in this occurrence.
        """
        for idx in handled:
            self._masked_positions.add((seg_id, idx + 1))

        if seg_id in ENVELOPE_SEGMENTS:
            for idx, value in enumerate(elements):
                pos = (seg_id, idx + 1)
                if idx in handled or not value.strip():
                    continue
                if pos in ENVELOPE_SECRETS:
                    self._flag(pos, "authorization or security information", value)
                elif pos in ENVELOPE_IDS:
                    self._flag(pos, "trading-partner ID, envelope masking is off", value)
            return

        beside = _label((seg_id, masked_names[0] + 1)) if masked_names else None
        for idx, value in enumerate(elements):
            if idx in handled or not value.strip():
                continue
            pos = (seg_id, idx + 1)
            if pos in self.positions.free_text:
                self._flag(pos, "free text", value)
                continue
            if beside and pos in self.positions.identifier:
                self._flag(pos, f"identifier beside a masked {beside}", value)
                continue
            if self.positions.is_quiet(pos):
                continue
            reason = classify(value)
            if reason is None and beside and len(value.strip()) > SHORT_CODE:
                reason = f"unmasked value beside a masked {beside}"
            if reason is not None:
                self._flag(pos, reason, value)
            else:
                self._unflagged.append((pos, value))

    def results(self) -> list[Residual]:
        # Inconsistent coverage: a position some rule masked elsewhere in
        # the file and left alone here (a qualifier-gated rule, usually).
        # Skipped for deny-by-default, where a kept value is a decision.
        if not self.deny_by_default:
            for pos, value in self._unflagged:
                if pos in self._masked_positions:
                    self._flag(pos, "masked elsewhere in this file, not here", value)
        self._unflagged = []
        return sorted(self._found.values(), key=lambda r: (r.position, r.reason))
