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
    RequiredPairDef,
    RequiredSegmentDef,
    TransactionDefinition,
)

#: Segments whose qualifier lives in element 01 by X12 convention.
_QUALIFIED_SEGMENTS = {"REF", "DTM", "N1", "N9", "SAC", "AMT", "PER", "FOB"}

#: Segments carrying positional qualifier/value pairs, with the pair
#: range as (first qualifier slot, last qualifier slot, step) — PO106/07
#: through PO124/25 for the 850, same shape for the 810's IT1.
_PAIRED_SEGMENTS = {"PO1": (6, 24, 2), "IT1": (6, 24, 2)}


class PartnerRulesError(Exception):
    """A partner-rules overlay failed validation; the message names the
    file and entry index of every problem."""


def _load_codes(
    node: dict, where: str, errors: list
) -> tuple[str | None, tuple[str, ...]]:
    """Parse an overlay entry's ``qualifier`` / ``qualifiers`` (Design 018).

    Mutually exclusive; ``qualifiers`` must be a non-empty list. Problems
    append to ``errors`` and the offending field returns empty.
    """
    qualifier = str(node["qualifier"]) if node.get("qualifier") is not None else None
    raw = node.get("qualifiers")
    qualifiers: tuple[str, ...] = ()
    if raw is not None:
        if not isinstance(raw, list) or not raw or not all(
            isinstance(c, (str, int)) for c in raw
        ):
            errors.append(f"{where}: 'qualifiers' must be a non-empty list of codes")
        else:
            qualifiers = tuple(str(c) for c in raw)
    if qualifier is not None and qualifiers:
        errors.append(f"{where}: set 'qualifier' or 'qualifiers', not both")
    return qualifier, qualifiers


