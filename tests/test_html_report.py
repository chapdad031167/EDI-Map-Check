"""Shareable HTML reporting + trends (design 010).

Covers the single-run and interchange HTML renderers (self-contained,
escaping, badge, collapsed PASS rows), the trends aggregation shared with
Streamlit, the trends HTML, and the CLI (`--export-html`, `mapcheck report`).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from mapcheck.cli import main
from mapcheck.engine import Status, validate_files
from mapcheck.engine.results import Category, Finding, RunResult
from mapcheck.report.history import RunHistory
from mapcheck.report.html import (
    export_html,
    render_interchange_html,
    render_run_html,
    render_trends_html,
)
from mapcheck.report.trends import compute_trends

SPEC = "850_reference_spec.xlsx"
SRC = "850_baseline.edi"

_EXTERNAL = re.compile(r"https?://|src\s*=|<script", re.I)


def _run(examples_dir, output):
    return validate_files(
        str(examples_dir / "specs" / SPEC),
        str(examples_dir / "source" / SRC),
        str(examples_dir / "output" / output),
    )


# ---------------------------------------------------------------------------
# single-run report
# ---------------------------------------------------------------------------


class TestRunReport:
    def test_self_contained(self, examples_dir):
        html = render_run_html(_run(examples_dir, "po_baseline_defects.json"))
        assert html.startswith("<!doctype html>")
        assert not _EXTERNAL.search(html)  # nothing fetched from the network

    def test_fail_badge_and_root_causes(self, examples_dir):
        html = render_run_html(_run(examples_dir, "po_baseline_defects.json"))
        assert 'class="badge fail big"' in html
        assert "value_mismatch" in html and "missing_output" in html

    def test_clean_run_pass_badge(self, examples_dir):
        html = render_run_html(_run(examples_dir, "po_baseline.json"))
        assert 'class="badge pass big"' in html

    def test_pass_rows_collapsed(self, examples_dir):
        html = render_run_html(_run(examples_dir, "po_baseline_defects.json"))
        assert "<details>" in html
        assert re.search(r"<summary>\d+ passing check\(s\)</summary>", html)

    def test_escapes_untrusted_values(self):
        result = RunResult(
            spec_path="s", source_path="x", output_path="y", spec_name="t",
            findings=[Finding(
                status=Status.FAIL, message="bad <b>value</b>", row_id="M-1",
                target="order.x", expected="<script>alert(1)</script>", actual="&",
                category=Category.VALUE_MISMATCH,
            )],
            run_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        )
        html = render_run_html(result)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_export_writes_file(self, examples_dir, tmp_path):
        out = export_html(_run(examples_dir, "po_baseline.json"), tmp_path / "r.html")
        assert out.exists() and out.read_text().startswith("<!doctype html>")


# ---------------------------------------------------------------------------
# interchange report
# ---------------------------------------------------------------------------


class TestInterchangeReport:
    def test_per_document_sections(self, examples_dir):
        from mapcheck.engine import validate_interchange_files

        result = validate_interchange_files(
            str(examples_dir / "specs" / "850_multi_reference_spec.xlsx"),
            str(examples_dir / "source" / "850_multi_defects.edi"),
            str(examples_dir / "output" / "orders_multi_defects.json"),
        )
        html = render_interchange_html(result)
        assert "interchange report" in html
        assert not _EXTERNAL.search(html)
        # one collapsible section per document
        assert html.count("<details>") >= len(result.documents)


# ---------------------------------------------------------------------------
# trends aggregation + HTML
# ---------------------------------------------------------------------------


class TestTrends:
    def _seed(self, db, examples_dir):
        with RunHistory(db) as h:
            h.record(_run(examples_dir, "po_baseline.json"))
            h.record(_run(examples_dir, "po_baseline_defects.json"))
            h.record(validate_files(
                str(examples_dir / "specs" / "850_ergonomics_spec.xlsx"),
                str(examples_dir / "source" / "850_ergonomics.edi"),
                str(examples_dir / "output" / "ergonomics_baseline.json"),
            ))

    def test_aggregates_per_spec(self, examples_dir, tmp_path):
        db = tmp_path / "h.db"
        self._seed(db, examples_dir)
        with RunHistory(db) as h:
            trends = compute_trends(h)
        assert trends.total_runs == 3
        assert trends.distinct_specs == 2
        specs = {s.spec: s for s in trends.specs}
        assert specs["850_reference_spec.xlsx"].total == 2
        assert specs["850_reference_spec.xlsx"].pass_rate == 0.5
        assert specs["850_ergonomics_spec.xlsx"].pass_rate == 1.0
        # top root causes come from the defective run
        assert dict(trends.top_categories)["missing_output"] >= 1

    def test_partner_runs_group_separately(self, examples_dir, tmp_path):
        """One base spec under two deltas is two checks — pooling them
        averages a failing partner into a passing one until neither shows."""
        db = tmp_path / "h.db"
        with RunHistory(db) as h:
            h.record(_run(examples_dir, "po_baseline.json"))
            h.record(
                _run(examples_dir, "po_baseline_defects.json"),
                partner_file=str(examples_dir / "specs" / "partner_acme_delta.xlsx"),
            )
        with RunHistory(db) as h:
            trends = compute_trends(h)
        labels = {s.spec for s in trends.specs}
        assert trends.distinct_specs == 2
        assert "850_reference_spec.xlsx" in labels
        assert "850_reference_spec.xlsx + partner_acme_delta.xlsx" in labels

    def test_series_oldest_to_newest(self, examples_dir, tmp_path):
        db = tmp_path / "h.db"
        self._seed(db, examples_dir)
        with RunHistory(db) as h:
            trends = compute_trends(h)
        ref = next(s for s in trends.specs if s.spec == "850_reference_spec.xlsx")
        assert ref.series() == ["PASS", "FAIL"]  # recorded clean then defect

    def test_empty_db(self, tmp_path):
        with RunHistory(tmp_path / "h.db") as h:
            trends = compute_trends(h)
        assert trends.is_empty
        assert "No runs recorded yet" in render_trends_html(trends)

    def test_trends_html_self_contained(self, examples_dir, tmp_path):
        db = tmp_path / "h.db"
        self._seed(db, examples_dir)
        with RunHistory(db) as h:
            html = render_trends_html(compute_trends(h))
        assert not _EXTERNAL.search(html)
        assert "history trends" in html
        assert "<svg" in html  # sparklines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_validate_export_html(self, examples_dir, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "r.html"
        code = main([
            "validate",
            "--spec", str(examples_dir / "specs" / SPEC),
            "--source", str(examples_dir / "source" / SRC),
            "--output", str(examples_dir / "output" / "po_baseline_defects.json"),
            "--no-history", "--no-color", "--export-html", str(out),
        ])
        assert code == 1 and out.exists()
        assert "HTML report written" in capsys.readouterr().out

    def test_report_html_and_text(self, examples_dir, tmp_path, capsys):
        db = tmp_path / "h.db"
        with RunHistory(db) as h:
            h.record(_run(examples_dir, "po_baseline.json"))
        # text
        code = main(["report", "--db", str(db)])
        out = capsys.readouterr().out
        assert code == 0 and "pass rate" in out and "850_reference_spec.xlsx" in out
        # html
        html = tmp_path / "t.html"
        code = main(["report", "--db", str(db), "--html", str(html)])
        assert code == 0 and html.exists()

    def test_report_missing_db(self, tmp_path, capsys):
        code = main(["report", "--db", str(tmp_path / "nope.db")])
        assert code == 2
        assert "no history database" in capsys.readouterr().err
