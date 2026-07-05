"""Findings and run results produced by the validation engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    NOT_TESTED = "NOT TESTED"


class Category(str, Enum):
    """Root-cause grouping for non-PASS findings."""

    VALUE_MISMATCH = "value_mismatch"  # wrong value landed in the target
    MISSING_OUTPUT = "missing_output"  # expected a value, target absent
    UNEXPECTED_OUTPUT = "unexpected_output"  # target populated when it must be absent
    CONDITION_LOGIC = "condition_logic"  # wrong if/then branch fired
    CODE_TRANSLATION = "code_translation"  # code list lookup wrong or impossible
    CONSTANT_DEFAULT = "constant_default"  # hardcoded/default value wrong or missing
    FORMAT = "format"  # data type, format, or length violation
    COUNT_MISMATCH = "count_mismatch"  # loop/line/CTT reconciliation failed
    SOURCE_DATA = "source_data"  # source value invalid per the spec
    UNMAPPED_SOURCE = "unmapped_source"  # source data no rule references
    UNMAPPED_TARGET = "unmapped_target"  # output data no rule produces
    CONTROL = "control"  # interchange control problems (pyx12)


@dataclass(frozen=True)
class Finding:
    """One line of the validation report."""

    status: Status
    message: str
    row_id: str | None = None  # spec Row ID, when tied to a rule
    sheet_row: int | None = None  # Excel row in the Mapping sheet
    source_ref: str = ""  # e.g. "N1[ST] N104" or "PO1 #2 PO103"
    target: str = ""  # concrete target path, e.g. "lines[1].uom"
    expected: str | None = None
    actual: str | None = None
    category: Category | None = None

    @property
    def sort_key(self) -> tuple[int, str]:
        order = {
            Status.FAIL: 0,
            Status.WARNING: 1,
            Status.NOT_TESTED: 2,
            Status.PASS: 3,
        }
        return order[self.status], self.row_id or "~"


@dataclass
class RunResult:
    """Everything one validation run produced."""

    spec_path: str
    source_path: str
    output_path: str
    spec_name: str | None = None
    findings: list[Finding] = field(default_factory=list)
    run_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def counts(self) -> dict[Status, int]:
        counts = {status: 0 for status in Status}
        for finding in self.findings:
            counts[finding.status] += 1
        return counts

    @property
    def category_counts(self) -> dict[Category, int]:
        counts: dict[Category, int] = {}
        for finding in self.findings:
            if finding.category is not None and finding.status is not Status.PASS:
                counts[finding.category] = counts.get(finding.category, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    @property
    def overall(self) -> Status:
        counts = self.counts
        if counts[Status.FAIL]:
            return Status.FAIL
        if counts[Status.WARNING]:
            return Status.WARNING
        return Status.PASS

    @property
    def exit_code(self) -> int:
        return 1 if self.counts[Status.FAIL] else 0

    def sorted_findings(self) -> list[Finding]:
        return sorted(self.findings, key=lambda f: f.sort_key)
