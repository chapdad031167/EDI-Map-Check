"""The run lifecycle in the app (Design 016): labels, recording,
regression rendering, and the History page's building blocks.

The app derives baseline labels from file names because upload paths are
ephemeral; these tests pin that derivation, the record-then-rebuild round
trip (stored findings redraw the same table content the live run showed),
and the delta rendering rules (regressions first, tones by kind).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import app
from mapcheck.engine.validator import validate_files
from mapcheck.report.history import RunHistory
from mapcheck.report.regression import Change, RegressionDelta, regress

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples"

SPEC = EXAMPLES / "specs" / "850_reference_spec.xlsx"
SOURCE = EXAMPLES / "source" / "850_baseline.edi"
CLEAN_OUTPUT = EXAMPLES / "output" / "po_baseline.json"
DEFECT_OUTPUT = EXAMPLES / "output" / "po_baseline_defects.json"


class TestBaselineLabel:
    def test_file_names_only(self):
        label = app.baseline_label(
            "/tmp/abc123/850_reference_spec.xlsx",
            "/tmp/def456/850_baseline.edi",
            "/tmp/ghi789/po_baseline.json",
        )
        assert label == "850_reference_spec.xlsx | 850_baseline.edi -> po_baseline.json"

    def test_stable_across_fresh_temp_dirs(self, tmp_path: Path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        for d in (a, b):
            d.mkdir()
            shutil.copy(SPEC, d / SPEC.name)
        assert app.baseline_label(
            str(a / SPEC.name), str(SOURCE), str(CLEAN_OUTPUT)
        ) == app.baseline_label(str(b / SPEC.name), str(SOURCE), str(CLEAN_OUTPUT))

    def test_partner_delta_folds_in(self):
        label = app.baseline_label(
            "base.xlsx", "po.edi", "out.json", "partner_acme_delta.xlsx"
        )
        assert label.endswith(" | delta: partner_acme_delta.xlsx")

    def test_history_db_honors_env(self, monkeypatch):
        monkeypatch.setenv("MAPCHECK_HISTORY_DB", "/data/mapcheck_history.db")
        assert app._history_db() == Path("/data/mapcheck_history.db")
        monkeypatch.delenv("MAPCHECK_HISTORY_DB")
        assert app._history_db() == Path("mapcheck_history.db")


class TestRecordAndRebuild:
    def test_stored_findings_redraw_the_live_table(self, tmp_path: Path):
        result = validate_files(str(SPEC), str(SOURCE), str(CLEAN_OUTPUT))
        with RunHistory(tmp_path / "h.db") as history:
            run_id = history.record(result)
            stored = history.findings_for(run_id)
        live = app._findings_frame(result)
        rebuilt = app._stored_findings_frame(stored)
        assert set(live.columns) == set(rebuilt.columns)
        key = ["Status", "Row ID", "Source", "Target", "Message"]
        assert sorted(map(tuple, live[key].values.tolist())) == sorted(
            map(tuple, rebuilt[key].values.tolist())
        )


def _two_runs(tmp_path: Path) -> tuple[RunHistory, int, int, str]:
    """A clean run and a defective run of the *same file names*."""
    for name, output in (("clean", CLEAN_OUTPUT), ("defect", DEFECT_OUTPUT)):
        d = tmp_path / name
        d.mkdir()
        shutil.copy(output, d / "out.json")
    clean = validate_files(str(SPEC), str(SOURCE), str(tmp_path / "clean" / "out.json"))
    defect = validate_files(str(SPEC), str(SOURCE), str(tmp_path / "defect" / "out.json"))
    history = RunHistory(tmp_path / "h.db")
    baseline_id = history.record(clean)
    current_id = history.record(defect)
    label = app.baseline_label(str(SPEC), str(SOURCE), str(tmp_path / "x" / "out.json"))
    return history, baseline_id, current_id, label


class TestBlessAndRegress:
    def test_same_label_finds_the_baseline(self, tmp_path: Path):
        history, baseline_id, current_id, label = _two_runs(tmp_path)
        history.bless(baseline_id, label, label="clean June run")
        found = history.baseline_for(label)
        assert found is not None and found["run_id"] == baseline_id
        assert history.baselines()[0]["label"] == "clean June run"
        history.close()

    def test_defective_rerun_is_a_regression(self, tmp_path: Path):
        history, baseline_id, current_id, _ = _two_runs(tmp_path)
        delta = regress(history, baseline_id, current_id)
        assert delta.is_regression
        assert delta.regressions
        history.close()

    def test_cli_path_keys_do_not_collide_with_labels(self, tmp_path: Path):
        history, baseline_id, _, label = _two_runs(tmp_path)
        from mapcheck.report.regression import baseline_key

        history.bless(baseline_id, baseline_key("a.xlsx", "b.edi", "c.json"))
        assert history.baseline_for(label) is None
        history.close()


class TestDeltaRendering:
    def _delta(self) -> RegressionDelta:
        new = Change(
            kind="NEW", document_key="", identity=("", "M-003", ""),
            baseline=None, current={"status": "FAIL"},
            regression=True, detail="FAIL",
        )
        resolved = Change(
            kind="RESOLVED", document_key="", identity=("", "M-007", ""),
            baseline={"status": "FAIL"}, current=None,
            regression=False, detail="FAIL",
        )
        changed = Change(
            kind="CHANGED", document_key="", identity=("", "M-009", ""),
            baseline={"status": "PASS"}, current={"status": "WARNING"},
            regression=False, detail="status: 'PASS' -> 'WARNING'",
        )
        return RegressionDelta(
            baseline_run_id=1, current_run_id=2,
            changes=[resolved, changed, new],
        )

    def test_regressions_render_first_with_fail_tone(self):
        html_out = app.delta_table_html(self._delta())
        first_row = html_out.split("<tbody>")[1].split("</tr>")[0]
        assert "status-fail" in first_row and "NEW" in first_row
        assert "status-pass" in html_out  # RESOLVED row
        assert "status-warning" in html_out  # CHANGED row

    def test_strip_tones(self):
        delta = self._delta()
        strip = app.regression_strip_html(delta, baseline_run_id=1)
        assert "verdict-fail" in strip
        assert "VS BASELINE RUN #1" in strip
        empty = RegressionDelta(baseline_run_id=1, current_run_id=2)
        assert "verdict-pass" in app.regression_strip_html(empty, 1)
        assert "NO CHANGES" in app.regression_strip_html(empty, 1)


class TestRunsTable:
    def test_baseline_marker_and_tones(self):
        runs = [
            {
                "id": 7, "run_at": "2026-08-13T12:00:00", "result": "PASS",
                "passed": 40, "failed": 0, "warnings": 0, "not_tested": 6,
                "source_file": "/tmp/x/850_baseline.edi",
                "output_file": "/tmp/x/po_baseline.json",
            },
            {
                "id": 8, "run_at": "2026-08-13T12:05:00", "result": "FAIL",
                "passed": 30, "failed": 6, "warnings": 1, "not_tested": 6,
                "source_file": "/tmp/y/850_defects.edi",
                "output_file": "/tmp/y/po_defects.json",
            },
        ]
        table = app.runs_table_html(runs, blessed={7: {"run_id": 7}}, children={8: 3})
        assert "BASELINE" in table
        assert "status-pass" in table and "status-fail" in table
        assert "850_baseline.edi -&gt; po_baseline.json" in table
        assert "(3 documents)" in table

    def test_escapes_html(self):
        runs = [
            {
                "id": 1, "run_at": "t", "result": "PASS",
                "passed": 0, "failed": 0, "warnings": 0, "not_tested": 0,
                "source_file": "<b>.edi", "output_file": "o.json",
            }
        ]
        assert "<b>.edi" not in app.runs_table_html(runs, blessed={}, children={})
