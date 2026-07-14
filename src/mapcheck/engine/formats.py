"""Value normalization for data type and format checks (rule category 5).

Converts X12 source strings and output-file values into comparable Python
values per the spec's Data Type and Format columns, reporting hard
violations (:class:`NormalizationError`) and soft warnings.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from mapcheck.spec.formats import FormatSpec
from mapcheck.spec.model import DataType


class NormalizationError(Exception):
    """Internal: a value could not be normalized. Carries the reason."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


#: A real X12 numeric is well under this. Bounding the magnitude stops a
#: crafted value like ``1E999999999`` — which parses instantly but expands to
#: gigabytes when rendered with ``format(Decimal, "f")`` — from OOMing an
#: (often unattended, e.g. ``mapcheck batch``) run.
_MAX_DECIMAL_DIGITS = 4000


def _checked_decimal(text: str) -> Decimal:
    """``Decimal(text)`` with a guard on absurd magnitude/precision."""
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise NormalizationError(f"{text!r} is not a valid number") from None
    _, digits, exponent = number.as_tuple()
    if isinstance(exponent, str) or len(digits) > _MAX_DECIMAL_DIGITS or abs(
        exponent
    ) > _MAX_DECIMAL_DIGITS:
        raise NormalizationError(
            f"{text!r} has an out-of-range magnitude (guarding against expansion)"
        )
    return number


def normalize_source(value: str, data_type: DataType | None, fmt: FormatSpec) -> Any:
    """Convert an X12 element string to a comparable Python value.

    Raises :class:`NormalizationError` when the source value is invalid for the
    declared type (a source-data defect).
    """
    if data_type in (None, DataType.STRING):
        return value
    if data_type is DataType.INTEGER:
        try:
            return int(value)
        except ValueError:
            raise NormalizationError(f"{value!r} is not a valid integer") from None
    if data_type is DataType.DECIMAL:
        number = _checked_decimal(value)
        if fmt.implied is not None:
            if "." in value:
                raise NormalizationError(
                    f"{value!r} has an explicit decimal point but the spec says "
                    f"implied:{fmt.implied}"
                )
            number = number.scaleb(-fmt.implied)
        return number
    if data_type is DataType.DATE:
        return _parse_x12_date(value)
    if data_type is DataType.TIME:
        return _parse_x12_time(value)
    raise AssertionError(f"unhandled data type {data_type}")


def _parse_x12_date(value: str) -> date:
    for pattern in ("%Y%m%d", "%y%m%d"):
        if len(value) == len(datetime.now().strftime(pattern)):
            try:
                return datetime.strptime(value, pattern).date()
            except ValueError:
                break
    raise NormalizationError(f"{value!r} is not a valid X12 date (CCYYMMDD or YYMMDD)")


def _parse_x12_time(value: str) -> time:
    for pattern in ("%H%M", "%H%M%S"):
        if len(value) == len("0000") + (2 if pattern.endswith("%S") else 0):
            try:
                return datetime.strptime(value, pattern).time()
            except ValueError:
                break
    raise NormalizationError(f"{value!r} is not a valid X12 time (HHMM or HHMMSS)")


