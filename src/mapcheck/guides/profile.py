"""The GuideProfile: what a parsed implementation guide asserts.

An intermediate, inspectable artifact in the crosswalk ethos — YAML,
diffable, deterministic — and the single input to everything downstream
(partner-flavored drafts, partner-rules overlays). Facts the parser was
not certain of live in ``review`` with page context, never in the data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

#: Normalized usage values, from the guide family's wording.
USAGES = ("must_use", "used", "not_used")


class GuideProfileError(Exception):
    """A profile file failed validation; the message names every problem."""


@dataclass(frozen=True)
class GuideCode:
    """One entry of a partner's code subset for an element."""

    code: str
    name: str = ""


@dataclass(frozen=True)
class GuideElement:
    """One element row of a segment's Element Summary."""

    ref: str  # e.g. "BEG01"
    name: str = ""
    req: str = ""  # M / O / C / X, as printed
    type: str = ""  # ID / AN / DT / N0 ...
    min: int | None = None
    max: int | None = None
    usage: str = ""  # must_use / used / not_used
    codes: tuple[GuideCode, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class GuideSegment:
    """One segment block of the guide."""

    id: str  # e.g. "BEG"
    name: str = ""
    pos: str = ""
    max_use: str = ""
    loop: str = ""
    usage: str = ""  # must_use / used / not_used
    notes: tuple[str, ...] = ()
    elements: tuple[GuideElement, ...] = ()

    def element(self, ref: str) -> GuideElement | None:
        for el in self.elements:
            if el.ref == ref:
                return el
        return None


@dataclass
class GuideProfile:
    """Everything one guide parse produced."""

    transaction: str
    partner: str
    source: str = ""
    version: str = ""
    segments: list[GuideSegment] = field(default_factory=list)
    #: Facts the parser saw but would not swear to, with page context.
    review: list[str] = field(default_factory=list)
    #: parse coverage = confident facts / detected facts
    facts_confident: int = 0
    facts_detected: int = 0

    @property
    def parse_coverage(self) -> float:
        if self.facts_detected == 0:
            return 0.0
        return self.facts_confident / self.facts_detected

    def segment(self, seg_id: str) -> GuideSegment | None:
        for seg in self.segments:
            if seg.id == seg_id:
                return seg
        return None

    def element_usage(self) -> dict[tuple[str, int], GuideElement]:
        """(segment id, element position) -> element, for draft annotation."""
        table: dict[tuple[str, int], GuideElement] = {}
        for seg in self.segments:
            for el in seg.elements:
                position = int(el.ref[len(seg.id):] or 0)
                table[(seg.id, position)] = el
        return table

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "transaction": self.transaction,
            "partner": self.partner,
            "source": self.source,
            "version": self.version,
            "parse_coverage": round(self.parse_coverage, 4),
            "facts_confident": self.facts_confident,
            "facts_detected": self.facts_detected,
            "segments": [
                {
                    "id": seg.id,
                    "name": seg.name,
                    "pos": seg.pos,
                    "max_use": seg.max_use,
                    "loop": seg.loop,
                    "usage": seg.usage,
                    **({"notes": list(seg.notes)} if seg.notes else {}),
                    "elements": [
                        {
                            "ref": el.ref,
                            "name": el.name,
                            "req": el.req,
                            "type": el.type,
                            "min": el.min,
                            "max": el.max,
                            "usage": el.usage,
                            **(
                                {
                                    "codes": [
                                        {"code": c.code, "name": c.name}
                                        for c in el.codes
                                    ]
                                }
                                if el.codes
                                else {}
                            ),
                            **({"notes": list(el.notes)} if el.notes else {}),
                        }
                        for el in seg.elements
                    ],
                }
                for seg in self.segments
            ],
            "review": list(self.review),
        }

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(
            yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: str | Path) -> "GuideProfile":
        path = Path(path)
        if not path.exists():
            raise GuideProfileError(f"guide profile not found: {path}")
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise GuideProfileError(f"{path}: invalid YAML: {exc}") from exc
        if not isinstance(data, dict) or not data.get("transaction"):
            raise GuideProfileError(
                f"{path}: not a guide profile (missing 'transaction')"
            )
        errors: list[str] = []
        segments: list[GuideSegment] = []
        for s_index, seg_node in enumerate(data.get("segments", []) or []):
            where = f"{path}: segments[{s_index}]"
            if not isinstance(seg_node, dict) or not seg_node.get("id"):
                errors.append(f"{where}: expected a mapping with an 'id'")
                continue
            usage = str(seg_node.get("usage", "") or "")
            if usage and usage not in USAGES:
                errors.append(f"{where}: unknown usage {usage!r}")
                continue
            elements: list[GuideElement] = []
            for e_index, el_node in enumerate(seg_node.get("elements", []) or []):
                el_where = f"{where}.elements[{e_index}]"
                if not isinstance(el_node, dict) or not el_node.get("ref"):
                    errors.append(f"{el_where}: expected a mapping with a 'ref'")
                    continue
                el_usage = str(el_node.get("usage", "") or "")
                if el_usage and el_usage not in USAGES:
                    errors.append(f"{el_where}: unknown usage {el_usage!r}")
                    continue
                elements.append(
                    GuideElement(
                        ref=str(el_node["ref"]),
                        name=str(el_node.get("name", "") or ""),
                        req=str(el_node.get("req", "") or ""),
                        type=str(el_node.get("type", "") or ""),
                        min=el_node.get("min"),
                        max=el_node.get("max"),
                        usage=el_usage,
                        codes=tuple(
                            GuideCode(code=str(c["code"]), name=str(c.get("name", "") or ""))
                            for c in (el_node.get("codes") or [])
                            if isinstance(c, dict) and c.get("code") is not None
                        ),
                        notes=tuple(str(n) for n in (el_node.get("notes") or [])),
                    )
                )
            segments.append(
                GuideSegment(
                    id=str(seg_node["id"]).upper(),
                    name=str(seg_node.get("name", "") or ""),
                    pos=str(seg_node.get("pos", "") or ""),
                    max_use=str(seg_node.get("max_use", "") or ""),
                    loop=str(seg_node.get("loop", "") or ""),
                    usage=usage,
                    notes=tuple(str(n) for n in (seg_node.get("notes") or [])),
                    elements=tuple(elements),
                )
            )
        if errors:
            raise GuideProfileError(
                f"{len(errors)} problem(s) in guide profile {path}:\n  - "
                + "\n  - ".join(errors)
            )
        profile = cls(
            transaction=str(data["transaction"]),
            partner=str(data.get("partner", "") or ""),
            source=str(data.get("source", "") or ""),
            version=str(data.get("version", "") or ""),
            segments=segments,
            review=[str(r) for r in (data.get("review") or [])],
        )
        # counts are parse-time facts; a loaded profile keeps its coverage
        profile.facts_detected = int(data.get("facts_detected", 0) or 0)
        profile.facts_confident = int(data.get("facts_confident", 0) or 0)
        return profile
