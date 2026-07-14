"""Batch / CI mode (design 008): run many checks from a ``mapcheck.yaml``.

A manifest lists the arguments each ordinary ``validate`` (or ``regress``)
run already takes. ``run_batch`` executes them in order, records each in the
history DB, and returns a :class:`BatchResult` the CLI renders as a roll-up
and (optionally) a JUnit-XML report. Nothing in the engine changes — this is
pure orchestration over ``validate_files`` / ``validate_interchange_files``
and regression mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, quoteattr

import yaml

from mapcheck.engine import Status, validate_files, validate_interchange_files
from mapcheck.output.adapter import OutputLoadError
from mapcheck.output.idoc import DefinitionError
from mapcheck.report.history import RunHistory
from mapcheck.spec.parser import SpecLoadError, load_spec
from mapcheck.x12.parser import X12ParseError

_EXEC_ERRORS = (SpecLoadError, X12ParseError, OutputLoadError, DefinitionError, OSError)

#: Recognized keys on a manifest check (anything else is an error).
_CHECK_KEYS = {
    "name", "spec", "source", "output", "partner", "transaction",
    "output-def", "regress", "label",
}
_REQUIRED = ("name", "spec", "source", "output")


class ManifestError(Exception):
    """Raised when a ``mapcheck.yaml`` cannot be loaded."""


@dataclass(frozen=True)
class Check:
    """One manifest entry: a single validation (or regression) to run."""

    name: str
    spec: str
    source: str
    output: str
    partner: str | None = None
    transaction: str | None = None
    output_def: str | None = None
    regress: bool = False
    label: str | None = None


@dataclass
class Manifest:
    checks: list[Check]
    db: str | None = None


def _resolve(base: Path, value: str | None) -> str | None:
    if value is None:
        return None
    p = Path(value)
    return str(p if p.is_absolute() else base / p)


def load_manifest(path: str | Path) -> Manifest:
    """Parse and validate a ``mapcheck.yaml``; resolve paths relative to it."""
    path = Path(path)
    if not path.exists():
        raise ManifestError(f"manifest not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ManifestError(f"{path.name}: invalid YAML: {exc}") from None
    if not isinstance(data, dict):
        raise ManifestError(f"{path.name}: top level must be a mapping with 'checks'")

    base = path.parent
    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ManifestError(f"{path.name}: 'defaults' must be a mapping")
    raw_checks = data.get("checks")
    if not isinstance(raw_checks, list) or not raw_checks:
        raise ManifestError(f"{path.name}: 'checks' must be a non-empty list")

    checks: list[Check] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_checks, start=1):
        if not isinstance(raw, dict):
            raise ManifestError(f"{path.name}: check #{i} must be a mapping")
        unknown = set(raw) - _CHECK_KEYS
        if unknown:
            raise ManifestError(
                f"{path.name}: check #{i} has unknown key(s): {', '.join(sorted(unknown))}"
            )
        for key in _REQUIRED:
            if not raw.get(key):
                raise ManifestError(f"{path.name}: check #{i} is missing required '{key}'")
        name = str(raw["name"])
        if name in seen:
            raise ManifestError(f"{path.name}: duplicate check name {name!r}")
        seen.add(name)
        checks.append(
            Check(
                name=name,
                spec=_resolve(base, raw["spec"]),  # type: ignore[arg-type]
                source=_resolve(base, raw["source"]),  # type: ignore[arg-type]
                output=_resolve(base, raw["output"]),  # type: ignore[arg-type]
                partner=_resolve(base, raw.get("partner")),
                transaction=raw.get("transaction"),
                output_def=_resolve(base, raw.get("output-def")),
                regress=bool(raw.get("regress", False)),
                label=raw.get("label"),
            )
        )

    db = defaults.get("db")
    return Manifest(checks=checks, db=_resolve(base, db) if db else None)


@dataclass
class CheckOutcome:
    """The result of running one check."""

    name: str
    classname: str
    status: str  # "pass" | "fail" | "error"
    counts: dict[Status, int] = field(default_factory=dict)
    detail: str = ""  # failure/error body for the report and JUnit
    error: str | None = None

    @property
    def is_error(self) -> bool:
        return self.status == "error"

    @property
    def is_fail(self) -> bool:
        return self.status == "fail"


@dataclass
class BatchResult:
    outcomes: list[CheckOutcome]

    @property
    def exit_code(self) -> int:
        # An execution error means results are incomplete → 2 wins over 1.
        if any(o.is_error for o in self.outcomes):
            return 2
        if any(o.is_fail for o in self.outcomes):
            return 1
        return 0

    @property
    def totals(self) -> dict[str, int]:
        return {
            "tests": len(self.outcomes),
            "failures": sum(o.is_fail for o in self.outcomes),
            "errors": sum(o.is_error for o in self.outcomes),
        }


def _summarize(counts: dict[Status, int], category_counts: dict[Any, int]) -> str:
    roots = ", ".join(f"{c.value}: {n}" for c, n in category_counts.items())
    line = (
        f"{counts[Status.FAIL]} FAIL / {counts[Status.WARNING]} WARNING / "
        f"{counts[Status.PASS]} PASS"
    )
    return f"{line}\nRoot causes: {roots}" if roots else line


def _run_validate(check: Check, history: RunHistory | None) -> CheckOutcome:
    from mapcheck.cli import _is_interchange

    merged = None
    output_format = None
    if check.output_def:
        from mapcheck.output.idoc import register_output_definition

        output_format = register_output_definition(check.output_def).format
    if check.partner:
        from mapcheck.spec.overrides import resolve_spec

        merged, _ = resolve_spec(check.spec, check.partner)
        spec = merged
    else:
        spec = load_spec(check.spec)

    classname = spec.transaction_set or "validate"
    if _is_interchange(spec, check.source, check.output):
        result = validate_interchange_files(
            check.spec, check.source, check.output,
            transaction=check.transaction, output_format=output_format, spec=merged,
        )
        if history is not None:
            history.record_interchange(result)
    else:
        result = validate_files(
            check.spec, check.source, check.output,
            transaction=check.transaction, output_format=output_format, spec=merged,
        )
        if history is not None:
            history.record(result)

    counts = result.counts
    status = "fail" if result.overall is Status.FAIL else "pass"
    detail = _summarize(counts, result.category_counts) if status == "fail" else ""
    return CheckOutcome(check.name, classname, status, counts, detail)


def _run_regress(check: Check, history: RunHistory) -> CheckOutcome:
    from mapcheck.cli import _is_interchange
    from mapcheck.report.regression import baseline_key, format_delta, regress

    merged = None
    if check.partner:
        from mapcheck.spec.overrides import resolve_spec

        merged, _ = resolve_spec(check.spec, check.partner)
        spec = merged
    else:
        spec = load_spec(check.spec)
    classname = spec.transaction_set or "regress"

    interchange = _is_interchange(spec, check.source, check.output)
    if interchange:
        result = validate_interchange_files(
            check.spec, check.source, check.output,
            transaction=check.transaction, spec=merged,
        )
        current_id = history.record_interchange(result)
    else:
        result = validate_files(
            check.spec, check.source, check.output,
            transaction=check.transaction, spec=merged,
        )
        current_id = history.record(result)

    key = check.label or baseline_key(check.spec, check.source, check.output, check.partner)
    baseline = history.baseline_for(key)
    if baseline is None:
        return CheckOutcome(
            check.name, classname, "pass", result.counts,
            detail=f"no baseline yet — bless run #{current_id} to establish one",
        )
    delta = regress(history, baseline["run_id"], current_id)
    if delta.is_regression:
        return CheckOutcome(
            check.name, classname, "fail", result.counts,
            detail=format_delta(delta, color=False),
        )
    return CheckOutcome(check.name, classname, "pass", result.counts)


def run_batch(
    manifest: Manifest, db: str, strict: bool = False, record: bool = True
) -> BatchResult:
    """Run every check in order; never abort on one check's failure."""
    outcomes: list[CheckOutcome] = []
    history = RunHistory(db) if (record or any(c.regress for c in manifest.checks)) else None
    try:
        for check in manifest.checks:
            try:
                if check.regress:
                    assert history is not None
                    outcome = _run_regress(check, history)
                else:
                    outcome = _run_validate(check, history if record else None)
            except _EXEC_ERRORS as exc:
                outcome = CheckOutcome(
                    check.name, "error", "error", detail=str(exc), error=str(exc)
                )
            if strict and outcome.status == "pass" and outcome.counts.get(Status.WARNING):
                outcome.status = "fail"
                warn = outcome.counts[Status.WARNING]
                extra = f"--strict: {warn} warning(s) promoted to failure"
                outcome.detail = f"{outcome.detail}\n{extra}" if outcome.detail else extra
            outcomes.append(outcome)
    finally:
        if history is not None:
            history.close()
    return BatchResult(outcomes)


