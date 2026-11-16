"""SQLite persistence of validation runs.

Two things about a history are decided when it is opened (Design 021),
and both are properties of the handle so that no caller can forget them:

* **Whose runs it reaches.** A handle opened with a ``session_id`` writes
  that id on every run it records and reads back only runs carrying it,
  baselines included. Without one (the CLI, and the app in ``single``
  mode) it reaches everything, as it always has.
* **What a finding keeps.** ``full`` stores expected and actual verbatim;
  ``redacted`` stores a keyed hash of each and withholds the message;
  ``none`` stores no finding rows at all. Unless passed in, this comes
  from ``MAPCHECK_HISTORY_VALUES`` (see :mod:`mapcheck.deployment`).
"""

from __future__ import annotations

import hmac
import re
import secrets
import sqlite3
from pathlib import Path
from typing import Any

from mapcheck.deployment import (
    VALUES_FULL,
    VALUES_MODES,
    VALUES_NONE,
    VALUES_REDACTED,
    DeploymentConfigError,
    history_values,
)
from mapcheck.engine.results import Finding, InterchangeResult, RunResult, Status

#: What a redacted value is shown as. The stored form is a hash; this is
#: the only thing a report ever prints in its place.
REDACTED = "<redacted>"

#: A finding's message quotes the values it is about ("expected 'ACME',
#: output has 'ACNE'"), so a redacted row cannot keep it.
REDACTED_MESSAGE = "(message withheld: history values are redacted)"

_HASH_PREFIX = "redacted:"
_DOC_PREFIX = "doc-"
_SESSION_PREFIX = "session:"
#: A positional document label ("#1") names an order, not a value.
_POSITIONAL = re.compile(r"#\d+")

_RUN_COLUMNS = (
    "id, run_at, spec_file, source_file, output_file, result,"
    " passed, failed, warnings, not_tested, interchange_id, document_key,"
    " partner_file, values_mode"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    spec_file TEXT NOT NULL,
    source_file TEXT NOT NULL,
    output_file TEXT NOT NULL,
    result TEXT NOT NULL,
    passed INTEGER NOT NULL,
    failed INTEGER NOT NULL,
    warnings INTEGER NOT NULL,
    not_tested INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
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
CREATE INDEX IF NOT EXISTS idx_findings_run ON findings(run_id);
CREATE TABLE IF NOT EXISTS baselines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    baseline_key TEXT NOT NULL UNIQUE,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    label TEXT,
    blessed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _migrate(connection: sqlite3.Connection) -> None:
    """Additively add multi-transaction columns to an existing runs table."""
    existing = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
    if "interchange_id" not in existing:
        connection.execute("ALTER TABLE runs ADD COLUMN interchange_id INTEGER")
    if "document_key" not in existing:
        connection.execute("ALTER TABLE runs ADD COLUMN document_key TEXT")
    if "partner_file" not in existing:
        # A partner delta changes what was validated, so it belongs to the
        # run's identity: without it, `bless` cannot rebuild the key that
        # `regress --partner` looks its baseline up by.
        connection.execute("ALTER TABLE runs ADD COLUMN partner_file TEXT")
    if "session_id" not in existing:
        # Which browser session recorded the run (Design 021). NULL for
        # every run written before the column existed and for every run
        # the CLI writes: those belong to no session.
        connection.execute("ALTER TABLE runs ADD COLUMN session_id TEXT")
    if "values_mode" not in existing:
        # What this run's finding rows hold. NULL reads as "full", which
        # is what every earlier run stored.
        connection.execute("ALTER TABLE runs ADD COLUMN values_mode TEXT")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id)"
    )


