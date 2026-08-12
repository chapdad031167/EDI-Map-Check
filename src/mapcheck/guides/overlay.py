"""Partner-rules overlays: guide requiredness applied to validation.

A :class:`PartnerRules` overlay carries the partner's presence rules —
required segments (qualified where the guide is unambiguous) and required
elements — in exactly the transaction-definition schema, so
``validate --partner-rules`` can append them to the definition for the
run and the Phase 2 required-elements engine enforces them unchanged.

Emission is derived, flag-never-guess: a segment whose qualifier cannot
be pinned to a single code gets an unqualified requirement plus a review
note; rules the schema cannot express are named in ``review``, never
silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from mapcheck.guides.profile import GuideProfile
from mapcheck.transactions.schema import (
    RequiredElementDef,
    RequiredSegmentDef,
    TransactionDefinition,
)

#: Segments whose qualifier lives in element 01 by X12 convention.
_QUALIFIED_SEGMENTS = {"REF", "DTM", "N1", "N9", "SAC", "AMT", "PER", "FOB"}


class PartnerRulesError(Exception):
    """A partner-rules overlay failed validation; the message names the
    file and entry index of every problem."""


@dataclass
class PartnerRules:
    """A partner's presence rules, ready to apply to a definition."""

    partner: str
    transaction: str
    source_guide: str = ""
    required_segments: list[RequiredSegmentDef] = field(default_factory=list)
    required_elements: list[RequiredElementDef] = field(default_factory=list)
    #: Guide rules the overlay schema cannot express — surfaced, not dropped.
    review: list[str] = field(default_factory=list)

    def apply(self, definition: TransactionDefinition) -> TransactionDefinition:
        """Return the definition with this overlay's rules appended.

        Entries duplicating a base rule (same segment/element) are skipped —
        the base definition already enforces them. A *conditional* base rule
        (``when_present``) does not suppress a partner rule: the partner's
        requirement is unconditional, so both run.
        """
        if self.transaction != definition.set_code:
            raise PartnerRulesError(
                f"partner rules are for transaction {self.transaction} but the "
                f"file is a {definition.set_code}"
            )
        base_segments = {
            (req.segment, req.qualifier) for req in definition.required_segments
        }
        base_elements = {
            (req.segment, req.element)
            for req in definition.required_elements
            if req.when_present is None
        }
        add_segments = tuple(
            req
            for req in self.required_segments
            if (req.segment, req.qualifier) not in base_segments
        )
        add_elements = tuple(
            req
            for req in self.required_elements
            if (req.segment, req.element) not in base_elements
        )
        return replace(
            definition,
            required_segments=(*definition.required_segments, *add_segments),
            required_elements=(*definition.required_elements, *add_elements),
        )

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        def seg_entry(req: RequiredSegmentDef) -> dict:
            entry: dict = {"segment": req.segment}
            if req.qualifier is not None:
                entry["qualifier"] = req.qualifier
                if req.qualifier_element != 1:
                    entry["qualifier_element"] = req.qualifier_element
            if req.name:
                entry["name"] = req.name
            return entry

        def el_entry(req: RequiredElementDef) -> dict:
            entry: dict = {"segment": req.segment, "element": req.element}
            if req.name:
                entry["name"] = req.name
            if req.when_present is not None:
                entry["when_present"] = req.when_present
                if req.when_name:
                    entry["when_name"] = req.when_name
            return entry

        return {
            "partner": self.partner,
            "transaction": self.transaction,
            "source_guide": self.source_guide,
            "required_segments": [seg_entry(r) for r in self.required_segments],
            "required_elements": [el_entry(r) for r in self.required_elements],
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
    def load(cls, path: str | Path) -> "PartnerRules":
        path = Path(path)
        if not path.exists():
            raise PartnerRulesError(f"partner rules file not found: {path}")
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise PartnerRulesError(f"{path}: invalid YAML: {exc}") from exc
        if not isinstance(data, dict) or not data.get("transaction"):
            raise PartnerRulesError(
                f"{path}: not a partner-rules overlay (missing 'transaction')"
            )
        errors: list[str] = []
        partner = str(data.get("partner", "") or "")

        segments: list[RequiredSegmentDef] = []
        for index, node in enumerate(data.get("required_segments", []) or []):
            where = f"{path}: required_segments[{index}]"
            if not isinstance(node, dict) or not node.get("segment"):
                errors.append(f"{where}: expected a mapping with a 'segment'")
                continue
            qualifier_element = node.get("qualifier_element", 1)
            if not isinstance(qualifier_element, int) or qualifier_element < 1:
                errors.append(f"{where}: 'qualifier_element' must be a 1-based position")
                continue
            segments.append(
                RequiredSegmentDef(
                    segment=str(node["segment"]).upper(),
                    qualifier=(
                        str(node["qualifier"]) if node.get("qualifier") is not None else None
                    ),
                    qualifier_element=qualifier_element,
                    name=str(node.get("name", "") or ""),
                    origin=partner,
                )
            )

        elements: list[RequiredElementDef] = []
        for index, node in enumerate(data.get("required_elements", []) or []):
            where = f"{path}: required_elements[{index}]"
            if (
                not isinstance(node, dict)
                or not node.get("segment")
                or not isinstance(node.get("element"), int)
                or node["element"] < 1
            ):
                errors.append(
                    f"{where}: expected a mapping with 'segment' and a 1-based 'element'"
                )
                continue
            when_present = node.get("when_present")
            if when_present is not None and (
                not isinstance(when_present, int) or when_present < 1
            ):
                errors.append(f"{where}: 'when_present' must be a 1-based position")
                continue
            elements.append(
                RequiredElementDef(
                    segment=str(node["segment"]).upper(),
                    element=node["element"],
                    name=str(node.get("name", "") or ""),
                    when_present=when_present,
                    when_name=str(node.get("when_name", "") or ""),
                    origin=partner,
                )
            )

        if errors:
            raise PartnerRulesError(
                f"{len(errors)} problem(s) in partner rules {path}:\n  - "
                + "\n  - ".join(errors)
            )
        return cls(
            partner=partner,
            transaction=str(data["transaction"]),
            source_guide=str(data.get("source_guide", "") or ""),
            required_segments=segments,
            required_elements=elements,
            review=[str(r) for r in (data.get("review") or [])],
        )


def emit_partner_rules(profile: GuideProfile) -> PartnerRules:
    """Derive a partner-rules overlay from a guide profile.

    Segment presence: every ``must_use`` segment. Where the segment is a
    qualified family (REF, DTM, N1, ...) and its element 01 carries exactly
    one code, the requirement is qualified by that code; multiple codes fall
    back to an unqualified requirement plus a review note.

    Element presence: ``must_use`` elements of unqualified required
    segments (a qualified segment's element rules cannot yet be scoped to
    its qualifier — named in ``review``). Entries the base definition
    already enforces are dropped at apply time, not here.
    """
    rules = PartnerRules(
        partner=profile.partner,
        transaction=profile.transaction,
        source_guide=profile.source,
    )
    # Real guides render one segment block per loop occurrence (three N1
    # blocks for ship-to / bill-to / ship-from). Distinct qualifiers emit
    # distinct rules; identical (segment, qualifier) pairs emit once.
    seen_segments: set[tuple[str, str | None]] = set()
    seen_elements: set[tuple[str, int]] = set()
    for segment in profile.segments:
        if segment.usage != "must_use":
            continue
        first = segment.element(f"{segment.id}01")
        codes = [c.code for c in first.codes] if first is not None else []
        qualified = segment.id in _QUALIFIED_SEGMENTS and len(codes) == 1
        if qualified:
            if (segment.id, codes[0]) in seen_segments:
                continue
            seen_segments.add((segment.id, codes[0]))
            code_name = first.codes[0].name if first is not None else ""
            rules.required_segments.append(
                RequiredSegmentDef(
                    segment=segment.id,
                    qualifier=codes[0],
                    qualifier_element=1,
                    name=code_name or segment.name,
                    origin=profile.partner,
                )
            )
            must_elements = [
                el for el in segment.elements
                if el.usage == "must_use" and not el.ref.endswith("01")
            ]
            if must_elements:
                refs = ", ".join(el.ref for el in must_elements)
                rules.review.append(
                    f"{segment.id}*{codes[0]}: element requirements ({refs}) "
                    "cannot yet be scoped to a qualifier — enforced only as "
                    "segment presence"
                )
            continue
        if segment.id in _QUALIFIED_SEGMENTS and len(codes) > 1:
            rules.review.append(
                f"{segment.id}: multiple qualifier codes ({', '.join(codes)}) — "
                "emitted unqualified; qualify by hand if one is the requirement"
            )
        if (segment.id, None) not in seen_segments:
            seen_segments.add((segment.id, None))
            rules.required_segments.append(
                RequiredSegmentDef(
                    segment=segment.id, name=segment.name, origin=profile.partner
                )
            )
        for el in segment.elements:
            if el.usage != "must_use":
                continue
            position = int(el.ref[len(segment.id):])
            if (segment.id, position) in seen_elements:
                continue
            seen_elements.add((segment.id, position))
            rules.required_elements.append(
                RequiredElementDef(
                    segment=segment.id,
                    element=position,
                    name=el.name,
                    origin=profile.partner,
                )
            )
    return rules
