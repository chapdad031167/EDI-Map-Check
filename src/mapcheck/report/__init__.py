"""Reporting: terminal output, Excel export, and SQLite run history."""

from mapcheck.report.excel import export_excel
from mapcheck.report.history import RunHistory
from mapcheck.report.terminal import render_report

__all__ = ["RunHistory", "export_excel", "render_report"]
