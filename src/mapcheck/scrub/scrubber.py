"""X12 data scrubber: profile model, deterministic masking, round-trip.

The scrubber works on the raw file text so nothing about structure is
inferred or reconstructed — delimiters are read from the ISA, segments are
split on the segment terminator, and only the values of configured element
positions change. Masking is deterministic per run (same input value → same
output, so pairing keys survive) and length- and character-class-preserving.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml

#: Strategies that pseudonymize (character-class + length preserving) vs the
#: fixed-filler redaction. Pseudonymizing strategies are aliases that document
#: intent in a profile; they share one primitive so a value masks consistently.
_PSEUDO = {"name", "text", "id"}
_STRATEGIES = _PSEUDO | {"redact"}

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
    element is one of ``when_in``)."""

    segment: str
    element: int
    strategy: str
    when_element: int | None = None
    when_in: tuple[str, ...] = ()

    def applies(self, elements: list[str]) -> bool:
        if self.when_element is None:
            return True
        idx = self.when_element - 1
        return 0 <= idx < len(elements) and elements[idx] in self.when_in


@dataclass
class Profile:
    name: str
    rules: list[Rule]
    envelope: bool = True

    def rules_for(self, seg_id: str) -> list[Rule]:
        return [r for r in self.rules if r.segment == seg_id]


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
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise ProfileError(f"{label}: profile must be a mapping with a 'rules' list")

    rules: list[Rule] = []
    for i, raw in enumerate(data["rules"], start=1):
        if not isinstance(raw, dict):
            raise ProfileError(f"{label}: rule #{i} must be a mapping")
        seg = raw.get("segment")
        element = raw.get("element")
        strategy = raw.get("strategy", "id")
        if not seg or not isinstance(element, int) or element < 1:
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
        rules.append(Rule(str(seg), element, strategy, when_element, when_in))

    envelope = bool(data.get("envelope", True))
    return Profile(name=str(data.get("name", label)), rules=rules, envelope=envelope)


@dataclass
class ScrubReport:
    """A count of how many values were masked, per segment/element."""

    masked: dict[tuple[str, int], int] = field(default_factory=dict)
    unique_values: int = 0

    @property
    def total(self) -> int:
        return sum(self.masked.values())

    def render(self) -> str:
        if not self.masked:
            return "No values matched the profile — nothing masked."
        lines = [f"Masked {self.total} value(s) ({self.unique_values} distinct):"]
        for (seg, ele), n in sorted(self.masked.items()):
            lines.append(f"  {seg}{ele:02d}: {n}")
        return "\n".join(lines)


class Scrubber:
    """Applies a profile to X12 text with a per-instance masking cache."""

    def __init__(self, profile: Profile, seed: str | None = None) -> None:
        self.profile = profile
        self.salt = seed if seed is not None else secrets.token_hex(8)
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

    def scrub(self, text: str) -> str:
        element_sep, segment_sep = _delimiters(text)
        by_seg = self._rules_with_envelope()

        parts = text.split(segment_sep)
        for i, chunk in enumerate(parts):
            lead = chunk[: len(chunk) - len(chunk.lstrip("\r\n \t"))]
            body = chunk[len(lead):]
            if not body:
                continue
            fields = body.split(element_sep)
            seg_id = fields[0]
            rules = by_seg.get(seg_id)
            if not rules:
                continue
            elements = fields[1:]
            changed = False
            for rule in rules:
                idx = rule.element - 1
                if idx < 0 or idx >= len(elements):
                    continue
                if not rule.applies(elements):
                    continue
                original = elements[idx]
                masked = self._mask_value(original, rule.strategy)
                if masked != original:
                    elements[idx] = masked
                    key = (seg_id, rule.element)
                    self.report.masked[key] = self.report.masked.get(key, 0) + 1
                    changed = True
            if changed:
                parts[i] = lead + element_sep.join([seg_id, *elements])
        return segment_sep.join(parts)


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
    text: str, profile: Profile | None = None, seed: str | None = None
) -> tuple[str, ScrubReport]:
    """Scrub X12 ``text`` with a profile; returns ``(scrubbed, report)``."""
    scrubber = Scrubber(profile or load_profile(), seed=seed)
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
) -> tuple[Path, ScrubReport]:
    """Scrub a file; default output is ``INPUT.scrubbed.EXT``."""
    input_path = Path(input_path)
    text = input_path.read_text(encoding="utf-8")
    scrubbed, report = scrub_text(text, profile, seed)
    target = scrubbed_path(input_path, output_path)
    target.write_text(scrubbed, encoding="utf-8")
    return target, report
