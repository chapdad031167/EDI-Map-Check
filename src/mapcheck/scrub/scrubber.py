"""X12 data scrubber: profile model, deterministic masking, round-trip.

The scrubber works on the raw file text so nothing about structure is
inferred or reconstructed — delimiters are read from the ISA, segments are
split on the segment terminator, and only the values of configured element
positions change. Masking is deterministic per run (same input value → same
output, so pairing keys survive) and length- and character-class-preserving.

A profile is either an allow-list (``mode: allow``, the default: mask the
positions the rules name, pass everything else through) or deny-by-default
(``mode: deny``: mask everything except what must survive for the file to
stay validatable). Either way the report names what was left in the clear
and looks like it should not have been (Design 020).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml

from mapcheck.scrub.residual import (
    ENVELOPE_IDS,
    ENVELOPE_SEGMENTS,
    Positions,
    Residual,
    ResidualScan,
    is_date,
    is_decimal,
)

#: Strategies that pseudonymize (character-class + length preserving) vs the
#: fixed-filler redaction. Pseudonymizing strategies are aliases that document
#: intent in a profile; they share one primitive so a value masks consistently.
_PSEUDO = {"name", "text", "id"}
_STRATEGIES = _PSEUDO | {"redact"}
_MODES = {"allow", "deny"}
_KEEP_KINDS = {"code", "math"}

DEFAULT_PROFILE = "pharma"

#: Envelope trading-partner IDs masked when ``profile.envelope`` is on.
_ENVELOPE_RULES = (
    ("ISA", 6, "id"),   # sender id
    ("ISA", 8, "id"),   # receiver id
    ("GS", 2, "id"),    # application sender
    ("GS", 3, "id"),    # application receiver
)


class ProfileError(Exception):
    """Raised when a scrub profile cannot be loaded."""


@dataclass(frozen=True)
class Rule:
    """Mask ``segment`` element ``element`` (optionally only when a qualifier
    element is one of ``when_in``). ``open_ended`` extends the rule to every
    later element of the segment; a profile writes it ``element: "3+"``."""

    segment: str
    element: int
    strategy: str
    when_element: int | None = None
    when_in: tuple[str, ...] = ()
    open_ended: bool = False

    def applies(self, elements: list[str]) -> bool:
        if self.when_element is None:
            return True
        idx = self.when_element - 1
        return 0 <= idx < len(elements) and elements[idx] in self.when_in

    def indexes(self, count: int) -> range:
        """0-based element indexes this rule covers in a segment that has
        ``count`` elements."""
        start = self.element - 1
        if start < 0 or start >= count:
            return range(0)
        return range(start, count if self.open_ended else start + 1)


@dataclass
class Profile:
    name: str
    rules: list[Rule]
    envelope: bool = True
    #: ``allow`` masks only what the rules name; ``deny`` masks everything
    #: that is not kept.
    mode: str = "allow"
    #: Deny mode: positions kept because they hold a code.
    keep_code: set[tuple[str, int]] = field(default_factory=set)
    #: Deny mode: positions kept because the math runs on them (masked
    #: again by ``--mask-math``).
    keep_math: set[tuple[str, int]] = field(default_factory=set)
    #: Deny mode: a value this short is a code, a unit or a small count.
    keep_short: int = 0

    def rules_for(self, seg_id: str) -> list[Rule]:
        return [r for r in self.rules if r.segment == seg_id]

    @property
    def deny_by_default(self) -> bool:
        return self.mode == "deny"


def _rule_element(raw: object) -> tuple[int, bool] | None:
    """``3`` -> (3, False); ``"3+"`` -> (3, True); anything else -> None."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return (raw, False) if raw >= 1 else None
    if isinstance(raw, str) and raw.endswith("+") and raw[:-1].isdigit():
        number = int(raw[:-1])
        return (number, True) if number >= 1 else None
    return None


