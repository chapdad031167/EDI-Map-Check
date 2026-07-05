"""Tests for the Format grammar and value normalization."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from mapcheck.engine.formats import (
    NormalizationError,
    check_length,
    display,
    normalize_actual,
    normalize_source,
)
from mapcheck.spec.formats import FormatSpec, FormatSpecError, parse_format
from mapcheck.spec.model import DataType


class TestParseFormat:
    def test_empty(self):
        assert parse_format(None) == FormatSpec()
        assert parse_format("") == FormatSpec()

    def test_combined(self):
        fmt = parse_format("implied:2;places:2")
        assert (fmt.implied, fmt.places) == (2, 2)

    def test_pattern_and_length(self):
        assert parse_format("%Y-%m-%d").pattern == "%Y-%m-%d"
        fmt = parse_format("len:1..30")
        assert (fmt.len_min, fmt.len_max) == (1, 30)

    @pytest.mark.parametrize("bad", ["implied:x", "len:5", "wat", "places:"])
    def test_unknown_tokens(self, bad):
        with pytest.raises(FormatSpecError):
            parse_format(bad)


class TestNormalizeSource:
    def test_date_ccyymmdd(self):
        assert normalize_source("20260615", DataType.DATE, FormatSpec()) == date(2026, 6, 15)

    def test_bad_date_raises(self):
        with pytest.raises(NormalizationError, match="not a valid X12 date"):
            normalize_source("20261301", DataType.DATE, FormatSpec())

    def test_implied_decimal(self):
        fmt = parse_format("implied:2")
        assert normalize_source("2500", DataType.DECIMAL, fmt) == Decimal("25.00")

    def test_implied_decimal_rejects_explicit_point(self):
        fmt = parse_format("implied:2")
        with pytest.raises(NormalizationError, match="explicit decimal point"):
            normalize_source("25.00", DataType.DECIMAL, fmt)

    def test_explicit_decimal(self):
        assert normalize_source("8.5", DataType.DECIMAL, FormatSpec()) == Decimal("8.5")

    def test_integer(self):
        assert normalize_source("12", DataType.INTEGER, FormatSpec()) == 12
        with pytest.raises(NormalizationError):
            normalize_source("12X", DataType.INTEGER, FormatSpec())

    def test_string_passthrough(self):
        assert normalize_source("ABC", DataType.STRING, FormatSpec()) == "ABC"
        assert normalize_source("ABC", None, FormatSpec()) == "ABC"


class TestNormalizeActual:
    def test_date_pattern(self):
        fmt = parse_format("%Y-%m-%d")
        value, warnings = normalize_actual("2026-06-15", DataType.DATE, fmt, typed=True)
        assert value == date(2026, 6, 15) and warnings == []

    def test_wrong_date_format_raises(self):
        fmt = parse_format("%Y-%m-%d")
        with pytest.raises(NormalizationError, match="does not match"):
            normalize_actual("06/15/2026", DataType.DATE, fmt, typed=True)

    def test_decimal_equivalence_across_forms(self):
        value, _ = normalize_actual(8.5, DataType.DECIMAL, FormatSpec(), typed=True)
        assert value == Decimal("8.5")
        value, _ = normalize_actual("8.50", DataType.DECIMAL, FormatSpec(), typed=False)
        assert value == Decimal("8.5")

    def test_places_enforced_on_strings_only(self):
        fmt = parse_format("places:2")
        with pytest.raises(NormalizationError, match="decimal places"):
            normalize_actual("8.5", DataType.DECIMAL, fmt, typed=False)
        value, _ = normalize_actual(8.5, DataType.DECIMAL, fmt, typed=True)
        assert value == Decimal("8.5")  # native numbers skip the places check

    def test_string_typed_int_warns(self):
        value, warnings = normalize_actual("6", DataType.INTEGER, FormatSpec(), typed=True)
        assert value == 6
        assert any("string" in w for w in warnings)

    def test_untyped_int_string_no_warning(self):
        value, warnings = normalize_actual("6", DataType.INTEGER, FormatSpec(), typed=False)
        assert value == 6 and warnings == []

    def test_bool_rejected_as_integer(self):
        with pytest.raises(NormalizationError):
            normalize_actual(True, DataType.INTEGER, FormatSpec(), typed=True)


class TestLengthAndDisplay:
    def test_check_length(self):
        fmt = parse_format("len:2..2")
        assert check_length("CO", fmt) is None
        assert "outside the allowed range" in check_length("COLO", fmt)
        assert check_length("anything", FormatSpec()) is None

    def test_display(self):
        assert display(Decimal("25.00")) == "25.00"
        assert display(date(2026, 6, 15)) == "2026-06-15"
        assert display(12) == "12"
