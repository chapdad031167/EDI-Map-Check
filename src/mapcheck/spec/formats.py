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
* ``tol:0.01`` — decimal comparisons pass within this absolute tolerance
  (only meaningful on a decimal Data Type).
* ``shift:+5d`` / ``shift:-30d`` / ``shift:+2w`` — the expected value is the
  source date shifted by N days (``d``) or weeks (``w``); only meaningful on a
  date Data Type.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


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
    tolerance: Decimal | None = None  # absolute decimal comparison tolerance
    shift_days: int | None = None  # expected = source date + shift_days


_LEN_RE = re.compile(r"^len:(\d+)\.\.(\d+)$")
_IMPLIED_RE = re.compile(r"^implied:(\d+)$")
_PLACES_RE = re.compile(r"^places:(\d+)$")
_TOL_RE = re.compile(r"^tol:(\d+(?:\.\d+)?)$")
_SHIFT_RE = re.compile(r"^shift:([+-]?\d+)([dw])$")


def parse_format(text: str | None) -> FormatSpec:
    """Parse a Format cell into a :class:`FormatSpec`.

    Raises :class:`FormatSpecError` on unknown tokens.
    """
    if not text:
        return FormatSpec()
    pattern = implied = places = len_min = len_max = None
    tolerance = shift_days = None
    for token in (t.strip() for t in text.split(";") if t.strip()):
        if "%" in token:
            pattern = token
        elif m := _IMPLIED_RE.match(token):
            implied = int(m.group(1))
        elif m := _PLACES_RE.match(token):
            places = int(m.group(1))
        elif m := _LEN_RE.match(token):
            len_min, len_max = int(m.group(1)), int(m.group(2))
        elif m := _TOL_RE.match(token):
            try:
                tolerance = Decimal(m.group(1))
            except InvalidOperation:  # pragma: no cover - regex already guards
                raise FormatSpecError(f"invalid tolerance {token!r}") from None
        elif m := _SHIFT_RE.match(token):
            amount = int(m.group(1))
            shift_days = amount * (7 if m.group(2) == "w" else 1)
        else:
            raise FormatSpecError(
                f"unknown format token {token!r} (expected a strftime pattern, "
                "implied:N, places:N, len:MIN..MAX, tol:N, or shift:±Nd/±Nw)"
            )
    return FormatSpec(
        pattern=pattern, implied=implied, places=places, len_min=len_min,
        len_max=len_max, tolerance=tolerance, shift_days=shift_days,
    )