def load_profile(name_or_path: str | Path | None = None) -> Profile:
    """Load a scrub profile by bundled name (``pharma``) or file path."""
    name_or_path = name_or_path or DEFAULT_PROFILE
    text: str
    candidate = Path(name_or_path)
    if candidate.exists():
        text = candidate.read_text(encoding="utf-8")
        label = candidate.stem
    else:
        try:
            resource = resources.files("mapcheck.scrub") / "profiles" / f"{name_or_path}.yaml"
            text = resource.read_text(encoding="utf-8")
        except (FileNotFoundError, ModuleNotFoundError, OSError):
            raise ProfileError(
                f"scrub profile not found: {name_or_path!r} "
                "(give a .yaml path or a bundled profile name like 'pharma')"
            ) from None
        label = str(name_or_path)

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ProfileError(f"{label}: invalid YAML: {exc}") from None
    if not isinstance(data, dict):
        raise ProfileError(f"{label}: profile must be a mapping with a 'rules' list")

    mode = str(data.get("mode", "allow"))
    if mode not in _MODES:
        raise ProfileError(
            f"{label}: unknown mode {mode!r} (expected 'allow' or 'deny')"
        )
    # An allow-list with no rules masks nothing, so it must name some. A
    # deny-by-default profile masks without any.
    raw_rules = data.get("rules", [] if mode == "deny" else None)
    if not isinstance(raw_rules, list):
        raise ProfileError(f"{label}: profile must be a mapping with a 'rules' list")

    rules: list[Rule] = []
    for i, raw in enumerate(raw_rules, start=1):
        if not isinstance(raw, dict):
            raise ProfileError(f"{label}: rule #{i} must be a mapping")
        seg = raw.get("segment")
        element = _rule_element(raw.get("element"))
        strategy = raw.get("strategy", "id")
        if not seg or element is None:
            raise ProfileError(
                f"{label}: rule #{i} needs a 'segment' and a positive integer 'element'"
            )
        if strategy not in _STRATEGIES:
            raise ProfileError(
                f"{label}: rule #{i} has unknown strategy {strategy!r} "
                f"(expected one of {', '.join(sorted(_STRATEGIES))})"
            )
        when = raw.get("when")
        when_element: int | None = None
        when_in: tuple[str, ...] = ()
        if when is not None:
            if not isinstance(when, dict) or "element" not in when or "in" not in when:
                raise ProfileError(
                    f"{label}: rule #{i} 'when' needs an 'element' and an 'in' list"
                )
            when_element = int(when["element"])
            when_in = tuple(str(v) for v in when["in"])
        rules.append(
            Rule(str(seg), element[0], strategy, when_element, when_in, element[1])
        )

    keep_code: set[tuple[str, int]] = set()
    keep_math: set[tuple[str, int]] = set()
    raw_keep = data.get("keep", [])
    if not isinstance(raw_keep, list):
        raise ProfileError(f"{label}: 'keep' must be a list")
    for i, raw in enumerate(raw_keep, start=1):
        elements = raw.get("elements") if isinstance(raw, dict) else None
        kind = raw.get("kind", "code") if isinstance(raw, dict) else None
        if (
            not isinstance(raw, dict)
            or not raw.get("segment")
            or not isinstance(elements, list)
            or not all(isinstance(e, int) and not isinstance(e, bool) and e >= 1 for e in elements)
        ):
            raise ProfileError(
                f"{label}: keep #{i} needs a 'segment' and an 'elements' list of positive integers"
            )
        if kind not in _KEEP_KINDS:
            raise ProfileError(
                f"{label}: keep #{i} has unknown kind {kind!r} (expected 'code' or 'math')"
            )
        target = keep_code if kind == "code" else keep_math
        target.update((str(raw["segment"]), e) for e in elements)

    keep_short = data.get("keep_short", 0)
    if isinstance(keep_short, bool) or not isinstance(keep_short, int) or keep_short < 0:
        raise ProfileError(f"{label}: 'keep_short' must be a non-negative integer")

    envelope = bool(data.get("envelope", True))
    return Profile(
        name=str(data.get("name", label)),
        rules=rules,
        envelope=envelope,
        mode=mode,
        keep_code=keep_code,
        keep_math=keep_math,
        keep_short=keep_short,
    )


