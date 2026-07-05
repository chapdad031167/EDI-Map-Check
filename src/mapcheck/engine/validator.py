"""The validation engine: evaluates every spec rule against source + output.

For each mapping rule the engine derives the *expected* target value from
the X12 source (per the rule type), resolves the *actual* value from the
output file, and emits a :class:`~mapcheck.engine.results.Finding`. On top
of the per-rule checks it reconciles line counts, reports interchange
control problems, and flags unmapped data in both directions (spec rule
category 7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mapcheck.engine.formats import (
    NormalizationError,
    check_length,
    display,
    normalize_actual,
    normalize_source,
)
from mapcheck.spec.formats import FormatSpec, parse_format
from mapcheck.engine.results import Category, Finding, RunResult, Status
from mapcheck.output.adapter import MISSING, CanonicalOutput
from mapcheck.spec.model import (
    Condition,
    MappingRule,
    MappingSpec,
    OutcomeKind,
    RuleType,
    split_source_field,
)
from mapcheck.x12.model import Scope, Segment, Transaction850

#: Root-cause category for a wrong value, by rule type.
_MISMATCH_CATEGORY = {
    RuleType.DIRECT: Category.VALUE_MISMATCH,
    RuleType.CONDITIONAL: Category.CONDITION_LOGIC,
    RuleType.CODE_LIST: Category.CODE_TRANSLATION,
    RuleType.CONSTANT: Category.CONSTANT_DEFAULT,
    RuleType.LOOP_COUNT: Category.COUNT_MISMATCH,
}


@dataclass(frozen=True)
class _Expected:
    """What the source + spec say the target must hold."""

    kind: str  # 'value' | 'absent' | 'empty' | 'untestable' | 'source_defect'
    value: Any = None
    note: str = ""


def validate(
    spec: MappingSpec,
    tx: Transaction850,
    output: CanonicalOutput,
    source_path: str = "",
) -> RunResult:
    """Run the full validation and return the collected findings."""
    result = RunResult(
        spec_path=spec.source_path or "",
        source_path=source_path,
        output_path=output.source_path,
        spec_name=spec.meta.get("Spec Name"),
    )

    for note in tx.control_notes:
        result.findings.append(
            Finding(
                status=Status.WARNING,
                category=Category.CONTROL,
                source_ref="(envelope)",
                message=f"interchange control: {note}",
            )
        )

    for rule in spec.rules:
        if rule.is_per_line:
            result.findings.extend(_evaluate_per_line(rule, spec, tx, output))
        else:
            result.findings.append(_evaluate_in_scope(rule, spec, tx, output, None))

    _check_line_counts(tx, output, result)
    _check_unmapped_source(spec, tx, result)
    _check_unmapped_target(spec, output, result)
    return result


def validate_files(spec_path: str, source_path: str, output_path: str) -> RunResult:
    """Load the three artifacts and validate. Convenience for CLI/UI callers.

    Raises ``SpecLoadError``, ``X12ParseError``, or ``OutputLoadError`` when
    an input cannot be loaded.
    """
    from mapcheck.output.adapter import load_output
    from mapcheck.spec.parser import load_spec
    from mapcheck.x12.parser import parse_850

    spec = load_spec(spec_path)
    tx = parse_850(source_path)
    output = load_output(output_path)
    return validate(spec, tx, output, source_path=str(source_path))


# --------------------------------------------------------------------------
# Rule evaluation
# --------------------------------------------------------------------------


def _evaluate_per_line(
    rule: MappingRule, spec: MappingSpec, tx: Transaction850, output: CanonicalOutput
) -> list[Finding]:
    """Evaluate a lines[] rule once per PO1 loop / output line pair."""
    assert rule.loop_context is not None
    if rule.loop_context.segment_id != "PO1":
        return [
            Finding(
                status=Status.NOT_TESTED,
                row_id=rule.row_id,
                sheet_row=rule.sheet_row,
                source_ref=rule.source_ref(),
                target=rule.target_field,
                message=(
                    f"repeating loop {rule.loop_context.segment_id!r} is not supported "
                    "for per-line rules (MVP pairs lines[] with the PO1 loop)"
                ),
            )
        ]

    scopes = tx.scopes(rule.loop_context)
    findings: list[Finding] = []
    total = max(len(scopes), output.line_count())
    for index in range(total):
        target = rule.target_field.replace("[]", f"[{index}]")
        actual = output.get(rule.target_field, line_index=index)
        if index >= len(scopes):
            if actual is not MISSING:
                findings.append(
                    Finding(
                        status=Status.FAIL,
                        category=Category.COUNT_MISMATCH,
                        row_id=rule.row_id,
                        sheet_row=rule.sheet_row,
                        source_ref=f"PO1 #{index + 1} (absent)",
                        target=target,
                        actual=display(actual),
                        message=(
                            f"output line {index + 1} has no matching PO1 loop "
                            f"in the source (source has {len(scopes)})"
                        ),
                    )
                )
            continue
        findings.append(
            _evaluate_in_scope(rule, spec, tx, output, index, scope=scopes[index])
        )
    return findings


def _evaluate_in_scope(
    rule: MappingRule,
    spec: MappingSpec,
    tx: Transaction850,
    output: CanonicalOutput,
    line_index: int | None,
    scope: Scope | None = None,
) -> Finding:
    """Evaluate one rule in one concrete scope and produce its finding."""
    if scope is None and not rule.is_per_line:
        scopes = tx.scopes(rule.loop_context)
        scope = scopes[0] if scopes else None

    fmt = parse_format(rule.format)
    expected = _expected_for(rule, spec, tx, scope, fmt)
    actual = output.get(rule.target_field, line_index=line_index)

    target = (
        rule.target_field
        if line_index is None
        else rule.target_field.replace("[]", f"[{line_index}]")
    )
    source_ref = (
        rule.source_ref()
        if line_index is None
        else f"PO1 #{line_index + 1} {rule.source_field or ''}".strip()
    )

    def finding(
        status: Status,
        message: str,
        category: Category | None = None,
        expected_text: str | None = None,
        actual_text: str | None = None,
    ) -> Finding:
        return Finding(
            status=status,
            category=category,
            row_id=rule.row_id,
            sheet_row=rule.sheet_row,
            source_ref=source_ref,
            target=target,
            expected=expected_text,
            actual=actual_text,
            message=message,
        )

    actual_text = None if actual is MISSING else display(actual)

    if expected.kind == "source_defect":
        return finding(
            Status.FAIL,
            f"source data invalid: {expected.note}",
            Category.SOURCE_DATA,
            expected_text="(valid source value)",
            actual_text=actual_text,
        )

    if expected.kind == "untestable":
        if actual is MISSING:
            return finding(Status.NOT_TESTED, expected.note)
        return finding(
            Status.FAIL,
            f"output has a value but {expected.note}",
            Category.UNEXPECTED_OUTPUT,
            expected_text="(no value)",
            actual_text=actual_text,
        )

    if expected.kind == "absent":
        if actual is MISSING:
            return finding(Status.PASS, "correctly absent" + _why(expected.note))
        return finding(
            Status.FAIL,
            f"expected no value{_why(expected.note)}, output has {actual_text!r}",
            _MISMATCH_CATEGORY[rule.rule_type],
            expected_text="(no value)",
            actual_text=actual_text,
        )

    if expected.kind == "empty":
        if actual is MISSING:
            return finding(
                Status.FAIL,
                f"expected an empty value{_why(expected.note)}, field is absent",
                Category.MISSING_OUTPUT,
                expected_text="(empty)",
            )
        if actual in (None, ""):
            return finding(Status.PASS, "correctly empty" + _why(expected.note))
        return finding(
            Status.FAIL,
            f"expected an empty value{_why(expected.note)}",
            _MISMATCH_CATEGORY[rule.rule_type],
            expected_text="(empty)",
            actual_text=actual_text,
        )

    # expected.kind == "value"
    expected_text = display(expected.value)
    if actual is MISSING:
        category = (
            Category.CONSTANT_DEFAULT
            if rule.rule_type is RuleType.CONSTANT
            else Category.MISSING_OUTPUT
        )
        return finding(
            Status.FAIL,
            f"target field is missing from the output{_why(expected.note)}",
            category,
            expected_text=expected_text,
        )

    try:
        normalized, warnings = normalize_actual(actual, rule.data_type, fmt, output.typed)
    except NormalizationError as exc:
        return finding(
            Status.FAIL,
            f"format violation: {exc.reason}",
            Category.FORMAT,
            expected_text=expected_text,
            actual_text=actual_text,
        )

    if length_issue := check_length(actual, fmt):
        return finding(
            Status.FAIL,
            f"format violation: {length_issue}",
            Category.FORMAT,
            expected_text=expected_text,
            actual_text=actual_text,
        )

    if normalized != expected.value:
        return finding(
            Status.FAIL,
            f"expected {expected_text!r}, output has {display(normalized)!r}"
            + _why(expected.note),
            _MISMATCH_CATEGORY[rule.rule_type],
            expected_text=expected_text,
            actual_text=actual_text,
        )

    if warnings:
        return finding(
            Status.WARNING,
            "value matches, but " + "; ".join(warnings),
            Category.FORMAT,
            expected_text=expected_text,
            actual_text=actual_text,
        )
    return finding(
        Status.PASS,
        "ok" + _why(expected.note),
        expected_text=expected_text,
        actual_text=actual_text,
    )


def _why(note: str) -> str:
    return f" ({note})" if note else ""


def _expected_for(
    rule: MappingRule,
    spec: MappingSpec,
    tx: Transaction850,
    scope: Scope | None,
    fmt: FormatSpec,
) -> _Expected:
    """Derive the expected target value for one rule in one scope."""
    if rule.rule_type is RuleType.CONSTANT:
        return _literal_expected(rule.default_value or "", rule, fmt, note="hardcoded constant")

    if rule.rule_type is RuleType.LOOP_COUNT:
        count = len(tx.loops(rule.source_field or ""))
        return _Expected(
            kind="value", value=count, note=f"count of {rule.source_field} loops in source"
        )

    if rule.rule_type is RuleType.CONDITIONAL:
        assert rule.condition is not None and rule.then_outcome is not None
        branch_true = _evaluate_condition(rule.condition, scope)
        outcome = rule.then_outcome if branch_true else rule.else_outcome
        assert outcome is not None
        note = f"condition {rule.condition.raw!r} is {'true' if branch_true else 'false'}"
        if outcome.kind is OutcomeKind.SKIP:
            return _Expected(kind="absent", note=note)
        if outcome.kind is OutcomeKind.BLANK:
            return _Expected(kind="empty", note=note)
        if outcome.kind is OutcomeKind.LITERAL:
            return _literal_expected(outcome.literal or "", rule, fmt, note=note)
        return _source_expected(rule, spec, scope, fmt, note=note)  # SOURCE

    # DIRECT / CODE_LIST
    return _source_expected(rule, spec, scope, fmt)


def _source_expected(
    rule: MappingRule,
    spec: MappingSpec,
    scope: Scope | None,
    fmt: FormatSpec,
    note: str = "",
) -> _Expected:
    """Expected value for rules that read the source element."""
    assert rule.source_field is not None
    seg_id, element = split_source_field(rule.source_field)

    raw: str | None = None
    if scope is not None:
        raw = scope.value(seg_id, element)

    if raw is None:
        if rule.default_value is not None:
            return _literal_expected(
                rule.default_value,
                rule,
                fmt,
                note=f"source {rule.source_field} empty, spec default applies",
            )
        if scope is None:
            reason = f"source segment {rule.loop_context or seg_id} not present in this file"
        elif scope.first(seg_id) is None:
            reason = f"source segment {seg_id} not present in {scope.label}"
        else:
            reason = f"source element {rule.source_field} is empty"
        return _Expected(kind="untestable", note=reason)

    if rule.rule_type is RuleType.CODE_LIST:
        assert rule.code_list_ref is not None
        code_list = spec.code_lists[rule.code_list_ref]
        translated = code_list.translate(raw)
        if translated is None:
            return _Expected(
                kind="source_defect",
                note=(
                    f"source value {raw!r} has no entry in code list "
                    f"{rule.code_list_ref} "
                    f"(valid: {', '.join(sorted(code_list.entries))})"
                ),
            )
        return _literal_expected(
            translated, rule, fmt, note=f"code list {rule.code_list_ref}: {raw!r} -> {translated!r}"
        )

    try:
        value = normalize_source(raw, rule.data_type, fmt)
    except NormalizationError as exc:
        return _Expected(kind="source_defect", note=f"{rule.source_field} {exc.reason}")
    return _Expected(kind="value", value=value, note=note)


def _literal_expected(
    literal: str, rule: MappingRule, fmt: FormatSpec, note: str = ""
) -> _Expected:
    """Expected value from a spec literal (constant, default, or Then/Else)."""
    try:
        value, _ = normalize_actual(literal, rule.data_type, fmt, typed=False)
    except NormalizationError as exc:
        return _Expected(
            kind="source_defect",
            note=f"spec literal {literal!r} does not fit the declared format: {exc.reason}",
        )
    return _Expected(kind="value", value=value, note=note)


def _evaluate_condition(condition: Condition, scope: Scope | None) -> bool:
    """Evaluate AND-joined predicates against a scope.

    Fields resolve within the rule's Loop Context scope; a missing scope or
    element reads as empty, so ``EXISTS`` is false and ``=`` compares
    against the empty string.
    """
    for predicate in condition.predicates:
        seg_id, element = split_source_field(predicate.field)
        value = scope.value(seg_id, element) if scope is not None else None
        if predicate.op == "EXISTS":
            ok = value is not None
        elif predicate.op == "=":
            ok = (value or "") == predicate.values[0]
        elif predicate.op == "!=":
            ok = (value or "") != predicate.values[0]
        else:  # IN
            ok = (value or "") in predicate.values
        if not ok:
            return False
    return True


# --------------------------------------------------------------------------
# Cross-cutting checks
# --------------------------------------------------------------------------


def _check_line_counts(tx: Transaction850, output: CanonicalOutput, result: RunResult) -> None:
    source_count = len(tx.po1_loops)
    output_count = output.line_count()
    if source_count != output_count:
        result.findings.append(
            Finding(
                status=Status.FAIL,
                category=Category.COUNT_MISMATCH,
                source_ref="PO1 loops",
                target="lines[]",
                expected=str(source_count),
                actual=str(output_count),
                message=(
                    f"source has {source_count} PO1 loop(s) but the output has "
                    f"{output_count} line(s)"
                ),
            )
        )


def _referenced_elements(spec: MappingSpec, tx: Transaction850) -> set[tuple[int, int]]:
    """(segment identity, element index) pairs any rule reads or qualifies on."""
    referenced: set[tuple[int, int]] = set()

    def mark(segment: Segment | None, element: int) -> None:
        if segment is not None:
            referenced.add((id(segment), element))

    for rule in spec.rules:
        for scope in tx.scopes(rule.loop_context):
            if rule.loop_context is not None and rule.loop_context.qualifier is not None:
                mark(scope.segments[0], 1)
            if rule.source_field and rule.rule_type is not RuleType.LOOP_COUNT:
                seg_id, element = split_source_field(rule.source_field)
                mark(scope.first(seg_id), element)
            if rule.condition is not None:
                for predicate in rule.condition.predicates:
                    seg_id, element = split_source_field(predicate.field)
                    mark(scope.first(seg_id), element)
    return referenced


def _check_unmapped_source(spec: MappingSpec, tx: Transaction850, result: RunResult) -> None:
    referenced = _referenced_elements(spec, tx)
    for label, segment in tx.business_segments():
        unreferenced = [
            f"{segment.ref(index)}={value!r}"
            for index, value in enumerate(segment.elements, start=1)
            if value != "" and (id(segment), index) not in referenced
        ]
        if unreferenced:
            result.findings.append(
                Finding(
                    status=Status.WARNING,
                    category=Category.UNMAPPED_SOURCE,
                    source_ref=f"{label} {segment.seg_id}",
                    message=(
                        "source data not referenced by any spec rule: "
                        + ", ".join(unreferenced)
                    ),
                )
            )


def _check_unmapped_target(
    spec: MappingSpec, output: CanonicalOutput, result: RunResult
) -> None:
    targeted = {rule.target_field for rule in spec.rules}
    for normalized, concrete, value in output.walk_paths():
        if normalized not in targeted:
            result.findings.append(
                Finding(
                    status=Status.WARNING,
                    category=Category.UNMAPPED_TARGET,
                    target=concrete,
                    actual=display(value),
                    message="output field is not produced by any spec rule",
                )
            )
