"""Tests for the coded condition / outcome mini-language."""

import pytest

from mapcheck.spec.conditions import (
    ConditionSyntaxError,
    parse_condition,
    parse_outcome,
)
from mapcheck.spec.model import OutcomeKind


class TestParseCondition:
    def test_equality(self):
        cond = parse_condition("N101 = 'ST'")
        assert len(cond.predicates) == 1
        pred = cond.predicates[0]
        assert (pred.field, pred.op, pred.values) == ("N101", "=", ("ST",))

    def test_inequality(self):
        pred = parse_condition("BEG02 != 'SA'").predicates[0]
        assert (pred.op, pred.values) == ("!=", ("SA",))

    def test_in_list(self):
        pred = parse_condition("PO103 IN ('EA', 'CA', 'DZ')").predicates[0]
        assert pred.op == "IN"
        assert pred.values == ("EA", "CA", "DZ")

    def test_exists(self):
        pred = parse_condition("EXISTS(REF02)").predicates[0]
        assert (pred.field, pred.op) == ("REF02", "EXISTS")

    def test_and_joined(self):
        cond = parse_condition("N101 = 'ST' AND N103 = '92'")
        assert [p.field for p in cond.predicates] == ["N101", "N103"]

    def test_lowercase_keywords_accepted(self):
        cond = parse_condition("N101 = 'ST' and exists(N104)")
        assert cond.predicates[1].op == "EXISTS"

    def test_empty_value_allowed(self):
        pred = parse_condition("BEG02 = ''").predicates[0]
        assert pred.values == ("",)

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "N101",
            "N101 =",
            "N101 = ST",  # unquoted value
            "N101 = 'ST' OR N101 = 'BT'",  # OR not supported
            "NOTAFIELD = 'X'",
            "N101 = 'ST' N103 = '92'",  # missing AND
            "EXISTS(REF02",
        ],
    )
    def test_syntax_errors(self, bad):
        with pytest.raises(ConditionSyntaxError):
            parse_condition(bad)


class TestParseOutcome:
    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            ("SOURCE", OutcomeKind.SOURCE),
            ("source", OutcomeKind.SOURCE),
            ("SKIP", OutcomeKind.SKIP),
            ("BLANK", OutcomeKind.BLANK),
        ],
    )
    def test_keywords(self, text, kind):
        assert parse_outcome(text).kind is kind

    def test_literal(self):
        outcome = parse_outcome("'DROP SHIP'")
        assert outcome.kind is OutcomeKind.LITERAL
        assert outcome.literal == "DROP SHIP"

    def test_empty_literal(self):
        assert parse_outcome("''").literal == ""

    @pytest.mark.parametrize("bad", ["", "Y", "DEFAULT", "'unterminated"])
    def test_rejects_bare_words(self, bad):
        with pytest.raises(ConditionSyntaxError):
            parse_outcome(bad)
