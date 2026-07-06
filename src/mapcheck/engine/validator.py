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
from decimal import Decimal, InvalidOperation
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
    LoopContext,
    MappingRule,
    MappingSpec,
    OutcomeKind,
    RuleType,
    split_source_field,
)
from mapcheck.transactions.schema import Operand
from mapcheck.x12.model import Scope, Segment, TransactionDocument

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
    tx: TransactionDocument,
    output: CanonicalOutput,
    source_path: str = "",
) -> RunResult:
    """Run the full validation and return the collected findings."""
    result = RunResult(
        spec_path=spec.source_path or "",
        source_path=source_path,
        output_path=output.source_path,
        spec_name=spec.meta.get("Spec Name"),
        transaction_set=tx.definition.set_code,
        transaction_name=tx.definition.name,
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
    for note in tx.definition_notes:
        result.findings.append(
            Finding(
                status=Status.WARNING,
                category=Category.SOURCE_DATA,
                source_ref="(structure)",
                message=f"transaction structure: {note}",
            )
        )
    for error in tx.hierarchy_errors:
        result.findings.append(
            Finding(
                status=Status.FAIL,
                category=Category.SOURCE_DATA,
                source_ref="(hierarchy)",
                message=f"hierarchical structure defect: {error}",
            )
        )

    for rule in spec.rules:
        if rule.is_per_line:
            result.findings.extend(_evaluate_per_line(rule, spec, tx, output))
        else:
            result.findings.append(_evaluate_in_scope(rule, spec, tx, output, None))

    _check_line_counts(tx, output, result)
    _check_reconciliation(tx, result)
    _check_unmapped_source(spec, tx, result)
    _check_unmapped_target(spec, output, result)
    return result


def validate_files(
    spec_path: str,
    source_path: str,
    output_path: str,
    transaction: str | None = None,
) -> RunResult:
    """Load the three artifacts and validate. Convenience for CLI/UI callers.

    The transaction set is auto-detected from the source file's ST01 unless
    ``transaction`` forces a specific registered definition. The spec's Meta
    ``Transaction Set`` must agree with the source file.

    Raises ``SpecLoadError``, ``X12ParseError``, or ``OutputLoadError`` when
    an input cannot be loaded or the spec and source disagree.
    """
    from mapcheck.output.adapter import load_output
    from mapcheck.spec.parser import SpecLoadError, load_spec
    from mapcheck.transactions.registry import UnknownTransactionError, default_registry
    from mapcheck.x12.parser import X12ParseError, parse_transaction

    spec = load_spec(spec_path)
    definition = None
    if transaction is not None:
        try:
            definition = default_registry.get(transaction)
        except UnknownTransactionError as exc:
            raise X12ParseError(str(exc.args[0])) from exc
    tx = parse_transaction(source_path, definition=definition)
    if spec.transaction_set and spec.transaction_set != tx.definition.set_code:
        raise SpecLoadError(
            [
                f"spec is for transaction set {spec.transaction_set} but the source "
                f"file is a {tx.definition.set_code} ({tx.definition.name})"
            ]
        )
    output = load_output(output_path)
    return validate(spec, tx, output, source_path=str(source_path))


# --------------------------------------------------------------------------
# Rule evaluation
# --------------------------------------------------------------------------


def _evaluate_per_line(
    rule: MappingRule, spec: MappingSpec, tx: TransactionDocument, output: CanonicalOutput
) -> list[Finding]:
    """Evaluate a lines[] rule once per line-loop / output line pair."""
    assert rule.loop_context is not None
    pairing = tx.definition.output_pairing
    pairing_context = LoopContext.parse(pairing.loop) if pairing else None
    # A path context (LIN>QTY[QA]) still pairs per-line on its base loop.
    if pairing_context is None or rule.loop_context.base() != pairing_context:
        supported = pairing.loop if pairing else "(none declared)"
        return [
            Finding(
                status=Status.NOT_TESTED,
                row_id=rule.row_id,
                sheet_row=rule.sheet_row,
                source_ref=rule.source_ref(),
                target=rule.target_field,
                message=(
                    f"loop context {rule.loop_context} is not paired "
                    f"with {rule.target_field.split('[')[0]}[] targets — the "
                    f"{tx.definition.set_code} definition pairs lines[] with {supported}"
                ),
            )
        ]

    scopes = tx.scopes(rule.loop_context)
    findings: list[Finding] = []
    total = max(len(scopes), output.line_count(pairing.list_path))
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
                        source_ref=f"{pairing.loop} #{index + 1} (absent)",
                        target=target,
                        actual=display(actual),
                        message=(
                            f"output line {index + 1} has no matching {pairing.loop} loop "
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
    tx: TransactionDocument,
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
    line_loop = tx.line_loop_id or "line"
    source_ref = (
        rule.source_ref()
        if line_index is None
        else f"{line_loop} #{line_index + 1} {rule.source_field or ''}".strip()
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
    tx: TransactionDocument,
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


def _check_line_counts(tx: TransactionDocument, output: CanonicalOutput, result: RunResult) -> None:
    pairing = tx.definition.output_pairing
    if pairing is None:
        return
    source_count = len(tx.scopes(LoopContext.parse(pairing.loop)))
    output_count = output.line_count(pairing.list_path)
    if source_count != output_count:
        result.findings.append(
            Finding(
                status=Status.FAIL,
                category=Category.COUNT_MISMATCH,
                source_ref=f"{pairing.loop} loops",
                target=f"{pairing.list_path}[]",
                expected=str(source_count),
                actual=str(output_count),
                message=(
                    f"source has {source_count} {pairing.loop} loop(s) but the output has "
                    f"{output_count} line(s)"
                ),
            )
        )


def _loop_occurrences(reference: str, tx: TransactionDocument) -> list[Scope]:
    """Occurrences a loop reference (``PO1``, ``HL``, ``HL[I]``) selects.

    Unlike :meth:`TransactionDocument.scopes`, hierarchical occurrences are
    NOT ancestor-extended here — sums and counts must not double-read
    parent data.
    """
    context = LoopContext.parse(reference)
    return [
        Scope(label=reference, segments=tuple(loop.segments))
        for loop in tx.loops(context.segment_id)
        if context.qualifier is None or loop.qualifier == context.qualifier
    ]


def _scoped_value(field: str, context: str | None, tx: TransactionDocument) -> str | None:
    """Read ``SEGnn`` from the flat scope, or from a Loop Context string."""
    seg_id, element = split_source_field(field)
    if context is None:
        return tx.flat_scope().value(seg_id, element)
    scopes = tx.scopes(LoopContext.parse(context))
    return scopes[0].value(seg_id, element) if scopes else None


def _sum_operand(operand: Operand, tx: TransactionDocument) -> tuple[Any, str]:
    """Evaluate a sum operand.

    ``sum_value`` sums the element over **every** matching segment in each
    occurrence (an 855 line's repeated ACKs all count); ``sum_expr``
    multiplies its element refs once per occurrence (first match each).
    Missing/non-numeric contributions are skipped — which correctly skews
    the total when the source is incomplete.
    """
    assert operand.sum_loop is not None
    total = Decimal(0)
    for scope in _loop_occurrences(operand.sum_loop, tx):
        if operand.sum_value is not None:
            seg_id, element = split_source_field(operand.sum_value)
            for segment in scope.segments:
                if segment.seg_id != seg_id:
                    continue
                raw = segment.element(element)
                if raw is None:
                    continue
                try:
                    number = Decimal(raw)
                except InvalidOperation:
                    continue
                if operand.implied is not None:
                    number = number.scaleb(-operand.implied)
                total += number
        else:
            product = Decimal(1)
            complete = True
            for ref in operand.sum_expr:
                seg_id, element = split_source_field(ref)
                raw = scope.value(seg_id, element)
                if raw is None:
                    complete = False
                    break
                try:
                    product *= Decimal(raw)
                except InvalidOperation:
                    complete = False
                    break
            if complete:
                if operand.implied is not None:
                    product = product.scaleb(-operand.implied)
                total += product
    what = operand.sum_value or " * ".join(operand.sum_expr)
    return total, f"sum({what} over {operand.sum_loop})={display(total)}"


def _resolve_operand(operand: Operand, tx: TransactionDocument) -> tuple[Any, str] | None:
    """Resolve a reconciliation operand to ``(comparable value, display)``.

    Returns None when the operand cannot be evaluated (element absent).
    """
    if operand.count is not None:
        count = len(_loop_occurrences(operand.count, tx))
        return count, f"count({operand.count})={count}"
    if operand.sum_loop is not None:
        return _sum_operand(operand, tx)
    if operand.is_combine:
        total = Decimal(0)
        parts: list[str] = []
        for sign, children in ((1, operand.add), (-1, operand.subtract)):
            for child in children:
                resolved = _resolve_operand(child, tx)
                if resolved is None:
                    continue
                child_value, child_text = resolved
                if not isinstance(child_value, (Decimal, int)):
                    continue
                total += sign * Decimal(child_value)
                parts.append(("+ " if sign > 0 else "- ") + child_text)
        return total, f"({' '.join(parts)})={display(total)}"
    assert operand.value is not None
    raw = _scoped_value(operand.value, operand.context, tx)
    if raw is None:
        return None
    label = f"{operand.value}@{operand.context}" if operand.context else operand.value
    try:
        number = Decimal(raw)
    except InvalidOperation:
        return raw, f"{label}={raw!r}"
    if operand.implied is not None:
        number = number.scaleb(-operand.implied)
    return number, f"{label}={display(number)}"


def _check_reconciliation(tx: TransactionDocument, result: RunResult) -> None:
    """Run the definition's declarative source-side reconciliation rules.

    Rules are silent when they pass or cannot be evaluated; a mismatch
    emits a finding at the rule's declared severity.
    """
    for rule in tx.definition.reconciliation:
        if rule.when_exists is not None:
            if _scoped_value(rule.when_exists, rule.when_context, tx) is None:
                continue
        left = _resolve_operand(rule.left, tx)
        right = _resolve_operand(rule.right, tx)
        if left is None or right is None:
            continue
        left_value, left_text = left
        right_value, right_text = right
        if isinstance(left_value, int):
            left_value = Decimal(left_value)
        if isinstance(right_value, int):
            right_value = Decimal(right_value)
        if rule.check == "not_after":
            # ordering check (e.g. effective date <= expiration date);
            # CCYYMMDD values compare correctly as numbers
            if not (isinstance(left_value, Decimal) and isinstance(right_value, Decimal)):
                continue
            violated = left_value > right_value
            relation = "must not be after"
        else:
            violated = left_value != right_value
            relation = "!="
        if violated:
            result.findings.append(
                Finding(
                    status=Status.FAIL if rule.severity == "error" else Status.WARNING,
                    category=Category.COUNT_MISMATCH,
                    source_ref=f"recon:{rule.id}",
                    expected=left_text,
                    actual=right_text,
                    message=(
                        (rule.description + " — " if rule.description else "")
                        + f"source reconciliation failed: {left_text} {relation} {right_text}"
                    ),
                )
            )



def _referenced_elements(spec: MappingSpec, tx: TransactionDocument) -> set[tuple[int, int]]:
    """(segment identity, element index) pairs any rule reads or qualifies on."""
    referenced: set[tuple[int, int]] = set()

    def mark(segment: Segment | None, element: int) -> None:
        if segment is not None:
            referenced.add((id(segment), element))

    # Hierarchical control elements (HL01/HL02/HL03) are read by the tree
    # machinery itself; no spec rule needs to reference them.
    for loop_def in tx.definition.all_loops():
        if loop_def.hierarchy is None:
            continue
        for occurrence in tx.loops(loop_def.id):
            for element in (
                loop_def.hierarchy.id_element,
                loop_def.hierarchy.parent_element,
                loop_def.hierarchy.level_element,
            ):
                mark(occurrence.trigger, element)

    def mark_all(scope: Scope, field: str) -> None:
        # A rule that reads SEGnn references every SEGnn in its scope: a
        # repeating segment (an 855 line's second ACK) is still spec-covered
        # data even though value rules read the first occurrence.
        seg_id, element = split_source_field(field)
        for segment in scope.segments:
            if segment.seg_id == seg_id:
                mark(segment, element)

    for rule in spec.rules:
        context = rule.loop_context
        for scope in tx.scopes(context):
            if context is not None and scope.segments:
                if context.sub_qualifier is not None:
                    # path contexts: the narrowed segments' element 01 is
                    # the qualifier the rule selects on
                    for segment in scope.segments:
                        mark(segment, 1)
                elif context.qualifier is not None:
                    context_loop = tx.definition.loop(context.segment_id)
                    mark(scope.segments[0], context_loop.qualifier if context_loop else 1)
            if rule.source_field and rule.rule_type is not RuleType.LOOP_COUNT:
                mark_all(scope, rule.source_field)
            if rule.condition is not None:
                for predicate in rule.condition.predicates:
                    mark_all(scope, predicate.field)
    return referenced


def _check_unmapped_source(spec: MappingSpec, tx: TransactionDocument, result: RunResult) -> None:
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
