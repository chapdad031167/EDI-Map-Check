"""Design 020: the scrubber names what it did not mask.

Covers the five decisions: the gaps closed in the shipped profile (each
leak the design measured is a regression test here), the residual-risk
scan and its report, the deny-by-default ``strict`` profile, the
same-seed warning for files scrubbed side by side, and the CLI flags
around them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import app
from mapcheck.cli import main
from mapcheck.scrub import Positions, ProfileError, classify, load_profile
from mapcheck.scrub.residual import is_date, is_decimal, parse_element_ref
from mapcheck.scrub.scrubber import Profile, Rule, scrub_text
from mapcheck.x12.parser import parse_interchange

ISA = (
    "ISA*00*          *00*          *ZZ*MAPCHECKSND    *ZZ*MAPCHECKRCV    "
    "*260615*1200*U*00401*000000001*0*T*>"
)
GS = "GS*PO*MAPCHECKSND*MAPCHECKRCV*20260615*1200*1*X*004010"


def _file(*body: str, set_code: str = "850") -> str:
    """A well-formed single-transaction interchange around ``body``."""
    transaction = [f"ST*{set_code}*0001", *body]
    transaction.append(f"SE*{len(transaction) + 1}*0001")
    segments = [ISA, GS, *transaction, "GE*1*1", "IEA*1*000000001"]
    return "~\n".join(segments) + "~\n"


def _segments(text: str) -> list[list[str]]:
    return [chunk.strip().split("*") for chunk in text.split("~") if chunk.strip()]


def _segment(text: str, seg_id: str, occurrence: int = 0) -> list[str]:
    return [s for s in _segments(text) if s[0] == seg_id][occurrence]


def _reasons(report) -> dict[str, str]:
    return {r.position: r.reason for r in report.residuals}


def _pii(examples_dir: Path) -> str:
    return (examples_dir / "source" / "850_pii.edi").read_text()


# ---------------------------------------------------------------------------
# Decision 1: the leaks the design measured, closed in the shipped profile
# ---------------------------------------------------------------------------


class TestMeasuredLeaksAreClosed:
    """Each of these survived a default scrub of the repo's own PII
    example before Design 020."""

    @pytest.fixture
    def scrubbed(self, examples_dir):
        text, report = scrub_text(_pii(examples_dir), load_profile(), seed="demo")
        return text, report

    def test_state_and_postal_code(self, scrubbed):
        n4 = _segment(scrubbed[0], "N4")
        assert n4[2] != "CO" and n4[3] != "80301"
        assert len(n4[2]) == 2 and len(n4[3]) == 5 and n4[3].isdigit()

    def test_party_identifiers_beside_the_masked_names(self, scrubbed):
        ship_to, bill_to = _segment(scrubbed[0], "N1", 0), _segment(scrubbed[0], "N1", 1)
        assert ship_to[4] != "0042" and bill_to[4] != "0001"
        # the same name still masks the same way on both parties
        assert ship_to[2] == bill_to[2] != "RIVERSIDE MARKET"

    def test_po_number(self, scrubbed):
        assert "POPII001" not in scrubbed[0]

    def test_upc(self, scrubbed):
        po1 = _segment(scrubbed[0], "PO1")
        assert po1[7] != "614141007349" and po1[6] == "UP"  # qualifier stays

    def test_nothing_is_left_for_the_residual_scan(self, scrubbed):
        assert scrubbed[1].residuals == []

    def test_ref_is_masked_under_a_qualifier_the_profile_never_named(self):
        text = _file("BEG*00*SA*PO1**20260615", "REF*ZZ*ACCT778812")
        scrubbed, _ = scrub_text(text, load_profile(), seed="x")
        assert "ACCT778812" not in scrubbed
        assert _segment(scrubbed, "REF")[1] == "ZZ"

    def test_free_text_segments(self):
        text = _file(
            "BEG*00*SA*PO1**20260615",
            "NTE*GEN*CALL JANE DOE AT THE DOCK",
            "MSG*LEAVE WITH SECURITY",
        )
        scrubbed, report = scrub_text(text, load_profile(), seed="x")
        assert "JANE DOE" not in scrubbed and "SECURITY" not in scrubbed
        assert _segment(scrubbed, "NTE")[1] == "GEN"
        assert report.residuals == []

    def test_address_lines_past_the_second(self):
        text = _file("N1*ST*ACME*92*0042", "N3*1 MAIN ST*SUITE 4*DOCK B*GATE 7")
        scrubbed, _ = scrub_text(text, load_profile(), seed="x")
        n3 = _segment(scrubbed, "N3")
        assert "DOCK B" not in n3 and "GATE 7" not in n3
        assert len(n3) == 5


# ---------------------------------------------------------------------------
# Decision 2: the detectors
# ---------------------------------------------------------------------------


class TestDetectors:
    @pytest.mark.parametrize(
        ("value", "reason"),
        [
            ("80301", "postal-code shape"),
            ("803011234", "postal-code shape"),
            ("80301-1234", "postal-code shape"),
            ("3035551212", "phone-number shape"),
            ("13035551212", "phone-number shape"),
            ("303-555-1212", "phone-number shape"),
            ("(303) 555-1212", "phone-number shape"),
            ("614141007349", "UPC/GTIN shape"),
            ("00614141007349", "UPC/GTIN shape"),
            ("AB1234563", "DEA-number shape"),
            ("12345-678-90", "NDC shape"),
            ("jane.doe@example.com", "email address"),
            ("POPII001", "account or reference shape"),
            ("SEE ACCT778812 FOR TERMS", "account or reference shape"),
        ],
    )
    def test_flags(self, value, reason):
        assert classify(value) == reason

    @pytest.mark.parametrize(
        "value",
        [
            "", "   ", "EA", "92", "12", "8.5", "1200", "0042",
            "123456", "1234567", "20260615", "12345678",
            "BOULDER", "RIVERSIDE MARKET", "ABCDEF", "A1B2C",
            "4501 CASCADE AVE",
        ],
    )
    def test_stays_quiet(self, value):
        assert classify(value) is None

    def test_decimal_and_date_shapes(self):
        assert is_decimal("8.5") and is_decimal("-12.50") and is_decimal(".5")
        assert not is_decimal("85") and not is_decimal("8.5.1") and not is_decimal("A.5")
        assert is_date("20260615")
        assert not is_date("20261340") and not is_date("260615") and not is_date("80301123")

    def test_element_refs(self):
        assert parse_element_ref("CTT01") == ("CTT", 1)
        assert parse_element_ref("W0301") == ("W03", 1)
        assert parse_element_ref("AK902") == ("AK9", 2)
        assert parse_element_ref("nonsense") is None


class TestQuietPositions:
    """A code is supposed to survive, and a quantity is not a postal code."""

    def test_code_in_an_identifier_looking_shape_is_not_flagged(self):
        # PID04 is a code position; the same value in a segment nobody
        # knows is reported.
        text = _file("PID*F*08*ZZ*CODE123456", "ZZZ*CODE123456")
        _, report = scrub_text(text, load_profile(), seed="x")
        assert _reasons(report) == {"ZZZ01": "account or reference shape"}

    def test_five_digit_quantity_is_not_a_postal_code(self):
        text = _file("PO1*1*80301*EA*8.5", "CTT*1*80301")
        _, report = scrub_text(text, load_profile(), seed="x")
        assert report.residuals == []

    def test_five_digit_value_in_an_unknown_position_is_flagged(self):
        text = _file("ZZZ*AB*80301")
        _, report = scrub_text(text, load_profile(), seed="x")
        assert _reasons(report) == {"ZZZ02": "postal-code shape"}

    def test_math_positions_are_learned_from_the_transaction_definition(self):
        # W0701 is a reconciliation operand of the 944, and nowhere in the
        # bundled table.
        assert ("W07", 1) not in Positions.bundled().math
        assert ("W07", 1) in Positions.for_transactions({"944"}).math
        text = _file("W07*80301*EA", set_code="944")
        _, report = scrub_text(text, load_profile(), seed="x")
        assert report.residuals == []

    def test_control_numbers_are_never_math(self):
        learned = Positions.for_transactions({"850"})
        assert ("CTT", 1) in learned.control and ("CTT", 1) not in learned.math


class TestStructuralFlags:
    def test_identifier_beside_a_masked_name_whatever_it_contains(self):
        names_only = Profile(name="t", rules=[Rule("N1", 2, "name")])
        text = _file("N1*ST*RIVERSIDE MARKET*92*42")
        _, report = scrub_text(text, names_only, seed="x")
        # two characters: no shape would ever catch it
        assert classify("42") is None
        assert _reasons(report) == {"N104": "identifier beside a masked N102"}

    def test_both_party_ids_reported_on_one_line(self):
        names_only = Profile(name="t", rules=[Rule("N1", 2, "name")])
        text = _file("N1*ST*RIVERSIDE MARKET*92*0042", "N1*BT*RIVERSIDE MARKET*92*0001")
        _, report = scrub_text(text, names_only, seed="x")
        (residual,) = report.residuals
        assert residual.values == ["0042", "0001"] and residual.occurrences == 2

    def test_free_text_is_reported_whatever_it_says(self):
        text = _file("PID*F****TRAIL MIX")
        _, report = scrub_text(text, load_profile(), seed="x")
        assert _reasons(report) == {"PID05": "free text"}

    def test_position_masked_under_one_qualifier_and_not_another(self):
        gated = Profile(
            name="t",
            rules=[Rule("REF", 2, "id", when_element=1, when_in=("DEA",))],
        )
        text = _file("REF*DEA*AB1234563", "REF*CR*HELLO")
        scrubbed, report = scrub_text(text, gated, seed="x")
        assert "AB1234563" not in scrubbed and "HELLO" in scrubbed
        assert _reasons(report) == {"REF02": "masked elsewhere in this file, not here"}

    def test_envelope_ids_reported_when_envelope_masking_is_off(self, examples_dir):
        profile = load_profile()
        profile.envelope = False
        _, report = scrub_text(_pii(examples_dir), profile, seed="x")
        assert set(_reasons(report)) == {"ISA06", "ISA08", "GS02", "GS03"}

    def test_isa_security_information_is_reported(self, examples_dir):
        text = _pii(examples_dir).replace("*00*          *ZZ*", "*01*HUNTER2   *ZZ*", 1)
        _, report = scrub_text(text, load_profile(), seed="x")
        assert _reasons(report) == {"ISA04": "authorization or security information"}

    def test_segment_nobody_mentions_and_rule_for_a_segment_not_there(self):
        profile = Profile(name="t", rules=[Rule("NOPE", 9, "id")])
        text = _file("ZZZ*ACCT778812*X")
        scrubbed, report = scrub_text(text, profile, seed="x")
        assert _segment(scrubbed, "ZZZ") == ["ZZZ", "ACCT778812", "X"]
        assert _reasons(report) == {"ZZZ01": "account or reference shape"}


class TestReport:
    def test_names_what_survived(self):
        names_only = Profile(name="t", rules=[Rule("N1", 2, "name")])
        text = _file(
            "N1*ST*RIVERSIDE MARKET*92*0042",
            "N4*BOULDER*CO*80301",
            "N1*BT*RIVERSIDE MARKET*92*0001",
            "N4*BOULDER*CO*80301",
        )
        _, report = scrub_text(text, names_only, seed="x")
        rendered = report.render()
        assert "Masked 6 value(s) (5 distinct):" in rendered  # 2 names, 4 envelope IDs
        assert "2 position(s) hold values that look like identifiers and were NOT masked:" in rendered
        assert "N104  0042, 0001  identifier beside a masked N102" in rendered
        assert "N403  80301       postal-code shape  (2 occurrences)" in rendered
        assert rendered.endswith(
            "Review these before sharing the file, or add rules to the profile."
        )

    def test_clean_report_does_not_promise_a_clean_file(self, examples_dir):
        _, report = scrub_text(_pii(examples_dir), load_profile(), seed="x")
        assert "pattern check, not a guarantee" in report.render()

    def test_long_values_and_long_lists_are_trimmed(self):
        text = _file(*[f"NTE*GEN*{'NOTE ' * 12}{n}" for n in range(5)])
        _, report = scrub_text(text, Profile(name="t", rules=[]), seed="x")
        (residual,) = report.residuals
        assert residual.occurrences == 5
        shown = residual.shown()
        assert shown.count("...") == 3 and shown.endswith("+2 more")


# ---------------------------------------------------------------------------
# Decision 3: the strict profile
# ---------------------------------------------------------------------------


class TestStrictProfile:
    @pytest.fixture
    def source(self, examples_dir) -> str:
        return (examples_dir / "source" / "850_baseline.edi").read_text()

    def test_loads_as_deny_by_default(self):
        strict = load_profile("strict")
        assert strict.deny_by_default and strict.keep_short == 3
        assert not load_profile("pharma").deny_by_default

    def test_scrubbed_file_still_parses_and_reconciles(self, source, tmp_path):
        scrubbed, _ = scrub_text(source, load_profile("strict"), seed="x")
        out = tmp_path / "strict.edi"
        out.write_text(scrubbed)
        interchange = parse_interchange(out)
        assert interchange.control_errors == []
        # every control number and count is where it was
        for seg_id in ("ISA", "GS", "ST", "SE", "GE", "IEA", "CTT"):
            before, after = _segment(source, seg_id), _segment(scrubbed, seg_id)
            if seg_id in ("ISA", "GS"):
                before = [v for i, v in enumerate(before) if (seg_id, i) not in
                          {("ISA", 6), ("ISA", 8), ("GS", 2), ("GS", 3)}]
                after = [v for i, v in enumerate(after) if (seg_id, i) not in
                         {("ISA", 6), ("ISA", 8), ("GS", 2), ("GS", 3)}]
            assert before == after

    def test_shape_is_preserved_everywhere(self, source):
        scrubbed, _ = scrub_text(source, load_profile("strict"), seed="x")
        before, after = _segments(source), _segments(scrubbed)
        assert [s[0] for s in before] == [s[0] for s in after]
        assert [[len(v) for v in s] for s in before] == [[len(v) for v in s] for s in after]

    def test_qualifiers_and_codes_survive(self, source):
        scrubbed, _ = scrub_text(source, load_profile("strict"), seed="x")
        for seg_id, element in (("BEG", 1), ("BEG", 2), ("CUR", 1), ("CUR", 2),
                                ("N1", 1), ("N1", 3), ("PO1", 3), ("PO1", 6),
                                ("PID", 1), ("SAC", 1), ("SAC", 2), ("AMT", 1)):
            assert _segment(scrubbed, seg_id)[element] == _segment(source, seg_id)[element]
        assert [s[1] for s in _segments(scrubbed) if s[0] == "REF"] == ["DP", "IA", "PD"]
        assert [s[1] for s in _segments(scrubbed) if s[0] == "DTM"] == ["002", "001"]

    def test_everything_else_is_masked(self, source):
        scrubbed, _ = scrub_text(source, load_profile("strict"), seed="x")
        for leaked in (
            "PO4400021", "VEND8821", "SUMMER26", "ALPINE OUTFITTERS", "0118",
            "4501 CASCADE AVE", "BOULDER", "80301", "614141007349",
            "TRAIL MIX", "MAPCHECKSND",
        ):
            assert leaked not in scrubbed
        # short, but an identifier or not a code: masked anyway
        assert _segment(scrubbed, "REF")[2] != "045"
        assert _segment(scrubbed, "N4")[2] != "CO"

    def test_math_is_kept_by_default(self, source):
        scrubbed, report = scrub_text(source, load_profile("strict"), seed="x")
        for seg_id, element in (("PO1", 2), ("PO1", 4), ("BEG", 5), ("DTM", 2),
                                ("SAC", 5), ("AMT", 2)):
            assert _segment(scrubbed, seg_id)[element] == _segment(source, seg_id)[element]
        assert "quantities, amounts and dates" in report.render()

    def test_mask_math_masks_it(self, source):
        scrubbed, report = scrub_text(
            source, load_profile("strict"), seed="x", keep_math=False
        )
        changed = [
            (seg_id, element)
            for seg_id, element in (("PO1", 2), ("PO1", 4), ("BEG", 5), ("DTM", 2),
                                    ("SAC", 5), ("AMT", 2))
            if _segment(scrubbed, seg_id)[element] != _segment(source, seg_id)[element]
        ]
        assert len(changed) >= 5  # a digit can land on itself; six never do
        assert "quantities, amounts and dates" not in report.render()
        # and the envelope still reconciles: counts are not math
        assert _segment(scrubbed, "CTT")[1] == "3" and _segment(scrubbed, "SE")[1] == "22"

    def test_large_quantity_is_kept_and_postal_code_is_not(self):
        text = _file("PO1*1*12500*EA*8.5", "N4*BOULDER*CO*80301", "CTT*1")
        scrubbed, _ = scrub_text(text, load_profile("strict"), seed="x")
        assert _segment(scrubbed, "PO1")[2] == "12500"
        assert _segment(scrubbed, "N4")[3] != "80301"

    def test_unknown_segment_keeps_its_qualifier_and_loses_its_value(self):
        text = _file("ZZZ*AB*SECRETVALUE99")
        scrubbed, _ = scrub_text(text, load_profile("strict"), seed="x")
        zzz = _segment(scrubbed, "ZZZ")
        assert zzz[1] == "AB" and zzz[2] != "SECRETVALUE99" and len(zzz[2]) == 13

    def test_isa_security_information_is_masked(self, examples_dir):
        text = _pii(examples_dir).replace("*00*          *ZZ*", "*01*HUNTER2   *ZZ*", 1)
        scrubbed, report = scrub_text(text, load_profile("strict"), seed="x")
        assert "HUNTER2" not in scrubbed
        assert len(scrubbed.split("~")[0]) == len(text.split("~")[0])
        assert report.residuals == []

    def test_nothing_residual_on_the_pii_example(self, examples_dir):
        _, report = scrub_text(_pii(examples_dir), load_profile("strict"), seed="x")
        assert report.residuals == []

    def test_envelope_off_keeps_the_partner_ids(self, examples_dir):
        strict = load_profile("strict")
        strict.envelope = False
        scrubbed, _ = scrub_text(_pii(examples_dir), strict, seed="x")
        assert scrubbed.split("~")[0] == _pii(examples_dir).split("~")[0]


class TestProfileGrammar:
    def _load(self, tmp_path: Path, body: str):
        path = tmp_path / "p.yaml"
        path.write_text(body)
        return load_profile(path)

    def test_open_ended_element(self, tmp_path):
        profile = self._load(
            tmp_path, 'rules:\n  - {segment: N3, element: "2+", strategy: text}\n'
        )
        (rule,) = profile.rules
        assert rule.element == 2 and rule.open_ended
        assert list(rule.indexes(4)) == [1, 2, 3]
        assert list(rule.indexes(1)) == []

    @pytest.mark.parametrize("element", ['"x+"', '"0+"', "0", "true", '"3"'])
    def test_bad_element(self, tmp_path, element):
        with pytest.raises(ProfileError, match="positive integer 'element'"):
            self._load(tmp_path, f"rules:\n  - {{segment: N3, element: {element}}}\n")

    def test_unknown_mode(self, tmp_path):
        with pytest.raises(ProfileError, match="unknown mode"):
            self._load(tmp_path, "mode: paranoid\nrules: []\n")

    def test_deny_profile_needs_no_rules_and_an_allow_profile_does(self, tmp_path):
        assert self._load(tmp_path, "mode: deny\n").deny_by_default
        with pytest.raises(ProfileError, match="'rules' list"):
            self._load(tmp_path, "name: t\n")

    def test_keep_list(self, tmp_path):
        profile = self._load(
            tmp_path,
            "mode: deny\nkeep_short: 2\nkeep:\n"
            "  - {segment: ZZZ, elements: [1]}\n"
            "  - {segment: ZZZ, elements: [2], kind: math}\n",
        )
        assert profile.keep_code == {("ZZZ", 1)} and profile.keep_math == {("ZZZ", 2)}
        text = _file("ZZZ*LONGCODE77*98765*SECRET99")
        kept, _ = scrub_text(text, profile, seed="x")
        assert _segment(kept, "ZZZ")[1:3] == ["LONGCODE77", "98765"]
        assert _segment(kept, "ZZZ")[3] != "SECRET99"
        no_math, _ = scrub_text(text, profile, seed="x", keep_math=False)
        assert _segment(no_math, "ZZZ")[1] == "LONGCODE77"
        assert _segment(no_math, "ZZZ")[2] != "98765"

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            ("mode: deny\nkeep: nope\n", "'keep' must be a list"),
            ("mode: deny\nkeep:\n  - {segment: Z}\n", "keep #1 needs"),
            ("mode: deny\nkeep:\n  - {segment: Z, elements: [0]}\n", "keep #1 needs"),
            ("mode: deny\nkeep:\n  - {segment: Z, elements: [1], kind: x}\n", "unknown kind"),
            ("mode: deny\nkeep_short: -1\n", "'keep_short'"),
        ],
    )
    def test_bad_keep(self, tmp_path, body, message):
        with pytest.raises(ProfileError, match=message):
            self._load(tmp_path, body)


# ---------------------------------------------------------------------------
# Decisions 4 and 5: two files, one seed
# ---------------------------------------------------------------------------


class TestSameSeedAcrossFiles:
    ORDER = _file("BEG*00*SA*PO4400021**20260615", "N1*ST*ALPINE OUTFITTERS*92*0118")
    INVOICE = _file(
        "BIG*20260701*INV9001**PO4400021", "N1*ST*ALPINE OUTFITTERS*92*0118",
        set_code="810",
    )

    def test_shared_values_mask_the_same_under_one_seed(self):
        order, _ = scrub_text(self.ORDER, load_profile(), seed="pair")
        invoice, _ = scrub_text(self.INVOICE, load_profile(), seed="pair")
        assert _segment(order, "N1")[2] == _segment(invoice, "N1")[2] != "ALPINE OUTFITTERS"
        assert _segment(order, "N1")[4] == _segment(invoice, "N1")[4] != "0118"

    def test_and_differently_without_one(self):
        order, _ = scrub_text(self.ORDER, load_profile())
        invoice, _ = scrub_text(self.INVOICE, load_profile())
        assert _segment(order, "N1")[2] != _segment(invoice, "N1")[2]


class TestCli:
    @pytest.fixture
    def leaky(self, tmp_path) -> Path:
        path = tmp_path / "in.edi"
        path.write_text(_file("BEG*00*SA*PO1**20260615", "PID*F****TRAIL MIX"))
        return path

    def test_report_names_the_residual(self, leaky, capsys):
        assert main(["scrub", str(leaky), "--seed", "s", "--report"]) == 0
        out = capsys.readouterr().out
        assert "were NOT masked" in out and "PID05" in out and "free text" in out

    def test_without_report_the_residual_is_still_announced(self, leaky, capsys):
        assert main(["scrub", str(leaky), "--seed", "s"]) == 0
        out = capsys.readouterr().out
        assert "1 position(s) still hold values that look like identifiers" in out
        assert "--report" in out and "TRAIL MIX" not in out

    def test_a_clean_scrub_announces_nothing(self, examples_dir, tmp_path, capsys):
        src = tmp_path / "in.edi"
        src.write_text(_pii(examples_dir))
        assert main(["scrub", str(src), "--seed", "s"]) == 0
        assert "look like identifiers" not in capsys.readouterr().out

    def test_fail_on_residual(self, leaky, examples_dir, tmp_path, capsys):
        assert main(["scrub", str(leaky), "--seed", "s", "--fail-on-residual"]) == 1
        assert (leaky.parent / "in.scrubbed.edi").exists()  # still written
        clean = tmp_path / "clean.edi"
        clean.write_text(_pii(examples_dir))
        assert main(["scrub", str(clean), "--seed", "s", "--fail-on-residual"]) == 0

    def test_strict_profile_and_mask_math(self, examples_dir, tmp_path, capsys):
        src = tmp_path / "in.edi"
        src.write_text((examples_dir / "source" / "850_baseline.edi").read_text())
        out = tmp_path / "strict.edi"
        code = main(["scrub", str(src), "-o", str(out), "--profile", "strict",
                     "--seed", "s", "--mask-math", "--report"])
        assert code == 0
        assert "Kept in the clear by design" in capsys.readouterr().out
        assert "TRAIL MIX" not in out.read_text()
        assert _segment(out.read_text(), "CTT")[1] == "3"

    def test_mask_math_says_so_when_it_cannot_apply(self, leaky, capsys):
        assert main(["scrub", str(leaky), "--seed", "s", "--mask-math"]) == 0
        assert "--mask-math has no effect" in capsys.readouterr().err

    def test_second_unseeded_file_beside_a_first_is_warned_about(
        self, examples_dir, tmp_path, capsys
    ):
        first, second = tmp_path / "source.edi", tmp_path / "output.edi"
        first.write_text(_pii(examples_dir))
        second.write_text(_pii(examples_dir))
        assert main(["scrub", str(first)]) == 0
        assert "warning" not in capsys.readouterr().err  # nothing to pair with yet
        assert main(["scrub", str(second)]) == 0
        err = capsys.readouterr().err
        assert "no --seed given" in err and "source.scrubbed.edi" in err

    def test_seeded_files_side_by_side_are_not_warned_about(
        self, examples_dir, tmp_path, capsys
    ):
        first, second = tmp_path / "source.edi", tmp_path / "output.edi"
        first.write_text(_pii(examples_dir))
        second.write_text(_pii(examples_dir))
        assert main(["scrub", str(first), "--seed", "pair"]) == 0
        assert main(["scrub", str(second), "--seed", "pair"]) == 0
        assert "warning" not in capsys.readouterr().err

    def test_seed_help_states_what_a_seed_costs(self, capsys):
        with pytest.raises(SystemExit):
            main(["scrub", "--help"])
        help_text = " ".join(capsys.readouterr().out.split())
        assert "Treat it as a secret" in help_text
        assert "trying every value" in help_text


class TestScrubPage:
    def test_warning_counts_what_survived(self):
        message = app.scrub_residual_warning(3)
        assert message.startswith("3 position(s) still hold values")
        assert "Review them before you share this file." in message