def normalize_actual(
    value: Any, data_type: DataType | None, fmt: FormatSpec, typed: bool
) -> tuple[Any, list[str]]:
    """Convert an output value to a comparable Python value.

    Returns ``(normalized, warnings)``; raises :class:`NormalizationError` when the
    value violates the declared type/format (a hard format defect).
    Warnings cover soft issues, e.g. a typed output carrying an integer as a
    JSON string.
    """
    warnings: list[str] = []
    if data_type in (None, DataType.STRING):
        if typed and not isinstance(value, str):
            warnings.append(f"expected a string, output has {type(value).__name__} {value!r}")
        return str(value), warnings

    if data_type is DataType.INTEGER:
        if isinstance(value, bool):
            raise NormalizationError(f"{value!r} is not a valid integer")
        if isinstance(value, int):
            return value, warnings
        if isinstance(value, float) and value.is_integer():
            warnings.append(f"integer expected, output has float {value!r}")
            return int(value), warnings
        if isinstance(value, str):
            if typed:
                warnings.append(f"integer expected, output has string {value!r}")
            try:
                return int(value.strip()), warnings
            except ValueError:
                raise NormalizationError(f"{value!r} is not a valid integer") from None
        raise NormalizationError(f"{value!r} is not a valid integer")

    if data_type is DataType.DECIMAL:
        text = None
        if isinstance(value, bool):
            raise NormalizationError(f"{value!r} is not a valid number")
        if isinstance(value, str):
            text = value.strip()
            if typed:
                warnings.append(f"number expected, output has string {value!r}")
        elif isinstance(value, (int, float)):
            text = repr(value)
        else:
            raise NormalizationError(f"{value!r} is not a valid number")
        number = _checked_decimal(text)
        if fmt.places is not None and isinstance(value, str):
            _, _, frac = text.partition(".")
            if len(frac) != fmt.places:
                raise NormalizationError(
                    f"{value!r} does not show the required {fmt.places} decimal places"
                )
        return number, warnings

    if data_type in (DataType.DATE, DataType.TIME):
        if not isinstance(value, str):
            raise NormalizationError(f"{value!r} is not a string-formatted {data_type.value}")
        pattern = fmt.pattern or ("%Y-%m-%d" if data_type is DataType.DATE else "%H:%M")
        try:
            parsed = datetime.strptime(value, pattern)
        except ValueError:
            raise NormalizationError(
                f"{value!r} does not match the required {data_type.value} format {pattern!r}"
            ) from None
        return (parsed.date() if data_type is DataType.DATE else parsed.time()), warnings

    raise AssertionError(f"unhandled data type {data_type}")


def normalize_x12(value: str, data_type: DataType | None, fmt: FormatSpec) -> tuple[Any, list[str]]:
    """Convert an X12 element on the **target** side (outbound specs).

    The Format column describes the X12 representation the map must
    produce: dates default to CCYYMMDD unless a pattern overrides,
    ``implied:N`` scales pointless decimals, ``places:N`` requires N shown
    decimal places. Raises :class:`NormalizationError` on violations —
    a hard format defect in the produced file.
    """
    warnings: list[str] = []
    if data_type in (None, DataType.STRING):
        return value, warnings
    if data_type is DataType.INTEGER:
        try:
            return int(value), warnings
        except ValueError:
            raise NormalizationError(f"{value!r} is not a valid integer") from None
    if data_type is DataType.DECIMAL:
        number = _checked_decimal(value)
        if fmt.implied is not None:
            if "." in value:
                raise NormalizationError(
                    f"{value!r} has an explicit decimal point but the spec says "
                    f"implied:{fmt.implied}"
                )
            number = number.scaleb(-fmt.implied)
        elif fmt.places is not None:
            _, _, frac = value.partition(".")
            if len(frac) != fmt.places:
                raise NormalizationError(
                    f"{value!r} does not show the required {fmt.places} decimal places"
                )
        return number, warnings
    if data_type in (DataType.DATE, DataType.TIME):
        pattern = fmt.pattern or ("%Y%m%d" if data_type is DataType.DATE else "%H%M")
        try:
            parsed = datetime.strptime(value, pattern)
        except ValueError:
            raise NormalizationError(
                f"{value!r} does not match the required {data_type.value} format {pattern!r}"
            ) from None
        return (parsed.date() if data_type is DataType.DATE else parsed.time()), warnings
    raise AssertionError(f"unhandled data type {data_type}")


def check_length(value: Any, fmt: FormatSpec) -> str | None:
    """Return a violation message when the string form breaks len:MIN..MAX."""
    if fmt.len_min is None:
        return None
    text = str(value)
    if not (fmt.len_min <= len(text) <= fmt.len_max):  # type: ignore[operator]
        return (
            f"length {len(text)} outside the allowed range "
            f"{fmt.len_min}..{fmt.len_max} for {text!r}"
        )
    return None


def display(value: Any) -> str:
    """Human-friendly rendering of a normalized value for reports."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat("minutes")
    return str(value)
