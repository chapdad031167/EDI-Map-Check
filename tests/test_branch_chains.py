"""Design 022: if / else-if chains.

An Else of ``NEXT`` passes the decision to the next Mapping row. Rows
linked that way form a chain, read top to bottom, and the first true
condition decides. Covers the loader's refusals, the engine's choice of
deciding row in both directions and at both scopes, the false FAIL two
plain CONDITIONAL rows give on one target, and the regression identity
that is the reason a chain's finding is filed under its first row.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mapcheck.engine.results import Status
from mapcheck.engine.validator import validate_files
from mapcheck.report.history import RunHistory
from mapcheck.report.regression import CHANGED, regress
from mapcheck.spec.importer import import_mapping, write_workbook
from mapcheck.spec.model import OutcomeKind
from mapcheck.spec.overrides import resolve_spec
from mapcheck.spec.parser import SpecLoadError, load_spec
from mapcheck.spec.template import MAPPING_COLUMNS, build_template

ISA = (
    "ISA*00*          *00*          *ZZ*MAPCHECKSND    *ZZ*MAPCHECKRCV    "
    "*260615*1200*U*00401*000000001*0*T*>"
)

_COLUMN_KEYS = (
    "row_id", "source", "context", "target", "rule_type", "cond_text", "cond",
    "then", "else_", "default", "code_list", "data_type", "fmt", "notes",
)
assert len(_COLUMN_KEYS) == len(MAPPING_COLUMNS)


def row(row_id: str, target: str, rule_type: str, **cells: str) -> tuple:
    """One Mapping-sheet row; unnamed cells stay blank."""
    values = dict.fromkeys(_COLUMN_KEYS, "")
    values.update(row_id=row_id, target=target, rule_type=rule_type, data_type="string")
    values.update(cells)
    return tuple(values[k] for k in _COLUMN_KEYS)


def write_spec(
    path: Path,
    rows: list[tuple],
    code_rows: list[tuple] = (),
    meta: dict[str, str] | None = None,
) -> Path:
    wb = build_template()
    for sheet, data in (("Mapping", rows), ("CodeLists", code_rows)):
        ws = wb[sheet]
        for r, cells in enumerate(data, start=2):
            for c, value in enumerate(cells, start=1):
                if value not in ("", None):
                    ws.cell(row=r, column=c, value=value)
    ws_meta = wb["Meta"]
    for r in range(2, ws_meta.max_row + 1):
        key = ws_meta.cell(row=r, column=1).value
        if meta and key in meta:
            ws_meta.cell(row=r, column=2, value=meta[key])
    wb.save(path)
    return path


def x12_850(tmp_path: Path, *body: str, name: str = "source.edi") -> Path:
    transaction = ["ST*850*0001", *body]
    transaction.append(f"SE*{len(transaction) + 1}*0001")
    segments = [
        ISA, "GS*PO*MAPCHECKSND*MAPCHECKRCV*20260615*1200*1*X*004010",
        *transaction, "GE*1*1", "IEA*1*000000001",
    ]
    path = tmp_path / name
    path.write_text("~\n".join(segments) + "~\n")
    return path


def output_json(tmp_path: Path, data: dict, name: str = "output.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


def findings_for(result, target: str) -> list:
    return [f for f in result.findings if f.target == target and f.row_id]


def load_errors(path: Path) -> str:
    with pytest.raises(SpecLoadError) as excinfo:
        load_spec(path)
    return str(excinfo.value)


#: A ship-to id from the store number, else from a vendor reference, else
#: a hardcoded default. Three rows, three sources, one target.
SHIP_ID_CHAIN = [
    row("R-10", "order.ship_id", "CONDITIONAL", source="N104", context="N1[ST]",
        cond="N103 = '92'", then="SOURCE", else_="NEXT"),
    row("R-11", "order.ship_id", "CONDITIONAL", source="REF02", context="REF[IA]",
        cond="EXISTS(REF02)", then="SOURCE", else_="NEXT"),
    row("R-12", "order.ship_id", "CONSTANT", default="UNKNOWN"),
]

HEADER = ["BEG*00*SA*PO1**20260615"]


def run_ship_id(tmp_path: Path, body: list[str], ship_id: str | None, rows=SHIP_ID_CHAIN):
    spec = write_spec(tmp_path / "spec.xlsx", rows)
    source = x12_850(tmp_path, *HEADER, *body)
    order = {} if ship_id is None else {"ship_id": ship_id}
    output = output_json(tmp_path, {"order": order})
    result = validate_files(str(spec), str(source), str(output))
    return findings_for(result, "order.ship_id")


# ---------------------------------------------------------------------------
# the spec model and the loader
# ---------------------------------------------------------------------------


class TestGrammar:
    def test_next_loads_and_groups_into_a_chain(self, tmp_path):
        spec = load_spec(write_spec(tmp_path / "s.xlsx", [
            row("R-01", "order.po", "DIRECT", source="BEG03"),
            *SHIP_ID_CHAIN,
        ]))
        assert spec.rules[1].else_outcome.kind is OutcomeKind.NEXT
        assert spec.rules[1].passes_on and not spec.rules[3].passes_on
        assert [[r.row_id for r in unit] for unit in spec.units()] == [
            ["R-01"], ["R-10", "R-11", "R-12"],
        ]

    def test_a_spec_without_next_is_all_single_units(self, reference_spec_path):
        spec = load_spec(reference_spec_path)
        assert all(len(unit) == 1 for unit in spec.units())
        assert [u[0] for u in spec.units()] == list(spec.rules)

    def test_next_is_refused_as_a_then(self, tmp_path):
        errors = load_errors(write_spec(tmp_path / "s.xlsx", [
            row("R-10", "order.ship_id", "CONDITIONAL", source="N104", context="N1[ST]",
                cond="N103 = '92'", then="NEXT"),
        ]))
        assert "Then: NEXT is only allowed as an Else" in errors

    def test_next_is_refused_on_a_row_that_is_not_conditional(self, tmp_path):
        errors = load_errors(write_spec(tmp_path / "s.xlsx", [
            row("R-10", "order.ship_id", "DIRECT", source="N104", context="N1[ST]",
                else_="NEXT"),
            row("R-11", "order.ship_id", "CONSTANT", default="UNKNOWN"),
        ]))
        assert "Else: NEXT is only allowed on CONDITIONAL rules, not DIRECT" in errors

    def test_a_todo_cannot_pass_the_decision_on(self, tmp_path):
        errors = load_errors(write_spec(tmp_path / "s.xlsx", [
            row("R-10", "order.ship_id", "TODO", else_="NEXT"),
            row("R-11", "order.ship_id", "CONSTANT", default="UNKNOWN"),
        ]))
        assert "Else: NEXT is only allowed on CONDITIONAL rules, not TODO" in errors

    def test_next_must_be_followed_by_the_same_target(self, tmp_path):
        errors = load_errors(write_spec(tmp_path / "s.xlsx", [
            SHIP_ID_CHAIN[0],
            row("R-11", "order.other", "CONSTANT", default="UNKNOWN"),
        ]))
        assert "Mapping row 2 (R-10): Else is NEXT" in errors
        assert "order.ship_id" in errors and "Mapping row 3 (R-11) targets order.other" in errors

    def test_next_on_the_last_row_has_nothing_to_pass_to(self, tmp_path):
        errors = load_errors(write_spec(tmp_path / "s.xlsx", [
            row("R-01", "order.po", "DIRECT", source="BEG03"),
            SHIP_ID_CHAIN[0],
        ]))
        assert "Mapping row 3 (R-10): Else is NEXT but there is no next row" in errors

    def test_a_chain_may_not_mix_line_loops(self, tmp_path):
        errors = load_errors(write_spec(tmp_path / "s.xlsx", [
            row("L-1", "lines[].item", "CONDITIONAL", source="PO107", context="PO1",
                cond="PO106 = 'UP'", then="SOURCE", else_="NEXT"),
            row("L-2", "lines[].item", "DIRECT", source="N104", context="N1"),
        ]))
        assert "Mapping row 2 (L-1): the rows of a chain must all be per-line" in errors

    def test_an_outbound_chain_must_stay_on_one_x12_occurrence(self, tmp_path):
        errors = load_errors(write_spec(tmp_path / "s.xlsx", [
            row("X-1", "N102", "CONDITIONAL", source="vendor.dba", context="N1[SE]",
                cond="EXISTS(vendor.dba)", then="SOURCE", else_="NEXT"),
            row("X-2", "N102", "DIRECT", source="vendor.name", context="N1[ST]"),
        ], meta={"Transaction Set": "855", "Direction": "outbound"}))
        assert "N1[SE] N102" in errors and "targets N1[ST] N102" in errors

    def test_a_row_with_its_own_error_is_not_reported_twice_as_a_broken_link(self, tmp_path):
        errors = load_errors(write_spec(tmp_path / "s.xlsx", [
            SHIP_ID_CHAIN[0],
            row("R-11", "order.ship_id", "CONDITIONAL", source="REF02", context="REF[IA]",
                cond="REF02 is sort of there", then="SOURCE", else_="NEXT"),
            SHIP_ID_CHAIN[2],
        ]))
        assert "Condition (Coded)" in errors and "Else is NEXT" not in errors

    def test_a_partner_delta_that_breaks_a_chain_is_refused(self, tmp_path):
        base = write_spec(tmp_path / "base.xlsx", SHIP_ID_CHAIN)
        delta = write_spec(tmp_path / "delta.xlsx", [
            row("R-12", "order.other", "CONSTANT", default="UNKNOWN"),
        ])
        with pytest.raises(SpecLoadError) as excinfo:
            resolve_spec(base, delta)
        message = str(excinfo.value)
        assert "after merging the partner delta" in message and "R-11" in message


# ---------------------------------------------------------------------------
# the engine: which row decides
# ---------------------------------------------------------------------------


class TestHeaderChain:
    STORE = "N1*ST*STORE 118*92*0118"
    STORE_OTHER_QUALIFIER = "N1*ST*STORE 118*91*0118"
    VENDOR_REF = "REF*IA*VEND8821"

    def test_first_row_decides(self, tmp_path):
        (finding,) = run_ship_id(tmp_path, [self.VENDOR_REF, self.STORE], "0118")
        assert finding.status is Status.PASS
        assert finding.row_id == "R-10"
        assert finding.message.startswith("decided by R-10: R-10 N103 = '92' is true")

    def test_first_true_condition_wins_when_two_are_true(self, tmp_path):
        # both the store number and the vendor reference are present
        (finding,) = run_ship_id(tmp_path, [self.VENDOR_REF, self.STORE], "VEND8821")
        assert finding.status is Status.FAIL
        assert finding.expected == "0118" and finding.actual == "VEND8821"

    def test_second_row_decides_and_reads_its_own_segment(self, tmp_path):
        (finding,) = run_ship_id(
            tmp_path, [self.VENDOR_REF, self.STORE_OTHER_QUALIFIER], "VEND8821"
        )
        assert finding.status is Status.PASS
        assert finding.row_id == "R-10"  # filed under the head, not the decider
        assert finding.source_ref == "REF[IA] REF02"
        assert finding.message.startswith(
            "decided by R-11: R-10 N103 = '92' is false; R-11 EXISTS(REF02) is true"
        )

    def test_the_tail_decides_when_no_condition_is_true(self, tmp_path):
        (finding,) = run_ship_id(tmp_path, [self.STORE_OTHER_QUALIFIER], "UNKNOWN")
        assert finding.status is Status.PASS and finding.row_id == "R-10"
        assert finding.message.startswith("decided by R-12 (no condition was true): ")

    def test_a_wrong_default_is_caught(self, tmp_path):
        (finding,) = run_ship_id(tmp_path, [self.STORE_OTHER_QUALIFIER], "0118")
        assert finding.status is Status.FAIL
        assert finding.expected == "UNKNOWN" and finding.actual == "0118"

    def test_one_finding_for_the_chain_not_one_per_row(self, tmp_path):
        assert len(run_ship_id(tmp_path, [self.VENDOR_REF, self.STORE], "0118")) == 1

    def test_no_element_the_chain_reads_is_reported_unmapped(self, tmp_path):
        spec = write_spec(tmp_path / "spec.xlsx", SHIP_ID_CHAIN)
        source = x12_850(tmp_path, *HEADER, self.VENDOR_REF, self.STORE)
        output = output_json(tmp_path, {"order": {"ship_id": "0118"}})
        result = validate_files(str(spec), str(source), str(output))
        unmapped = " ".join(f.message for f in result.findings if "not referenced" in f.message)
        for element in ("N103", "N104", "REF02"):
            assert f"{element}=" not in unmapped


class TestTails:
    STORE_OTHER_QUALIFIER = "N1*ST*STORE 118*91*0118"

    def _rows(self, tail: tuple) -> list[tuple]:
        return [SHIP_ID_CHAIN[0], tail]

    def test_conditional_tail_takes_its_then(self, tmp_path):
        tail = row("R-11", "order.ship_id", "CONDITIONAL", source="N104", context="N1[ST]",
                   cond="N103 = '91'", then="SOURCE", else_="'NONE'")
        (finding,) = run_ship_id(
            tmp_path, [self.STORE_OTHER_QUALIFIER], "0118", rows=self._rows(tail)
        )
        assert finding.status is Status.PASS
        assert "decided by R-11: R-10 N103 = '92' is false" in finding.message
        assert "N103 = '91'" in finding.message  # the tail's own condition is reported

    def test_conditional_tail_takes_its_else(self, tmp_path):
        tail = row("R-11", "order.ship_id", "CONDITIONAL", source="N104", context="N1[ST]",
                   cond="N103 = 'ZZ'", then="SOURCE", else_="'NONE'")
        (finding,) = run_ship_id(
            tmp_path, [self.STORE_OTHER_QUALIFIER], "NONE", rows=self._rows(tail)
        )
        assert finding.status is Status.PASS

    def test_skip_tail_expects_the_target_absent(self, tmp_path):
        tail = row("R-11", "order.ship_id", "CONDITIONAL", source="N104", context="N1[ST]",
                   cond="N103 = 'ZZ'", then="SOURCE", else_="SKIP")
        rows = self._rows(tail)
        (absent,) = run_ship_id(tmp_path, [self.STORE_OTHER_QUALIFIER], None, rows=rows)
        assert absent.status is Status.PASS
        (present,) = run_ship_id(tmp_path, [self.STORE_OTHER_QUALIFIER], "0118", rows=rows)
        assert present.status is Status.FAIL

    def test_direct_tail(self, tmp_path):
        tail = row("R-11", "order.ship_id", "DIRECT", source="BEG03")
        (finding,) = run_ship_id(
            tmp_path, [self.STORE_OTHER_QUALIFIER], "PO1", rows=self._rows(tail)
        )
        assert finding.status is Status.PASS and finding.source_ref == "BEG03"

    def test_code_list_tail(self, tmp_path):
        tail = row("R-11", "order.ship_id", "CODE_LIST", source="BEG02", code_list="TYPES")
        spec = write_spec(tmp_path / "spec.xlsx", self._rows(tail),
                          code_rows=[("TYPES", "SA", "STANDALONE", "")])
        source = x12_850(tmp_path, *HEADER, self.STORE_OTHER_QUALIFIER)
        output = output_json(tmp_path, {"order": {"ship_id": "STANDALONE"}})
        result = validate_files(str(spec), str(source), str(output))
        (finding,) = findings_for(result, "order.ship_id")
        assert finding.status is Status.PASS

    def test_todo_tail_is_not_tested_only_when_it_is_reached(self, tmp_path):
        tail = row("R-11", "order.ship_id", "TODO", notes="final else not decided")
        rows = self._rows(tail)
        (reached,) = run_ship_id(tmp_path, [self.STORE_OTHER_QUALIFIER], "0118", rows=rows)
        assert reached.status is Status.NOT_TESTED and reached.row_id == "R-10"
        assert "final else (R-11) is TODO" in reached.message
        (decided,) = run_ship_id(tmp_path, ["N1*ST*STORE 118*92*0118"], "0118", rows=rows)
        assert decided.status is Status.PASS


class TestPerLineChain:
    ROWS = [
        row("L-1", "lines[].item", "CONDITIONAL", source="PO107", context="PO1",
            cond="PO106 = 'UP'", then="SOURCE", else_="NEXT"),
        row("L-2", "lines[].item", "CONDITIONAL", source="PO107", context="PO1",
            cond="PO106 = 'VN'", then="SOURCE", else_="NEXT"),
        row("L-3", "lines[].item", "CONSTANT", context="PO1", default="NONE"),
    ]
    LINES = [
        "PO1*1*12*EA*8.5**UP*614141007349",
        "PO1*2*6*CA*24**VN*PART77",
        "PO1*3*5*DZ*12",
        "CTT*3",
    ]

    def _run(self, tmp_path: Path, items: list[str]):
        spec = write_spec(tmp_path / "spec.xlsx", self.ROWS)
        source = x12_850(tmp_path, *HEADER, *self.LINES)
        output = output_json(tmp_path, {"lines": [{"item": item} for item in items]})
        result = validate_files(str(spec), str(source), str(output))
        return [f for f in result.findings if f.row_id == "L-1"]

    def test_each_line_decides_for_itself(self, tmp_path):
        findings = self._run(tmp_path, ["614141007349", "PART77", "NONE"])
        assert [f.status for f in findings] == [Status.PASS] * 3
        assert [f.target for f in findings] == [f"lines[{n}].item" for n in range(3)]
        deciders = [f.message.split(":")[0] for f in findings]
        assert deciders == [
            "decided by L-1", "decided by L-2", "decided by L-3 (no condition was true)",
        ]

    def test_a_defect_on_one_line_is_one_finding(self, tmp_path):
        findings = self._run(tmp_path, ["614141007349", "WRONG", "NONE"])
        assert [f.status for f in findings] == [Status.PASS, Status.FAIL, Status.PASS]
        assert findings[1].expected == "PART77"

    def test_an_extra_output_line_is_still_a_count_mismatch(self, tmp_path):
        findings = self._run(tmp_path, ["614141007349", "PART77", "NONE", "GHOST"])
        assert len(findings) == 4
        assert findings[3].status is Status.FAIL
        assert "no matching PO1 loop" in findings[3].message


class TestWhatThisReplaces:
    """Two plain CONDITIONAL rows on one target are each judged alone. The
    first row's default Else expects the target absent at exactly the
    moment the second expects a value."""

    BODY = ["REF*IA*VEND8821", "N1*ST*STORE 118*91*0118"]

    def test_two_plain_rows_report_a_defect_the_map_does_not_have(self, tmp_path):
        plain = [
            row("R-10", "order.ship_id", "CONDITIONAL", source="N104", context="N1[ST]",
                cond="N103 = '92'", then="SOURCE"),
            row("R-11", "order.ship_id", "CONDITIONAL", source="REF02", context="REF[IA]",
                cond="EXISTS(REF02)", then="SOURCE"),
        ]
        findings = run_ship_id(tmp_path, self.BODY, "VEND8821", rows=plain)
        assert sorted(f.status.value for f in findings) == ["FAIL", "PASS"]

    def test_the_same_logic_as_a_chain_passes(self, tmp_path):
        (finding,) = run_ship_id(tmp_path, self.BODY, "VEND8821")
        assert finding.status is Status.PASS


class TestOrAsTwoRows:
    ROWS = [
        row("O-1", "order.ship_id", "CONDITIONAL", source="N104", context="N1[ST]",
            cond="N103 = '92'", then="SOURCE", else_="NEXT"),
        row("O-2", "order.ship_id", "CONDITIONAL", source="N104", context="N1[ST]",
            cond="N103 = 'ZZ'", then="SOURCE", else_="SKIP"),
    ]

    @pytest.mark.parametrize("qualifier", ["92", "ZZ"])
    def test_either_qualifier_maps_the_source(self, tmp_path, qualifier):
        (finding,) = run_ship_id(
            tmp_path, [f"N1*ST*STORE 118*{qualifier}*0118"], "0118", rows=self.ROWS
        )
        assert finding.status is Status.PASS

    def test_neither_expects_the_target_absent(self, tmp_path):
        (finding,) = run_ship_id(tmp_path, ["N1*ST*STORE 118*91*0118"], None, rows=self.ROWS)
        assert finding.status is Status.PASS


# ---------------------------------------------------------------------------
# outbound
# ---------------------------------------------------------------------------


class TestOutboundChain:
    META = {"Transaction Set": "855", "Direction": "outbound"}

    def _run(self, examples_dir: Path, tmp_path: Path, rows: list[tuple]):
        spec = write_spec(tmp_path / "spec.xlsx", rows, meta=self.META)
        return validate_files(
            str(spec),
            str(examples_dir / "source" / "poa_response.json"),
            str(examples_dir / "output" / "855_ack_baseline.edi"),
        )

    def test_header_chain_falls_to_its_tail(self, examples_dir, tmp_path):
        result = self._run(examples_dir, tmp_path, [
            row("X-1", "N102", "CONDITIONAL", source="vendor.dba", context="N1[SE]",
                cond="EXISTS(vendor.dba)", then="SOURCE", else_="NEXT"),
            row("X-2", "N102", "DIRECT", source="vendor.name", context="N1[SE]"),
        ])
        (finding,) = [f for f in result.findings if f.row_id == "X-1"]
        assert finding.status is Status.PASS
        assert finding.target == "N1[SE] N102" and finding.source_ref == "vendor.name"
        assert finding.message.startswith("decided by X-2 (no condition was true)")
        assert not [f for f in result.findings if f.row_id == "X-2"]

    def test_per_line_chain_decides_each_line(self, examples_dir, tmp_path):
        result = self._run(examples_dir, tmp_path, [
            row("X-1", "ACK01", "CONDITIONAL", context="PO1",
                cond="lines[].line_status = 'ACCEPTED'", then="'IA'", else_="NEXT"),
            row("X-2", "ACK01", "CONSTANT", context="PO1", default="IR"),
        ])
        findings = [f for f in result.findings if f.row_id == "X-1"]
        assert len(findings) == 3
        assert all(f.status is Status.PASS for f in findings)
        assert all(f.message.startswith("decided by X-1") for f in findings)


# ---------------------------------------------------------------------------
# why the finding is filed under the first row
# ---------------------------------------------------------------------------


class TestRegressionIdentity:
    def test_a_different_branch_deciding_is_one_changed_finding(self, tmp_path):
        """Both runs fail, on different branches. Filed under the deciding
        row that would read as one finding resolved and another appearing;
        filed under the chain's head it is the same target, changed."""
        spec = write_spec(tmp_path / "spec.xlsx", SHIP_ID_CHAIN)
        output = output_json(tmp_path, {"order": {"ship_id": "WRONG"}})
        first = x12_850(tmp_path, *HEADER, "N1*ST*STORE 118*92*0118", name="a.edi")
        second = x12_850(
            tmp_path, *HEADER, "REF*IA*VEND8821", "N1*ST*STORE 118*91*0118", name="b.edi"
        )
        with RunHistory(tmp_path / "h.db", values="full") as history:
            runs = [
                history.record(validate_files(str(spec), str(source), str(output)))
                for source in (first, second)
            ]
            delta = regress(history, *runs)
        on_target = [c for c in delta.changes if "order.ship_id" in str(c.identity)]
        assert [c.kind for c in on_target] == [CHANGED]
        assert on_target[0].identity[1] == "R-10"


