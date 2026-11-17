"""Spec import (design 004): partner Excel/CSV → native MapCheck workbook.

Covers the reader (header auto-location, xlsx + csv), the column mapper
(synonym auto-detect, overrides, exclusivity, silent-loss reporting), the
evidence-based classifier and condition translation, the three reference
partner fixtures (≥80% auto-classified DoD), and the round-trip guarantee.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from mapcheck.spec.importer import (
    CONDITION_TEXT,
    DATA_TYPE,
    RULE_TYPE,
    SOURCE_FIELD,
    TARGET_FIELD,
    ImportError_,
    classify_row,
    derive_condition,
    import_mapping,
    read_table,
    resolve_columns,
    write_workbook,
    write_worklist,
)
from mapcheck.spec.model import RuleType
from mapcheck.spec.parser import load_spec

PARTNERS = "partner_specs"


def _partner(examples_dir: Path, name: str) -> Path:
    return examples_dir / PARTNERS / name


# ---------------------------------------------------------------------------
# reader
# ---------------------------------------------------------------------------


class TestReader:
    def test_csv_and_header_location(self, tmp_path):
        p = tmp_path / "m.csv"
        p.write_text("Some Banner Row,,\nX12 Element,Target,Type\nBEG03,order.po,string\n")
        table = read_table(p)
        assert table.headers == ["X12 Element", "Target", "Type"]
        assert table.rows[0]["X12 Element"] == "BEG03"

    def test_xlsx_skips_blank_and_banner(self, tmp_path):
        wb = Workbook()
        ws = wb.active
        ws.append(["CONFIDENTIAL — partner map"])
        ws.append([])
        ws.append(["Element", "Target Field", "Default"])
        ws.append(["BEG03", "order.po", ""])
        p = tmp_path / "m.xlsx"
        wb.save(p)
        table = read_table(p)
        assert table.headers[0] == "Element"
        assert len(table.rows) == 1

    def test_unknown_extension_rejected(self, tmp_path):
        p = tmp_path / "m.pdf"
        p.write_text("x")
        with pytest.raises(ImportError_, match="unsupported document type"):
            read_table(p)


# ---------------------------------------------------------------------------
# column mapping
# ---------------------------------------------------------------------------


class TestColumnMapping:
    def test_synonyms(self):
        m = resolve_columns(["X12 Element", "ERP Field", "Logic", "Default", "Lookup"])
        assert m[SOURCE_FIELD] == "X12 Element"
        assert m[TARGET_FIELD] == "ERP Field"
        assert m[CONDITION_TEXT] == "Logic"

    def test_exact_beats_word_match(self):
        # "Business Rule" (exact -> Condition) must win over "rule" -> Rule Type
        m = resolve_columns(["Element", "Destination Field", "Business Rule"])
        assert m[CONDITION_TEXT] == "Business Rule"
        assert RULE_TYPE not in m

    def test_rule_and_type_disambiguate(self):
        m = resolve_columns(["Element", "Target", "Rule", "Type"])
        assert m[RULE_TYPE] == "Rule"
        assert m[DATA_TYPE] == "Type"

    def test_one_header_one_column(self):
        m = resolve_columns(["Field", "Data Type"])
        assert len({v for v in m.values()}) == len(m.values())

    def test_override_by_letter_and_name(self):
        headers = ["A col", "B col", "C col"]
        m = resolve_columns(headers, overrides={TARGET_FIELD: "B", SOURCE_FIELD: "A col"})
        assert m[TARGET_FIELD] == "B col"
        assert m[SOURCE_FIELD] == "A col"

    def test_missing_target_is_error(self):
        with pytest.raises(ImportError_, match="Target Field"):
            resolve_columns(["foo", "bar"])

    def test_bad_override_is_error(self):
        with pytest.raises(ImportError_, match="not a header or column letter"):
            resolve_columns(["Target"], overrides={TARGET_FIELD: "ZZ"})


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------


def _classify(**cells):
    mapping = {c: c for c in cells}
    return classify_row(mapping, cells, "R-1")


class TestClassifier:
    def test_direct(self):
        r = _classify(**{SOURCE_FIELD: "BEG03", TARGET_FIELD: "order.po"})
        assert r.rule_type is RuleType.DIRECT and not r.needs_review

    def test_code_list(self):
        r = _classify(**{SOURCE_FIELD: "BEG01", "Code List Ref": "TX", TARGET_FIELD: "order.p"})
        assert r.rule_type is RuleType.CODE_LIST and not r.needs_review

    def test_constant(self):
        r = _classify(**{"Default Value": "PO_IN", TARGET_FIELD: "order.rt"})
        assert r.rule_type is RuleType.CONSTANT and not r.needs_review
        assert SOURCE_FIELD not in r.values

    def test_conditional_translatable(self):
        r = _classify(**{SOURCE_FIELD: "N104", CONDITION_TEXT: "when N103 = 92",
                         TARGET_FIELD: "st.id"})
        assert r.rule_type is RuleType.CONDITIONAL and not r.needs_review
        assert r.values["Condition (Coded)"] == "N103 = '92'"

    def test_conditional_prose_flagged(self):
        r = _classify(**{SOURCE_FIELD: "REF02", CONDITION_TEXT: "for special deals",
                         TARGET_FIELD: "order.x"})
        assert r.rule_type is RuleType.CONDITIONAL and r.needs_review

    def test_no_evidence_flagged(self):
        r = _classify(**{TARGET_FIELD: "order.mystery"})
        assert r.rule_type is None and r.needs_review

    def test_explicit_type_wins(self):
        r = _classify(**{RULE_TYPE: "xref", SOURCE_FIELD: "X", "Code List Ref": "L",
                         TARGET_FIELD: "t"})
        assert r.rule_type is RuleType.CODE_LIST


class TestConditionDerivation:
    @pytest.mark.parametrize("prose,coded", [
        ("N101 = 'ST'", "N101 = 'ST'"),
        ("when N103 = 92", "N103 = '92'"),
        ("only when N101 is ST", "N101 = 'ST'"),
        ("BEG02 != DS", "BEG02 != 'DS'"),
        ("when REF02 is present", "EXISTS(REF02)"),
    ])
    def test_translatable(self, prose, coded):
        assert derive_condition(prose) == coded

    @pytest.mark.parametrize("prose", [
        "map for promotional deals only", "see appendix B", "business decision", ""
    ])
    def test_not_translatable(self, prose):
        assert derive_condition(prose) is None


# ---------------------------------------------------------------------------
# reference fixtures + DoD
# ---------------------------------------------------------------------------


class TestPartnerFixtures:
    def test_aggregate_auto_classified_ratio(self, examples_dir):
        total = review = 0
        for name in ["acme_renamed.xlsx", "globex_mixed.csv", "initech_prose.xlsx"]:
            res = import_mapping(_partner(examples_dir, name))
            total += len(res.rows)
            review += len(res.review_rows)
        assert (total - review) / total >= 0.80

    def test_acme_all_classified_no_loss(self, examples_dir):
        res = import_mapping(_partner(examples_dir, "acme_renamed.xlsx"))
        assert res.review_rows == []
        assert res.unmapped_columns == []
        assert res.column_mapping[RULE_TYPE] == "Rule"

    def test_globex_flags_evidence_free_row(self, examples_dir):
        res = import_mapping(_partner(examples_dir, "globex_mixed.csv"))
        assert len(res.review_rows) == 1
        assert "mystery" in res.review_rows[0].values[TARGET_FIELD]

    def test_initech_prose_condition_flagged(self, examples_dir):
        res = import_mapping(_partner(examples_dir, "initech_prose.xlsx"))
        flagged = res.review_rows
        assert len(flagged) == 1
        assert "promo" in flagged[0].values[TARGET_FIELD]
        # the translatable prose conditions were coded
        coded = [r for r in res.rows if r.values.get("Condition (Coded)")]
        assert len(coded) == 2


# ---------------------------------------------------------------------------
# round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_clean_import_loads_and_is_stable(self, examples_dir, tmp_path):
        res = import_mapping(
            _partner(examples_dir, "acme_renamed.xlsx"),
            meta={"Transaction Set": "850", "Spec Name": "ACME 850"},
            code_lists_path=_partner(examples_dir, "acme_lookup.xlsx"),
        )
        assert res.review_rows == []
        out = write_workbook(res, tmp_path / "imported.xlsx")
        spec = load_spec(out)
        assert len(spec.rules) == 5
        assert "TX_PURPOSE" in spec.code_lists
        rt = {r.rule_type for r in spec.rules}
        assert RuleType.CODE_LIST in rt and RuleType.CONDITIONAL in rt
        # stable reload
        spec2 = load_spec(out)
        key = lambda s: [(r.row_id, r.rule_type, r.target_field) for r in s.rules]
        assert key(spec) == key(spec2)

    def test_draft_with_review_rows_does_not_load(self, examples_dir, tmp_path):
        from mapcheck.spec.parser import SpecLoadError

        res = import_mapping(_partner(examples_dir, "globex_mixed.csv"))
        out = write_workbook(res, tmp_path / "draft.xlsx")
        with pytest.raises(SpecLoadError):
            load_spec(out)

    def test_worklist_written(self, examples_dir, tmp_path):
        res = import_mapping(_partner(examples_dir, "globex_mixed.csv"))
        wl = write_worklist(res, tmp_path / "wl.txt")
        text = wl.read_text()
        assert "Needs review" in text
        assert "mystery" in text


# ---------------------------------------------------------------------------
# a document already in the native layout imports faithfully
# ---------------------------------------------------------------------------

CODED = "Condition (Coded)"

NATIVE_CSV = """\
Row ID,Source Field,Loop Context,Target Field,Rule Type,Condition (Text),Condition (Coded),Then,Else,Default Value,Code List Ref,Data Type,Format,Notes
C-001,BEG03,,order.po,DIRECT,,,,,,,string,len:1..22,
C-002,N104,N1[ST],ship_to.id,CONDITIONAL,Only when the qualifier is 92,N103 = '92',SOURCE,SKIP,,,string,,
C-003,BEG02,,order.type,CONDITIONAL,SA becomes STANDARD,BEG02 = 'SA','STANDARD','OTHER',,,string,,
C-004,,,order.source,CONSTANT,,,,,EDI,,string,,
C-005,,,order.ship_name,TODO,Join N102 and N104 with a dash,,,,,,,,GAP: concatenation
"""


class TestSuppliedCodedCondition:
    """The column was matched and reported as mapped, and its value was
    then never read: a condition the author had already coded was replaced
    by whatever the prose happened to translate to, or by nothing."""

    def test_kept_as_written(self):
        r = _classify(**{SOURCE_FIELD: "N104", TARGET_FIELD: "st.id", RULE_TYPE: "CONDITIONAL",
                         CONDITION_TEXT: "ship-to stores and DCs",
                         CODED: "N103 IN ('92', 'ZZ')"})
        assert not r.needs_review
        assert r.values[CODED] == "N103 IN ('92', 'ZZ')"
        assert r.values["Then"] == "SOURCE"

    def test_wins_over_what_the_prose_would_translate_to(self):
        r = _classify(**{SOURCE_FIELD: "N104", TARGET_FIELD: "st.id",
                         CONDITION_TEXT: "when N103 = 92",
                         CODED: "N103 = '92' AND EXISTS(N104)"})
        assert r.values[CODED] == "N103 = '92' AND EXISTS(N104)"

    def test_alone_it_makes_the_row_conditional(self):
        r = _classify(**{SOURCE_FIELD: "REF02", TARGET_FIELD: "order.ref",
                         CODED: "EXISTS(REF02)"})
        assert r.rule_type is RuleType.CONDITIONAL and not r.needs_review

    def test_invalid_one_is_flagged_and_not_thrown_away(self):
        r = _classify(**{SOURCE_FIELD: "N104", TARGET_FIELD: "st.id", RULE_TYPE: "CONDITIONAL",
                         CODED: "N103 is roughly 92"})
        assert r.needs_review and "not valid" in r.reason
        assert r.values[CODED] == "N103 is roughly 92"

    def test_on_a_row_of_another_type_it_goes_to_a_human(self):
        r = _classify(**{SOURCE_FIELD: "BEG03", TARGET_FIELD: "order.po", RULE_TYPE: "DIRECT",
                         CODED: "EXISTS(BEG03)"})
        assert r.needs_review and "CONDITIONAL?" in r.reason
        assert r.values[CODED] == "EXISTS(BEG03)"


class TestNativeLayoutImport:
    @pytest.fixture
    def result(self, tmp_path):
        doc = tmp_path / "rows.csv"
        doc.write_text(NATIVE_CSV, encoding="utf-8")
        return import_mapping(doc, meta={"Transaction Set": "850"})

    def test_nothing_needs_review_and_nothing_is_ignored(self, result):
        assert result.review_rows == []
        assert result.unmapped_columns == []

    def test_row_ids_and_notes_survive(self, result, tmp_path):
        assert [r.row_id for r in result.rows] == [f"C-00{n}" for n in range(1, 6)]
        out = write_workbook(result, tmp_path / "spec.xlsx")
        from openpyxl import load_workbook

        rows = list(load_workbook(out)["Mapping"].iter_rows(min_row=2, values_only=True))
        assert rows[4][0] == "C-005"
        assert rows[4][-1].startswith("GAP: concatenation | ")

    def test_todo_stays_todo(self, result, tmp_path):
        todo = result.rows[4]
        assert todo.rule_type is RuleType.TODO and not todo.needs_review
        text = write_worklist(result, tmp_path / "wl.txt").read_text()
        assert "TODO rows: 1" in text

    def test_imported_spec_loads_with_its_conditions(self, result, tmp_path):
        spec = load_spec(write_workbook(result, tmp_path / "spec.xlsx"))
        by_id = {r.row_id: r for r in spec.rules}
        assert len(by_id) == 5
        assert by_id["C-002"].rule_type is RuleType.CONDITIONAL
        assert by_id["C-005"].rule_type is RuleType.TODO

    def test_row_ids_are_generated_when_one_repeats(self, tmp_path):
        doc = tmp_path / "rows.csv"
        doc.write_text(NATIVE_CSV.replace("C-002", "C-001"), encoding="utf-8")
        result = import_mapping(doc)
        assert [r.row_id for r in result.rows][:2] == ["IMP-001", "IMP-002"]
        assert "Row ID" in result.unmapped_columns  # said out loud, not dropped

    def test_a_partner_comments_column_is_not_taken_for_notes(self, tmp_path):
        doc = tmp_path / "partner.csv"
        doc.write_text(
            "X12 Element,ERP Field,Comments\nBEG03,order.po,ask Dana about this\n",
            encoding="utf-8",
        )
        result = import_mapping(doc)
        assert result.rows[0].notes == ""
