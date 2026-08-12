"""Implementation-guide import (Design 014).

Parses the templated guide family (SpecBuilder-style layouts) into a
reviewable :class:`~mapcheck.guides.profile.GuideProfile`, which feeds a
partner-flavored draft spec and a partner-rules overlay for validation.
"""

from mapcheck.guides.overlay import (
    PartnerRules,
    PartnerRulesError,
    emit_partner_rules,
)
from mapcheck.guides.parser import GuideParseError, parse_guide
from mapcheck.guides.profile import (
    GuideCode,
    GuideElement,
    GuideProfile,
    GuideProfileError,
    GuideSegment,
)

__all__ = [
    "GuideCode",
    "GuideElement",
    "GuideParseError",
    "GuideProfile",
    "GuideProfileError",
    "GuideSegment",
    "PartnerRules",
    "PartnerRulesError",
    "emit_partner_rules",
    "parse_guide",
]