# ---------------------------------------------------------------------------
# import-spec
# ---------------------------------------------------------------------------


class TestImport:
    def test_next_survives_an_import(self, tmp_path):
        doc = tmp_path / "rows.csv"
        doc.write_text(
            "Row ID,Source Field,Loop Context,Target Field,Rule Type,Condition (Coded),"
            "Then,Else,Default Value\n"
            "R-10,N104,N1[ST],order.ship_id,CONDITIONAL,N103 = '92',SOURCE,NEXT,\n"
            "R-11,,,order.ship_id,CONSTANT,,,,UNKNOWN\n",
            encoding="utf-8",
        )
        result = import_mapping(doc, meta={"Transaction Set": "850"})
        assert result.review_rows == []
        spec = load_spec(write_workbook(result, tmp_path / "spec.xlsx"))
        assert [[r.row_id for r in u] for u in spec.units()] == [["R-10", "R-11"]]


# ---------------------------------------------------------------------------
# the bundled scenario
# ---------------------------------------------------------------------------


class TestBundledScenario:
    def _run(self, examples_dir: Path, output: str):
        return validate_files(
            str(examples_dir / "specs" / "850_chains_spec.xlsx"),
            str(examples_dir / "source" / "850_chains.edi"),
            str(examples_dir / "output" / output),
        )

    def test_spec_holds_three_chains(self, examples_dir):
        spec = load_spec(examples_dir / "specs" / "850_chains_spec.xlsx")
        chains = [[r.row_id for r in u] for u in spec.units() if len(u) > 1]
        assert chains == [
            ["C-010", "C-011", "C-012"], ["C-030", "C-031", "C-032"], ["C-040", "C-041"],
        ]

    def test_baseline_is_clean(self, examples_dir):
        result = self._run(examples_dir, "chains_baseline.json")
        assert result.overall is Status.PASS
        assert {f.status for f in result.findings} == {Status.PASS}

    def test_defect_variant_trips_exactly_one_finding(self, examples_dir):
        result = self._run(examples_dir, "chains_defects.json")
        (bad,) = [f for f in result.findings if f.status is not Status.PASS]
        assert bad.status is Status.FAIL and bad.row_id == "C-010"
        assert bad.target == "ship_to.id"
        assert bad.expected == "VEND8821" and bad.actual == "0118"
        assert bad.message.startswith("decided by C-011: ")
