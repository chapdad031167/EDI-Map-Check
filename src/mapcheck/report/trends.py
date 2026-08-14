"""History-trends aggregation (design 010), shared by the HTML export and
Streamlit so the two never drift.

Everything here is computed from the ``runs`` + ``findings`` history tables;
no new schema. Trends group by spec file — "how healthy is each map?".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mapcheck.report.history import RunHistory

#: Ordinal for a result string, worst first (for sorting specs).
_RESULT_RANK = {"FAIL": 0, "WARNING": 1, "PASS": 2}


@dataclass
class SpecTrend:
    """Trend for one spec file across its recent top-level runs."""

    spec: str  # file name, plus the partner delta when one was applied
    runs: list[dict]  # chronological (oldest → newest)

    @property
    def total(self) -> int:
        return len(self.runs)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.runs if r["result"] == "PASS")

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def latest(self) -> str:
        return self.runs[-1]["result"] if self.runs else "PASS"

    def series(self) -> list[str]:
        """Result per run, oldest → newest (for a sparkline)."""
        return [r["result"] for r in self.runs]


@dataclass
class Trends:
    specs: list[SpecTrend] = field(default_factory=list)
    top_categories: list[tuple[str, int]] = field(default_factory=list)
    total_runs: int = 0
    distinct_specs: int = 0

    @property
    def overall_pass_rate(self) -> float:
        passed = sum(s.passed for s in self.specs)
        return passed / self.total_runs if self.total_runs else 0.0

    @property
    def is_empty(self) -> bool:
        return self.total_runs == 0


def _spec_label(run: dict) -> str:
    """How a run is grouped and shown in the trends table.

    Runs group by file name, not path: the UI's uploads land in a fresh
    temp directory every time, so the path is not stable enough to group
    on. The partner delta belongs in that name — one base spec validated
    under two partners is two different checks, and pooling them averages
    a failing partner into a passing one until neither is visible.
    """
    spec = Path(run["spec_file"]).name
    partner = run.get("partner_file")
    return f"{spec} + {Path(partner).name}" if partner else spec


def compute_trends(history: RunHistory, limit: int = 200) -> Trends:
    """Aggregate recent history into per-spec pass-rate + top root causes."""
    runs = history.recent_runs(limit=limit)
    # Top-level runs only (a standalone run or an interchange parent); child
    # per-document rows carry an interchange_id and are rolled into the parent.
    top_level = [r for r in runs if r.get("interchange_id") is None]

    by_spec: dict[str, list[dict]] = {}
    for run in top_level:
        by_spec.setdefault(_spec_label(run), []).append(run)

    specs: list[SpecTrend] = []
    for name, spec_runs in by_spec.items():
        # recent_runs is newest-first; a sparkline reads oldest → newest.
        specs.append(SpecTrend(spec=name, runs=list(reversed(spec_runs))))
    specs.sort(key=lambda s: (_RESULT_RANK.get(s.latest, 3), -s.total, s.spec))

    # Top root causes: category counts across every recorded non-PASS finding
    # in the window (children included, so interchange documents count).
    categories: dict[str, int] = {}
    for run in runs:
        for finding in history.findings_for(run["id"]):
            cat = finding.get("category")
            if cat and finding.get("status") != "PASS":
                categories[cat] = categories.get(cat, 0) + 1
    top_categories = sorted(categories.items(), key=lambda kv: (-kv[1], kv[0]))

    return Trends(
        specs=specs,
        top_categories=top_categories,
        total_runs=len(top_level),
        distinct_specs=len(by_spec),
    )