_STATUS_LABEL = {"pass": "PASS", "fail": "FAIL", "error": "ERROR"}


def format_report(result: BatchResult, color: bool | None = None) -> str:
    """A roll-up table over the checks, ending in a one-line verdict."""
    use_color = color if color is not None else False
    codes = {"PASS": "32", "FAIL": "31", "ERROR": "33"}

    def paint(text: str, key: str) -> str:
        return f"\033[{codes[key]}m{text}\033[0m" if use_color else text

    lines = ["EDI MapCheck — batch report", ""]
    width = max((len(o.name) for o in result.outcomes), default=4)
    for o in result.outcomes:
        label = _STATUS_LABEL[o.status]
        counts = o.counts
        tally = (
            f"{counts.get(Status.FAIL, 0)}F / {counts.get(Status.WARNING, 0)}W / "
            f"{counts.get(Status.PASS, 0)}P"
            if counts else "-"
        )
        lines.append(f"  {paint(label, label):<6}  {o.name:<{width}}  {tally}")
        if o.detail and o.status != "pass":
            for d in o.detail.splitlines():
                lines.append(f"          {d}")
    totals = result.totals
    lines.append("")
    verdict = (
        f"{totals['tests']} checks — {totals['failures']} failed, "
        f"{totals['errors']} errored (exit {result.exit_code})"
    )
    key = "PASS" if result.exit_code == 0 else ("ERROR" if result.exit_code == 2 else "FAIL")
    lines.append(paint(verdict, key))
    return "\n".join(lines)


def to_junit(result: BatchResult, name: str = "mapcheck") -> str:
    """Render the batch result as a JUnit-XML document (one testcase/check)."""
    totals = result.totals
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<testsuite name={quoteattr(name)} tests="{totals["tests"]}" '
        f'failures="{totals["failures"]}" errors="{totals["errors"]}">',
    ]
    for o in result.outcomes:
        attrs = f"name={quoteattr(o.name)} classname={quoteattr(o.classname)}"
        if o.status == "pass":
            parts.append(f"  <testcase {attrs}/>")
        elif o.status == "fail":
            parts.append(f"  <testcase {attrs}>")
            parts.append(
                f'    <failure message={quoteattr(_first_line(o.detail))}>'
                f"{escape(o.detail)}</failure>"
            )
            parts.append("  </testcase>")
        else:  # error
            parts.append(f"  <testcase {attrs}>")
            parts.append(
                f'    <error message={quoteattr(_first_line(o.error or o.detail))}>'
                f"{escape(o.detail)}</error>"
            )
            parts.append("  </testcase>")
    parts.append("</testsuite>")
    return "\n".join(parts) + "\n"


def _first_line(text: str) -> str:
    return (text or "").splitlines()[0] if text else ""
