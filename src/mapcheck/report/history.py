"""SQLite persistence of validation runs."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from mapcheck.engine.results import InterchangeResult, RunResult, Status

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
"""


def _migrate(connection: sqlite3.Connection) -> None:
    """Additively add multi-transaction columns to an existing runs table."""
    existing = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
    if "interchange_id" not in existing:
        connection.execute("ALTER TABLE runs ADD COLUMN interchange_id INTEGER")
    if "document_key" not in existing:
        connection.execute("ALTER TABLE runs ADD COLUMN document_key TEXT")


class RunHistory:
    """Validation run history stored in a SQLite database file."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._connection = sqlite3.connect(self.db_path)
        self._connection.executescript(_SCHEMA)
        _migrate(self._connection)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "RunHistory":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _insert_run(
        self,
        result: RunResult,
        interchange_id: int | None = None,
        document_key: str | None = None,
        counts: dict[Status, int] | None = None,
    ) -> int:
        counts = counts if counts is not None else result.counts
        cursor = self._connection.execute(
            "INSERT INTO runs (run_at, spec_file, source_file, output_file, result,"
            " passed, failed, warnings, not_tested, interchange_id, document_key)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
            ),
        )
        run_id = cursor.lastrowid
        assert run_id is not None
        self._connection.executemany(
            "INSERT INTO findings (run_id, row_id, source_ref, target, status,"
            " category, expected, actual, message) VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    run_id,
                    f.row_id,
                    f.source_ref,
                    f.target,
                    f.status.value,
                    f.category.value if f.category else None,
                    f.expected,
                    f.actual,
                    f.message,
                )
                for f in result.sorted_findings()
            ],
        )
        return run_id

    def record(self, result: RunResult) -> int:
        """Persist a run and its findings; returns the run id."""
        run_id = self._insert_run(result)
        self._connection.commit()
        return run_id

    def record_interchange(self, interchange: InterchangeResult) -> int:
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
        parent_id = self._insert_run(parent, counts=interchange.counts)
        for document in interchange.documents:
            self._insert_run(
                document.result, interchange_id=parent_id, document_key=document.key
            )
        self._connection.commit()
        return parent_id

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Most recent runs, newest first."""
        cursor = self._connection.execute(
            "SELECT id, run_at, spec_file, source_file, output_file, result,"
            " passed, failed, warnings, not_tested, interchange_id, document_key"
            " FROM runs ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        columns = [c[0] for c in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def findings_for(self, run_id: int) -> list[dict[str, Any]]:
        """All findings recorded for one run."""
        cursor = self._connection.execute(
            "SELECT row_id, source_ref, target, status, category, expected, actual, message"
            " FROM findings WHERE run_id = ? ORDER BY id",
            (run_id,),
        )
        columns = [c[0] for c in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