class RunHistory:
    """Validation run history stored in a SQLite database file."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        session_id: str | None = None,
        values: str | None = None,
    ) -> None:
        resolved = history_values() if values is None else values
        if resolved not in VALUES_MODES:
            raise DeploymentConfigError(
                f"history values setting {resolved!r} is not valid; use one of: "
                + ", ".join(VALUES_MODES)
            )
        self.db_path = Path(db_path)
        #: When set, this handle sees and writes only this session's runs.
        self.session_id = session_id
        #: What newly recorded findings keep: full, redacted or none.
        self.values = resolved
        self._salt_cache: bytes | None = None
        self._connection = sqlite3.connect(self.db_path)
        self._connection.executescript(_SCHEMA)
        _migrate(self._connection)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "RunHistory":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- session scope -------------------------------------------------------

    def _scope(self) -> tuple[str, tuple[Any, ...]]:
        """SQL restricting a ``runs`` query to this handle's session."""
        if self.session_id is None:
            return "", ()
        return " AND session_id = ?", (self.session_id,)

    def _stored_key(self, baseline_key: str) -> str:
        """The key a baseline is stored under.

        ``baseline_key`` is unique across the table, and two visitors who
        validate identically named files derive the same label. Stored
        raw, one visitor blessing a run would repoint the other's
        baseline. A session's keys carry its id instead, which the
        browser never sees, so they cannot collide with another
        session's or with the CLI's. Widening the uniqueness to a second
        column would mean rebuilding the table; this stays additive.
        """
        if self.session_id is None:
            return baseline_key
        return f"{_SESSION_PREFIX}{self.session_id}|{baseline_key}"

    # -- redaction -----------------------------------------------------------

    def _salt(self) -> bytes:
        """This database's hashing key, created on first use.

        It makes hashes useless across databases and against precomputed
        tables. It is stored beside the data, so it does not stop someone
        who holds the file from guessing short values one by one.
        """
        if self._salt_cache is None:
            created = self._connection.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('redaction_salt', ?)",
                (secrets.token_hex(32),),
            )
            if created.rowcount:
                self._connection.commit()
            row = self._connection.execute(
                "SELECT value FROM meta WHERE key = 'redaction_salt'"
            ).fetchone()
            self._salt_cache = bytes.fromhex(row[0])
        return self._salt_cache

    def _digest(self, text: str) -> str:
        return hmac.new(self._salt(), text.encode("utf-8"), "sha256").hexdigest()

    def _redact_value(self, value: str | None) -> str | None:
        """A stable stand-in for a value. Absence stays absence: that a
        target was missing is the finding itself, not a value."""
        if value is None:
            return None
        return _HASH_PREFIX + self._digest(value)[:32]

    def _redact_key(self, key: str | None) -> str | None:
        """A stable stand-in for a document's pairing key, which is a
        field value (a PO number, say) and so no safer than any other."""
        if not key or _POSITIONAL.fullmatch(key):
            return key
        return _DOC_PREFIX + self._digest("document-key\x00" + key)[:12]

    def _redacted_view(self, finding: dict[str, Any]) -> dict[str, Any]:
        """A stored-verbatim finding as a redacted run would have kept it."""
        view = dict(finding)
        view["expected"] = self._redact_value(finding.get("expected"))
        view["actual"] = self._redact_value(finding.get("actual"))
        view["message"] = REDACTED_MESSAGE
        return view

    def _finding_row(self, run_id: int, finding: Finding) -> tuple[Any, ...]:
        expected, actual, message = finding.expected, finding.actual, finding.message
        if self.values == VALUES_REDACTED:
            expected = self._redact_value(expected)
            actual = self._redact_value(actual)
            message = REDACTED_MESSAGE
        return (
            run_id,
            finding.row_id,
            finding.source_ref,
            finding.target,
            finding.status.value,
            finding.category.value if finding.category else None,
            expected,
            actual,
            message,
        )

    # -- recording -----------------------------------------------------------

    def _insert_run(
        self,
        result: RunResult,
        interchange_id: int | None = None,
        document_key: str | None = None,
        counts: dict[Status, int] | None = None,
        partner_file: str | None = None,
    ) -> int:
        counts = counts if counts is not None else result.counts
        cursor = self._connection.execute(
            "INSERT INTO runs (run_at, spec_file, source_file, output_file, result,"
            " passed, failed, warnings, not_tested, interchange_id, document_key,"
            " partner_file, session_id, values_mode)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                result.run_at.isoformat(timespec="seconds"),
                result.spec_path,
                result.source_path,
                result.output_path,
                result.overall.value,
                counts[Status.PASS],
                counts[Status.FAIL],
                counts[Status.WARNING],
                counts[Status.NOT_TESTED],
                interchange_id,
                document_key,
                partner_file,
                self.session_id,
                self.values,
            ),
        )
        run_id = cursor.lastrowid
        assert run_id is not None
        if self.values != VALUES_NONE:
            self._connection.executemany(
                "INSERT INTO findings (run_id, row_id, source_ref, target, status,"
                " category, expected, actual, message) VALUES (?,?,?,?,?,?,?,?,?)",
                [self._finding_row(run_id, f) for f in result.sorted_findings()],
            )
        return run_id

    def _prepare(self) -> None:
        """Settle the hashing key before a run's rows are written, so
        creating it never commits half a run."""
        if self.values == VALUES_REDACTED:
            self._salt()

    def _document_key(self, key: str, position: int) -> str | None:
        """A document's key as this handle's setting allows it stored."""
        if self.values == VALUES_REDACTED:
            return self._redact_key(key)
        if self.values == VALUES_NONE:
            return f"#{position}"
        return key

    def record(self, result: RunResult, partner_file: str | None = None) -> int:
        """Persist a run and its findings; returns the run id."""
        self._prepare()
        run_id = self._insert_run(result, partner_file=partner_file)
        self._connection.commit()
        return run_id

    def record_interchange(
        self, interchange: InterchangeResult, partner_file: str | None = None
    ) -> int:
        """Persist a whole interchange: a parent row whose count columns are
        the whole-interchange rollup but which stores only the file-level
        findings, plus a child run row per document. Returns the parent id."""
        parent = RunResult(
            spec_path=interchange.spec_path,
            source_path=interchange.source_path,
            output_path=interchange.output_path,
            spec_name=interchange.spec_name,
            findings=list(interchange.file_findings),
            run_at=interchange.run_at,
        )
        self._prepare()
        parent_id = self._insert_run(
            parent, counts=interchange.counts, partner_file=partner_file
        )
        for position, document in enumerate(interchange.documents, start=1):
            self._insert_run(
                document.result,
                interchange_id=parent_id,
                document_key=self._document_key(document.key, position),
                partner_file=partner_file,
            )
        self._connection.commit()
        return parent_id

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Most recent runs this handle can reach, newest first."""
        scope, params = self._scope()
        cursor = self._connection.execute(
            f"SELECT {_RUN_COLUMNS} FROM runs WHERE 1 = 1{scope}"
            " ORDER BY id DESC LIMIT ?",
            (*params, limit),
        )
        columns = [c[0] for c in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def findings_for(self, run_id: int) -> list[dict[str, Any]]:
        """All findings recorded for one run (none for a run out of reach)."""
        if self.session_id is not None and self.run(run_id) is None:
            return []
        cursor = self._connection.execute(
            "SELECT row_id, source_ref, target, status, category, expected, actual, message"
            " FROM findings WHERE run_id = ? ORDER BY id",
            (run_id,),
        )
        columns = [c[0] for c in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def run(self, run_id: int) -> dict[str, Any] | None:
        """One run row by id, or None (also for a run out of reach)."""
        scope, params = self._scope()
        cursor = self._connection.execute(
            f"SELECT {_RUN_COLUMNS} FROM runs WHERE id = ?{scope}",
            (run_id, *params),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(zip([c[0] for c in cursor.description], row))

    def values_mode_of(self, run_id: int) -> str:
        """What a recorded run's findings hold: full, redacted or none."""
        run = self.run(run_id)
        if run is None:
            raise ValueError(f"no run #{run_id} in this history database")
        return run["values_mode"] or VALUES_FULL

    def child_runs(self, parent_run_id: int) -> list[dict[str, Any]]:
        """Per-document child runs of an interchange parent, in order."""
        scope, params = self._scope()
        cursor = self._connection.execute(
            "SELECT id, document_key FROM runs WHERE interchange_id = ?"
            f"{scope} ORDER BY id",
            (parent_run_id, *params),
        )
        return [dict(zip([c[0] for c in cursor.description], r)) for r in cursor.fetchall()]

    # -- baselines (regression mode) ----------------------------------------

    def bless(self, run_id: int, baseline_key: str, label: str | None = None) -> None:
        """Mark a recorded run as the golden baseline for ``baseline_key``.

        Only a run this handle can reach, so a session cannot bless, or
        repoint a baseline at, a run that is not its own.
        """
        run = self.run(run_id)
        if run is None:
            raise ValueError(f"no run #{run_id} in this history database")
        if (run["values_mode"] or VALUES_FULL) == VALUES_NONE:
            raise ValueError(
                f"run #{run_id} was recorded without findings "
                "(MAPCHECK_HISTORY_VALUES=none), so it cannot serve as a baseline"
            )
        from datetime import datetime, timezone

        self._connection.execute(
            "INSERT INTO baselines (baseline_key, run_id, label, blessed_at)"
            " VALUES (?,?,?,?)"
            " ON CONFLICT(baseline_key) DO UPDATE SET"
            " run_id=excluded.run_id, label=excluded.label, blessed_at=excluded.blessed_at",
            (
                self._stored_key(baseline_key),
                run_id,
                label,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        self._connection.commit()

    def baselines(self) -> list[dict[str, Any]]:
        """Every blessed baseline this handle can reach, most recently
        blessed first. A session sees its own, under the keys it used."""
        prefix = self._stored_key("")
        cursor = self._connection.execute(
            "SELECT baseline_key, run_id, label, blessed_at FROM baselines"
            " WHERE substr(baseline_key, 1, ?) = ?"
            " ORDER BY blessed_at DESC, id DESC",
            (len(prefix), prefix),
        )
        columns = [c[0] for c in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        for row in rows:
            row["baseline_key"] = row["baseline_key"][len(prefix):]
        return rows

    def baseline_for(self, baseline_key: str) -> dict[str, Any] | None:
        """The blessed baseline for a key, or None."""
        cursor = self._connection.execute(
            "SELECT run_id, label, blessed_at FROM baselines WHERE baseline_key = ?",
            (self._stored_key(baseline_key),),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(zip([c[0] for c in cursor.description], row))

    def snapshot(
        self, run_id: int, redact: bool = False
    ) -> dict[str, list[dict[str, Any]]]:
        """A run's findings grouped by document key (``""`` = file-level /
        single-document), reconstructed from the DB for diffing.

        ``redact`` returns the run as a redacted one would have stored it,
        hashing on the way out when it was stored verbatim. That is what
        lets a baseline blessed under ``full`` still be compared after the
        store switches to ``redacted``, value against value, with neither
        side shown.
        """
        run = self.run(run_id)
        if run is None:
            raise ValueError(f"no run #{run_id} in this history database")
        convert = redact and (run["values_mode"] or VALUES_FULL) == VALUES_FULL

        def findings(of_run: int) -> list[dict[str, Any]]:
            rows = self.findings_for(of_run)
            return [self._redacted_view(f) for f in rows] if convert else rows

        snap: dict[str, list[dict[str, Any]]] = {"": findings(run_id)}
        for child in self.child_runs(run_id):
            key = child["document_key"]
            if convert:
                key = self._redact_key(key)
            snap[key or ""] = findings(child["id"])
        return snap
