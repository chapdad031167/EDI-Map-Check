"""Deployment hardening (Design 021): who can see the history, and what
it holds.

Covers the three settings and their defaults, the additive migration, the
session scope a ``shared`` deployment puts on runs, baselines and
blessing, the History page with and without the database download, the
``redacted`` and ``none`` storage settings (including that neither can
turn a real regression into a pass), the password gate, and that the CLI
is not session-scoped whatever the mode.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest
import yaml
from streamlit.testing.v1 import AppTest

import app
from mapcheck import deployment
from mapcheck.batch import load_manifest, run_batch
from mapcheck.cli import main
from mapcheck.deployment import (
    DeploymentConfigError,
    app_password,
    deployment_mode,
    history_values,
    history_values_explicit,
    password_matches,
)
from mapcheck.engine import validate_files, validate_interchange_files
from mapcheck.engine.results import Category, Finding, RunResult, Status
from mapcheck.report.history import REDACTED, REDACTED_MESSAGE, RunHistory
from mapcheck.report.regression import (
    CHANGED,
    DOC_REMOVED,
    RegressionUnavailable,
    diff_snapshots,
    format_delta,
    regress,
)
from mapcheck.report.trends import compute_trends

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples"

SPEC = EXAMPLES / "specs" / "850_reference_spec.xlsx"
SOURCE = EXAMPLES / "source" / "850_baseline.edi"
CLEAN_OUTPUT = EXAMPLES / "output" / "po_baseline.json"
DEFECT_OUTPUT = EXAMPLES / "output" / "po_baseline_defects.json"

MULTI_SPEC = EXAMPLES / "specs" / "850_multi_reference_spec.xlsx"
MULTI_SOURCE = EXAMPLES / "source" / "850_multi_baseline.edi"
MULTI_OUTPUT = EXAMPLES / "output" / "orders_multi_baseline.json"

#: Real field values the defective 850 run's findings quote: in expected,
#: in actual, and inside messages.
LEAKY_VALUES = ("PO4400021", "PO4400012", "GRANOLA BARS VARIETY", "614141007351")

#: The stored form of a redacted value. No report may print one.
_STORED_HASH = re.compile(r"redacted:[0-9a-f]{8}")

_ENV = ("MAPCHECK_MODE", "MAPCHECK_HISTORY_VALUES", "MAPCHECK_PASSWORD")


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    """Every test starts from an unconfigured deployment."""
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)


def _clean() -> RunResult:
    return validate_files(str(SPEC), str(SOURCE), str(CLEAN_OUTPUT))


def _defect() -> RunResult:
    return validate_files(str(SPEC), str(SOURCE), str(DEFECT_OUTPUT))


def _interchange():
    return validate_interchange_files(
        str(MULTI_SPEC), str(MULTI_SOURCE), str(MULTI_OUTPUT)
    )


def _one_finding(actual: str) -> RunResult:
    """A run whose only finding is a FAIL on one target with ``actual``."""
    return RunResult(
        spec_path="spec.xlsx",
        source_path="in.edi",
        output_path="out.json",
        findings=[
            Finding(
                status=Status.FAIL,
                message=f"expected 'ACME CORP', output has '{actual}'",
                row_id="M-001",
                source_ref="N1[ST] N102",
                target="ship_to.name",
                expected="ACME CORP",
                actual=actual,
                category=Category.VALUE_MISMATCH,
            )
        ],
    )


def _signature(delta) -> list[tuple[str, str, bool]]:
    return [(c.kind, c.where, c.regression) for c in delta.changes]


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------


class TestSettings:
    def test_defaults_are_today(self):
        assert deployment_mode({}) == "single"
        assert history_values({}) == "full"
        assert not history_values_explicit({})
        assert app_password({}) is None

    def test_shared_mode(self):
        assert deployment_mode({"MAPCHECK_MODE": "shared"}) == "shared"
        assert deployment_mode({"MAPCHECK_MODE": " Shared "}) == "shared"

    def test_shared_defaults_values_to_redacted(self):
        env = {"MAPCHECK_MODE": "shared"}
        assert history_values(env) == "redacted"
        assert not history_values_explicit(env)

    @pytest.mark.parametrize("values", ["full", "redacted", "none"])
    def test_an_explicit_values_setting_wins_in_either_mode(self, values):
        for mode in ("single", "shared"):
            env = {"MAPCHECK_MODE": mode, "MAPCHECK_HISTORY_VALUES": values}
            assert history_values(env) == values
            assert history_values_explicit(env)

    def test_a_mistyped_mode_is_an_error_not_single(self):
        """Falling back to ``single`` would publish every visitor's runs
        to every other on a deployment its operator believes is shared."""
        with pytest.raises(DeploymentConfigError, match="MAPCHECK_MODE"):
            deployment_mode({"MAPCHECK_MODE": "shard"})
        with pytest.raises(DeploymentConfigError):
            history_values({"MAPCHECK_MODE": "shard"})

    def test_a_mistyped_values_setting_is_an_error(self):
        with pytest.raises(DeploymentConfigError, match="MAPCHECK_HISTORY_VALUES"):
            history_values({"MAPCHECK_HISTORY_VALUES": "hashed"})

    def test_blank_counts_as_unset(self):
        env = {"MAPCHECK_MODE": "", "MAPCHECK_HISTORY_VALUES": " ", "MAPCHECK_PASSWORD": ""}
        assert deployment_mode(env) == "single"
        assert history_values(env) == "full"
        assert app_password(env) is None

    def test_the_store_refuses_an_unknown_setting(self, tmp_path: Path):
        with pytest.raises(DeploymentConfigError):
            RunHistory(tmp_path / "h.db", values="hashed")
        assert not (tmp_path / "h.db").exists()

    def test_the_store_follows_the_environment(self, tmp_path: Path, monkeypatch):
        with RunHistory(tmp_path / "a.db") as history:
            assert history.values == "full"
        monkeypatch.setenv("MAPCHECK_MODE", "shared")
        with RunHistory(tmp_path / "b.db") as history:
            assert history.values == "redacted"
        monkeypatch.setenv("MAPCHECK_HISTORY_VALUES", "none")
        with RunHistory(tmp_path / "c.db") as history:
            assert history.values == "none"


# ---------------------------------------------------------------------------
# migration
# ---------------------------------------------------------------------------

#: The schema exactly as it stood before this design.
_OLD_SCHEMA = """
CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    spec_file TEXT NOT NULL,
    source_file TEXT NOT NULL,
    output_file TEXT NOT NULL,
    result TEXT NOT NULL,
    passed INTEGER NOT NULL,
    failed INTEGER NOT NULL,
    warnings INTEGER NOT NULL,
    not_tested INTEGER NOT NULL,
    interchange_id INTEGER,
    document_key TEXT,
    partner_file TEXT
);
CREATE TABLE findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    row_id TEXT,
    source_ref TEXT,
    target TEXT,
    status TEXT NOT NULL,
    category TEXT,
    expected TEXT,
    actual TEXT,
    message TEXT NOT NULL
);
CREATE INDEX idx_findings_run ON findings(run_id);
CREATE TABLE baselines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    baseline_key TEXT NOT NULL UNIQUE,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    label TEXT,
    blessed_at TEXT NOT NULL
);
"""


class TestMigration:
    @pytest.fixture
    def old_db(self, tmp_path: Path) -> Path:
        path = tmp_path / "old.db"
        connection = sqlite3.connect(path)
        connection.executescript(_OLD_SCHEMA)
        connection.execute(
            "INSERT INTO runs (run_at, spec_file, source_file, output_file, result,"
            " passed, failed, warnings, not_tested)"
            " VALUES ('2026-08-01T00:00:00', 'spec.xlsx', 'in.edi', 'out.json',"
            " 'FAIL', 0, 1, 0, 0)"
        )
        connection.execute(
            "INSERT INTO findings (run_id, row_id, source_ref, target, status,"
            " category, expected, actual, message)"
            " VALUES (1, 'M-001', 'N1[ST] N102', 'ship_to.name', 'FAIL',"
            " 'value_mismatch', 'ACME CORP', 'ACNE CORP', 'm')"
        )
        connection.execute(
            "INSERT INTO baselines (baseline_key, run_id, label, blessed_at)"
            " VALUES ('L', 1, NULL, '2026-08-01T00:00:00')"
        )
        connection.commit()
        connection.close()
        return path

    def test_old_database_opens_and_its_rows_appear(self, old_db: Path):
        with RunHistory(old_db) as history:
            runs = history.recent_runs()
            assert [r["id"] for r in runs] == [1]
            assert runs[0]["values_mode"] is None
            assert history.values_mode_of(1) == "full"
            assert history.findings_for(1)[0]["actual"] == "ACNE CORP"
            assert history.baseline_for("L")["run_id"] == 1
            assert history.baselines()[0]["baseline_key"] == "L"

    def test_migration_is_additive(self, old_db: Path):
        RunHistory(old_db).close()
        connection = sqlite3.connect(old_db)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
        assert {"session_id", "values_mode"} <= columns
        assert connection.execute(
            "SELECT session_id, values_mode FROM runs WHERE id = 1"
        ).fetchone() == (None, None)
        connection.close()
        RunHistory(old_db).close()  # opening twice must not fail

    def test_old_rows_belong_to_no_session(self, old_db: Path):
        with RunHistory(old_db, session_id="visitor") as history:
            assert history.recent_runs() == []
            assert history.run(1) is None
            assert history.baseline_for("L") is None

    def test_an_old_baseline_still_gates_a_new_run(self, old_db: Path):
        with RunHistory(old_db, values="full") as history:
            same = history.record(_one_finding("ACNE CORP"))
            assert regress(history, 1, same).is_empty
            worse = history.record(_one_finding("ZZZZ CORP"))
            assert [c.kind for c in regress(history, 1, worse).changes] == [CHANGED]


# ---------------------------------------------------------------------------
# session scope (shared mode)
# ---------------------------------------------------------------------------


class TestSessionScope:
    @pytest.fixture
    def db(self, tmp_path: Path) -> Path:
        return tmp_path / "h.db"

    def test_each_session_sees_only_its_own_runs(self, db: Path):
        with RunHistory(db, session_id="alice", values="full") as alice, \
                RunHistory(db, session_id="bob", values="full") as bob:
            a = alice.record(_clean())
            b = bob.record(_defect())
            assert [r["id"] for r in alice.recent_runs()] == [a]
            assert [r["id"] for r in bob.recent_runs()] == [b]
            assert alice.run(b) is None and bob.run(a) is None
            assert alice.findings_for(b) == []
            assert bob.findings_for(a) == []
            assert alice.findings_for(a)  # its own are there
            with pytest.raises(ValueError):
                alice.snapshot(b)
            with pytest.raises(ValueError):
                regress(alice, a, b)

    def test_interchange_documents_are_scoped_with_their_parent(self, db: Path):
        with RunHistory(db, session_id="alice", values="full") as alice, \
                RunHistory(db, session_id="bob", values="full") as bob:
            parent = alice.record_interchange(_interchange())
            children = alice.child_runs(parent)
            assert len(children) > 1
            assert bob.child_runs(parent) == []
            assert bob.findings_for(children[0]["id"]) == []
            assert bob.recent_runs() == []

    def test_trends_are_per_session(self, db: Path):
        with RunHistory(db, session_id="alice", values="full") as alice, \
                RunHistory(db, session_id="bob", values="full") as bob:
            alice.record(_clean())
            bob.record(_defect())
            bob.record(_defect())
            assert compute_trends(alice).total_runs == 1
            assert compute_trends(alice).overall_pass_rate == 1.0
            assert compute_trends(bob).total_runs == 2
            assert compute_trends(bob).overall_pass_rate == 0.0
            assert compute_trends(alice).top_categories == []

    def test_one_session_cannot_bless_anothers_run(self, db: Path):
        with RunHistory(db, session_id="alice", values="full") as alice, \
                RunHistory(db, session_id="bob", values="full") as bob:
            a = alice.record(_clean())
            with pytest.raises(ValueError, match="no run"):
                bob.bless(a, "L")
            assert alice.baseline_for("L") is None

    def test_same_label_does_not_repoint_anothers_baseline(self, db: Path):
        """Two visitors validating identically named files derive the same
        label; the second bless must not take over the first's baseline."""
        with RunHistory(db, session_id="alice", values="full") as alice, \
                RunHistory(db, session_id="bob", values="full") as bob:
            a = alice.record(_clean())
            b = bob.record(_defect())
            alice.bless(a, "L")
            assert bob.baseline_for("L") is None
            bob.bless(b, "L")
            assert alice.baseline_for("L")["run_id"] == a
            assert bob.baseline_for("L")["run_id"] == b
            assert [x["run_id"] for x in alice.baselines()] == [a]
            assert [x["baseline_key"] for x in alice.baselines()] == ["L"]
            assert [x["run_id"] for x in bob.baselines()] == [b]

    def test_session_baselines_stay_out_of_the_unscoped_key_space(self, db: Path):
        with RunHistory(db, session_id="alice", values="full") as alice, \
                RunHistory(db, values="full") as everyone:
            a = alice.record(_clean())
            alice.bless(a, "L")
            assert everyone.baseline_for("L") is None
            c = everyone.record(_defect())
            everyone.bless(c, "L")
            assert alice.baseline_for("L")["run_id"] == a
            assert everyone.baseline_for("L")["run_id"] == c

    def test_an_unscoped_handle_sees_every_run(self, db: Path):
        """``single`` mode and the CLI: nothing is hidden, whoever wrote it."""
        with RunHistory(db, session_id="alice", values="full") as alice, \
                RunHistory(db, values="full") as everyone:
            a = alice.record(_clean())
            c = everyone.record(_defect())
            assert {r["id"] for r in everyone.recent_runs()} == {a, c}
            assert everyone.run(a) is not None
            assert [r["id"] for r in alice.recent_runs()] == [a]

    def test_the_session_id_is_stored_on_every_row(self, db: Path):
        with RunHistory(db, session_id="alice", values="full") as alice, \
                RunHistory(db, values="full") as everyone:
            alice.record_interchange(_interchange())
            everyone.record(_clean())
        connection = sqlite3.connect(db)
        owners = [r[0] for r in connection.execute("SELECT session_id FROM runs ORDER BY id")]
        connection.close()
        assert owners[-1] is None
        assert len(owners) > 2 and set(owners[:-1]) == {"alice"}


