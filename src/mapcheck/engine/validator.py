"""The validation engine: evaluates every spec rule against source + output.

For each mapping rule the engine derives the *expected* target value from
the source document (per the rule type), resolves the *actual* value from
the produced document, and emits a :class:`~mapcheck.engine.results.Finding`.
On top of the per-rule checks it reconciles line counts, reports
interchange control problems, and flags unmapped data in both directions
(spec rule category 7).

Which document plays which role comes from the spec's direction:

* **inbound** — expected values derive from the parsed X12 transaction,
  actuals resolve from the canonical output model.
* **outbound** — the roles swap: expected values derive from the internal
  document (loaded through the same canonical model), actuals resolve
  from the parsed X12 file the map produced.

The swap lives entirely in two source-reader classes and the actual-value
resolvers; the rule loop, root-cause categories, and finding assembly are
shared, direction-agnostic code.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from mapcheck.engine.formats import (
    NormalizationError,
    check_length,
    display,
    normalize_actual,
    normalize_source,
    normalize_x12,
)
from mapcheck.spec.formats import FormatSpec, parse_format
from mapcheck.engine.results import (
    Category,
    DocumentResult,
    Finding,
    InterchangeResult,
    RunResult,
    Status,
)
from mapcheck.output.adapter import MISSING, CanonicalOutput
from mapcheck.spec.model import (
    Condition,
    Direction,
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


# --------------------------------------------------------------------------
# Source-side readers: how expected values see their document
# --------------------------------------------------------------------------

_NEUTRAL_FMT = parse_format(None)


class _X12Source:
    """Reads the parsed X12 document as the *source* side (inbound specs).

    One instance per evaluation scope: fields resolve within the rule's
    Loop Context scope exactly as before the outbound refactor.
    """

    def __init__(self, tx: TransactionDocument, scope: Scope | None) -> None:
        self.tx = tx
        self.scope = scope

    def read(self, field: str) -> str | None:
        seg_id, element = split_source_field(field)
        return self.scope.value(seg_id, element) if self.scope is not None else None

    #: X12 elements are already strings; conditions read them unchanged.
    condition_value = read

    def missing_reason(self, rule: MappingRule) -> str:
        seg_id, _ = split_source_field(rule.source_field or "")
        if self.scope is None:
            return f"source segment {rule.loop_context or seg_id} not present in this file"
        if self.scope.first(seg_id) is None:
            return f"source segment {seg_id} not present in {self.scope.label}"
        return f"source element {rule.source_field} is empty"

    def loop_count(self, ref: str) -> tuple[int, str]:
        count = len(self.tx.loops(ref))
        return count, f"count of {ref} loops in source"

    def normalize(self, raw: Any, rule: MappingRule, fmt: FormatSpec) -> Any:
        return normalize_source(raw, rule.data_type, fmt)

    def normalize_literal(self, literal: str, rule: MappingRule, fmt: FormatSpec) -> Any:
        value, _ = normalize_actual(literal, rule.data_type, fmt, typed=False)
        return value


class _CanonicalSource:
    """Reads the internal document as the *source* side (outbound specs).

    Fields are canonical paths; per-line rules carry the current line
    index. Absent (MISSING), null, and empty all read as "nothing there" —
    matching how an X12 source treats an empty element.
    """

    def __init__(self, output: CanonicalOutput, line_index: int | None) -> None:
        self.output = output
        self.line_index = line_index

    def read(self, field: str) -> Any | None:
        value = self.output.get(field, line_index=self.line_index)
        if value is MISSING or value is None or value == "":
            return None
        return value

    def condition_value(self, field: str) -> str | None:
        value = self.read(field)
        return None if value is None else str(value)

    def missing_reason(self, rule: MappingRule) -> str:
        assert rule.source_field is not None
        if self.output.get(rule.source_field, line_index=self.line_index) is MISSING:
            return f"source field {rule.source_field} is absent from the source document"
        return f"source field {rule.source_field} is empty"

    def loop_count(self, ref: str) -> tuple[int, str]:
        count = self.output.line_count(ref[:-2] if ref.endswith("[]") else ref)
        return count, f"count of {ref} entries in source"

    def normalize(self, raw: Any, rule: MappingRule, fmt: FormatSpec) -> Any:
        # Internal-convention parse (ISO dates, plain decimals): the Format
        # column describes the X12 target side, not this document.
        value, _ = normalize_actual(raw, rule.data_type, _NEUTRAL_FMT, self.output.typed)
        return value

    def normalize_literal(self, literal: str, rule: MappingRule, fmt: FormatSpec) -> Any:
        value, _ = normalize_x12(literal, rule.data_type, fmt)
        return value


def validate(
    spec: MappingSpec,
    tx: TransactionDocument,
    output: CanonicalOutput,
    source_path: str = "",
    output_path: str | None = None,
) -> RunResult:
    """Run the full validation and return the collected findings.

    ``tx`` is always the X12 document and ``output`` the canonical one;
    the spec's direction decides which is the source of expected values.
    ``output_path`` defaults to the canonical document's path (inbound
    convention) — outbound callers pass the X12 file's path instead.
    """
    outbound = spec.direction is Direction.OUTBOUND
    result = RunResult(
        spec_path=spec.source_path or "",
        source_path=source_path,
        output_path=output_path if output_path is not None else output.source_path,
        spec_name=spec.meta.get("Spec Name"),
        transaction_set=tx.definition.set_code,
        transaction_name=tx.definition.name,
    )

    for note in spec.load_notes:
        result.findings.append(
            Finding(status=Status.WARNING, source_ref="(spec)", message=f"spec note: {note}")
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
    # Structure problems in the X12 document: source-data defects inbound,
    # defects of the *produced* file outbound.
    structure_category = Category.UNEXPECTED_OUTPUT if outbound else Category.SOURCE_DATA
    structure_side = "output " if outbound else ""
    for note in tx.definition_notes:
        result.findings.append(
            Finding(
                status=Status.WARNING,
                category=structure_category,
                source_ref="(structure)",
                message=f"{structure_side}transaction structure: {note}",
            )
        )
    for error in tx.hierarchy_errors:
        result.findings.append(
            Finding(
                status=Status.FAIL,
                category=structure_category,
                source_ref="(hierarchy)",
                message=f"{structure_side}hierarchical structure defect: {error}",
            )
        )

    for rule in spec.rules:
        if outbound:
            if rule.is_per_line:
                result.findings.extend(_evaluate_per_line_out(rule, spec, tx, output))
            else:
                result.findings.append(_evaluate_in_scope_out(rule, spec, tx, output, None))
        elif rule.is_per_line:
            result.findings.extend(_evaluate_per_line(rule, spec, tx, output))
        else:
            result.findings.append(_evaluate_in_scope(rule, spec, tx, output, None))

    if outbound:
        _check_line_counts_out(tx, output, result)
        _check_reconciliation(tx, result, side="output")
        _check_unmapped_source_out(spec, output, result)
        _check_unmapped_target_out(spec, tx, result)
    else:
        _check_line_counts(tx, output, result)
        _check_reconciliation(tx, result)
        _check_unmapped_source(spec, tx, result)
        _check_unmapped_target(spec, output, result)
    _stamp_origins(result, spec)
    return result


def _stamp_origins(result: RunResult, spec: MappingSpec) -> None:
    """Tag findings with their rule's origin (partner-override provenance).

    A no-op for a plain (unmerged) spec, where every rule is ``base``.
    """
    origins = {r.row_id: r.origin for r in spec.rules if r.origin != "base"}
    if not origins:
        return
    for i, finding in enumerate(result.findings):
        origin = origins.get(finding.row_id) if finding.row_id else None
        if origin:
            result.findings[i] = dataclass_replace(finding, origin=origin)


def validate_files(
    spec_path: str,
    source_path: str,
    output_path: str,
    transaction: str | None = None,
    output_format: str | None = None,
    spec: MappingSpec | None = None,
) -> RunResult:
    """Load the three artifacts and validate. Convenience for CLI/UI callers.

    ``source_path`` is the translation's input and ``output_path`` its
    result; the spec's direction decides which of them is the X12 file.
    The transaction set is auto-detected from the X12 file's ST01 unless
    ``transaction`` forces a specific registered definition. The spec's Meta
    ``Transaction Set`` must agree with the X12 file. ``output_format``
    names a registered output-format definition for the canonical document
    (used for user-supplied formats that can't be auto-detected). Pass a
    pre-loaded ``spec`` to skip loading ``spec_path`` — used for a
    partner-override merged spec.

    Raises ``SpecLoadError``, ``X12ParseError``, or ``OutputLoadError`` when
    an input cannot be loaded or the spec and X12 file disagree.
    """
    from mapcheck.output.adapter import load_output
    from mapcheck.spec.parser import SpecLoadError, load_spec
    from mapcheck.transactions.registry import UnknownTransactionError, default_registry
    from mapcheck.x12.parser import X12ParseError, parse_transaction

    if spec is None:
        spec = load_spec(spec_path)
    definition = None
    if transaction is not None:
        try:
            definition = default_registry.get(transaction)
        except UnknownTransactionError as exc:
            raise X12ParseError(str(exc.args[0])) from exc

    x12_path, x12_role = (
        (output_path, "output") if spec.direction is Direction.OUTBOUND else (source_path, "source")
    )
    tx = parse_transaction(x12_path, definition=definition)
    if spec.transaction_set and spec.transaction_set != tx.definition.set_code:
        raise SpecLoadError(
            [
                f"spec is for transaction set {spec.transaction_set} but the {x12_role} "
                f"file is a {tx.definition.set_code} ({tx.definition.name})"
            ]
        )
    if spec.direction is Direction.OUTBOUND:
        doc = load_output(source_path, output_format=output_format)
        return validate(
            spec, tx, doc, source_path=str(source_path), output_path=str(output_path)
        )
    output = load_output(output_path, output_format=output_format)
    return validate(spec, tx, output, source_path=str(source_path))


# --------------------------------------------------------------------------
# Interchange (multi-transaction) validation
# --------------------------------------------------------------------------


def _read_pairing_key(doc: Any, key_ref: str) -> str | None:
    """Read the pairing key from a source/target document.

    The document type decides how the reference is read: an X12
    ``TransactionDocument`` takes a ``SEGnn`` element (optionally prefixed
    by a Loop Context, ``N1[ST] N104``); a ``CanonicalOutput`` takes a
    dot path. Returns None when the key is absent.
    """
    if isinstance(doc, TransactionDocument):
        context_str, _, field = key_ref.strip().rpartition(" ")
        scopes = doc.scopes(LoopContext.parse(context_str)) if context_str else [doc.flat_scope()]
        seg_id, element = split_source_field(field)
        for scope in scopes:
            value = scope.value(seg_id, element)
            if value is not None:
                return value
        return None
    value = doc.get(key_ref)
    return None if value is MISSING else str(value)


def _pair_documents(
    source_docs: list[Any],
    target_docs: list[Any],
    source_key_ref: str | None,
    target_key_ref: str | None,
    source_label: str,
    target_label: str,
) -> tuple[list[tuple[Any, Any, str]], list[Finding]]:
    """Match source documents to target documents by key.

    Returns ``(pairs, file_findings)`` where each pair is
    ``(source_doc, target_doc, key)``. Orphans and duplicate keys become
    file-level findings; missing source → ``missing_output``, missing
    target → ``unexpected_output``, duplicates → ``count_mismatch``.
    """
    from mapcheck.spec.parser import SpecLoadError

    findings: list[Finding] = []

    if source_key_ref is None or target_key_ref is None:
        if len(source_docs) == 1 and len(target_docs) == 1:
            return [(source_docs[0], target_docs[0], "#1")], findings
        raise SpecLoadError(
            [
                f"this interchange pairs {len(source_docs)} source document(s) with "
                f"{len(target_docs)} output document(s), but the spec declares no "
                "Pairing Key (source)/(target) in its Meta sheet — multi-document "
                "pairing cannot be done positionally"
            ]
        )

    def index(docs: list[Any], key_ref: str, label: str) -> dict[str, Any]:
        by_key: dict[str, Any] = {}
        seen: set[str] = set()
        for position, doc in enumerate(docs):
            key = _read_pairing_key(doc, key_ref)
            if key is None:
                findings.append(
                    Finding(
                        status=Status.FAIL,
                        category=Category.MISSING_OUTPUT,
                        source_ref=f"{label} #{position + 1}",
                        message=(
                            f"{label} document #{position + 1} has no pairing key "
                            f"({key_ref}) — cannot be paired"
                        ),
                    )
                )
                continue
            if key in by_key:
                if key not in seen:
                    seen.add(key)
                    findings.append(
                        Finding(
                            status=Status.FAIL,
                            category=Category.COUNT_MISMATCH,
                            source_ref=f"{label} key {key!r}",
                            message=(
                                f"two {label} documents share pairing key {key!r} — "
                                "keys must be unique within an interchange"
                            ),
                        )
                    )
                continue  # keep the first occurrence
            by_key[key] = doc
        return by_key

    source_by_key = index(source_docs, source_key_ref, source_label)
    target_by_key = index(target_docs, target_key_ref, target_label)

    pairs: list[tuple[Any, Any, str]] = []
    for key, source_doc in source_by_key.items():
        target_doc = target_by_key.get(key)
        if target_doc is None:
            findings.append(
                Finding(
                    status=Status.FAIL,
                    category=Category.MISSING_OUTPUT,
                    source_ref=f"{source_label} key {key!r}",
                    message=(
                        f"{source_label} document {key!r} has no matching {target_label} "
                        "document in the output"
                    ),
                )
            )
            continue
        pairs.append((source_doc, target_doc, key))
    for key in target_by_key:
        if key not in source_by_key:
            findings.append(
                Finding(
                    status=Status.FAIL,
                    category=Category.UNEXPECTED_OUTPUT,
                    source_ref=f"{target_label} key {key!r}",
                    message=(
                        f"{target_label} document {key!r} has no matching {source_label} "
                        "transaction in the source"
                    ),
                )
            )
    return pairs, findings


def validate_interchange(
    spec: MappingSpec,
    interchange: "Interchange",
    documents: list[CanonicalOutput],
    source_path: str,
    output_path: str,
) -> InterchangeResult:
    """Validate every paired (transaction, output document) in an interchange.

    ``interchange`` always holds the X12 transactions and ``documents`` the
    canonical output documents; the spec's direction decides which side is
    the pairing source. Each matched pair runs through :func:`validate`.
    """
    outbound = spec.direction is Direction.OUTBOUND
    x12_docs = interchange.documents
    src_key = spec.meta.get("Pairing Key (source)")
    tgt_key = spec.meta.get("Pairing Key (target)")

    if outbound:
        source_docs, target_docs = documents, x12_docs
        source_label, target_label = "source", "output"
    else:
        source_docs, target_docs = x12_docs, documents
        source_label, target_label = "source", "output"

    pairs, file_findings = _pair_documents(
        source_docs, target_docs, src_key, tgt_key, source_label, target_label
    )

    result = InterchangeResult(
        spec_path=spec.source_path or "",
        source_path=source_path,
        output_path=output_path,
        spec_name=spec.meta.get("Spec Name"),
    )
    for note in interchange.control_notes:
        result.file_findings.append(
            Finding(
                status=Status.WARNING,
                category=Category.CONTROL,
                source_ref="(envelope)",
                message=f"interchange control: {note}",
            )
        )
    result.file_findings.extend(file_findings)

    for source_doc, target_doc, key in pairs:
        tx = target_doc if outbound else source_doc
        canonical = source_doc if outbound else target_doc
        run = validate(
            spec, tx, canonical, source_path=source_path, output_path=output_path
        )
        st = tx.envelope.get("st_control", "")
        result.documents.append(
            DocumentResult(
                key=key,
                result=run,
                source_ref=f"ST {st}" if st else key,
                output_ref=key,
            )
        )
    return result


def validate_interchange_files(
    spec_path: str,
    source_path: str,
    output_path: str,
    transaction: str | None = None,
    output_format: str | None = None,
    spec: MappingSpec | None = None,
) -> InterchangeResult:
    """Load the artifacts and validate a whole interchange.

    Mirrors :func:`validate_files` but pairs many source transactions with
    many output documents. The spec's direction decides which side is X12.
    Pass a pre-loaded ``spec`` for a partner-override merged spec.
    """
    from mapcheck.output.adapter import load_output_documents
    from mapcheck.spec.parser import SpecLoadError, load_spec
    from mapcheck.transactions.registry import UnknownTransactionError, default_registry
    from mapcheck.x12.parser import X12ParseError, parse_interchange

    if spec is None:
        spec = load_spec(spec_path)
    definition = None
    if transaction is not None:
        try:
            definition = default_registry.get(transaction)
        except UnknownTransactionError as exc:
            raise X12ParseError(str(exc.args[0])) from exc

    outbound = spec.direction is Direction.OUTBOUND
    x12_path, x12_role = (output_path, "output") if outbound else (source_path, "source")
    interchange = parse_interchange(x12_path, definition=definition)
    if spec.transaction_set:
        mismatched = {
            d.definition.set_code
            for d in interchange.documents
            if d.definition.set_code != spec.transaction_set
        }
        if mismatched:
            raise SpecLoadError(
                [
                    f"spec is for transaction set {spec.transaction_set} but the {x12_role} "
                    f"interchange also contains: {', '.join(sorted(mismatched))}"
                ]
            )
    canonical_path = source_path if outbound else output_path
    documents = load_output_documents(canonical_path, output_format=output_format)
    return validate_interchange(
        spec, interchange, documents, source_path=str(source_path), output_path=str(output_path)
    )


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


# --------------------------------------------------------------------------
# Outbound rule evaluation: canonical source, X12 target
# --------------------------------------------------------------------------


def _x12_actual(rule: MappingRule, scope: Scope | None) -> Any:
    """Resolve the rule's X12 target element within a target scope.

    X12 cannot distinguish an empty element from an absent one, so both
    resolve to MISSING — which is why SKIP is fully testable on this side
    and BLANK is not.
    """
    if scope is None:
        return MISSING
    seg_id, element = split_source_field(rule.target_field)
    value = scope.value(seg_id, element)
    return MISSING if value is None else value


def _outbound_refs(
    rule: MappingRule, tx: TransactionDocument, line_index: int | None
) -> tuple[str, str]:
    """(source_ref, target) display labels for an outbound finding."""
    if line_index is None:
        return rule.source_ref(), rule.target_ref()
    line_loop = tx.line_loop_id or "line"
    source_ref = (
        rule.source_field.replace("[]", f"[{line_index}]")
        if rule.source_field
        else "(none)"
    )
    return source_ref, f"{line_loop} #{line_index + 1} {rule.target_field}"


def _evaluate_in_scope_out(
    rule: MappingRule,
    spec: MappingSpec,
    tx: TransactionDocument,
    output: CanonicalOutput,
    line_index: int | None,
    scope: Scope | None = None,
) -> Finding:
    """Evaluate one outbound rule against one X12 target scope."""
    if scope is None and not rule.is_per_line:
        scopes = tx.scopes(rule.loop_context)
        scope = scopes[0] if scopes else None

    fmt = parse_format(rule.format)
    expected = _expected_for(rule, spec, _CanonicalSource(output, line_index), fmt)
    actual = _x12_actual(rule, scope)
    source_ref, target = _outbound_refs(rule, tx, line_index)

    def normalize_target(value: Any, r: MappingRule, f: FormatSpec) -> tuple[Any, list[str]]:
        return normalize_x12(value, r.data_type, f)

    return _judge(
        rule,
        expected,
        actual,
        source_ref=source_ref,
        target=target,
        fmt=fmt,
        normalize_target=normalize_target,
        blank_testable=False,
    )


def _evaluate_per_line_out(
    rule: MappingRule,
    spec: MappingSpec,
    tx: TransactionDocument,
    output: CanonicalOutput,
) -> list[Finding]:
    """Evaluate an outbound per-line rule: lines[] entry n ↔ loop occurrence n."""
    assert rule.loop_context is not None
    pairing = tx.definition.output_pairing
    pairing_context = LoopContext.parse(pairing.loop) if pairing else None
    if pairing_context is None or rule.loop_context.base() != pairing_context:
        supported = pairing.loop if pairing else "(none declared)"
        return [
            Finding(
                status=Status.NOT_TESTED,
                row_id=rule.row_id,
                sheet_row=rule.sheet_row,
                source_ref=rule.source_ref(),
                target=rule.target_ref(),
                message=(
                    f"loop context {rule.loop_context} is not paired with the "
                    f"source {pairing.list_path if pairing else 'lines'}[] list — the "
                    f"{tx.definition.set_code} definition pairs lines[] with {supported}"
                ),
            )
        ]

    scopes = tx.scopes(rule.loop_context)
    source_count = output.line_count(pairing.list_path)
    findings: list[Finding] = []
    total = max(len(scopes), source_count)
    for index in range(total):
        scope = scopes[index] if index < len(scopes) else None
        if index >= source_count:
            actual = _x12_actual(rule, scope)
            if actual is not MISSING:
                _, target = _outbound_refs(rule, tx, index)
                findings.append(
                    Finding(
                        status=Status.FAIL,
                        category=Category.COUNT_MISMATCH,
                        row_id=rule.row_id,
                        sheet_row=rule.sheet_row,
                        source_ref=f"{pairing.list_path}[{index}] (absent)",
                        target=target,
                        actual=display(actual),
                        message=(
                            f"output {pairing.loop} loop {index + 1} has no matching "
                            f"{pairing.list_path}[] entry in the source "
                            f"(source has {source_count})"
                        ),
                    )
                )
            continue
        findings.append(_evaluate_in_scope_out(rule, spec, tx, output, index, scope=scope))
    return findings


def _evaluate_in_scope(
    rule: MappingRule,
    spec: MappingSpec,
    tx: TransactionDocument,
    output: CanonicalOutput,
    line_index: int | None,
    scope: Scope | None = None,
) -> Finding:
    """Evaluate one inbound rule in one concrete scope and produce its finding."""
    if scope is None and not rule.is_per_line:
        scopes = tx.scopes(rule.loop_context)
        scope = scopes[0] if scopes else None

    fmt = parse_format(rule.format)
    expected = _expected_for(rule, spec, _X12Source(tx, scope), fmt)
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

    def normalize_target(value: Any, r: MappingRule, f: FormatSpec) -> tuple[Any, list[str]]:
        return normalize_actual(value, r.data_type, f, output.typed)

    return _judge(
        rule,
        expected,
        actual,
        source_ref=source_ref,
        target=target,
        fmt=fmt,
        normalize_target=normalize_target,
    )


def _judge(
    rule: MappingRule,
    expected: _Expected,
    actual: Any,
    *,
    source_ref: str,
    target: str,
    fmt: FormatSpec,
    normalize_target: Any,
    blank_testable: bool = True,
) -> Finding:
    """The direction-agnostic decision table: expected vs. actual → finding.

    ``normalize_target`` converts the actual value per the target side's
    conventions; ``blank_testable`` is False on X12 targets, where empty
    and absent are indistinguishable and BLANK outcomes cannot be checked.
    """

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
        if not blank_testable:
            return finding(
                Status.NOT_TESTED,
                "BLANK outcome is not testable against an X12 target (an empty "
                "element and an absent one are indistinguishable)" + _why(expected.note),
            )
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
        normalized, warnings = normalize_target(actual, rule, fmt)
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

    tol_note = None
    if normalized != expected.value:
        if (
            fmt.tolerance is not None
            and isinstance(normalized, Decimal)
            and isinstance(expected.value, Decimal)
            and abs(normalized - expected.value) <= fmt.tolerance
        ):
            delta = abs(normalized - expected.value)
            tol_note = f"within tol:{display(fmt.tolerance)} (Δ{display(delta)})"
        else:
            return finding(
                Status.FAIL,
                f"expected {expected_text!r}, output has {display(normalized)!r}"
                + _why(expected.note),
                _MISMATCH_CATEGORY[rule.rule_type],
                expected_text=expected_text,
                actual_text=actual_text,
            )

    if warnings:
        extra = "; ".join(([tol_note] if tol_note else []) + warnings)
        return finding(
            Status.WARNING,
            "value matches, but " + extra,
            Category.FORMAT,
            expected_text=expected_text,
            actual_text=actual_text,
        )
    return finding(
        Status.PASS,
        ("ok" + (f" — {tol_note}" if tol_note else "")) + _why(expected.note),
        expected_text=expected_text,
        actual_text=actual_text,
    )


def _why(note: str) -> str:
    return f" ({note})" if note else ""


def _expected_for(
    rule: MappingRule,
    spec: MappingSpec,
    source: Any,
    fmt: FormatSpec,
) -> _Expected:
    """Derive the expected target value for one rule from its source reader."""
    if rule.rule_type is RuleType.CONSTANT:
        return _literal_expected(
            rule.default_value or "", rule, fmt, source, note="hardcoded constant"
        )

    if rule.rule_type is RuleType.LOOP_COUNT:
        count, note = source.loop_count(rule.source_field or "")
        return _Expected(kind="value", value=count, note=note)

    if rule.rule_type is RuleType.CONDITIONAL:
        assert rule.condition is not None and rule.then_outcome is not None
        branch_true = _evaluate_condition(rule.condition, source)
        outcome = rule.then_outcome if branch_true else rule.else_outcome
        assert outcome is not None
        note = f"condition {rule.condition.raw!r} is {'true' if branch_true else 'false'}"
        if outcome.kind is OutcomeKind.SKIP:
            return _Expected(kind="absent", note=note)
        if outcome.kind is OutcomeKind.BLANK:
            return _Expected(kind="empty", note=note)
        if outcome.kind is OutcomeKind.LITERAL:
            return _literal_expected(outcome.literal or "", rule, fmt, source, note=note)
        return _source_expected(rule, spec, source, fmt, note=note)  # SOURCE

    # DIRECT / CODE_LIST
    return _source_expected(rule, spec, source, fmt)


def _source_expected(
    rule: MappingRule,
    spec: MappingSpec,
    source: Any,
    fmt: FormatSpec,
    note: str = "",
) -> _Expected:
    """Expected value for rules that read the source document."""
    assert rule.source_field is not None
    raw = source.read(rule.source_field)

    if raw is None:
        if rule.default_value is not None:
            return _literal_expected(
                rule.default_value,
                rule,
                fmt,
                source,
                note=f"source {rule.source_field} empty, spec default applies",
            )
        return _Expected(kind="untestable", note=source.missing_reason(rule))

    if rule.rule_type is RuleType.CODE_LIST:
        assert rule.code_list_ref is not None
        code_list = spec.code_lists[rule.code_list_ref]
        translated = code_list.translate(raw if isinstance(raw, str) else str(raw))
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
            translated,
            rule,
            fmt,
            source,
            note=f"code list {rule.code_list_ref}: {raw!r} -> {translated!r}",
        )

    try:
        value = source.normalize(raw, rule, fmt)
    except NormalizationError as exc:
        return _Expected(kind="source_defect", note=f"{rule.source_field} {exc.reason}")
    if fmt.shift_days is not None and isinstance(value, date):
        value = value + timedelta(days=fmt.shift_days)
        shift_note = f"source date shifted {fmt.shift_days:+d}d"
        note = f"{note}; {shift_note}" if note else shift_note
    return _Expected(kind="value", value=value, note=note)


def _literal_expected(
    literal: str, rule: MappingRule, fmt: FormatSpec, source: Any, note: str = ""
) -> _Expected:
    """Expected value from a spec literal (constant, default, or Then/Else).

    The literal is normalized with the *target side's* conventions (the
    source reader knows which those are), so it lands comparable with the
    normalized actual value.
    """
    try:
        value = source.normalize_literal(literal, rule, fmt)
    except NormalizationError as exc:
        return _Expected(
            kind="source_defect",
            note=f"spec literal {literal!r} does not fit the declared format: {exc.reason}",
        )
    return _Expected(kind="value", value=value, note=note)


def _evaluate_condition(condition: Condition, source: Any) -> bool:
    """Evaluate AND-joined predicates against the source reader.

    Fields resolve within the rule's evaluation scope; a missing scope or
    element reads as empty, so ``EXISTS`` is false and ``=`` compares
    against the empty string.
    """
    for predicate in condition.predicates:
        value = source.condition_value(predicate.field)
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


def _check_line_counts_out(
    tx: TransactionDocument, output: CanonicalOutput, result: RunResult
) -> None:
    """Outbound mirror: internal lines[] entries vs. X12 pairing-loop count."""
    pairing = tx.definition.output_pairing
    if pairing is None:
        return
    source_count = output.line_count(pairing.list_path)
    output_count = len(tx.scopes(LoopContext.parse(pairing.loop)))
    if source_count != output_count:
        result.findings.append(
            Finding(
                status=Status.FAIL,
                category=Category.COUNT_MISMATCH,
                source_ref=f"{pairing.list_path}[] entries",
                target=f"{pairing.loop} loops",
                expected=str(source_count),
                actual=str(output_count),
                message=(
                    f"source has {source_count} {pairing.list_path}[] entry(ies) but "
                    f"the output has {output_count} {pairing.loop} loop(s)"
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


def _check_reconciliation(
    tx: TransactionDocument, result: RunResult, side: str = "source"
) -> None:
    """Run the definition's declarative X12-side reconciliation rules.

    Rules are silent when they pass or cannot be evaluated; a mismatch
    emits a finding at the rule's declared severity. ``side`` names the
    document in messages: the X12 file is the source inbound and the
    produced output outbound (where these checks audit the produced
    file's internal consistency).
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
        if rule.check in ("not_after", "not_greater"):
            # ordering checks: dates (CCYYMMDD compares correctly as a
            # number) or counts/amounts; same math, different wording
            if not (isinstance(left_value, Decimal) and isinstance(right_value, Decimal)):
                continue
            violated = left_value > right_value
            relation = "must not be after" if rule.check == "not_after" else "must not exceed"
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
                        + f"{side} reconciliation failed: {left_text} {relation} {right_text}"
                    ),
                )
            )