@dataclass
class ScrubReport:
    """What a scrub masked, and what it left that looks like it matters."""

    masked: dict[tuple[str, int], int] = field(default_factory=dict)
    unique_values: int = 0
    #: Unmasked values that look like identifiers (Design 020).
    residuals: list[Residual] = field(default_factory=list)
    #: What a deny-by-default profile kept on purpose, in words.
    kept_note: str = ""

    @property
    def total(self) -> int:
        return sum(self.masked.values())

    def render(self) -> str:
        if not self.masked:
            lines = ["No values matched the profile, nothing masked."]
        else:
            lines = [f"Masked {self.total} value(s) ({self.unique_values} distinct):"]
            for (seg, ele), n in sorted(self.masked.items()):
                lines.append(f"  {seg}{ele:02d}: {n}")
        if self.kept_note:
            lines += ["", self.kept_note]
        lines.append("")
        lines.extend(self.render_residuals().splitlines())
        return "\n".join(lines)

    def render_residuals(self) -> str:
        """The residual-risk section on its own."""
        if not self.residuals:
            return (
                "Nothing left unmasked matched an identifier pattern. That is a "
                "pattern check, not a guarantee: read the file before you share it."
            )
        count = len(self.residuals)
        lines = [
            f"{count} position(s) hold values that look like identifiers "
            "and were NOT masked:"
        ]
        shown = [(r.position, r.shown(), r) for r in self.residuals]
        pos_width = max(len(p) for p, _, _ in shown)
        val_width = max(len(v) for _, v, _ in shown)
        for position, values, residual in shown:
            times = (
                f"  ({residual.occurrences} occurrences)"
                if residual.occurrences > len(residual.values)
                else ""
            )
            lines.append(
                f"  {position:<{pos_width}}  {values:<{val_width}}  "
                f"{residual.reason}{times}"
            )
        lines.append("Review these before sharing the file, or add rules to the profile.")
        return "\n".join(lines)


class Scrubber:
    """Applies a profile to X12 text with a per-instance masking cache.

    ``keep_math`` only matters to a deny-by-default profile: on (the
    default) it leaves quantities, amounts and dates in the clear so the
    scrubbed file still passes its own totals; off masks them too.
    """

    def __init__(
        self, profile: Profile, seed: str | None = None, keep_math: bool = True
    ) -> None:
        self.profile = profile
        self.salt = seed if seed is not None else secrets.token_hex(8)
        self.keep_math = keep_math
        self._cache: dict[tuple[str, str], str] = {}
        self.report = ScrubReport()

    # -- masking primitives -------------------------------------------------

    def _mask_value(self, value: str, strategy: str) -> str:
        if value == "" or value.isspace():
            return value
        cache_key = (value, strategy)
        if cache_key in self._cache:
            return self._cache[cache_key]
        masked = self._redact(value) if strategy == "redact" else self._pseudonymize(value)
        self._cache[cache_key] = masked
        self.report.unique_values += 1
        return masked

    def _rng_bytes(self, value: str) -> bytes:
        return hashlib.sha256(f"{self.salt}\x00{value}".encode()).digest()

    def _pseudonymize(self, value: str) -> str:
        """Length- and character-class-preserving replacement."""
        stream = _ByteStream(self._rng_bytes(value))
        out = []
        for ch in value:
            if ch.isdigit():
                out.append(str(stream.next() % 10))
            elif ch.isalpha():
                out.append(chr(ord("A") + stream.next() % 26))
            else:
                out.append(ch)  # separators, spaces, padding preserved
        return "".join(out)

    @staticmethod
    def _redact(value: str) -> str:
        return "".join("X" if ch.isalnum() else ch for ch in value)

    # -- segment / file processing -----------------------------------------

    def _rules_with_envelope(self) -> dict[str, list[Rule]]:
        by_seg: dict[str, list[Rule]] = {}
        for rule in self.profile.rules:
            by_seg.setdefault(rule.segment, []).append(rule)
        if self.profile.envelope:
            for seg, ele, strat in _ENVELOPE_RULES:
                by_seg.setdefault(seg, []).append(Rule(seg, ele, strat))
        return by_seg

    def _kept(self, pos: tuple[str, int], value: str, positions: Positions) -> bool:
        """Deny-by-default: does this value survive?"""
        v = value.strip()
        if not v:
            return True
        if pos in positions.control:
            return True
        if pos[0] in ENVELOPE_SEGMENTS:
            if pos in ENVELOPE_IDS:
                return not self.profile.envelope
            # Everything else in the envelope is structure, except what
            # the table does not list: ISA02/ISA04, which can hold a
            # password.
            return pos in positions.structure
        if pos in positions.math or pos in self.profile.keep_math:
            return self.keep_math
        if pos in positions.code or pos in self.profile.keep_code:
            return True
        # Never short enough to pass for a code: an identifier or prose.
        if pos in positions.identifier or pos in positions.free_text:
            return False
        if self.keep_math and (is_decimal(v) or is_date(v)):
            return True
        return len(v) <= self.profile.keep_short

    def scrub(self, text: str) -> str:
        element_sep, segment_sep = _delimiters(text)
        by_seg = self._rules_with_envelope()
        deny = self.profile.deny_by_default

        parts = text.split(segment_sep)
        split: list[tuple[str, list[str]] | None] = []
        set_codes: set[str] = set()
        for chunk in parts:
            lead = chunk[: len(chunk) - len(chunk.lstrip("\r\n \t"))]
            body = chunk[len(lead):]
            if not body:
                split.append(None)
                continue
            fields = body.split(element_sep)
            if fields[0] == "ST" and len(fields) > 1:
                set_codes.add(fields[1].strip())
            split.append((lead, fields))

        positions = Positions.for_transactions(set_codes)
        scan = ResidualScan(positions, deny_by_default=deny)

        for i, entry in enumerate(split):
            if entry is None:
                continue
            lead, fields = entry
            seg_id = fields[0]
            original = fields[1:]
            elements = list(original)
            handled: set[int] = set()
            masked_names: list[int] = []

            def mask(idx: int, strategy: str) -> None:
                value = original[idx]
                handled.add(idx)
                masked = self._mask_value(value, strategy)
                if masked != value:
                    elements[idx] = masked
                    key = (seg_id, idx + 1)
                    self.report.masked[key] = self.report.masked.get(key, 0) + 1
                    if strategy == "name":
                        masked_names.append(idx)

            for rule in by_seg.get(seg_id, ()):
                # Gate on the original values: an earlier rule may already
                # have masked the qualifier this one tests.
                if not rule.applies(original):
                    continue
                for idx in rule.indexes(len(original)):
                    if idx not in handled:
                        mask(idx, rule.strategy)
            if deny:
                for idx, value in enumerate(original):
                    if idx in handled:
                        continue
                    if not self._kept((seg_id, idx + 1), value, positions):
                        mask(idx, "text")

            scan.segment(seg_id, original, handled, masked_names)
            if elements != original:
                parts[i] = lead + element_sep.join([seg_id, *elements])

        self.report.residuals = scan.results()
        if deny:
            self.report.kept_note = self._kept_note()
        return segment_sep.join(parts)

    def _kept_note(self) -> str:
        kept = ["envelope control numbers and counts", "qualifiers and codes"]
        if self.profile.keep_short:
            kept.append(f"values of {self.profile.keep_short} characters or fewer")
        if self.keep_math:
            kept.append("quantities, amounts and dates (--mask-math masks those too)")
        return "Kept in the clear by design: " + "; ".join(kept) + "."