# ---------------------------------------------------------------------------
# the app in each mode
# ---------------------------------------------------------------------------

_HISTORY_PAGE = "import app\napp._history_page()\n"
_WHOLE_APP = "import app\napp.main()\n"
_DOWNLOAD_DB = "Download history database (.db)"


def _download_labels(at: AppTest) -> list[str]:
    return [button.label for button in at.get("download_button")]


# Streamlit's own bar chart trips a pandas deprecation; not ours to fix.
@pytest.mark.filterwarnings("ignore:The inplace keyword in DataFrame.reset_index")
class TestHistoryPage:
    @pytest.fixture
    def db(self, tmp_path: Path, monkeypatch) -> Path:
        path = tmp_path / "h.db"
        monkeypatch.setenv("MAPCHECK_HISTORY_DB", str(path))
        with RunHistory(path, session_id="alice", values="full") as alice, \
                RunHistory(path, session_id="bob", values="full") as bob:
            alice.record(_clean())
            bob.record(_defect())
        return path

    def _page(self, session: str | None = None) -> AppTest:
        at = AppTest.from_string(_HISTORY_PAGE, default_timeout=60)
        if session is not None:
            at.session_state[app._SESSION_ID] = session
        at.run()
        assert not at.exception
        return at

    def test_single_mode_is_unchanged(self, db: Path):
        at = self._page()
        assert _DOWNLOAD_DB in _download_labels(at)
        options = at.selectbox[0].options
        assert len(options) == 2  # every run, whoever recorded it
        captions = [c.value for c in at.caption]
        assert any(str(db.resolve()) in c for c in captions)
        assert not any("History values" in c for c in captions)
        assert not any("Shared mode" in c for c in captions)

    def test_shared_mode_has_no_database_download(self, db: Path, monkeypatch):
        monkeypatch.setenv("MAPCHECK_MODE", "shared")
        at = self._page("alice")
        assert _DOWNLOAD_DB not in _download_labels(at)
        # the per-session trends export is still offered
        assert "Download trends report (HTML)" in _download_labels(at)
        # nor does the page say where on the server the file lives
        assert not any(str(db.parent) in c.value for c in at.caption)

    def test_shared_mode_lists_only_this_sessions_runs(self, db: Path, monkeypatch):
        monkeypatch.setenv("MAPCHECK_MODE", "shared")
        alice = self._page("alice").selectbox[0].options
        bob = self._page("bob").selectbox[0].options
        assert len(alice) == 1 and "PASS" in alice[0]
        assert len(bob) == 1 and "FAIL" in bob[0]

    def test_a_new_session_sees_nothing(self, db: Path, monkeypatch):
        """No session id carried over, as after a page refresh."""
        monkeypatch.setenv("MAPCHECK_MODE", "shared")
        at = self._page()
        assert len(at.selectbox) == 0
        assert any("No runs recorded yet" in i.value for i in at.info)
        assert _download_labels(at) == []

    def test_shared_mode_says_what_it_is_doing(self, db: Path, monkeypatch):
        monkeypatch.setenv("MAPCHECK_MODE", "shared")
        captions = [c.value for c in self._page("alice").caption]
        assert any("A page refresh starts a new session" in c for c in captions)
        assert any(
            "History values: **redacted**" in c and "MAPCHECK_MODE=shared" in c
            for c in captions
        )

    def test_the_storage_note_names_an_explicit_setting(self, db: Path, monkeypatch):
        monkeypatch.setenv("MAPCHECK_MODE", "shared")
        monkeypatch.setenv("MAPCHECK_HISTORY_VALUES", "full")
        captions = [c.value for c in self._page("alice").caption]
        assert any(
            "History values: **full**" in c and "MAPCHECK_HISTORY_VALUES" in c
            for c in captions
        )

    def test_single_mode_notes_a_non_default_setting(self, db: Path, monkeypatch):
        monkeypatch.setenv("MAPCHECK_HISTORY_VALUES", "none")
        captions = [c.value for c in self._page().caption]
        assert any("History values: **none**" in c for c in captions)


