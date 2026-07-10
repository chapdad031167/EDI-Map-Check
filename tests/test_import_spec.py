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