class _ByteStream:
    """Endless deterministic byte stream from a seed (re-hash on exhaustion)."""

    def __init__(self, seed: bytes) -> None:
        self._seed = seed
        self._buf = seed
        self._pos = 0

    def next(self) -> int:
        if self._pos >= len(self._buf):
            self._buf = hashlib.sha256(self._buf).digest()
            self._pos = 0
        b = self._buf[self._pos]
        self._pos += 1
        return b


def _delimiters(text: str) -> tuple[str, str]:
    """Read the element separator and segment terminator from the ISA."""
    isa = text.find("ISA")
    if isa == -1 or len(text) < isa + 106:
        raise ValueError("not an X12 interchange (no ISA header found)")
    element_sep = text[isa + 3]
    segment_sep = text[isa + 105]
    return element_sep, segment_sep


def scrub_text(
    text: str,
    profile: Profile | None = None,
    seed: str | None = None,
    keep_math: bool = True,
) -> tuple[str, ScrubReport]:
    """Scrub X12 ``text`` with a profile; returns ``(scrubbed, report)``."""
    scrubber = Scrubber(profile or load_profile(), seed=seed, keep_math=keep_math)
    return scrubber.scrub(text), scrubber.report


def scrubbed_path(input_path: str | Path, output_path: str | Path | None = None) -> Path:
    """Where :func:`scrub_file` would write, so a caller can check first."""
    if output_path is not None:
        return Path(output_path)
    input_path = Path(input_path)
    return input_path.with_suffix(f".scrubbed{input_path.suffix}")


def scrub_file(
    input_path: str | Path,
    output_path: str | Path | None = None,
    profile: Profile | None = None,
    seed: str | None = None,
    keep_math: bool = True,
) -> tuple[Path, ScrubReport]:
    """Scrub a file; default output is ``INPUT.scrubbed.EXT``."""
    input_path = Path(input_path)
    text = input_path.read_text(encoding="utf-8")
    scrubbed, report = scrub_text(text, profile, seed, keep_math)
    target = scrubbed_path(input_path, output_path)
    target.write_text(scrubbed, encoding="utf-8")
    return target, report
