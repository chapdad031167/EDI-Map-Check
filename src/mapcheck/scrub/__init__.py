"""Data scrubber (design 009): mask sensitive X12 element values.

Point ``mapcheck scrub`` at a real X12 file and get back a structurally
identical file with the values of configured element positions masked — safe
to share, still valid to validate. Structure, delimiters, segment counts,
element lengths, and referential consistency (same input value → same masked
value) are preserved; only the configured values change.
"""

from __future__ import annotations

from mapcheck.scrub.residual import Positions, Residual, classify
from mapcheck.scrub.scrubber import (
    Profile,
    ProfileError,
    Rule,
    ScrubReport,
    Scrubber,
    load_profile,
    scrub_text,
)

__all__ = [
    "Positions",
    "Profile",
    "ProfileError",
    "Residual",
    "Rule",
    "ScrubReport",
    "Scrubber",
    "classify",
    "load_profile",
    "scrub_text",
]