class TestRecordingThroughTheApp:
    """The Validate page end to end: what a click actually stores."""

    @pytest.fixture
    def db(self, tmp_path: Path, monkeypatch) -> Path:
        path = tmp_path / "h.db"
        monkeypatch.setenv("MAPCHECK_HISTORY_DB", str(path))
        return path

    def _run_validation(self) -> AppTest:
        at = AppTest.from_string(_WHOLE_APP, default_timeout=120).run()
        assert not at.exception
        next(b for b in at.button if b.label == "Run validation").click().run()
        assert not at.exception
        return at

    @staticmethod
    def _rows(db: Path) -> list[tuple]:
        connection = sqlite3.connect(db)
        rows = connection.execute(
            "SELECT session_id, values_mode FROM runs ORDER BY id"
        ).fetchall()
        connection.close()
        return rows

    def test_single_mode_records_as_it_always_has(self, db: Path):
        self._run_validation()
        assert self._rows(db) == [(None, "full")]

    def test_shared_mode_records_under_the_session_and_redacted(
        self, db: Path, monkeypatch
    ):
        monkeypatch.setenv("MAPCHECK_MODE", "shared")
        first = self._run_validation()
        second = self._run_validation()
        ids = [at.session_state[app._SESSION_ID] for at in (first, second)]
        assert ids[0] != ids[1] and all(len(i) >= 32 for i in ids)
        assert self._rows(db) == [(ids[0], "redacted"), (ids[1], "redacted")]
        with RunHistory(db, session_id=ids[0]) as history:
            assert len(history.recent_runs()) == 1

    def test_a_misconfigured_mode_stops_the_app(self, db: Path, monkeypatch):
        monkeypatch.setenv("MAPCHECK_MODE", "shard")
        at = AppTest.from_string(_WHOLE_APP, default_timeout=60).run()
        assert not at.exception
        assert any("misconfigured" in e.value for e in at.error)
        assert len(at.button) == 0 and len(at.toggle) == 0


