"""Validation engine: rule evaluation, findings, and run results."""

from mapcheck.engine.results import Category, Finding, RunResult, Status
from mapcheck.engine.validator import validate, validate_files

__all__ = ["Category", "Finding", "RunResult", "Status", "validate", "validate_files"]
