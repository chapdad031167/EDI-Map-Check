"""Regression mode (design 006): baseline blessing + delta diffing.

Covers the ``baselines`` table and migration, the pure snapshot diff
classifier (NEW / RESOLVED / CHANGED / DOC ADDED / DOC REMOVED), finding
identity (reorders and message-only edits are not regressions), the exit
gate, and the end-to-end ``bless`` / ``regress`` CLI flow for both a single
document and a multi-transaction interchange.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mapcheck.cli import main
from mapcheck.engine import Status, validate_files
from mapcheck.report.history import RunHistory
from mapcheck.report.regression import (
    CHANGED,
    DOC_ADDED,
    DOC_REMOVED,
    NEW,
    RESOLVED,
    baseline_key,
    diff_snapshots,
    format_delta,
    regress,
)

SPEC = "850_reference_spec.xlsx"
SRC = "850_baseline.edi"
MULTI_SPEC = "850_multi_reference_spec.xlsx"
MULTI_SRC = "850_multi_baseline.edi"


def _f(status, *, row_id="", target="", source_ref="", category=None,
       expected=None, actual=None, message="m"):
    return {
        "row_id": row_id, "source_ref": source_ref, "target": target,
        "status": status, "category": category, "expected": expected,
        "actual": actual, "message": message,
    }


# ---------------------------------------------------------------------------
# baseline key
# ---------------------------------------------------------------------------


class TestBaselineKey:
    def test_stable_across_dot_slash(self):
        assert baseline_key("./a.xlsx", "b.edi", "c.json") == baseline_key(
            "a.xlsx", "b.edi", "c.json"
        )

    def test_partner_is_part_of_the_key(self):
        assert baseline_key("a", "b", "c") != baseline_key("a", "b", "c", "acme")

    def test_a_pipe_in_a_path_cannot_forge_the_separator(self):
        """'|' is legal in a POSIX filename; unescaped it shifts the
        boundary and hands one validation another's baseline."""
        assert baseline_key("a|b", "c.edi", "d.json") != baseline_key(
            "a", "b|c.edi", "d.json"
        )

    def test_ordinary_paths_keep_their_existing_key(self):
        """Escaping must not orphan baselines already blessed."""
        assert baseline_key("spec.xlsx", "s.edi", "o.json") == (
            "spec.xlsx|s.edi|o.json"
        )


# ---------------------------------------------------------------------------
# diff classifier (pure, hand-built snapshots)
# ---------------------------------------------------------------------------


