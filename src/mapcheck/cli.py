"""The ``mapcheck`` command-line interface.

Subcommands:

* ``mapcheck validate --spec spec.xlsx --source po.edi --output out.json``
* ``mapcheck init-spec new_spec.xlsx`` — write a blank spec template
* ``mapcheck history`` — list recent validation runs
* ``mapcheck transactions`` — list registered transaction definitions
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mapcheck import __version__
from mapcheck.engine.validator import validate_files
from mapcheck.output.adapter import OutputLoadError
from mapcheck.report.excel import export_excel
from mapcheck.report.history import RunHistory
from mapcheck.report.terminal import render_report
from mapcheck.spec.parser import SpecLoadError
from mapcheck.spec.template import create_template
from mapcheck.x12.parser import X12ParseError

DEFAULT_DB = "mapcheck_history.db"

#: Exit code for input/usage problems (1 is reserved for FAIL results).
EXIT_USAGE = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mapcheck",
        description=(
            "EDI MapCheck — validate that a translated output file matches "
            "what the mapping spec says an X12 850 source should produce."
        ),
    )
    parser.add_argument("--version", action="version", version=f"mapcheck {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate", help="run a validation")
    p_val.add_argument("--spec", required=True, help="mapping spec workbook (.xlsx)")
    p_val.add_argument("--source", required=True, help="X12 850 source file")
    p_val.add_argument("--output", required=True, help="translated output file (.json or flat)")
    p_val.add_argument(
        "--transaction",
        metavar="SET",
        help="force a transaction set (default: auto-detect from the source file's ST01)",
    )
    p_val.add_argument(
        "--export-xlsx",
        metavar="PATH",
        help="also write a color-coded Excel report to PATH",
    )
    p_val.add_argument(
        "--db",
        default=DEFAULT_DB,
        help=f"SQLite history database (default: ./{DEFAULT_DB})",
    )
    p_val.add_argument(
        "--no-history", action="store_true", help="do not record this run in the history db"
    )
    p_val.add_argument(
        "-v", "--verbose", action="store_true", help="include PASS rows in the report"
    )
    p_val.add_argument(
        "--no-color", action="store_true", help="disable ANSI colors in the report"
    )

    p_init = sub.add_parser("init-spec", help="write a blank mapping spec template")
    p_init.add_argument("path", help="where to write the template (.xlsx)")

    p_hist = sub.add_parser("history", help="list recent validation runs")
    p_hist.add_argument("--db", default=DEFAULT_DB, help="SQLite history database")
    p_hist.add_argument("--limit", type=int, default=20, help="number of runs to show")

    sub.add_parser("transactions", help="list registered transaction definitions")
    return parser


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        result = validate_files(
            args.spec, args.source, args.output, transaction=args.transaction
        )
    except (SpecLoadError, X12ParseError, OutputLoadError) as exc:
        print(f"mapcheck: {exc}", file=sys.stderr)
        return EXIT_USAGE

    color = False if args.no_color else None
    print(render_report(result, verbose=args.verbose, color=color))

    if not args.no_history:
        with RunHistory(args.db) as history:
            run_id = history.record(result)
        print(f"\nRun #{run_id} recorded in {args.db}")

    if args.export_xlsx:
        path = export_excel(result, args.export_xlsx)
        print(f"Excel report written to {path}")
    return result.exit_code


def _cmd_init_spec(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if path.exists():
        print(f"mapcheck: {path} already exists, not overwriting", file=sys.stderr)
        return EXIT_USAGE
    create_template(path)
    print(f"Blank spec template written to {path}")
    return 0


def _cmd_history(args: argparse.Namespace) -> int:
    if not Path(args.db).exists():
        print(f"mapcheck: no history database at {args.db}", file=sys.stderr)
        return EXIT_USAGE
    with RunHistory(args.db) as history:
        runs = history.recent_runs(limit=args.limit)
    if not runs:
        print("No runs recorded yet.")
        return 0
    header = (
        f"{'ID':>4}  {'RUN AT (UTC)':<20} {'RESULT':<8} "
        f"{'PASS':>5} {'FAIL':>5} {'WARN':>5} {'N/T':>5}  SOURCE -> OUTPUT"
    )
    print(header)
    for run in runs:
        print(
            f"{run['id']:>4}  {run['run_at']:<20} {run['result']:<8} "
            f"{run['passed']:>5} {run['failed']:>5} {run['warnings']:>5} "
            f"{run['not_tested']:>5}  "
            f"{Path(run['source_file']).name} -> {Path(run['output_file']).name}"
        )
    return 0


def _cmd_transactions(args: argparse.Namespace) -> int:
    from mapcheck.transactions.registry import default_registry

    definitions = default_registry.all()
    print(f"{'SET':<6} {'NAME':<40} {'GROUP':<6} {'VERSION':<8} LOOPS")
    for definition in definitions:
        loops = ", ".join(loop.id for loop in definition.all_loops()) or "-"
        print(
            f"{definition.set_code:<6} {definition.name:<40} "
            f"{definition.functional_group:<6} {definition.version or '-':<8} {loops}"
        )
    print(f"\n{len(definitions)} transaction definition(s) registered")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    handlers = {
        "validate": _cmd_validate,
        "init-spec": _cmd_init_spec,
        "history": _cmd_history,
        "transactions": _cmd_transactions,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
