"""Guide import (Design 014): parser, profile, overlay, and guided drafts.

The synthetic fixture guide (tests/fixtures/guides/) is the golden input:
same guide in, same profile out — deterministically. Flag-never-guess is
tested as behavior: lines the grammar cannot hold land in ``review`` with
page context, never in the data. The PDF twin must extract to the exact
same profile as the .txt (parity), because both are one guide family.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from openpyxl import load_workbook

from mapcheck.guides.overlay import (
    PartnerRules,
    PartnerRulesError,
    emit_partner_rules,
)
from mapcheck.guides.parser import GuideParseError, parse_guide
from mapcheck.guides.profile import GuideProfile, GuideProfileError
from mapcheck.output.idoc import default_output_registry
from mapcheck.spec.draft import (
    Crosswalk,
    assemble_draft,
    bundled_crosswalks,
    generate_draft,
    load_crosswalks,
)
from mapcheck.transactions.registry import default_registry
from mapcheck.transactions.schema import RequiredElementDef, RequiredSegmentDef

REPO = Path(__file__).resolve().parent.parent
GUIDES = REPO / "tests" / "fixtures" / "guides"
GUIDE_TXT = GUIDES / "acme_pharma_850_guide.txt"
GUIDE_PDF = GUIDES / "acme_pharma_850_guide.pdf"

DEFINITION_850 = default_registry.get("850")
ORDERS05 = default_output_registry.get("idoc-orders05")


def _profile() -> GuideProfile:
    return parse_guide(GUIDE_TXT, transaction="850", partner="acme_pharma")


# --------------------------------------------------------------------------
# Family detection and extraction
# --------------------------------------------------------------------------


class TestFamilyDetection:
    def test_non_guide_text_is_rejected_naming_fingerprints(self, tmp_path: Path):
        other = tmp_path / "notes.txt"
        other.write_text("Meeting notes\nDiscussed the 850 project.\n", encoding="utf-8")
        with pytest.raises(GuideParseError) as err:
            parse_guide(other, transaction="850", partner="x")
        message = str(err.value)
        assert "not a recognized implementation-guide layout" in message
        assert "segment header block" in message
        assert "Element Summary" in message

    def test_unsupported_suffix_is_rejected(self, tmp_path: Path):
        doc = tmp_path / "guide.docx"
        doc.write_bytes(b"PK\x03\x04")
        with pytest.raises(GuideParseError, match="unsupported guide format"):
            parse_guide(doc, transaction="850", partner="x")

    def test_missing_file(self):
        with pytest.raises(GuideParseError, match="not found"):
            parse_guide(GUIDES / "no_such_guide.txt", transaction="850", partner="x")


# --------------------------------------------------------------------------
# Golden profile from the synthetic fixture
# --------------------------------------------------------------------------


class TestGoldenProfile:
    def test_segment_inventory(self):
        profile = _profile()
        assert [seg.id for seg in profile.segments] == [
            "BEG", "CUR", "REF", "PER", "DTM", "N1", "N3", "N4",
            "PO1", "PID", "SAC", "CTT",
        ]
        assert profile.transaction == "850"
        assert profile.partner == "acme_pharma"
        assert profile.source == GUIDE_TXT.name

    def test_usages_and_loops(self):
        profile = _profile()
        usage = {seg.id: seg.usage for seg in profile.segments}
        assert usage["BEG"] == "must_use"
        assert usage["CUR"] == "used"
        assert usage["SAC"] == "not_used"
        assert profile.segment("N3").loop == "N1"
        assert profile.segment("PO1").loop == "PO1"
        assert profile.segment("BEG").loop == ""  # printed as N/A

    def test_element_rows(self):
        beg = _profile().segment("BEG")
        assert [el.ref for el in beg.elements] == [
            "BEG01", "BEG02", "BEG03", "BEG04", "BEG05",
        ]
        beg04 = beg.element("BEG04")
        assert beg04.usage == "not_used"
        assert beg04.req == "O"
        assert beg04.type == "AN"
        assert (beg04.min, beg04.max) == (1, 30)

    def test_code_subsets_attach_to_their_element(self):
        profile = _profile()
        beg02 = profile.segment("BEG").element("BEG02")
        assert [(c.code, c.name) for c in beg02.codes] == [("NE", "New Order")]
        po1 = profile.segment("PO1")
        assert [c.code for c in po1.element("PO106").codes] == ["VN"]
        assert [c.code for c in po1.element("PO108").codes] == ["UP"]
        assert po1.element("PO107").codes == ()

    def test_notes_attach_to_element_and_flow_with_label_stripped(self):
        profile = _profile()
        beg05 = profile.segment("BEG").element("BEG05")
        assert beg05.notes == (
            "This is the date assigned by Acme Pharma to the purchase order.",
        )
        po109 = profile.segment("PO1").element("PO109")
        assert po109.notes == (
            "Every PO1 line must carry a UP qualifier pair with the UPC.",
        )

    def test_full_coverage_and_empty_review(self):
        profile = _profile()
        assert profile.review == []
        assert profile.parse_coverage == 1.0
        assert profile.facts_detected == 64

    def test_deterministic(self):
        assert _profile().to_dict() == _profile().to_dict()


class TestPdfParity:
    def test_pdf_twin_extracts_identically(self):
        pytest.importorskip("pdfplumber")
        txt = _profile().to_dict()
        pdf = parse_guide(GUIDE_PDF, transaction="850", partner="acme_pharma").to_dict()
        txt.pop("source")
        pdf.pop("source")
        assert txt == pdf


# --------------------------------------------------------------------------
# Flag-never-guess: uncertain lines go to review, never into the data
# --------------------------------------------------------------------------


def _guide_text(*blocks: str) -> str:
    head = (
        "Fixture Guide\n\n"
        "BEG Beginning Segment for Purchase Order Pos: 020 Max: 1\n"
        "User Option (Usage): Must use\n\n"
        "Element Summary:\n"
        "BEG01 353 Transaction Set Purpose Code M ID 2/2 Must use\n"
    )
    return head + "".join(blocks)


class TestFlagNeverGuess:
    def test_mangled_element_row_is_review_not_data(self, tmp_path: Path):
        guide = tmp_path / "g.txt"
        guide.write_text(
            _guide_text("BEG02 92 Purchase Order Type Code M ID 2/2\n"),
            encoding="utf-8",
        )
        profile = parse_guide(guide, transaction="850", partner="x")
        beg = profile.segment("BEG")
        assert beg.element("BEG02") is None
        assert len(profile.review) == 1
        assert "BEG02" in profile.review[0]
        assert "page 1" in profile.review[0]
        assert profile.parse_coverage < 1.0

    def test_unrecognized_segment_usage_is_review(self, tmp_path: Path):
        guide = tmp_path / "g.txt"
        guide.write_text(
            _guide_text(
                "\nCUR Currency Pos: 040 Max: 1\n"
                "User Option (Usage): Sometimes\n\n"
                "Element Summary:\n"
                "CUR01 98 Entity Identifier Code M ID 2/3 Used\n"
            ),
            encoding="utf-8",
        )
        profile = parse_guide(guide, transaction="850", partner="x")
        assert profile.segment("CUR").usage == ""
        assert any("Sometimes" in note for note in profile.review)

    def test_orphan_code_row_is_review(self, tmp_path: Path):
        guide = tmp_path / "g.txt"
        guide.write_text(
            _guide_text(
                "\nCUR Currency Pos: 040 Max: 1\n"
                "User Option (Usage): Used\n"
                "Code List Summary (Total Codes: 3, Included: 1)\n"
                "Code Name\n"
                "XX Mystery\n"
                "\nElement Summary:\n"
                "CUR01 98 Entity Identifier Code M ID 2/3 Used\n"
            ),
            encoding="utf-8",
        )
        profile = parse_guide(guide, transaction="850", partner="x")
        assert any("code row with no open element" in note for note in profile.review)
        assert all(not el.codes for el in profile.segment("CUR").elements)


# --------------------------------------------------------------------------
# Profile serialization
# --------------------------------------------------------------------------


class TestProfileRoundTrip:
    def test_save_load_round_trip(self, tmp_path: Path):
        profile = _profile()
        path = profile.save(tmp_path / "acme.yaml")
        again = GuideProfile.load(path)
        assert again.to_dict() == profile.to_dict()
        assert again.parse_coverage == profile.parse_coverage

    def test_load_rejects_non_profile(self, tmp_path: Path):
        path = tmp_path / "other.yaml"
        path.write_text("just: text\n", encoding="utf-8")
        with pytest.raises(GuideProfileError, match="missing 'transaction'"):
            GuideProfile.load(path)

    def test_load_names_every_problem(self, tmp_path: Path):
        path = tmp_path / "bad.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "transaction": "850",
                    "segments": [
                        {"name": "no id"},
                        {"id": "BEG", "usage": "sometimes"},
                        {"id": "REF", "elements": [{"ref": "REF01", "usage": "meh"}]},
                    ],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(GuideProfileError) as err:
            GuideProfile.load(path)
        message = str(err.value)
        assert "3 problem(s)" in message
        assert "segments[0]" in message
        assert "segments[1]" in message
        assert "segments[2].elements[0]" in message


# --------------------------------------------------------------------------
# Overlay emission and apply
# --------------------------------------------------------------------------


class TestOverlayEmission:
    def test_qualified_segments_pin_single_code(self):
        rules = emit_partner_rules(_profile())
        by_segment = {(r.segment, r.qualifier): r for r in rules.required_segments}
        assert ("REF", "IA") in by_segment
        assert ("DTM", "002") in by_segment
        assert by_segment[("DTM", "002")].name == "Requested Delivery"
        assert by_segment[("DTM", "002")].origin == "acme_pharma"
        # BEG/N1/PO1/CTT are unqualified requirements
        assert ("BEG", None) in by_segment
        assert ("N1", None) in by_segment  # N101 carries no code subset

    def test_element_rules_from_unqualified_segments(self):
        rules = emit_partner_rules(_profile())
        refs = {(r.segment, r.element) for r in rules.required_elements}
        assert ("PO1", 8) in refs and ("PO1", 9) in refs  # the UP pair
        assert ("CTT", 2) in refs
        assert ("BEG", 4) not in refs  # Not used, never required
        # qualified segments contribute no element rules (review instead)
        assert not any(seg == "REF" for seg, _ in refs)
        assert any("REF*IA" in note for note in rules.review)
        assert any("DTM*002" in note for note in rules.review)

    def test_multi_code_qualifier_falls_back_unqualified(self, tmp_path: Path):
        guide = tmp_path / "g.txt"
        guide.write_text(
            "REF Reference Identification Pos: 050 Max: 1\n"
            "User Option (Usage): Must use\n\n"
            "Element Summary:\n"
            "REF01 128 Reference Identification Qualifier M ID 2/3 Must use\n"
            "Code List Summary (Total Codes: 320, Included: 2)\n"
            "Code Name\n"
            "IA Internal Vendor Number\n"
            "DP Department Number\n"
            "REF02 127 Reference Identification M AN 1/30 Must use\n",
            encoding="utf-8",
        )
        rules = emit_partner_rules(parse_guide(guide, transaction="850", partner="x"))
        assert [(r.segment, r.qualifier) for r in rules.required_segments] == [("REF", None)]
        assert any("multiple qualifier codes" in note for note in rules.review)
        # unqualified fallback also carries the element rules
        assert {(r.segment, r.element) for r in rules.required_elements} == {
            ("REF", 1), ("REF", 2),
        }

    def test_apply_dedups_against_unconditional_base_only(self):
        rules = emit_partner_rules(_profile())
        base = DEFINITION_850
        base_pairs = {(r.segment, r.element, r.when_present) for r in base.required_elements}
        assert ("BEG", 3, None) in base_pairs  # unconditional base rule
        assert ("PO1", 2, 3) in base_pairs  # conditional base rule
        merged = rules.apply(base)
        merged_partner = [
            (r.segment, r.element) for r in merged.required_elements if r.origin
        ]
        assert ("BEG", 3) not in merged_partner  # base already enforces it
        assert ("PO1", 2) in merged_partner  # conditional base does not
        assert len(merged.required_segments) == len(base.required_segments) + 6

    def test_apply_rejects_wrong_transaction(self):
        rules = emit_partner_rules(_profile())
        other = default_registry.get("810")
        with pytest.raises(PartnerRulesError, match="850.*810"):
            rules.apply(other)


class TestOverlayRoundTrip:
    def test_save_load_round_trip(self, tmp_path: Path):
        rules = emit_partner_rules(_profile())
        path = rules.save(tmp_path / "acme_rules.yaml")
        again = PartnerRules.load(path)
        assert again.to_dict() == rules.to_dict()
        assert all(r.origin == "acme_pharma" for r in again.required_segments)

    def test_load_names_every_problem(self, tmp_path: Path):
        path = tmp_path / "bad.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "transaction": "850",
                    "partner": "x",
                    "required_segments": [{"qualifier": "IA"}],
                    "required_elements": [{"segment": "REF", "element": 0}],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(PartnerRulesError) as err:
            PartnerRules.load(path)
        message = str(err.value)
        assert "required_segments[0]" in message
        assert "required_elements[0]" in message

    def test_committed_example_overlay_loads(self):
        rules = PartnerRules.load(REPO / "examples" / "partner_rules" / "acme_pharma_850.yaml")
        assert rules.partner == "acme_pharma"
        assert len(rules.required_segments) == 6
        profile = GuideProfile.load(
            REPO / "examples" / "partner_rules" / "acme_pharma_850_profile.yaml"
        )
        assert profile.parse_coverage == 1.0


# --------------------------------------------------------------------------
# Required-segment enforcement (definition-level, no spec involved)
# --------------------------------------------------------------------------


class TestRequiredSegmentLoader:
    def test_definition_yaml_round_trip(self, tmp_path: Path):
        from mapcheck.transactions.loader import parse_definition

        data = {
            "transaction": {"set": "850", "name": "PO", "functional_group": "PO"},
            "structure": [{"area": "heading", "segments": ["BEG"]}],
            "required_segments": [
                {"segment": "dtm", "qualifier": "002", "name": "Requested Delivery"},
                {"segment": "PO1"},
            ],
        }
        definition = parse_definition(data, source="inline")
        assert definition.required_segments == (
            RequiredSegmentDef(segment="DTM", qualifier="002", name="Requested Delivery"),
            RequiredSegmentDef(segment="PO1"),
        )

    def test_loader_rejects_bad_entries(self):
        from mapcheck.transactions.loader import DefinitionError, parse_definition

        data = {
            "transaction": {"set": "850", "name": "PO", "functional_group": "PO"},
            "structure": [{"area": "heading", "segments": ["BEG"]}],
            "required_segments": [{"qualifier": "IA"}, {"segment": "REF", "qualifier_element": 0}],
        }
        with pytest.raises(DefinitionError) as err:
            parse_definition(data, source="inline")
        message = str(err.value)
        assert "required_segments[0]" in message
        assert "required_segments[1].qualifier_element" in message


# --------------------------------------------------------------------------
# Guided drafts (consumer one)
# --------------------------------------------------------------------------


def _starter() -> Crosswalk:
    return load_crosswalks(bundled_crosswalks("850", "orders05"))


class TestGuidedDraft:
    def test_partner_notes_flow_to_filled_rows(self):
        result = assemble_draft(DEFINITION_850, ORDERS05, _starter(), guide=_profile())
        beg05_rows = [r for r in result.rows if r.source == "BEG05"]
        assert beg05_rows
        assert all(
            "Partner note: This is the date assigned by Acme Pharma" in r.notes
            for r in beg05_rows
        )

    def test_not_used_elements_leave_unmapped_source(self):
        plain = assemble_draft(DEFINITION_850, ORDERS05, _starter())
        guided = assemble_draft(DEFINITION_850, ORDERS05, _starter(), guide=_profile())
        plain_fields = {el.field for el in plain.unmapped_source}
        guided_fields = {el.field for el in guided.unmapped_source}
        assert "SAC01" in plain_fields and "SAC01" not in guided_fields
        assert "PO105" in plain_fields and "PO105" not in guided_fields
        # elements the guide does not mention stay
        assert "SAC03" in guided_fields

    def test_must_use_markers_on_unmapped_source(self):
        result = assemble_draft(DEFINITION_850, ORDERS05, _starter(), guide=_profile())
        usage = {el.field: el.partner_usage for el in result.unmapped_source}
        assert usage["PO108"] == "Must use"
        assert usage["PO109"] == "Must use"
        assert usage["CTT02"] == "Must use"
        assert usage["PER01"] == "Used"
        assert usage["SAC03"] == ""  # not in the guide

    def test_code_lists_filter_to_partner_subset(self):
        result = assemble_draft(DEFINITION_850, ORDERS05, _starter(), guide=_profile())
        assert [e.source for e in result.code_lists["SAP_ACTION"]] == ["00"]
        assert [e.source for e in result.code_lists["PO_TYPE_SAP"]] == ["NE"]
        # PO103 carries no code subset in the guide: UOM_SAP is untouched
        assert [e.source for e in result.code_lists["UOM_SAP"]] == ["EA", "CA", "DZ"]
        assert result.guide_review == ()

    def test_partner_code_without_translation_is_review(self, tmp_path: Path):
        crosswalk_file = tmp_path / "xw.yaml"
        crosswalk_file.write_text(
            yaml.safe_dump(
                {
                    "rules": [
                        {
                            "source": "BEG02",
                            "target": "header.bsart",
                            "rule": "CODE_LIST",
                            "code_list": "PO_TYPE",
                        }
                    ],
                    "code_lists": {
                        "PO_TYPE": [{"source": "SA", "target": "NB"}],
                    },
                }
            ),
            encoding="utf-8",
        )
        crosswalk = load_crosswalks([crosswalk_file])
        result = assemble_draft(DEFINITION_850, ORDERS05, crosswalk, guide=_profile())
        assert result.code_lists["PO_TYPE"] == ()  # SA is not a partner code
        assert any(
            "partner code NE (New Order) has no crosswalk translation" in note
            for note in result.guide_review
        )

    def test_mapped_but_not_used_element_is_review(self, tmp_path: Path):
        crosswalk_file = tmp_path / "xw.yaml"
        crosswalk_file.write_text(
            yaml.safe_dump(
                {
                    "rules": [
                        {"source": "BEG04", "target": "org.012", "rule": "DIRECT"}
                    ]
                }
            ),
            encoding="utf-8",
        )
        crosswalk = load_crosswalks([crosswalk_file])
        result = assemble_draft(DEFINITION_850, ORDERS05, crosswalk, guide=_profile())
        assert any(
            "BEG04 is mapped to org.012 but the guide marks it Not used" in note
            for note in result.guide_review
        )

    def test_unguided_draft_is_unchanged(self):
        result = assemble_draft(DEFINITION_850, ORDERS05, _starter())
        assert result.guided is False
        assert result.guide_review == ()
        assert all(el.partner_usage == "" for el in result.unmapped_source)

    def test_guided_workbook_content(self, tmp_path: Path):
        out = tmp_path / "draft.xlsx"
        generate_draft(
            DEFINITION_850, ORDERS05, bundled_crosswalks("850", "orders05"), out,
            guide=_profile(),
        )
        wb = load_workbook(out)
        ws = wb["Unmapped Source"]
        headers = [c.value for c in ws[1]]
        assert headers[:4] == ["Source Field", "Loop Context", "Element Name", "Partner Usage"]
        rows = {row[0]: row[3] for row in ws.iter_rows(min_row=2, values_only=True) if row[0]}
        assert rows["PO108"] == "Must use"
        meta = {
            row[0]: row[1]
            for row in wb["Meta"].iter_rows(values_only=True)
            if row and row[0]
        }
        assert meta["Guide"] == "acme_pharma — acme_pharma_850_guide.txt"

    def test_guided_draft_deterministic(self, tmp_path: Path):
        results = [
            assemble_draft(DEFINITION_850, ORDERS05, _starter(), guide=_profile())
            for _ in range(2)
        ]
        assert results[0] == results[1]


# --------------------------------------------------------------------------
# CLI verbs
# --------------------------------------------------------------------------


class TestCli:
    def test_import_guide_writes_profile_and_overlay(self, tmp_path: Path, capsys):
        from mapcheck.cli import main

        profile_path = tmp_path / "acme.yaml"
        overlay_path = tmp_path / "acme_rules.yaml"
        code = main(
            [
                "import-guide", str(GUIDE_TXT),
                "--transaction", "850", "--partner", "acme_pharma",
                "--profile", str(profile_path), "--overlay", str(overlay_path),
            ]
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "parse coverage 1.00" in out
        assert GuideProfile.load(profile_path).partner == "acme_pharma"
        assert PartnerRules.load(overlay_path).transaction == "850"

    def test_import_guide_refuses_overwrite(self, tmp_path: Path, capsys):
        from mapcheck.cli import main

        existing = tmp_path / "acme.yaml"
        existing.write_text("x", encoding="utf-8")
        code = main(
            [
                "import-guide", str(GUIDE_TXT),
                "--transaction", "850", "--partner", "acme_pharma",
                "--profile", str(existing),
            ]
        )
        assert code == 2
        assert "already exists" in capsys.readouterr().err

    def test_import_guide_notes_unregistered_set(self, tmp_path: Path, capsys):
        from mapcheck.cli import main

        code = main(
            [
                "import-guide", str(GUIDE_TXT),
                "--transaction", "832", "--partner", "x",
                "--profile", str(tmp_path / "p.yaml"),
            ]
        )
        assert code == 0
        assert "no registered definition" in capsys.readouterr().err

    def test_draft_spec_accepts_profile_and_raw_guide(self, tmp_path: Path, capsys):
        from mapcheck.cli import main

        profile_path = tmp_path / "acme.yaml"
        _profile().save(profile_path)
        for name, guide_arg in (
            ("from_profile.xlsx", str(profile_path)),
            ("from_raw.xlsx", str(GUIDE_TXT)),
        ):
            code = main(
                [
                    "draft-spec", "--transaction", "850", "--target", "orders05",
                    "--guide", guide_arg, "--output", str(tmp_path / name),
                ]
            )
            assert code == 0
        out = capsys.readouterr().out
        assert "flavored by partner acme_pharma" in out  # profile path
        assert "flavored by the partner guide" in out  # raw path, unnamed

    def test_draft_spec_rejects_wrong_transaction_profile(self, tmp_path: Path, capsys):
        from mapcheck.cli import main

        profile = _profile()
        profile.transaction = "810"
        profile_path = profile.save(tmp_path / "other.yaml")
        code = main(
            [
                "draft-spec", "--transaction", "850", "--target", "orders05",
                "--guide", str(profile_path), "--output", str(tmp_path / "d.xlsx"),
            ]
        )
        assert code == 2
        assert "transaction set 810" in capsys.readouterr().err