@dataclass
class PartnerRules:
    """A partner's presence rules, ready to apply to a definition."""

    partner: str
    transaction: str
    source_guide: str = ""
    required_segments: list[RequiredSegmentDef] = field(default_factory=list)
    required_elements: list[RequiredElementDef] = field(default_factory=list)
    required_pairs: list[RequiredPairDef] = field(default_factory=list)
    #: Guide rules the overlay schema cannot express — surfaced, not dropped.
    review: list[str] = field(default_factory=list)

    def apply(self, definition: TransactionDefinition) -> TransactionDefinition:
        """Return the definition with this overlay's rules appended.

        Entries duplicating a base rule (same segment/element) are skipped —
        the base definition already enforces them; an *unconditional* base
        rule also covers a partner rule scoped to one qualifier. A
        *conditional* base rule (``when_present``) does not suppress a
        partner rule: the partner's requirement is unconditional, so both
        run.
        """
        if self.transaction != definition.set_code:
            raise PartnerRulesError(
                f"partner rules are for transaction {self.transaction} but the "
                f"file is a {definition.set_code}"
            )
        base_segments = {
            (req.segment, req.match_codes(), req.loop)
            for req in definition.required_segments
        }
        base_elements = {
            (req.segment, req.element)
            for req in definition.required_elements
            if req.when_present is None
        }
        base_pairs = {(req.segment, req.code) for req in definition.required_pairs}
        add_segments = tuple(
            req
            for req in self.required_segments
            if (req.segment, req.match_codes(), req.loop) not in base_segments
        )
        add_elements = tuple(
            req
            for req in self.required_elements
            if (req.segment, req.element) not in base_elements
        )
        add_pairs = tuple(
            req
            for req in self.required_pairs
            if (req.segment, req.code) not in base_pairs
        )
        return replace(
            definition,
            required_segments=(*definition.required_segments, *add_segments),
            required_elements=(*definition.required_elements, *add_elements),
            required_pairs=(*definition.required_pairs, *add_pairs),
        )

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        def codes_into(entry: dict, req) -> None:
            if req.qualifiers:
                entry["qualifiers"] = list(req.qualifiers)
            elif req.qualifier is not None:
                entry["qualifier"] = req.qualifier
            if (req.qualifiers or req.qualifier is not None) and req.qualifier_element != 1:
                entry["qualifier_element"] = req.qualifier_element
            if req.loop:
                entry["loop"] = req.loop

        def seg_entry(req: RequiredSegmentDef) -> dict:
            entry: dict = {"segment": req.segment}
            codes_into(entry, req)
            if req.name:
                entry["name"] = req.name
            return entry

        def el_entry(req: RequiredElementDef) -> dict:
            entry: dict = {"segment": req.segment, "element": req.element}
            codes_into(entry, req)
            if req.name:
                entry["name"] = req.name
            if req.when_present is not None:
                entry["when_present"] = req.when_present
                if req.when_name:
                    entry["when_name"] = req.when_name
            return entry

        def pair_entry(req: RequiredPairDef) -> dict:
            entry: dict = {"segment": req.segment, "code": req.code}
            if (req.first_element, req.last_element, req.step) != (6, 24, 2):
                entry["first_element"] = req.first_element
                entry["last_element"] = req.last_element
                entry["step"] = req.step
            if req.name:
                entry["name"] = req.name
            return entry

        return {
            "partner": self.partner,
            "transaction": self.transaction,
            "source_guide": self.source_guide,
            "required_segments": [seg_entry(r) for r in self.required_segments],
            "required_elements": [el_entry(r) for r in self.required_elements],
            "required_pairs": [pair_entry(r) for r in self.required_pairs],
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
            qualifier, qualifiers = _load_codes(node, where, errors)
            segments.append(
                RequiredSegmentDef(
                    segment=str(node["segment"]).upper(),
                    qualifier=qualifier,
                    qualifiers=qualifiers,
                    qualifier_element=qualifier_element,
                    loop=str(node.get("loop", "") or ""),
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
            qualifier_element = node.get("qualifier_element", 1)
            if not isinstance(qualifier_element, int) or qualifier_element < 1:
                errors.append(f"{where}: 'qualifier_element' must be a 1-based position")
                continue
            qualifier, qualifiers = _load_codes(node, where, errors)
            elements.append(
                RequiredElementDef(
                    segment=str(node["segment"]).upper(),
                    element=node["element"],
                    name=str(node.get("name", "") or ""),
                    when_present=when_present,
                    when_name=str(node.get("when_name", "") or ""),
                    qualifier=qualifier,
                    qualifiers=qualifiers,
                    qualifier_element=qualifier_element,
                    loop=str(node.get("loop", "") or ""),
                    origin=partner,
                )
            )

        pairs: list[RequiredPairDef] = []
        for index, node in enumerate(data.get("required_pairs", []) or []):
            where = f"{path}: required_pairs[{index}]"
            if not isinstance(node, dict) or not node.get("segment") or not node.get("code"):
                errors.append(f"{where}: expected a mapping with 'segment' and 'code'")
                continue
            first = node.get("first_element", 6)
            last = node.get("last_element", 24)
            step = node.get("step", 2)
            if (
                not all(isinstance(v, int) for v in (first, last, step))
                or first < 1
                or step < 1
                or last < first
            ):
                errors.append(
                    f"{where}: pair range needs 1-based first_element, a "
                    "last_element at or after it, and a positive step"
                )
                continue
            pairs.append(
                RequiredPairDef(
                    segment=str(node["segment"]).upper(),
                    code=str(node["code"]),
                    first_element=first,
                    last_element=last,
                    step=step,
                    name=str(node.get("name", "") or ""),
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
            required_pairs=pairs,
            review=[str(r) for r in (data.get("review") or [])],
        )


def _seg_rule(seg_id, codes, loop, name, partner) -> RequiredSegmentDef:
    kw: dict = {}
    if len(codes) == 1:
        kw["qualifier"] = codes[0]
    elif len(codes) > 1:
        kw["qualifiers"] = tuple(codes)
    return RequiredSegmentDef(
        segment=seg_id, loop=loop, name=name, origin=partner, **kw
    )


def _el_rule(seg_id, position, codes, loop, name, partner) -> RequiredElementDef:
    kw: dict = {}
    if len(codes) == 1:
        kw["qualifier"] = codes[0]
    elif len(codes) > 1:
        kw["qualifiers"] = tuple(codes)
    return RequiredElementDef(
        segment=seg_id, element=position, loop=loop, name=name,
        origin=partner, **kw
    )


def emit_partner_rules(profile: GuideProfile) -> PartnerRules:
    """Derive a partner-rules overlay from a guide profile.

    Segment presence: every ``must_use`` segment. Where the segment is a
    qualified family (REF, DTM, N1, ...) its element 01's code(s) qualify
    the requirement — one code as ``qualifier``, several as a
    ``qualifiers`` set (Design 018) — and the block's other ``must_use``
    elements become qualifier-scoped element rules ("REF02 required in
    REF*IA occurrences" — Design 015). A ``must_use`` segment that sits in
    a loop it does not trigger is scoped to that loop (``loop``), so "PER
    within the N1 loop" ignores a heading PER.

    Paired segments (PO1, IT1): a ``must_use`` qualifier slot pinned to a
    single code becomes a pair rule ("every PO1 must carry a UP pair"),
    consuming its companion value slot; a multi-code slot stays positional
    with a review note.

    Element presence: remaining ``must_use`` elements of unqualified
    required segments. Entries the base definition already enforces are
    dropped at apply time, not here.
    """
    rules = PartnerRules(
        partner=profile.partner,
        transaction=profile.transaction,
        source_guide=profile.source,
    )
    # Real guides render one segment block per loop occurrence (three N1
    # blocks for ship-to / bill-to / ship-from). Distinct code sets / loop
    # scopes emit distinct rules; identical keys emit once.
    seen_segments: set[tuple] = set()
    seen_elements: set[tuple] = set()
    seen_pairs: set[tuple[str, str]] = set()
    for segment in profile.segments:
        if segment.usage != "must_use":
            continue
        # A segment sitting inside a loop it does not trigger is a member
        # (X12 names a loop after its trigger); scope its rules to the loop.
        loop_scope = (
            segment.loop if segment.loop and segment.id != segment.loop else ""
        )
        first = segment.element(f"{segment.id}01")
        codes = tuple(c.code for c in first.codes) if first is not None else ()
        is_family = segment.id in _QUALIFIED_SEGMENTS and len(codes) >= 1
        if is_family:
            seg_key = (segment.id, codes, loop_scope)
            if seg_key not in seen_segments:
                seen_segments.add(seg_key)
                code_name = first.codes[0].name if len(codes) == 1 else ""
                rules.required_segments.append(
                    _seg_rule(
                        segment.id, codes, loop_scope,
                        code_name or segment.name, profile.partner,
                    )
                )
            for el in segment.elements:
                if el.usage != "must_use" or el.ref.endswith("01"):
                    continue
                position = int(el.ref[len(segment.id):])
                el_key = (segment.id, position, codes, loop_scope)
                if el_key in seen_elements:
                    continue
                seen_elements.add(el_key)
                rules.required_elements.append(
                    _el_rule(
                        segment.id, position, codes, loop_scope,
                        el.name, profile.partner,
                    )
                )
            continue
        seg_key = (segment.id, (), loop_scope)
        if seg_key not in seen_segments:
            seen_segments.add(seg_key)
            rules.required_segments.append(
                _seg_rule(segment.id, (), loop_scope, segment.name, profile.partner)
            )
        # Pair rules first: a pinned qualifier slot and its value slot are
        # enforced as "carry this pair", not as two fixed positions.
        consumed: set[int] = set()
        pair_range = _PAIRED_SEGMENTS.get(segment.id)
        if pair_range is not None:
            first_slot, last_slot, step = pair_range
            slots = set(range(first_slot, last_slot + 1, step))
            for el in segment.elements:
                if el.usage != "must_use":
                    continue
                position = int(el.ref[len(segment.id):])
                if position not in slots or not el.codes:
                    continue
                slot_codes = [c.code for c in el.codes]
                if len(slot_codes) > 1:
                    rules.review.append(
                        f"{el.ref}: multiple codes ({', '.join(slot_codes)}) — "
                        "kept as a positional requirement; a pair rule needs "
                        "a single code"
                    )
                    continue
                consumed.add(position)
                consumed.add(position + 1)
                if (segment.id, slot_codes[0]) in seen_pairs:
                    continue
                seen_pairs.add((segment.id, slot_codes[0]))
                rules.required_pairs.append(
                    RequiredPairDef(
                        segment=segment.id,
                        code=slot_codes[0],
                        first_element=first_slot,
                        last_element=last_slot,
                        step=step,
                        name=el.codes[0].name,
                        origin=profile.partner,
                    )
                )
        for el in segment.elements:
            if el.usage != "must_use":
                continue
            position = int(el.ref[len(segment.id):])
            if position in consumed:
                continue
            el_key = (segment.id, position, (), loop_scope)
            if el_key in seen_elements:
                continue
            seen_elements.add(el_key)
            rules.required_elements.append(
                _el_rule(segment.id, position, (), loop_scope, el.name, profile.partner)
            )
    return rules
