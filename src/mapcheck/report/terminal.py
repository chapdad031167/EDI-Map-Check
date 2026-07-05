"""Plain-text / ANSI terminal rendering of a validation run."""

from __future__ import annotations

import sys

from mapcheck.engine.results import Finding, RunResult, Status

_ANSI = {
    Status.PASS: "\033[32m",
    Status.FAIL: "\033[31m",
    Status.WARNING: "\033[33m",
    Status.NOT_TESTED: "\033[90m",
}
_RESET = "\033[0m"
_BOLD = "\033[1m"


def _color(text: str, code: str, enabled: bool) -> str:
    return f"{code}{text}{_RESET}" if enabled else text


def _format_finding(finding: Finding, color: bool) -> str:
    status = _color(f"{finding.status.value:<10}", _ANSI[finding.status], color)
    row = finding.row_id or "-"
    location = finding.target or finding.source_ref or "-"
    detail = finding.message
    if finding.expected is not None and finding.status is Status.FAIL:
        detail = f"expected={finding.expected!r} actual={finding.actual!r} — {finding.message}"
    return f"{status} {row:<7} {location:<32} {detail}"


def render_report(
    result: RunResult,
    verbose: bool = False,
    color: bool | None = None,
) -> str:
    """Render the run as a terminal report string.

    ``verbose`` includes PASS rows; ``color`` defaults to auto-detection
    from stdout.
    """
    if color is None:
        color = sys.stdout.isatty()

    lines: list[str] = []
    lines.append(_color("EDI MapCheck — validation report", _BOLD, color))
    if result.transaction_set:
        name = f" — {result.transaction_name}" if result.transaction_name else ""
        lines.append(f"Transaction: {result.transaction_set}{name}")
    if result.spec_name:
        lines.append(f"Spec:   {result.spec_path} ({result.spec_name})")
    else:
        lines.append(f"Spec:   {result.spec_path}")
    lines.append(f"Source: {result.source_path}")
    lines.append(f"Output: {result.output_path}")
    lines.append("")

    shown = [
        f
        for f in result.sorted_findings()
        if verbose or f.status is not Status.PASS
    ]
    if shown:
        header = f"{'STATUS':<10} {'ROW':<7} {'FIELD':<32} DETAIL"
        lines.append(_color(header, _BOLD, color))
        lines.extend(_format_finding(f, color) for f in shown)
    else:
        lines.append("No findings to show (all rules passed; use --verbose for detail).")
    lines.append("")

    counts = result.counts
    summary = " / ".join(
        _color(f"{counts[status]} {status.value}", _ANSI[status], color) for status in Status
    )
    overall = _color(
        f"RESULT: {result.overall.value}", _ANSI[result.overall] + _BOLD, color
    )
    lines.append(f"Summary: {summary} — {overall}")

    if categories := result.category_counts:
        parts = ", ".join(f"{cat.value}: {n}" for cat, n in categories.items())
        lines.append(f"Root causes: {parts}")
    return "\n".join(lines)