# ---------------------------------------------------------------------------
# redacted
# ---------------------------------------------------------------------------


class TestRedacted:
    def test_the_database_file_does_not_hold_the_values(self, tmp_path: Path):
        """Searched as bytes, so nothing hides in a column the test forgot
        (the message quotes both values)."""
        with RunHistory(tmp_path / "full.db", values="full") as history:
            history.record(_defect())
        with RunHistory(tmp_path / "redacted.db", values="redacted") as history:
            history.record(_defect())
        full = (tmp_path / "full.db").read_bytes()
        redacted = (tmp_path / "redacted.db").read_bytes()
        for value in LEAKY_VALUES:
            assert value.encode() in full  # the probe can see a leak
            assert value.encode() not in redacted

    def test_what_a_redacted_row_keeps(self, tmp_path: Path):
        with RunHistory(tmp_path / "h.db", values="redacted") as history:
            run_id = history.record(_one_finding("ACNE CORP"))
            assert history.values_mode_of(run_id) == "redacted"
            (row,) = history.findings_for(run_id)
        assert (row["status"], row["category"]) == ("FAIL", "value_mismatch")
        assert (row["row_id"], row["target"]) == ("M-001", "ship_to.name")
        assert row["expected"].startswith("redacted:")
        assert row["actual"].startswith("redacted:")
        assert row["expected"] != row["actual"]
        assert row["message"] == REDACTED_MESSAGE

    def test_an_absent_value_stays_absent(self, tmp_path: Path):
        with RunHistory(tmp_path / "h.db", values="redacted") as history:
            run_id = history.record(_defect())
            rows = history.findings_for(run_id)
        missing = [r for r in rows if r["category"] == "missing_output"]
        assert missing and all(r["actual"] is None for r in missing)

    def test_a_changed_value_is_still_a_change(self, tmp_path: Path):
        """Same status, same category, only the value differs: the hash is
        all that can tell, and it does."""
        with RunHistory(tmp_path / "h.db", values="redacted") as history:
            baseline = history.record(_one_finding("ACNE CORP"))
            same = history.record(_one_finding("ACNE CORP"))
            other = history.record(_one_finding("ZZZZ CORP"))
            assert regress(history, baseline, same).is_empty
            delta = regress(history, baseline, other)
        assert delta.redacted
        assert [c.kind for c in delta.changes] == [CHANGED]
        assert delta.changes[0].detail == f"actual: {REDACTED!r} -> {REDACTED!r}"

    def test_the_rendered_delta_never_shows_a_value(self, tmp_path: Path):
        with RunHistory(tmp_path / "h.db", values="redacted") as history:
            baseline = history.record(_one_finding("ACNE CORP"))
            other = history.record(_one_finding("ZZZZ CORP"))
            delta = regress(history, baseline, other)
        for rendered in (format_delta(delta, color=False), app.delta_table_html(delta)):
            for value in ("ACNE", "ZZZZ", "ACME"):
                assert value not in rendered
            assert not _STORED_HASH.search(rendered)
        assert "'<redacted>' -> '<redacted>'" in format_delta(delta, color=False)
        assert "Stored values are redacted" in format_delta(delta, color=False)
        assert "&lt;redacted&gt;" in app.delta_table_html(delta)

    def test_the_regression_gate_matches_full(self, tmp_path: Path):
        """The real example pair: redacted reports the same changes at the
        same places, and regresses, exactly as full does."""
        deltas = {}
        for values in ("full", "redacted"):
            with RunHistory(tmp_path / f"{values}.db", values=values) as history:
                baseline = history.record(_clean())
                current = history.record(_defect())
                deltas[values] = regress(history, baseline, current)
        assert deltas["redacted"].is_regression
        assert deltas["redacted"].exit_code == 1
        assert _signature(deltas["redacted"]) == _signature(deltas["full"])
        rendered = format_delta(deltas["redacted"], color=False)
        for value in LEAKY_VALUES:
            assert value not in rendered

    def test_a_full_baseline_still_gates_after_switching_to_redacted(
        self, tmp_path: Path
    ):
        """Turning redaction on must not strand the baselines already
        blessed, nor flag every value as changed."""
        db = tmp_path / "h.db"
        with RunHistory(db, values="full") as history:
            baseline = history.record(_clean())
        with RunHistory(db, values="redacted") as history:
            same = history.record(_clean())
            worse = history.record(_defect())
            assert regress(history, baseline, same).is_empty
            mixed = regress(history, baseline, worse)
        with RunHistory(tmp_path / "ref.db", values="full") as history:
            reference = regress(
                history, history.record(_clean()), history.record(_defect())
            )
        assert mixed.redacted and mixed.is_regression
        assert _signature(mixed) == _signature(reference)
        for value in LEAKY_VALUES:
            assert value not in format_delta(mixed, color=False)

    def test_document_keys_are_values_too(self, tmp_path: Path):
        """An interchange pairs documents by a field value (the PO number
        here), which lands in the runs table."""
        interchange = _interchange()
        keys = [d.key for d in interchange.documents]
        assert len(keys) > 1 and not any(k.startswith("#") for k in keys)
        db = tmp_path / "h.db"
        with RunHistory(db, values="redacted") as history:
            parent = history.record_interchange(interchange)
            stored = [c["document_key"] for c in history.child_runs(parent)]
            again = history.record_interchange(_interchange())
            assert regress(history, parent, again).is_empty
        assert all(k.startswith("doc-") for k in stored)
        assert len(set(stored)) == len(keys)
        raw = db.read_bytes()
        for key in keys:
            assert key.encode() not in raw

    def test_a_removed_document_is_still_caught_across_settings(self, tmp_path: Path):
        db = tmp_path / "h.db"
        with RunHistory(db, values="full") as history:
            baseline = history.record_interchange(_interchange())
        shorter = _interchange()
        dropped = shorter.documents.pop()
        with RunHistory(db, values="redacted") as history:
            current = history.record_interchange(shorter)
            delta = regress(history, baseline, current)
        assert [c.kind for c in delta.changes] == [DOC_REMOVED]
        assert delta.is_regression
        assert dropped.key not in format_delta(delta, color=False)

    def test_positional_document_labels_are_kept(self, tmp_path: Path):
        with RunHistory(tmp_path / "h.db", values="redacted") as history:
            assert history._redact_key("#1") == "#1"
            assert history._redact_key("PO123").startswith("doc-")
            assert history._redact_key(None) is None

    def test_hashes_do_not_carry_across_databases(self, tmp_path: Path):
        rows = []
        for name in ("a.db", "b.db"):
            with RunHistory(tmp_path / name, values="redacted") as history:
                rows.append(history.findings_for(history.record(_one_finding("X")))[0])
        assert rows[0]["actual"] != rows[1]["actual"]

    def test_hashes_are_stable_across_reopens(self, tmp_path: Path):
        db = tmp_path / "h.db"
        with RunHistory(db, values="redacted") as history:
            first = history.record(_one_finding("ACNE CORP"))
        with RunHistory(db, values="redacted") as history:
            second = history.record(_one_finding("ACNE CORP"))
            assert regress(history, first, second).is_empty

    def test_the_history_page_shows_the_placeholder_not_the_hash(self, tmp_path: Path):
        with RunHistory(tmp_path / "h.db", values="redacted") as history:
            rows = history.findings_for(history.record(_defect()))
        frame = app._stored_findings_frame(rows, redacted=True)
        assert set(frame["Expected"]) <= {REDACTED, ""}
        assert set(frame["Actual"]) <= {REDACTED, ""}
        assert "" in set(frame["Actual"])  # a missing target is not a value
        assert not _STORED_HASH.search(frame.to_string())


