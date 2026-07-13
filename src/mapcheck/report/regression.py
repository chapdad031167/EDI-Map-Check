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


def baseline_key(spec: str, source: str, output: str, partner: str | None = None) -> str:
    """The normalized ``spec|source|output[|partner]`` that identifies which
    validation two runs share, so a re-run of the same inputs finds its
    baseline. ``--label`` overrides this when paths differ across machines."""
    parts = [os.path.normpath(spec), os.path.normpath(source), os.path.normpath(output)]
    if partner:
        parts.append(os.path.normpath(partner))
    return "|".join(parts)


def _identity(document_key: str, finding: dict[str, Any]) -> tuple[str, str, str]:
    """Stable location of a check: (document, rule row, target or source)."""
    return (
        document_key,
        finding.get("row_id") or "",
        finding.get("target") or finding.get("source_ref") or "",
    )


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
    identity: tuple[str, str, str] | None
    baseline: dict[str, Any] | None
    current: dict[str, Any] | None
    regression: bool
    detail: str

    @property
    def where(self) -> str:
        """Human-readable location for the report."""
        if self.identity is None:
            return self.document_key or "(interchange)"
        _, row_id, ref = self.identity
        loc = row_id or ref or "?"
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
        base_by_id = {_identity(doc_key, f): f for f in baseline[doc_key]}
        curr_by_id = {_identity(doc_key, f): f for f in current[doc_key]}

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
