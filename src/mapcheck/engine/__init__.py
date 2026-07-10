"""Validation engine: rule evaluation, findings, and run results."""

from mapcheck.engine.results import (
    Category,
    DocumentResult,
    Finding,
    InterchangeResult,
    RunResult,
    Status,
)
from mapcheck.engine.validator import (
    validate,
    validate_files,
    validate_interchange,
    validate_interchange_files,
)

__all__ = [
    "Category",
    "DocumentResult",
    "Finding",
    "InterchangeResult",
    "RunResult",
    "Status",
    "validate",
    "validate_files",
    "validate_interchange",
    "validate_interchange_files",
]
