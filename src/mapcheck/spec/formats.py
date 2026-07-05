"""Grammar for the spec's Format column.

A Format cell is a small ``;``-separated language:

* ``%Y-%m-%d`` (any token containing ``%``) — strftime pattern the OUTPUT
  value must match (dates/times). X12 source dates are read as CCYYMMDD or
  YYMMDD; source times as HHMM(SS).
* ``implied:N`` — the source element is X12 ``N``-type with N implied
  decimal places (``2500`` means ``25.00``).
* ``places:N`` — the output's string form must show exactly N decimal
  places. Checked only when the output value is a string (flat files);
  native JSON numbers can't preserve trailing zeros.
* ``len:MIN..MAX`` — allowed output string length range.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class FormatSpecError(ValueError):
    """Raised when a Format cell cannot be parsed."""


@dataclass(frozen=True)
class FormatSpec:
    """Parsed Format column."""

    pattern: str | None = None  # strftime pattern for the output value
    implied: int | None = None  # implied decimals on the source element
    places: int | None = None  # required decimal places in output string form
    len_min: int | None = None
    len_max: int | None = None


_LEN_RE = re.compile(r"^len:(\d+)\.\.(\d+)$")
_IMPLIED_RE = re.compile(r"^implied:(\d+)$")
_PLACES_RE = re.compile(r"^places:(\d+)$")


def parse_format(text: str | None) -> FormatSpec:
    """Parse a Format cell into a :class:`FormatSpec`.

    Raises :class:`FormatSpecError` on unknown tokens.
    """
    if not text:
        return FormatSpec()
    pattern = implied = places = len_min = len_max = None
    for token in (t.strip() for t in text.split(";") if t.strip()):
        if "%" in token:
            pattern = token
        elif m := _IMPLIED_RE.match(token):
            implied = int(m.group(1))
        elif m := _PLACES_RE.match(token):
            places = int(m.group(1))
        elif m := _LEN_RE.match(token):
            len_min, len_max = int(m.group(1)), int(m.group(2))
        else:
            raise FormatSpecError(
                f"unknown format token {token!r} "
                "(expected a strftime pattern, implied:N, places:N, or len:MIN..MAX)"
            )
    return FormatSpec(
        pattern=pattern, implied=implied, places=places, len_min=len_min, len_max=len_max
    )
