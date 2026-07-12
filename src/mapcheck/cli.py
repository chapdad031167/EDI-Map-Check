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
from mapcheck.engine.validator import validate_files, validate_interchange_files
from mapcheck.output.adapter import OutputLoadError
from mapcheck.output.idoc import DefinitionError
from mapcheck.report.excel import export_excel
from mapcheck.report.history import RunHistory
from mapcheck.report.terminal import render_interchange_report, render_report
from mapcheck.spec.parser import SpecLoadError, load_spec
from mapcheck.spec.template import create_template
from mapcheck.x12.parser import X12ParseError

DEFAULT_DB = "mapcheck_history.db"

#: Exit code for input/usage problems (1 is reserved for FAIL results).
EXIT_USAGE = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mapcheck",
        description=(
            "EDI MapCheck — validate that a translated file matches what the "
            "mapping spec says its source should produce, in either direction "
            "(X12 to internal, or internal to X12)."
        ),
    )
    parser.add_argument("--version", action="version", version=f"mapcheck {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate", help="run a validation")
    p_val.add_argument("--spec", required=True, help="mapping spec workbook (.xlsx)")
    p_val.add_argument(
        "--partner",
        metavar="DELTA",
        help="a partner delta workbook (.xlsx) merged onto --spec before validating",
    )
    p_val.add_argument(
        "--source",
        required=True,
        help="the translation's input (X12 for inbound specs, internal document for outbound)",
    )
    p_val.add_argument(
        "--output",
        required=True,
        help="the translation's result (internal document for inbound specs, X12 for outbound)",
    )
    p_val.add_argument(
        "--transaction",
        metavar="SET",
        help="force a transaction set (default: auto-detect from the X12 file's ST01)",
    )
    p_val.add_argument(
        "--output-def",
        metavar="PATH",
        help="register a user-supplied output-format definition (.yaml) and use it "
        "for the output file (for formats that can't be auto-detected, e.g. delimited)",
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
    p_init.add_argument(
        "--direction",
        choices=("inbound", "outbound"),
        default="inbound",
        help="map direction preset for the Meta sheet (default: inbound)",
    )

    p_imp = sub.add_parser(
        "import-spec", help="import a partner mapping document (.xlsx/.csv) into a spec"
    )
    p_imp.add_argument("input", help="partner mapping document (.xlsx or .csv)")
    p_imp.add_argument("--output", required=True, help="native MapCheck spec to write (.xlsx)")
    p_imp.add_argument(
        "--map",
        metavar="COLS",
        help="override column detection, e.g. "
        "\"Source Field=B, Target Field=E, Rule Type=F\" (header name or column letter)",
    )
    p_imp.add_argument(
        "--code-lists",
        metavar="PATH",
        help="a lookup-table document (.xlsx/.csv) to import into the CodeLists sheet",
    )
    p_imp.add_argument("--transaction", metavar="SET", help="Meta Transaction Set value")
    p_imp.add_argument(
        "--direction", choices=("inbound", "outbound"), help="Meta Direction value"
    )
    p_imp.add_argument("--spec-name", metavar="NAME", help="Meta Spec Name value")

    p_merge = sub.add_parser(
        "merge-spec", help="merge a partner delta onto a base spec and write the effective spec"
    )
    p_merge.add_argument("base", help="base mapping spec workbook (.xlsx)")
    p_merge.add_argument("--partner", required=True, help="partner delta workbook (.xlsx)")
    p_merge.add_argument("--output", required=True, help="effective merged spec to write (.xlsx)")

    p_hist = sub.add_parser("history", help="list recent validation runs")
    p_hist.add_argument("--db", default=DEFAULT_DB, help="SQLite history database")
    p_hist.add_argument("--limit", type=int, default=20, help="number of runs to show")

    sub.add_parser("transactions", help="list registered transaction definitions")
    return parser


def _is_interchange(spec, source_path: str, output_path: str) -> bool:
    """True when either side carries more than one document.

    Detects a JSON-array output container or an X12 file with more than one
    ST/SE, on whichever side the spec's direction makes the X12 file.
    """
    from mapcheck.spec.model import Direction
    from mapcheck.x12.parser import parse_interchange

    outbound = spec.direction is Direction.OUTBOUND
    x12_path = output_path if outbound else source_path
    canonical_path = source_path if outbound else output_path
    if Path(canonical_path).suffix.lower() == ".json":
        import json

        try:
            with open(canonical_path, encoding="utf-8") as fh:
                if isinstance(json.load(fh), list):
                    return True
        except (OSError, json.JSONDecodeError):
            pass
    try:
        return len(parse_interchange(x12_path).documents) > 1
    except X12ParseError:
        return False


def _cmd_validate(args: argparse.Namespace) -> int:
    color = False if args.no_color else None
    output_format = None
    merged_spec = None
    try:
        if args.output_def:
            from mapcheck.output.idoc import register_output_definition

            output_format = register_output_definition(args.output_def).format
        if args.partner:
            from mapcheck.spec.overrides import resolve_spec

            merged_spec, merge_warnings = resolve_spec(args.spec, args.partner)
            spec = merged_spec
            for note in merge_warnings:
                print(f"mapcheck: partner merge note: {note}", file=sys.stderr)
        else:
            spec = load_spec(args.spec)
        if _is_interchange(spec, args.source, args.output):
            return _run_interchange(args, color, output_format, merged_spec)
        result = validate_files(
            args.spec, args.source, args.output,
            transaction=args.transaction, output_format=output_format, spec=merged_spec,
        )
    except (SpecLoadError, X12ParseError, OutputLoadError, DefinitionError) as exc:
        print(f"mapcheck: {exc}", file=sys.stderr)
        return EXIT_USAGE

    print(render_report(result, verbose=args.verbose, color=color))

    if not args.no_history:
        with RunHistory(args.db) as history:
            run_id = history.record(result)
        print(f"\nRun #{run_id} recorded in {args.db}")

    if args.export_xlsx:
        path = export_excel(result, args.export_xlsx)
        print(f"Excel report written to {path}")
    return result.exit_code


def _run_interchange(
    args: argparse.Namespace, color: bool | None, output_format: str | None = None,
    spec=None,
) -> int:
    result = validate_interchange_files(
        args.spec, args.source, args.output,
        transaction=args.transaction, output_format=output_format, spec=spec,
    )
    print(render_interchange_report(result, verbose=args.verbose, color=color))

    if not args.no_history:
        with RunHistory(args.db) as history:
            run_id = history.record_interchange(result)
        print(f"\nInterchange run #{run_id} ({len(result.documents)} documents) recorded in {args.db}")

    if args.export_xlsx:
        print("Excel export of interchange runs is not yet supported; skipped.", file=sys.stderr)
    return result.exit_code


def _cmd_init_spec(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if path.exists():
        print(f"mapcheck: {path} already exists, not overwriting", file=sys.stderr)
        return EXIT_USAGE
    create_template(path, direction=args.direction)
    print(f"Blank spec template written to {path}")
    return 0


def _parse_map_overrides(text: str | None) -> dict[str, str]:
    if not text:
        return {}
    overrides: dict[str, str] = {}
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, sep, value = chunk.partition("=")
        if not sep:
            raise ValueError(f"malformed --map entry {chunk!r} (expected 'Our Column=their header')")
        overrides[key.strip()] = value.strip()
    return overrides


def _cmd_import_spec(args: argparse.Namespace) -> int:
    from mapcheck.spec.importer import (
        ImportError_,
        format_worklist,
        import_mapping,
        write_workbook,
        write_worklist,
    )

    output = Path(args.output)
    if output.exists():
        print(f"mapcheck: {output} already exists, not overwriting", file=sys.stderr)
        return EXIT_USAGE
    meta: dict[str, str] = {}
    if args.transaction:
        meta["Transaction Set"] = args.transaction
    if args.direction:
        meta["Direction"] = args.direction
    if args.spec_name:
        meta["Spec Name"] = args.spec_name
    try:
        overrides = _parse_map_overrides(args.map)
        result = import_mapping(
            args.input, overrides=overrides, meta=meta, code_lists_path=args.code_lists
        )
    except (ImportError_, ValueError) as exc:
        print(f"mapcheck: {exc}", file=sys.stderr)
        return EXIT_USAGE

    write_workbook(result, output)
    worklist_path = output.with_suffix(output.suffix + ".worklist.txt")
    write_worklist(result, worklist_path)

    print(format_worklist(result))
    print(f"Spec written to {output}")
    print(f"Worklist written to {worklist_path}")
    if result.review_rows:
        print(
            f"\n{len(result.review_rows)} row(s) need review before the spec will load."
        )
    return 0


def _cmd_merge_spec(args: argparse.Namespace) -> int:
    from mapcheck.spec.overrides import export_spec, resolve_spec

    output = Path(args.output)
    if output.exists():
        print(f"mapcheck: {output} already exists, not overwriting", file=sys.stderr)
        return EXIT_USAGE
    try:
        merged, warnings = resolve_spec(args.base, args.partner)
    except SpecLoadError as exc:
        print(f"mapcheck: {exc}", file=sys.stderr)
        return EXIT_USAGE
    for note in warnings:
        print(f"mapcheck: {note}", file=sys.stderr)
    export_spec(merged, output)
    overrides = sum(1 for r in merged.rules if r.origin != "base")
    print(
        f"Effective spec written to {output} — {len(merged.rules)} rules "
        f"({overrides} from the partner delta)"
    )
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
        "import-spec": _cmd_import_spec,
        "merge-spec": _cmd_merge_spec,
        "history": _cmd_history,
        "transactions": _cmd_transactions,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