class TestDiffClassifier:
    def test_identical_is_empty(self):
        snap = {"": [_f("PASS", row_id="M-001"), _f("FAIL", row_id="M-002")]}
        assert diff_snapshots(snap, snap) == []

    def test_reorder_and_message_only_are_not_changes(self):
        base = {"": [_f("FAIL", row_id="M-001", message="was worded this way"),
                     _f("PASS", row_id="M-002")]}
        curr = {"": [_f("PASS", row_id="M-002"),
                     _f("FAIL", row_id="M-001", message="now worded differently")]}
        assert diff_snapshots(base, curr) == []

    def test_file_level_findings_do_not_collapse_into_one(self):
        """Envelope and truncation findings carry no row id, target or
        source ref, so they all share a location. Keyed on that alone
        they overwrote each other and only the last survived the diff."""
        def envelope(status, message):
            return _f(status, message=message)

        base = {"": [envelope("PASS", "ISA13/IEA02 match"),
                     envelope("PASS", "GS06/GE02 match"),
                     envelope("PASS", "no truncation")]}
        curr = {"": [envelope("PASS", "ISA13/IEA02 match"),
                     envelope("FAIL", "GS06/GE02 MISMATCH"),
                     envelope("PASS", "no truncation")]}
        changes = diff_snapshots(base, curr)
        assert [c.kind for c in changes] == [CHANGED]
        assert changes[0].regression is True

    def test_file_level_findings_are_named_individually(self):
        base = {"": [_f("PASS"), _f("PASS")]}
        curr = {"": [_f("PASS"), _f("FAIL")]}
        changes = diff_snapshots(base, curr)
        assert changes[0].where == "file-level #2"

    def test_unchanged_file_level_findings_stay_quiet(self):
        snap = {"": [_f("PASS", message="a"), _f("PASS", message="b"),
                     _f("FAIL", message="c")]}
        assert diff_snapshots(snap, snap) == []

    def test_new_fail_is_a_regression(self):
        base = {"": [_f("PASS", row_id="M-001")]}
        curr = {"": [_f("PASS", row_id="M-001"),
                     _f("FAIL", row_id="M-009", target="order.x")]}
        changes = diff_snapshots(base, curr)
        assert [c.kind for c in changes] == [NEW]
        assert changes[0].regression is True

    def test_new_warning_is_reported_but_not_a_regression(self):
        base = {"": []}
        curr = {"": [_f("WARNING", source_ref="REF*XX")]}
        (change,) = diff_snapshots(base, curr)
        assert change.kind == NEW and change.regression is False

    def test_resolved_when_failure_disappears(self):
        base = {"": [_f("FAIL", row_id="M-004", target="order.po")]}
        curr = {"": []}
        (change,) = diff_snapshots(base, curr)
        assert change.kind == RESOLVED and change.regression is False

    def test_resolved_when_failure_becomes_pass(self):
        base = {"": [_f("FAIL", row_id="M-004", target="order.po", actual="X")]}
        curr = {"": [_f("PASS", row_id="M-004", target="order.po", actual="Y")]}
        (change,) = diff_snapshots(base, curr)
        assert change.kind == RESOLVED and change.regression is False

    def test_changed_value_that_becomes_fail_is_a_regression(self):
        base = {"": [_f("PASS", row_id="M-004", target="order.po", actual="ABC")]}
        curr = {"": [_f("FAIL", row_id="M-004", target="order.po", actual="XYZ")]}
        (change,) = diff_snapshots(base, curr)
        assert change.kind == CHANGED and change.regression is True

    def test_changed_between_failures_is_reported_not_regressing(self):
        # already failing in the baseline, still failing but for a new value:
        # the outcome changed but it did not newly break.
        base = {"": [_f("FAIL", row_id="M-004", target="t", actual="A")]}
        curr = {"": [_f("FAIL", row_id="M-004", target="t", actual="B")]}
        (change,) = diff_snapshots(base, curr)
        assert change.kind == CHANGED and change.regression is False

    def test_no_row_id_findings_key_on_source_ref(self):
        base = {"": [_f("WARNING", source_ref="N1*ZZ")]}
        curr = {"": [_f("FAIL", source_ref="N1*ZZ", actual="oops")]}
        (change,) = diff_snapshots(base, curr)
        assert change.kind == CHANGED and change.regression is True

    def test_doc_added_and_removed(self):
        base = {"": [], "PO-1": [_f("PASS", row_id="M-001")]}
        curr = {"": [], "PO-2": [_f("PASS", row_id="M-001")]}
        changes = diff_snapshots(base, curr)
        kinds = {(c.kind, c.document_key) for c in changes}
        assert (DOC_ADDED, "PO-2") in kinds
        assert (DOC_REMOVED, "PO-1") in kinds
        assert any(c.kind == DOC_REMOVED and c.regression for c in changes)
        assert all(not c.regression for c in changes if c.kind == DOC_ADDED)

    def test_per_document_attribution(self):
        base = {"": [], "PO-1": [_f("PASS", row_id="M-002", target="t")]}
        curr = {"": [], "PO-1": [_f("FAIL", row_id="M-002", target="t", actual="x")]}
        (change,) = diff_snapshots(base, curr)
        assert change.document_key == "PO-1"
        assert "PO-1" in change.where


# ---------------------------------------------------------------------------
# exit gate / delta object
# ---------------------------------------------------------------------------


class TestExitGate:
    def test_regression_trips_nonzero(self):
        base = {"": [_f("PASS", row_id="M-001")]}
        curr = {"": [_f("FAIL", row_id="M-001", actual="x")]}
        from mapcheck.report.regression import RegressionDelta

        d = RegressionDelta(1, 2, diff_snapshots(base, curr))
        assert d.is_regression and d.exit_code == 1

    def test_only_improvements_stay_zero(self):
        base = {"": [_f("FAIL", row_id="M-001", actual="x")]}
        curr = {"": [_f("PASS", row_id="M-001", actual="y")]}
        from mapcheck.report.regression import RegressionDelta

        d = RegressionDelta(1, 2, diff_snapshots(base, curr))
        assert not d.is_regression and d.exit_code == 0

    def test_empty_delta_is_zero(self):
        from mapcheck.report.regression import RegressionDelta

        d = RegressionDelta(1, 2, [])
        assert d.is_empty and d.exit_code == 0


