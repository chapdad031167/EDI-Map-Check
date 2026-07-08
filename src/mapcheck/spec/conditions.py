"""Parser for the coded condition and Then/Else outcome mini-language.

The Excel spec keeps two condition columns: a free-text one for humans and
a coded one for the engine. The coded grammar is deliberately tiny — no
``eval``, no arbitrary expressions:

.. code-block:: text

    condition := predicate ( 'AND' predicate )*
    predicate := FIELD '='  value
               | FIELD '!=' value
               | FIELD 'IN' '(' value ( ',' value )* ')'
               | 'EXISTS' '(' FIELD ')'
    value     := "'" chars "'"
    FIELD     := segment+element, e.g. N101

Outcomes (the Then/Else columns) are one of the keywords ``SOURCE``,
``SKIP``, ``BLANK``, or a quoted literal like ``'DROP SHIP'``.

FIELD notation depends on the spec's direction: inbound conditions test
X12 elements (``N101``), outbound ones test canonical paths into the
internal source document (``lines[].item_type``). Conditions always
address the *source* side, whichever document that is.
"""

from __future__ import annotations

import re

from mapcheck.spec.model import (
    Condition,
    Outcome,
    OutcomeKind,
    Predicate,
    is_canonical_path,
    split_source_field,
)


class ConditionSyntaxError(ValueError):
    """Raised when a coded condition or outcome cell cannot be parsed."""


_TOKEN_RE = re.compile(
    r"""\s*(?:
        (?P<string>'[^']*')
      | (?P<op>!=|=)
      | (?P<lparen>\()
      | (?P<rparen>\))
      | (?P<comma>,)
      | (?P<word>[A-Za-z_][A-Za-z0-9_]*(?:\[\])?(?:\.[A-Za-z0-9_]+(?:\[\])?)*)
    )""",
    re.VERBOSE,
)


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            raise ConditionSyntaxError(f"unexpected character at {text[pos:]!r}")
        pos = m.end()
        kind = m.lastgroup
        assert kind is not None
        tokens.append((kind, m.group(kind)))
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]], raw: str, allow_paths: bool) -> None:
        self.tokens = tokens
        self.raw = raw
        self.allow_paths = allow_paths
        self.pos = 0

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, kind: str | None = None) -> tuple[str, str]:
        tok = self.peek()
        if tok is None:
            raise ConditionSyntaxError(f"unexpected end of condition {self.raw!r}")
        if kind is not None and tok[0] != kind:
            raise ConditionSyntaxError(f"expected {kind}, got {tok[1]!r} in {self.raw!r}")
        self.pos += 1
        return tok

    def parse_condition(self) -> Condition:
        predicates = [self.parse_predicate()]
        while (tok := self.peek()) is not None:
            if tok[0] == "word" and tok[1].upper() == "AND":
                self.take()
                predicates.append(self.parse_predicate())
            else:
                raise ConditionSyntaxError(
                    f"expected AND or end of condition, got {tok[1]!r} in {self.raw!r}"
                )
        return Condition(predicates=tuple(predicates), raw=self.raw)

    def parse_predicate(self) -> Predicate:
        kind, value = self.take("word")
        if value.upper() == "EXISTS":
            self.take("lparen")
            _, fld = self.take("word")
            self.take("rparen")
            return Predicate(field=_validate_field(fld, self.raw, self.allow_paths), op="EXISTS")
        fld = _validate_field(value, self.raw, self.allow_paths)
        tok = self.take()
        if tok[0] == "op":
            val = self._take_string()
            return Predicate(field=fld, op=tok[1], values=(val,))
        if tok[0] == "word" and tok[1].upper() == "IN":
            self.take("lparen")
            values = [self._take_string()]
            while self.peek() and self.peek()[0] == "comma":  # type: ignore[index]
                self.take("comma")
                values.append(self._take_string())
            self.take("rparen")
            return Predicate(field=fld, op="IN", values=tuple(values))
        raise ConditionSyntaxError(f"expected operator after {fld!r} in {self.raw!r}")

    def _take_string(self) -> str:
        _, quoted = self.take("string")
        return quoted[1:-1]


def _validate_field(field: str, raw: str, allow_paths: bool) -> str:
    if allow_paths:
        # outbound: canonical paths only — case is preserved, since the
        # internal document's keys are case-sensitive
        if is_canonical_path(field):
            return field
        raise ConditionSyntaxError(
            f"invalid field reference {field!r} in condition {raw!r} "
            "(outbound conditions test the internal source document — "
            "expected a canonical path, e.g. order.currency or lines[].qty)"
        )
    try:
        split_source_field(field)
    except ValueError:
        raise ConditionSyntaxError(
            f"invalid field reference {field!r} in condition {raw!r} "
            "(expected segment+element, e.g. N101)"
        ) from None
    return field.upper()


def parse_condition(text: str, allow_paths: bool = False) -> Condition:
    """Parse a coded condition cell into a :class:`Condition`.

    ``allow_paths`` switches FIELD notation from X12 elements (inbound) to
    canonical paths (outbound). Raises :class:`ConditionSyntaxError` on
    invalid syntax.
    """
    raw = text.strip()
    if not raw:
        raise ConditionSyntaxError("empty condition")
    return _Parser(_tokenize(raw), raw, allow_paths).parse_condition()


_OUTCOME_KEYWORDS = {
    "SOURCE": OutcomeKind.SOURCE,
    "SKIP": OutcomeKind.SKIP,
    "BLANK": OutcomeKind.BLANK,
}


def parse_outcome(text: str) -> Outcome:
    """Parse a Then/Else cell: ``SOURCE``, ``SKIP``, ``BLANK``, or ``'literal'``.

    Raises :class:`ConditionSyntaxError` on anything else — bare words are
    rejected so a forgotten quote can't silently become a literal.
    """
    raw = text.strip()
    if not raw:
        raise ConditionSyntaxError("empty outcome")
    keyword = _OUTCOME_KEYWORDS.get(raw.upper())
    if keyword is not None:
        return Outcome(kind=keyword)
    if len(raw) >= 2 and raw.startswith("'") and raw.endswith("'"):
        return Outcome(kind=OutcomeKind.LITERAL, literal=raw[1:-1])
    raise ConditionSyntaxError(
        f"invalid outcome {raw!r} (expected SOURCE, SKIP, BLANK, or a 'quoted literal')"
    )