def _x12_fields_inbound(rule: MappingRule) -> list[str]:
    """The X12 element refs an inbound rule reads: source + condition fields."""
    fields: list[str] = []
    if rule.source_field and rule.rule_type is not RuleType.LOOP_COUNT:
        fields.append(rule.source_field)
    if rule.condition is not None:
        fields.extend(predicate.field for predicate in rule.condition.predicates)
    return fields


def _x12_fields_outbound(rule: MappingRule) -> list[str]:
    """The X12 element ref an outbound rule produces: its target."""
    return [rule.target_field]


def _referenced_elements(
    spec: MappingSpec,
    tx: TransactionDocument,
    fields_for: Any = _x12_fields_inbound,
) -> set[tuple[int, int]]:
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
            for field in fields_for(rule):
                mark_all(scope, field)
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


def _check_unmapped_source_out(
    spec: MappingSpec, output: CanonicalOutput, result: RunResult
) -> None:
    """Outbound mirror of rule 7a: internal source data no rule references.

    LOOP_COUNT sources reference the list itself, not its leaves, so they
    do not mark anything here.
    """
    referenced: set[str] = set()
    for rule in spec.rules:
        if rule.source_field and rule.rule_type is not RuleType.LOOP_COUNT:
            referenced.add(rule.source_field)
        if rule.condition is not None:
            referenced.update(predicate.field for predicate in rule.condition.predicates)
    for normalized, concrete, value in output.walk_paths():
        if normalized not in referenced:
            result.findings.append(
                Finding(
                    status=Status.WARNING,
                    category=Category.UNMAPPED_SOURCE,
                    source_ref=concrete,
                    message=(
                        "source field is not referenced by any spec rule "
                        f"(value {display(value)!r})"
                    ),
                )
            )


def _check_unmapped_target_out(
    spec: MappingSpec, tx: TransactionDocument, result: RunResult
) -> None:
    """Outbound mirror of rule 7b: X12 output data no rule produces."""
    referenced = _referenced_elements(spec, tx, fields_for=_x12_fields_outbound)
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
                    category=Category.UNMAPPED_TARGET,
                    target=f"{label} {segment.seg_id}",
                    message=(
                        "output data not produced by any spec rule: "
                        + ", ".join(unreferenced)
                    ),
                )
            )