# ---------------------------------------------------------------------------
# none
# ---------------------------------------------------------------------------


def _regress_argv(db: Path, output: Path) -> list[str]:
    return [
        "regress", "--spec", str(SPEC), "--source", str(SOURCE),
        "--output", str(output), "--db", str(db), "--label", "L", "--no-color",
    ]


class TestNone:
    def test_no_finding_rows_are_stored(self, tmp_path: Path):
        db = tmp_path / "h.db"
        with RunHistory(db, values="none") as history:
            run_id = history.record(_defect())
            assert history.findings_for(run_id) == []
            row = history.run(run_id)
        assert row["values_mode"] == "none"
        assert row["result"] == "FAIL" and row["failed"] > 0
        for value in LEAKY_VALUES:
            assert value.encode() not in db.read_bytes()

    def test_trends_and_pass_rates_still_compute(self, tmp_path: Path):
        with RunHistory(tmp_path / "h.db", values="none") as history:
            history.record(_clean())
            history.record(_defect())
            trends = compute_trends(history)
        assert trends.total_runs == 2
        assert trends.overall_pass_rate == 0.5
        assert trends.specs[0].latest == "FAIL"

    def test_interchange_keeps_counts_but_not_keys(self, tmp_path: Path):
        interchange = _interchange()
        db = tmp_path / "h.db"
        with RunHistory(db, values="none") as history:
            parent = history.record_interchange(interchange)
            children = history.child_runs(parent)
        assert [c["document_key"] for c in children] == [
            f"#{i}" for i in range(1, len(interchange.documents) + 1)
        ]
        for document in interchange.documents:
            assert document.key.encode() not in db.read_bytes()

    def test_regression_refuses_instead_of_passing(self, tmp_path: Path):
        """Clean baseline, defective rerun, nothing stored for either:
        the naive diff is empty, which would read as a pass."""
        with RunHistory(tmp_path / "h.db", values="none") as history:
            baseline = history.record(_clean())
            current = history.record(_defect())
            assert diff_snapshots(
                history.snapshot(baseline), history.snapshot(current)
            ) == []
            with pytest.raises(RegressionUnavailable, match="none"):
                regress(history, baseline, current)

    def test_a_full_baseline_against_a_none_run_refuses_too(self, tmp_path: Path):
        """Every baseline failure would otherwise read as RESOLVED."""
        db = tmp_path / "h.db"
        with RunHistory(db, values="full") as history:
            baseline = history.record(_defect())
        with RunHistory(db, values="none") as history:
            current = history.record(_defect())
            with pytest.raises(RegressionUnavailable):
                regress(history, baseline, current)

    def test_a_run_without_findings_cannot_be_blessed(self, tmp_path: Path):
        with RunHistory(tmp_path / "h.db", values="none") as history:
            run_id = history.record(_clean())
            with pytest.raises(ValueError, match="cannot serve as a baseline"):
                history.bless(run_id, "L")
            assert history.baseline_for("L") is None

    def test_cli_regress_exits_2_not_0(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.setenv("MAPCHECK_HISTORY_VALUES", "none")
        db = tmp_path / "h.db"
        assert main(_regress_argv(db, DEFECT_OUTPUT)) == 2
        assert "regression cannot run" in capsys.readouterr().err

    def test_cli_regress_against_an_earlier_full_baseline_exits_2(
        self, tmp_path: Path, monkeypatch, capsys
    ):
        """The baseline exists and is good; the setting changed under it."""
        db = tmp_path / "h.db"
        assert main(_regress_argv(db, CLEAN_OUTPUT)) == 0
        assert main(["bless", "1", "--db", str(db), "--label", "L"]) == 0
        assert main(_regress_argv(db, DEFECT_OUTPUT)) == 1  # the gate works
        monkeypatch.setenv("MAPCHECK_HISTORY_VALUES", "none")
        capsys.readouterr()
        assert main(_regress_argv(db, DEFECT_OUTPUT)) == 2
        assert "regression cannot run" in capsys.readouterr().err

    def test_cli_bless_refuses_a_run_without_findings(
        self, tmp_path: Path, monkeypatch, capsys
    ):
        monkeypatch.setenv("MAPCHECK_HISTORY_VALUES", "none")
        db = tmp_path / "h.db"
        with RunHistory(db) as history:
            run_id = history.record(_clean())
        assert main(["bless", str(run_id), "--db", str(db)]) == 2
        assert "cannot serve as a baseline" in capsys.readouterr().err

    def test_batch_regress_is_an_error_not_a_pass(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("MAPCHECK_HISTORY_VALUES", "none")
        manifest = tmp_path / "mapcheck.yaml"
        manifest.write_text(
            "checks:\n"
            f"  - name: reg\n    spec: {SPEC}\n    source: {SOURCE}\n"
            f"    output: {DEFECT_OUTPUT}\n    regress: true\n    label: L\n",
            encoding="utf-8",
        )
        result = run_batch(load_manifest(manifest), str(tmp_path / "h.db"))
        assert result.outcomes[0].status == "error"
        assert result.exit_code == 2
        assert "none" in result.outcomes[0].detail

    def test_cli_regress_works_under_redacted(self, tmp_path: Path, monkeypatch, capsys):
        """The setting CI can adopt without losing its gate."""
        monkeypatch.setenv("MAPCHECK_HISTORY_VALUES", "redacted")
        db = tmp_path / "h.db"
        assert main(_regress_argv(db, CLEAN_OUTPUT)) == 0
        assert main(["bless", "1", "--db", str(db), "--label", "L"]) == 0
        capsys.readouterr()
        assert main(_regress_argv(db, DEFECT_OUTPUT)) == 1
        out = capsys.readouterr().out
        assert "VERDICT: REGRESSION" in out
        for value in LEAKY_VALUES:
            assert value not in out


# ---------------------------------------------------------------------------
# the password gate
# ---------------------------------------------------------------------------


class TestPasswordGate:
    @pytest.fixture(autouse=True)
    def _db(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("MAPCHECK_HISTORY_DB", str(tmp_path / "h.db"))

    @staticmethod
    def _app() -> AppTest:
        at = AppTest.from_string(_WHOLE_APP, default_timeout=60).run()
        assert not at.exception
        return at

    @staticmethod
    def _submit(at: AppTest, password: str) -> AppTest:
        at.text_input[0].set_value(password)
        at.button[0].click().run()
        assert not at.exception
        return at

    def test_off_unless_set(self):
        at = self._app()
        assert len(at.text_input) == 0
        assert "Run validation" in [b.label for b in at.button]

    def test_a_blank_password_does_not_arm_the_gate(self, monkeypatch):
        monkeypatch.setenv("MAPCHECK_PASSWORD", "")
        assert "Run validation" in [b.label for b in self._app().button]

    def test_set_and_nothing_else_renders(self, monkeypatch):
        monkeypatch.setenv("MAPCHECK_PASSWORD", "correct horse")
        at = self._app()
        assert [t.label for t in at.text_input] == ["Password"]
        assert [b.label for b in at.button] == ["Enter"]
        assert len(at.toggle) == 0 and len(at.selectbox) == 0

    def test_a_wrong_password_stays_out(self, monkeypatch):
        monkeypatch.setenv("MAPCHECK_PASSWORD", "correct horse")
        at = self._submit(self._app(), "correct hors")
        assert [e.value for e in at.error] == ["That password is not correct."]
        assert [b.label for b in at.button] == ["Enter"]
        assert app._AUTHENTICATED not in at.session_state

    def test_the_right_password_opens_the_app_for_the_session(self, monkeypatch):
        monkeypatch.setenv("MAPCHECK_PASSWORD", "correct horse")
        at = self._submit(self._app(), "correct horse")
        assert len(at.text_input) == 0 and len(at.error) == 0
        assert "Run validation" in [b.label for b in at.button]
        at.run()  # still open on the next script run
        assert "Run validation" in [b.label for b in at.button]

    def test_the_gate_holds_in_shared_mode_too(self, monkeypatch):
        monkeypatch.setenv("MAPCHECK_MODE", "shared")
        monkeypatch.setenv("MAPCHECK_PASSWORD", "correct horse")
        assert [b.label for b in self._app().button] == ["Enter"]

    def test_comparison_is_constant_time(self, monkeypatch):
        calls = []
        real = deployment.hmac.compare_digest

        def spy(a, b):
            calls.append((a, b))
            return real(a, b)

        monkeypatch.setattr(deployment.hmac, "compare_digest", spy)
        assert password_matches("pässword", "pässword")
        assert not password_matches("password", "pässword")
        assert not password_matches("", "pässword")
        assert len(calls) == 3 and all(isinstance(a, bytes) for a, _ in calls)


# ---------------------------------------------------------------------------
# the CLI is not session-scoped
# ---------------------------------------------------------------------------


def _validate_argv(db: Path, *extra: str) -> list[str]:
    return [
        "validate", "--spec", str(SPEC), "--source", str(SOURCE),
        "--output", str(CLEAN_OUTPUT), "--db", str(db), "--no-color", *extra,
    ]


class TestCliIsNotSessionScoped:
    def test_cli_runs_carry_no_session_even_in_shared_mode(
        self, tmp_path: Path, monkeypatch, capsys
    ):
        monkeypatch.setenv("MAPCHECK_MODE", "shared")
        db = tmp_path / "h.db"
        assert main(_validate_argv(db)) == 0
        connection = sqlite3.connect(db)
        assert connection.execute("SELECT session_id FROM runs").fetchall() == [(None,)]
        connection.close()
        capsys.readouterr()
        assert main(["history", "--db", str(db)]) == 0
        assert "850_baseline.edi -> po_baseline.json" in capsys.readouterr().out

    def test_cli_sees_runs_the_shared_app_recorded(self, tmp_path: Path, capsys):
        db = tmp_path / "h.db"
        with RunHistory(db, session_id="alice", values="redacted") as alice:
            alice.record(_clean())
        assert main(["history", "--db", str(db)]) == 0
        assert "850_baseline.edi -> po_baseline.json" in capsys.readouterr().out

    def test_no_history_still_writes_nothing(self, tmp_path: Path, monkeypatch):
        """What this repo's CI runs: unaffected by any of this."""
        monkeypatch.setenv("MAPCHECK_MODE", "shared")
        db = tmp_path / "h.db"
        assert main(_validate_argv(db, "--no-history")) == 0
        assert not db.exists()

    def test_a_bad_setting_is_a_usage_error_not_a_traceback(
        self, tmp_path: Path, monkeypatch, capsys
    ):
        monkeypatch.setenv("MAPCHECK_HISTORY_VALUES", "hashed")
        assert main(_validate_argv(tmp_path / "h.db")) == 2
        assert "MAPCHECK_HISTORY_VALUES" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# what ships
# ---------------------------------------------------------------------------


class TestShippedDefaults:
    def test_the_image_defaults_to_shared(self):
        dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
        assert "MAPCHECK_MODE=shared" in dockerfile

    def test_compose_pins_single_for_the_laptop_path(self):
        compose = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
        environment = compose["services"]["mapcheck"]["environment"]
        assert "MAPCHECK_MODE=single" in environment
        assert not any(e.startswith("MAPCHECK_PASSWORD") for e in environment)

    def test_readme_documents_every_setting(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        for name in _ENV:
            assert name in readme
        assert "users just get a URL" not in readme
