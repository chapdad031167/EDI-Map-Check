"""Regression mode (design 006): diff a run against a blessed baseline.

A *baseline* is a known-good recorded run (see ``RunHistory.bless``). A
regression run re-validates the same inputs, records itself like any other
run, then diffs its findings against the baseline's and reports **only the
delta** — new failures, resolved failures, changed values, and added/removed
documents — exiting nonzero when something regressed.

Everything here works on findings already stored in the history DB, so a
regression is a pure history-layer comparison; the engine is untouched.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from mapcheck.report.history import RunHistory

# Delta classes -------------------------------------------------------------
NEW = "NEW"
RESOLVED = "RESOLVED"
CHANGED = "CHANGED"
DOC_ADDED = "DOC ADDED"
DOC_REMOVED = "DOC REMOVED"

_BAD_STATUSES = {"FAIL", "WARNING"}


def _escape_part(part: str) -> str:
    """Percent-escape the separator so a path cannot forge one.

    ``|`` is legal in a POSIX filename, and a raw join lets one path's
    pipe pass for the boundary between two: ``("a|b", "c")`` and
    ``("a", "b|c")`` produce the same key, which would hand one
    validation another's baseline. Escaping ``%`` first keeps the
    mapping reversible. Only a path containing ``%`` or ``|`` changes
    shape, so keys blessed for ordinary paths keep matching.
    """
    return part.replace("%", "%25").replace("|", "%7C")


def baseline_key(spec: str, source: str, output: str, partner: str | None = None) -> str:
    """The normalized ``spec|source|output[|partner]`` that identifies which
    validation two runs share, so a re-run of the same inputs finds its
    baseline. ``--label`` overrides this when paths differ across machines."""
    parts = [os.path.normpath(spec), os.path.normpath(source), os.path.normpath(output)]
    if partner:
        parts.append(os.path.normpath(partner))
    return "|".join(_escape_part(p) for p in parts)


def _identity(
    document_key: str, finding: dict[str, Any], occurrence: int = 0
) -> tuple[str, str, str, int]:
    """Stable location of a check: (document, rule row, target or source).

    ``occurrence`` separates findings that share all three. File-level
    findings — envelope reconciliation, truncation — carry no row id, no
    target and no source ref, so every one of them lands on the same
    triple; numbering the repeats keeps them apart. It stays 0 for any
    finding whose location is already unique, which is all of them once
    a rule row is involved.
    """
    return (
        document_key,
        finding.get("row_id") or "",
        finding.get("target") or finding.get("source_ref") or "",
        occurrence,
    )


def _by_identity(
    document_key: str, findings: list[dict[str, Any]]
) -> dict[tuple[str, str, str, int], dict[str, Any]]:
    """Index findings by identity, numbering any that share a location.

    Building this map by plain comprehension let a repeated location
    overwrite itself and kept only the last, so a file-level FAIL sitting
    beside other file-level findings never reached the diff at all.
    Findings are stored and read back in the engine's sort order, so the
    same check draws the same number in both runs.
    """
    table: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    counts: Counter[tuple[str, str, str, int]] = Counter()
    for finding in findings:
        base = _identity(document_key, finding)
        table[_identity(document_key, finding, counts[base])] = finding
        counts[base] += 1
    return table


def _payload(finding: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    """The outcome compared within a matched identity (never the message)."""
    return (
        finding.get("status"),
        finding.get("category"),
        finding.get("expected"),
        finding.get("actual"),
    )


@dataclass(frozen=True)
class Change:
    """One entry in a regression delta."""

    kind: str  # NEW / RESOLVED / CHANGED / DOC ADDED / DOC REMOVED
    document_key: str
    identity: tuple[str, str, str, int] | None
    baseline: dict[str, Any] | None
    current: dict[str, Any] | None
    regression: bool
    detail: str

    @property
    def where(self) -> str:
        """Human-readable location for the report."""
        if self.identity is None:
            return self.document_key or "(interchange)"
        _, row_id, ref, occurrence = self.identity
        # A file-level finding has no row or ref to name it by; say which
        # one it is rather than print a bare "?" for every one of them.
        loc = row_id or ref or f"file-level #{occurrence + 1}"
        if self.document_key:
            return f"{self.document_key} · {loc}"
        return loc


@dataclass
class RegressionDelta:
    """The full delta between a baseline run and a current run."""

    baseline_run_id: int
    current_run_id: int
    changes: list[Change] = field(default_factory=list)

    @property
    def regressions(self) -> list[Change]:
        return [c for c in self.changes if c.regression]

    @property
    def is_regression(self) -> bool:
        return bool(self.regressions)

    @property
    def is_empty(self) -> bool:
        return not self.changes

    @property
    def exit_code(self) -> int:
        return 1 if self.is_regression else 0

    def of_kind(self, kind: str) -> list[Change]:
        return [c for c in self.changes if c.kind == kind]


def _describe(baseline: dict[str, Any] | None, current: dict[str, Any] | None) -> str:
    """A compact 'was X, now Y' for the fields that differ."""
    if baseline is None:
        return (current or {}).get("status", "") or ""
    if current is None:
        return (baseline or {}).get("status", "") or ""
    bits: list[str] = []
    for label, key in (("status", "status"), ("category", "category"),
                       ("expected", "expected"), ("actual", "actual")):
        was, now = baseline.get(key), current.get(key)
        if was != now:
            bits.append(f"{label}: {was!r} -> {now!r}")
    return "; ".join(bits)


def diff_snapshots(
    baseline: dict[str, list[dict[str, Any]]],
    current: dict[str, list[dict[str, Any]]],
) -> list[Change]:
    """Classify the difference between two ``RunHistory.snapshot`` dicts.

    Keyed by ``document_key`` (``""`` = file-level / single document). A
    non-empty document key present on only one side is a DOC ADDED/REMOVED;
    within a shared document, findings are matched on their stable identity
    and their outcome compared.
    """
    changes: list[Change] = []
    baseline_docs = set(baseline)
    current_docs = set(current)

    # Whole-document add/remove (empty key is always present, never a doc move).
    for doc_key in sorted(current_docs - baseline_docs):
        if doc_key:
            changes.append(Change(DOC_ADDED, doc_key, None, None, None, False,
                                  "document not in baseline"))
    for doc_key in sorted(baseline_docs - current_docs):
        if doc_key:
            changes.append(Change(DOC_REMOVED, doc_key, None, None, None, True,
                                  "document present in baseline, gone now"))

    # Finding-level diff within each shared document.
    for doc_key in sorted(baseline_docs & current_docs):
        base_by_id = _by_identity(doc_key, baseline[doc_key])
        curr_by_id = _by_identity(doc_key, current[doc_key])

        for identity, curr in curr_by_id.items():
            base = base_by_id.get(identity)
            if base is None:
                # New location: only a new FAIL/WARNING is worth reporting.
                if curr["status"] in _BAD_STATUSES:
                    changes.append(Change(
                        NEW, doc_key, identity, None, curr,
                        regression=curr["status"] == "FAIL",
                        detail=_describe(None, curr)))
                continue
            if _payload(base) == _payload(curr):
                continue  # identical outcome — silent
            if base["status"] in _BAD_STATUSES and curr["status"] == "PASS":
                changes.append(Change(
                    RESOLVED, doc_key, identity, base, curr, False,
                    _describe(base, curr)))
            else:
                changes.append(Change(
                    CHANGED, doc_key, identity, base, curr,
                    regression=curr["status"] == "FAIL" and base["status"] != "FAIL",
                    detail=_describe(base, curr)))

        for identity, base in base_by_id.items():
            if identity in curr_by_id:
                continue
            # Location gone from the current run: a resolved defect if it had
            # been failing/warning; a vanished PASS is not a regression.
            if base["status"] in _BAD_STATUSES:
                changes.append(Change(
                    RESOLVED, doc_key, identity, base, None, False,
                    _describe(base, None)))

    return changes


_ORDER = {DOC_REMOVED: 0, NEW: 1, CHANGED: 2, DOC_ADDED: 3, RESOLVED: 4}


def regress(history: RunHistory, baseline_run_id: int, current_run_id: int) -> RegressionDelta:
    """Diff a recorded current run against a recorded baseline run."""
    changes = diff_snapshots(
        history.snapshot(baseline_run_id), history.snapshot(current_run_id)
    )
    changes.sort(key=lambda c: (_ORDER.get(c.kind, 9), c.document_key, c.where))
    return RegressionDelta(baseline_run_id, current_run_id, changes)


def format_delta(delta: RegressionDelta, color: bool | None = None) -> str:
    """Render a regression delta as a grouped report ending in a verdict."""
    use_color = _want_color(color)

    def paint(text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if use_color else text

    lines: list[str] = []
    lines.append(
        f"Regression: run #{delta.current_run_id} vs baseline run "
        f"#{delta.baseline_run_id}"
    )
    if delta.is_empty:
        lines.append("")
        lines.append(paint("  No changes — output matches the baseline.", "32"))
        lines.append("")
        lines.append(paint("VERDICT: no regression (exit 0)", "32"))
        return "\n".join(lines)

    palette = {
        DOC_REMOVED: "31", NEW: "31", CHANGED: "33", DOC_ADDED: "36", RESOLVED: "32",
    }
    for kind in (DOC_REMOVED, NEW, CHANGED, DOC_ADDED, RESOLVED):
        group = delta.of_kind(kind)
        if not group:
            continue
        lines.append("")
        lines.append(paint(f"{kind} ({len(group)})", palette[kind]))
        for change in group:
            flag = paint(" ⚠ regression", "31") if change.regression else ""
            detail = f" — {change.detail}" if change.detail else ""
            lines.append(f"  {change.where}{detail}{flag}")

    lines.append("")
    if delta.is_regression:
        lines.append(paint(
            f"VERDICT: REGRESSION — {len(delta.regressions)} regressing "
            f"change(s) (exit 1)", "31"))
    else:
        lines.append(paint(
            "VERDICT: changes present, none regressing (exit 0)", "33"))
    return "\n".join(lines)


def _want_color(color: bool | None) -> bool:
    if color is not None:
        return color
    import sys

    return sys.stdout.isatty()
