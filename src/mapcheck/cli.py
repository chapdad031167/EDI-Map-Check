"""The ``mapcheck`` command-line interface.

Subcommands:

* ``mapcheck validate --spec spec.xlsx --source po.edi --output out.json``
* ``mapcheck init-spec new_spec.xlsx`` — write a blank spec template
* ``mapcheck import-guide guide.pdf`` — parse a partner implementation guide
* ``mapcheck history`` — list recent validation runs
* ``mapcheck transactions`` — list registered transaction definitions
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from mapcheck import __version__
from mapcheck.engine.validator import validate_files, validate_interchange_files
from mapcheck.guides.overlay import PartnerRulesError
from mapcheck.output.adapter import OutputLoadError
from mapcheck.output.idoc import DefinitionError
from mapcheck.report.excel import export_excel
from mapcheck.report.history import RunHistory
from mapcheck.report.terminal import render_interchange_report, render_report
from mapcheck.spec.parser import SpecLoadError, load_spec
from mapcheck.spec.template import create_template
from mapcheck.x12.parser import X12ParseError

DEFAULT_DB = "mapcheck_history.db"


def _default_db() -> str:
    """Where run history goes when ``--db`` is not given.

    ``MAPCHECK_HISTORY_DB`` overrides it, the same variable the UI has
    always honored (Design 016). Without this the two halves of a
    container disagreed: the UI wrote where the variable pointed and
    the CLI wrote beside the working directory, so ``mapcheck history``
    showed none of the runs the UI had just recorded.
    """
    return os.environ.get("MAPCHECK_HISTORY_DB") or DEFAULT_DB

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
        "--partner-rules",
        metavar="OVERLAY",
        help="a partner-rules overlay (.yaml, from import-guide) whose presence "
        "rules are enforced on top of the base standard",
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
        "--export-html",
        metavar="PATH",
        help="also write a self-contained HTML report to PATH",
    )
    p_val.add_argument(
        "--db",
        default=_default_db(),
        help=f"SQLite history database (default: {_default_db()})",
    )
    p_val.add_argument(
        "--no-history", action="store_true",
        help="do not record this run in the history db (a recorded run stores expected/actual values verbatim, unmasked)",
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

    p_draft = sub.add_parser(
        "draft-spec",
        help="generate a draft mapping spec from the built-in definitions and a crosswalk",
    )
    p_draft.add_argument(
        "--transaction", required=True, metavar="SET", help="source transaction set (e.g. 850)"
    )
    p_draft.add_argument(
        "--target", required=True, metavar="FORMAT",
        help="target output format (e.g. orders05)",
    )
    p_draft.add_argument("--output", required=True, help="draft spec to write (.xlsx)")
    p_draft.add_argument(
        "--crosswalk", action="append", metavar="FILE", default=[],
        help="crosswalk YAML applied on top of the bundled starter crosswalk; "
        "repeatable — for the same target path, a later file's rule replaces "
        "an earlier one",
    )
    p_draft.add_argument(
        "--fill-unmapped", action="store_true",
        help="also emit TODO rows for optional (non-required) target paths",
    )
    p_draft.add_argument(
        "--guide",
        metavar="PROFILE",
        help="a guide profile (.yaml, from import-guide) that flavors the "
        "draft: partner notes, code subsets, and not-used elements",
    )

    p_guide = sub.add_parser(
        "import-guide",
        help="parse a partner implementation guide (.pdf/.txt) into a reviewable profile",
    )
    p_guide.add_argument(
        "input", help="implementation guide in the templated layout (.pdf or .txt)"
    )
    p_guide.add_argument(
        "--transaction", required=True, metavar="SET",
        help="transaction set the guide describes (e.g. 850) — stated, never guessed",
    )
    p_guide.add_argument(
        "--partner", required=True, metavar="NAME",
        help="partner name stamped into the profile and its findings",
    )
    p_guide.add_argument(
        "--profile", required=True, metavar="PATH",
        help="guide profile to write (.yaml)",
    )
    p_guide.add_argument(
        "--overlay", metavar="PATH",
        help="also write a partner-rules overlay (.yaml) for validate --partner-rules",
    )

    p_hist = sub.add_parser("history", help="list recent validation runs")
    p_hist.add_argument("--db", default=_default_db(), help="SQLite history database")
    p_hist.add_argument("--limit", type=int, default=20, help="number of runs to show")

    p_report = sub.add_parser(
        "report", help="history trends (pass-rate per spec, top root causes)"
    )
    p_report.add_argument("--db", default=_default_db(), help="SQLite history database")
    p_report.add_argument("--html", metavar="PATH", help="write a self-contained HTML dashboard")
    p_report.add_argument(
        "--limit", type=int, default=200, help="how many recent runs to aggregate"
    )

    p_bless = sub.add_parser(
        "bless", help="mark a recorded run as the golden baseline for its inputs"
    )
    p_bless.add_argument("run_id", type=int, help="run id (from `mapcheck history`) to bless")
    p_bless.add_argument(
        "--label",
        help="name this baseline instead of auto-keying by the run's paths "
        "(use when paths differ across machines, or for partner baselines)",
    )
    p_bless.add_argument("--db", default=_default_db(), help="SQLite history database")

    p_reg = sub.add_parser(
        "regress", help="validate now and report only the delta from the blessed baseline"
    )
    p_reg.add_argument("--spec", required=True, help="mapping spec workbook (.xlsx)")
    p_reg.add_argument(
        "--partner", metavar="DELTA", help="a partner delta workbook merged onto --spec"
    )
    p_reg.add_argument("--source", required=True, help="the translation's input")
    p_reg.add_argument("--output", required=True, help="the translation's result")
    p_reg.add_argument("--transaction", metavar="SET", help="force a transaction set")
    p_reg.add_argument(
        "--output-def", metavar="PATH", help="register an output-format definition (.yaml)"
    )
    p_reg.add_argument(
        "--label", help="match the baseline by this name instead of the input paths"
    )
    p_reg.add_argument("--db", default=_default_db(), help="SQLite history database")
    p_reg.add_argument("--no-color", action="store_true", help="disable ANSI colors")

    p_batch = sub.add_parser(
        "batch", help="run many checks from a mapcheck.yaml manifest (CI mode)"
    )
    p_batch.add_argument(
        "manifest", nargs="?", default="mapcheck.yaml",
        help="manifest file (default: ./mapcheck.yaml)",
    )
    p_batch.add_argument("--junit", metavar="PATH", help="also write a JUnit-XML report")
    p_batch.add_argument(
        "--strict", action="store_true", help="promote any WARNING to a build failure"
    )
    p_batch.add_argument("--db", default=_default_db(), help="SQLite history database")
    p_batch.add_argument(
        "--no-history", action="store_true",
        help="do not record these runs in the history db (a recorded run stores expected/actual values verbatim, unmasked)",
    )
    p_batch.add_argument("--no-color", action="store_true", help="disable ANSI colors")

    p_scrub = sub.add_parser(
        "scrub", help="mask sensitive values in an X12 file, preserving structure"
    )
    p_scrub.add_argument("input", help="X12 file to scrub (.edi)")
    p_scrub.add_argument(
        "-o", "--output", metavar="PATH",
        help="where to write the scrubbed file (default: INPUT.scrubbed.EXT)",
    )
    p_scrub.add_argument(
        "--profile", metavar="NAME|PATH", default="pharma",
        help="scrub profile — a bundled name (pharma) or a .yaml path",
    )
    p_scrub.add_argument(
        "--seed", metavar="VALUE",
        help="salt for reproducible masking (default: random per run)",
    )
    p_scrub.add_argument(
        "--report", action="store_true", help="print a summary of what was masked"
    )

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
    partner_rules = None
    try:
        if args.output_def:
            from mapcheck.output.idoc import register_output_definition

            output_format = register_output_definition(args.output_def).format
        if args.partner_rules:
            from mapcheck.guides.overlay import PartnerRules

            partner_rules = PartnerRules.load(args.partner_rules)
            # Rules the overlay could not express are not enforced — say so
            # at the moment someone relies on the overlay.
            for note in partner_rules.review:
                print(f"mapcheck: partner rules note (not enforced): {note}", file=sys.stderr)
        if args.partner:
            from mapcheck.spec.overrides import resolve_spec

            merged_spec, merge_warnings = resolve_spec(args.spec, args.partner)
            spec = merged_spec
            for note in merge_warnings:
                print(f"mapcheck: partner merge note: {note}", file=sys.stderr)
        else:
            spec = load_spec(args.spec)
        if _is_interchange(spec, args.source, args.output):
            return _run_interchange(args, color, output_format, merged_spec, partner_rules)
        result = validate_files(
            args.spec, args.source, args.output,
            transaction=args.transaction, output_format=output_format, spec=merged_spec,
            partner_rules=partner_rules,
        )
    except (
        SpecLoadError, X12ParseError, OutputLoadError, DefinitionError, PartnerRulesError,
    ) as exc:
        print(f"mapcheck: {exc}", file=sys.stderr)
        return EXIT_USAGE

    print(render_report(result, verbose=args.verbose, color=color))

    if not args.no_history:
        with RunHistory(args.db) as history:
            run_id = history.record(result, partner_file=args.partner)
        print(f"\nRun #{run_id} recorded in {args.db}")

    if args.export_xlsx:
        path = export_excel(result, args.export_xlsx)
        print(f"Excel report written to {path}")

    if args.export_html:
        from mapcheck.report.html import export_html

        path = export_html(result, args.export_html)
        print(f"HTML report written to {path}")
    return result.exit_code


def _run_interchange(
    args: argparse.Namespace, color: bool | None, output_format: str | None = None,
    spec=None, partner_rules=None,
) -> int:
    result = validate_interchange_files(
        args.spec, args.source, args.output,
        transaction=args.transaction, output_format=output_format, spec=spec,
        partner_rules=partner_rules,
    )
    print(render_interchange_report(result, verbose=args.verbose, color=color))

    if not args.no_history:
        with RunHistory(args.db) as history:
            run_id = history.record_interchange(result, partner_file=args.partner)
        print(f"\nInterchange run #{run_id} ({len(result.documents)} documents) recorded in {args.db}")

    if args.export_xlsx:
        print("Excel export of interchange runs is not yet supported; skipped.", file=sys.stderr)

    if getattr(args, "export_html", None):
        from mapcheck.report.html import export_html

        path = export_html(result, args.export_html)
        print(f"HTML report written to {path}")
    return result.exit_code


def _resolve_draft_target(name: str):
    """Resolve a --target name against the output-format registry.

    Accepts the registry's format name exactly ('idoc-orders05') or the
    short name users actually say ('orders05').
    """
    from mapcheck.output.idoc import default_output_registry as output_registry

    for defn in output_registry.all():
        if name in (defn.format, defn.format.rsplit("-", 1)[-1]):
            return defn
    known = ", ".join(sorted(d.format for d in output_registry.all()))
    raise DefinitionError(f"unknown target format {name!r} (registered: {known})")


def _load_draft_guide(guide_arg: str, set_code: str):
    """Resolve draft-spec's --guide: a profile .yaml or a raw guide file.

    A raw guide parses with the draft's transaction set and no partner
    name (the profile is transient here — import-guide is the verb that
    names and keeps one). A profile for a different transaction set is an
    error, never silently flavored onto the wrong draft.
    """
    from mapcheck.guides.parser import parse_guide
    from mapcheck.guides.profile import GuideProfile, GuideProfileError

    path = Path(guide_arg)
    if path.suffix.lower() in (".yaml", ".yml"):
        profile = GuideProfile.load(path)
    else:
        profile = parse_guide(path, transaction=set_code, partner="")
    if profile.transaction != set_code:
        raise GuideProfileError(
            f"{path}: guide profile is for transaction set {profile.transaction} "
            f"but the draft is a {set_code}"
        )
    return profile


def _cmd_draft_spec(args: argparse.Namespace) -> int:
    from mapcheck.guides.parser import GuideParseError
    from mapcheck.guides.profile import GuideProfileError
    from mapcheck.spec.draft import (
        CrosswalkError,
        DraftSpecError,
        bundled_crosswalks,
        generate_draft,
    )
    from mapcheck.transactions.registry import UnknownTransactionError, default_registry

    output = Path(args.output)
    if output.exists():
        print(f"mapcheck: {output} already exists, not overwriting", file=sys.stderr)
        return EXIT_USAGE
    try:
        definition = default_registry.get(args.transaction)
        target_def = _resolve_draft_target(args.target)
        guide = (
            _load_draft_guide(args.guide, definition.set_code) if args.guide else None
        )
        short_target = target_def.format.rsplit("-", 1)[-1]
        crosswalks = [
            *bundled_crosswalks(definition.set_code, short_target),
            *args.crosswalk,
        ]
        result = generate_draft(
            definition,
            target_def,
            crosswalks,
            output,
            include_optional_todos=args.fill_unmapped,
            guide=guide,
        )
    except (
        UnknownTransactionError, DefinitionError, CrosswalkError, DraftSpecError,
        GuideParseError, GuideProfileError,
    ) as exc:
        print(f"mapcheck: {exc}", file=sys.stderr)
        return EXIT_USAGE

    filled = sum(1 for row in result.rows if row.filled)
    print(f"Draft spec written to {output}")
    print(
        f"Rows: {len(result.rows)} ({filled} filled from "
        f"{len(result.crosswalk_files)} crosswalk file(s), {result.todo_count} TODO)"
    )
    print(f"Unmapped source elements: {len(result.unmapped_source)} (see the Unmapped Source sheet)")
    print(
        f"Prefill: {result.prefill:.2f} "
        f"({result.filled_required}/{result.total_required} required targets filled)"
    )
    if guide is not None:
        partner = f"partner {guide.partner}" if guide.partner else "the partner guide"
        print(
            f"Guide: flavored by {partner} ({guide.source or args.guide}) — "
            f"parse coverage {guide.parse_coverage:.2f}"
        )
        for note in guide.review:
            print(f"  - guide review: {note}")
        if result.guide_review:
            print(
                f"{len(result.guide_review)} decision(s) need review "
                "(see the Guide Review sheet):"
            )
            for note in result.guide_review:
                print(f"  - {note}")
    return 0


def _cmd_import_guide(args: argparse.Namespace) -> int:
    from mapcheck.guides.overlay import emit_partner_rules
    from mapcheck.guides.parser import GuideParseError, parse_guide
    from mapcheck.transactions.registry import default_registry

    profile_path = Path(args.profile)
    if profile_path.exists():
        print(f"mapcheck: {profile_path} already exists, not overwriting", file=sys.stderr)
        return EXIT_USAGE
    overlay_path = Path(args.overlay) if args.overlay else None
    if overlay_path is not None and overlay_path.exists():
        print(f"mapcheck: {overlay_path} already exists, not overwriting", file=sys.stderr)
        return EXIT_USAGE
    try:
        profile = parse_guide(
            args.input, transaction=args.transaction, partner=args.partner
        )
    except GuideParseError as exc:
        print(f"mapcheck: {exc}", file=sys.stderr)
        return EXIT_USAGE

    registered = sorted(d.set_code for d in default_registry.all())
    if profile.transaction not in registered:
        print(
            f"mapcheck: note: transaction set {profile.transaction} has no "
            f"registered definition (registered: {', '.join(registered)}) — the "
            "profile will still write, but validate and draft-spec need a "
            "registered set",
            file=sys.stderr,
        )

    profile.save(profile_path)
    element_count = sum(len(seg.elements) for seg in profile.segments)
    print(f"Guide profile written to {profile_path}")
    if profile.family:
        from mapcheck.guides.parser import FAMILY_NAMES

        print(f"Guide family: {FAMILY_NAMES.get(profile.family, profile.family)}")
    print(
        f"Parsed: {len(profile.segments)} segment(s), {element_count} element(s) — "
        f"parse coverage {profile.parse_coverage:.2f} "
        f"({profile.facts_confident}/{profile.facts_detected} facts)"
    )
    if profile.review:
        print(
            f"\n{len(profile.review)} item(s) need review "
            "(kept in the profile's review list):"
        )
        for note in profile.review:
            print(f"  - {note}")

    if overlay_path is not None:
        rules = emit_partner_rules(profile)
        rules.save(overlay_path)
        print(f"\nPartner rules overlay written to {overlay_path}")
        print(
            f"Rules: {len(rules.required_segments)} required segment(s), "
            f"{len(rules.required_elements)} required element(s), "
            f"{len(rules.required_pairs)} qualifier pair(s)"
        )
        for note in rules.review:
            print(f"  - review (not enforced): {note}")
        print(f"Enforce with: mapcheck validate ... --partner-rules {overlay_path}")
    return 0


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


def _cmd_bless(args: argparse.Namespace) -> int:
    from mapcheck.report.regression import baseline_key

    if not Path(args.db).exists():
        print(f"mapcheck: no history database at {args.db}", file=sys.stderr)
        return EXIT_USAGE
    with RunHistory(args.db) as history:
        run = history.run(args.run_id)
        if run is None:
            print(f"mapcheck: no run #{args.run_id} in {args.db}", file=sys.stderr)
            return EXIT_USAGE
        key = args.label or baseline_key(
            run["spec_file"],
            run["source_file"],
            run["output_file"],
            run["partner_file"],
        )
        history.bless(args.run_id, key, label=args.label)
    print(f"Run #{args.run_id} blessed as the baseline for '{key}'.")
    return 0


def _cmd_regress(args: argparse.Namespace) -> int:
    from mapcheck.report.regression import baseline_key, format_delta, regress

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
        interchange = _is_interchange(spec, args.source, args.output)
        if interchange:
            result = validate_interchange_files(
                args.spec, args.source, args.output,
                transaction=args.transaction, output_format=output_format, spec=merged_spec,
            )
        else:
            result = validate_files(
                args.spec, args.source, args.output,
                transaction=args.transaction, output_format=output_format, spec=merged_spec,
            )
    except (SpecLoadError, X12ParseError, OutputLoadError, DefinitionError) as exc:
        print(f"mapcheck: {exc}", file=sys.stderr)
        return EXIT_USAGE

    key = args.label or baseline_key(args.spec, args.source, args.output, args.partner)
    with RunHistory(args.db) as history:
        current_id = (
            history.record_interchange(result, partner_file=args.partner)
            if interchange
            else history.record(result, partner_file=args.partner)
        )
        baseline = history.baseline_for(key)
        if baseline is None:
            label_arg = f" --label {args.label!r}" if args.label else ""
            print(f"No baseline yet for '{key}'.")
            print(f"Recorded run #{current_id}. Bless it to establish the baseline:")
            print(f"    mapcheck bless {current_id}{label_arg}")
            return 0
        delta = regress(history, baseline["run_id"], current_id)
    print(format_delta(delta, color=color))
    return delta.exit_code


def _cmd_batch(args: argparse.Namespace) -> int:
    from mapcheck.batch import ManifestError, format_report, load_manifest, run_batch, to_junit

    color = False if args.no_color else None
    try:
        manifest = load_manifest(args.manifest)
    except ManifestError as exc:
        print(f"mapcheck: {exc}", file=sys.stderr)
        return EXIT_USAGE
    db = manifest.db or args.db
    result = run_batch(manifest, db, strict=args.strict, record=not args.no_history)
    print(format_report(result, color=color))
    if args.junit:
        Path(args.junit).write_text(to_junit(result), encoding="utf-8")
        print(f"\nJUnit report written to {args.junit}")
    return result.exit_code


def _cmd_report(args: argparse.Namespace) -> int:
    from mapcheck.report.trends import compute_trends

    if not Path(args.db).exists():
        print(f"mapcheck: no history database at {args.db}", file=sys.stderr)
        return EXIT_USAGE
    with RunHistory(args.db) as history:
        trends = compute_trends(history, limit=args.limit)
    if trends.is_empty:
        print("No runs recorded yet.")
        return 0

    if args.html:
        from mapcheck.report.html import export_trends_html

        path = export_trends_html(trends, args.html)
        print(f"Trends report written to {path}")
        return 0

    print(
        f"{trends.total_runs} runs across {trends.distinct_specs} spec(s) — "
        f"overall pass rate {trends.overall_pass_rate:.0%}"
    )
    print(f"\n{'SPEC':<40} {'PASS%':>6} {'RUNS':>5}  LATEST")
    for s in trends.specs:
        print(f"{s.spec[:40]:<40} {s.pass_rate:>6.0%} {s.total:>5}  {s.latest}")
    if trends.top_categories:
        print("\nTop root causes:")
        for cat, n in trends.top_categories[:8]:
            print(f"  {cat}: {n}")
    return 0


def _cmd_scrub(args: argparse.Namespace) -> int:
    from mapcheck.scrub import ProfileError, load_profile
    from mapcheck.scrub.scrubber import scrub_file, scrubbed_path

    if not Path(args.input).exists():
        print(f"mapcheck: input file not found: {args.input}", file=sys.stderr)
        return EXIT_USAGE
    # Guard the derived default too — a scrubbed file is the copy that gets
    # shared, so silently replacing one is how the unmasked original travels.
    out_target = scrubbed_path(args.input, args.output)
    if out_target.exists():
        print(f"mapcheck: {out_target} already exists, not overwriting", file=sys.stderr)
        return EXIT_USAGE
    try:
        profile = load_profile(args.profile)
    except ProfileError as exc:
        print(f"mapcheck: {exc}", file=sys.stderr)
        return EXIT_USAGE
    try:
        out_path, report = scrub_file(args.input, args.output, profile, seed=args.seed)
    except (OSError, ValueError) as exc:
        print(f"mapcheck: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"Scrubbed file written to {out_path} (profile: {profile.name})")
    if args.report:
        print()
        print(report.render())
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
        "draft-spec": _cmd_draft_spec,
        "import-guide": _cmd_import_guide,
        "init-spec": _cmd_init_spec,
        "import-spec": _cmd_import_spec,
        "merge-spec": _cmd_merge_spec,
        "history": _cmd_history,
        "report": _cmd_report,
        "bless": _cmd_bless,
        "regress": _cmd_regress,
        "batch": _cmd_batch,
        "scrub": _cmd_scrub,
        "transactions": _cmd_transactions,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