# ---------------------------------------------------------------------------
# baselines table + migration + RunHistory integration
# ---------------------------------------------------------------------------


class TestBaselinesTable:
    def _run(self, examples_dir, output):
        return validate_files(
            str(examples_dir / "specs" / SPEC),
            str(examples_dir / "source" / SRC),
            str(examples_dir / "output" / output),
        )

    def test_bless_and_lookup(self, examples_dir, tmp_path):
        with RunHistory(tmp_path / "h.db") as h:
            run_id = h.record(self._run(examples_dir, "po_baseline.json"))
            h.bless(run_id, "k1", label="clean-850")
            found = h.baseline_for("k1")
            assert found["run_id"] == run_id and found["label"] == "clean-850"
            assert h.baseline_for("nope") is None

    def test_rebless_replaces(self, examples_dir, tmp_path):
        with RunHistory(tmp_path / "h.db") as h:
            first = h.record(self._run(examples_dir, "po_baseline.json"))
            second = h.record(self._run(examples_dir, "po_baseline_defects.json"))
            h.bless(first, "k1")
            h.bless(second, "k1")
            assert h.baseline_for("k1")["run_id"] == second

    def test_bless_unknown_run_raises(self, tmp_path):
        with RunHistory(tmp_path / "h.db") as h:
            with pytest.raises(ValueError, match="no run"):
                h.bless(999, "k1")

    def test_snapshot_round_trips_findings(self, examples_dir, tmp_path):
        run = self._run(examples_dir, "po_baseline_defects.json")
        with RunHistory(tmp_path / "h.db") as h:
            run_id = h.record(run)
            snap = h.snapshot(run_id)
        assert set(snap) == {""}
        assert len(snap[""]) == len(run.findings)

    def test_migration_on_legacy_db(self, tmp_path):
        db = tmp_path / "legacy.db"
        conn = sqlite3.connect(db)
        conn.executescript(
            "CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " run_at TEXT, spec_file TEXT, source_file TEXT, output_file TEXT,"
            " result TEXT, passed INT, failed INT, warnings INT, not_tested INT);"
        )
        conn.commit()
        conn.close()
        with RunHistory(db) as h:  # should add baselines table + columns
            tables = {
                r[0]
                for r in h._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        assert "baselines" in tables


# ---------------------------------------------------------------------------
# end-to-end regress via history helper
# ---------------------------------------------------------------------------


class TestRegressHelper:
    def _record(self, h, examples_dir, output):
        return h.record(
            validate_files(
                str(examples_dir / "specs" / SPEC),
                str(examples_dir / "source" / SRC),
                str(examples_dir / "output" / output),
            )
        )

    def test_clean_rerun_is_empty(self, examples_dir, tmp_path):
        with RunHistory(tmp_path / "h.db") as h:
            base = self._record(h, examples_dir, "po_baseline.json")
            curr = self._record(h, examples_dir, "po_baseline.json")
            delta = regress(h, base, curr)
        assert delta.is_empty and delta.exit_code == 0

    def test_defect_rerun_regresses(self, examples_dir, tmp_path):
        with RunHistory(tmp_path / "h.db") as h:
            base = self._record(h, examples_dir, "po_baseline.json")
            curr = self._record(h, examples_dir, "po_baseline_defects.json")
            delta = regress(h, base, curr)
        assert delta.is_regression and delta.exit_code == 1
        assert any(c.kind in (NEW, CHANGED) and c.regression for c in delta.changes)

    def test_format_delta_shows_verdict(self, examples_dir, tmp_path):
        with RunHistory(tmp_path / "h.db") as h:
            base = self._record(h, examples_dir, "po_baseline.json")
            curr = self._record(h, examples_dir, "po_baseline_defects.json")
            text = format_delta(regress(h, base, curr), color=False)
        assert "REGRESSION" in text and "exit 1" in text
        assert "\033[" not in text


# ---------------------------------------------------------------------------
# CLI: bless + regress
# ---------------------------------------------------------------------------


def _recorded_run_id(out: str) -> int:
    """Pull the run id out of the bootstrap `Recorded run #N.` line."""
    import re

    match = re.search(r"Recorded run #(\d+)", out)
    assert match, f"no recorded run id in:\n{out}"
    return int(match.group(1))


class TestCli:
    """The realistic flow: one fixed output path whose *content* changes
    between the blessed baseline and the regression run."""

    def _regress_args(self, examples_dir, output_path, db, *extra):
        return [
            "regress",
            "--spec", str(examples_dir / "specs" / SPEC),
            "--source", str(examples_dir / "source" / SRC),
            "--output", str(output_path),
            "--db", str(db), "--no-color", *extra,
        ]

    def _write(self, examples_dir, name, dest):
        dest.write_bytes((examples_dir / "output" / name).read_bytes())

    def test_bootstrap_then_bless_then_regress(self, examples_dir, tmp_path, capsys):
        db = tmp_path / "h.db"
        out = tmp_path / "po.json"
        self._write(examples_dir, "po_baseline.json", out)

        # first regress with no baseline: records + guides, exit 0
        code = main(self._regress_args(examples_dir, out, db))
        text = capsys.readouterr().out
        assert code == 0 and "No baseline" in text and "mapcheck bless" in text
        run_id = _recorded_run_id(text)

        # bless the run it just recorded
        code = main(["bless", str(run_id), "--db", str(db)])
        assert code == 0 and "blessed" in capsys.readouterr().out

        # regress the same clean output: no delta, exit 0
        code = main(self._regress_args(examples_dir, out, db))
        assert code == 0
        assert "No changes" in capsys.readouterr().out

        # the translator regressed — same path, defective content now
        self._write(examples_dir, "po_baseline_defects.json", out)
        code = main(self._regress_args(examples_dir, out, db))
        assert code == 1
        assert "REGRESSION" in capsys.readouterr().out

    def test_bless_unknown_run_is_usage_error(self, tmp_path, capsys):
        db = tmp_path / "h.db"
        RunHistory(db).close()  # create empty db
        code = main(["bless", "42", "--db", str(db)])
        assert code == 2
        assert "no run #42" in capsys.readouterr().err

    def test_label_override(self, examples_dir, tmp_path, capsys):
        db = tmp_path / "h.db"
        out = tmp_path / "po.json"
        self._write(examples_dir, "po_baseline.json", out)
        text = capsys.readouterr()  # clear
        main(self._regress_args(examples_dir, out, db, "--label", "L"))
        run_id = _recorded_run_id(capsys.readouterr().out)
        main(["bless", str(run_id), "--label", "L", "--db", str(db)])
        capsys.readouterr()
        code = main(self._regress_args(examples_dir, out, db, "--label", "L"))
        assert code == 0 and "No changes" in capsys.readouterr().out


class TestPartnerBaseline:
    """``--partner`` puts the delta in the baseline key, so the run has to
    carry which delta it used or ``bless`` cannot rebuild that key — and a
    regression run that never finds its baseline passes CI unconditionally."""

    def _args(self, examples_dir, output_path, db, *extra):
        return [
            "regress",
            "--spec", str(examples_dir / "specs" / "partner_base_spec.xlsx"),
            "--partner", str(examples_dir / "specs" / "partner_acme_delta.xlsx"),
            "--source", str(examples_dir / "source" / "850_partner.edi"),
            "--output", str(output_path),
            "--db", str(db), "--no-color", *extra,
        ]

    def test_blessed_partner_run_is_found_on_re_run(
        self, examples_dir, tmp_path, capsys
    ):
        db = tmp_path / "h.db"
        out = tmp_path / "po.json"
        out.write_bytes((examples_dir / "output" / "partner_order.json").read_bytes())

        main(self._args(examples_dir, out, db))
        run_id = _recorded_run_id(capsys.readouterr().out)
        main(["bless", str(run_id), "--db", str(db)])
        capsys.readouterr()

        code = main(self._args(examples_dir, out, db))
        text = capsys.readouterr().out
        assert code == 0 and "No changes" in text
        assert "No baseline" not in text

    def test_partner_run_still_detects_a_regression(
        self, examples_dir, tmp_path, capsys
    ):
        db = tmp_path / "h.db"
        out = tmp_path / "po.json"
        out.write_bytes((examples_dir / "output" / "partner_order.json").read_bytes())

        main(self._args(examples_dir, out, db))
        run_id = _recorded_run_id(capsys.readouterr().out)
        main(["bless", str(run_id), "--db", str(db)])
        capsys.readouterr()

        payload = json.loads(out.read_text())
        payload["order"]["po_number"] = "REGRESSED"
        out.write_text(json.dumps(payload))

        code = main(self._args(examples_dir, out, db))
        assert code == 1
        assert "REGRESSION" in capsys.readouterr().out

    def test_run_row_records_which_delta_was_applied(
        self, examples_dir, tmp_path, capsys
    ):
        db = tmp_path / "h.db"
        out = tmp_path / "po.json"
        out.write_bytes((examples_dir / "output" / "partner_order.json").read_bytes())
        main(self._args(examples_dir, out, db))
        run_id = _recorded_run_id(capsys.readouterr().out)

        with RunHistory(db) as history:
            assert history.run(run_id)["partner_file"].endswith(
                "partner_acme_delta.xlsx"
            )

    def test_a_different_delta_does_not_reuse_the_baseline(
        self, examples_dir, tmp_path, capsys
    ):
        """Two deltas over one spec are two different validations."""
        db = tmp_path / "h.db"
        out = tmp_path / "po.json"
        out.write_bytes((examples_dir / "output" / "partner_order.json").read_bytes())
        main(self._args(examples_dir, out, db))
        run_id = _recorded_run_id(capsys.readouterr().out)
        main(["bless", str(run_id), "--db", str(db)])
        capsys.readouterr()

        globex = [
            "regress",
            "--spec", str(examples_dir / "specs" / "partner_base_spec.xlsx"),
            "--partner", str(examples_dir / "specs" / "partner_globex_delta.xlsx"),
            "--source", str(examples_dir / "source" / "850_partner.edi"),
            "--output", str(out), "--db", str(db), "--no-color",
        ]
        code = main(globex)
        assert code == 0 and "No baseline" in capsys.readouterr().out

    def test_legacy_run_without_a_partner_column_still_blesses(
        self, examples_dir, tmp_path, capsys
    ):
        """A run recorded before the column existed reads back as None."""
        db = tmp_path / "h.db"
        out = tmp_path / "po.json"
        out.write_bytes((examples_dir / "output" / "partner_order.json").read_bytes())
        main([
            "validate",
            "--spec", str(examples_dir / "specs" / "partner_base_spec.xlsx"),
            "--source", str(examples_dir / "source" / "850_partner.edi"),
            "--output", str(out), "--db", str(db), "--no-color",
        ])
        capsys.readouterr()
        with RunHistory(db) as history:
            run_id = history.recent_runs(limit=1)[0]["id"]
            assert history.run(run_id)["partner_file"] is None
        assert main(["bless", str(run_id), "--db", str(db)]) == 0


# ---------------------------------------------------------------------------
# interchange: per-document + DOC ADDED/REMOVED
# ---------------------------------------------------------------------------


class TestInterchange:
    def _args(self, examples_dir, source, output_path, db, *extra):
        return [
            "regress",
            "--spec", str(examples_dir / "specs" / MULTI_SPEC),
            "--source", str(examples_dir / "source" / source),
            "--output", str(output_path),
            "--db", str(db), "--no-color", *extra,
        ]

    def test_interchange_baseline_and_regress(self, examples_dir, tmp_path, capsys):
        db = tmp_path / "h.db"
        out = tmp_path / "orders.json"
        out.write_bytes((examples_dir / "output" / "orders_multi_baseline.json").read_bytes())

        # bootstrap on the clean multi baseline; bless the parent run it names
        main(self._args(examples_dir, MULTI_SRC, out, db, "--label", "multi"))
        run_id = _recorded_run_id(capsys.readouterr().out)
        main(["bless", str(run_id), "--label", "multi", "--db", str(db)])
        capsys.readouterr()

        # clean re-run: empty
        code = main(self._args(examples_dir, MULTI_SRC, out, db, "--label", "multi"))
        assert code == 0 and "No changes" in capsys.readouterr().out

        # defect multi-file (same output path, defective content + source)
        out.write_bytes((examples_dir / "output" / "orders_multi_defects.json").read_bytes())
        code = main(self._args(examples_dir, "850_multi_defects.edi", out, db, "--label", "multi"))
        assert code == 1
        text = capsys.readouterr().out
        assert "REGRESSION" in text
