"""Data scrubber (design 009): profile loader, masking strategies, fidelity.

Covers the profile loader (bundled + file + errors), the deterministic
length-/character-class-preserving strategies, referential consistency and
the ``--seed``, round-trip fidelity (delimiters, ISA width, control numbers,
segment counts), envelope masking, and the bundled synthetic PII 850 through
the CLI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapcheck.cli import main
from mapcheck.scrub import ProfileError, Profile, Rule, load_profile
from mapcheck.scrub.scrubber import Scrubber, _delimiters, scrub_text
from mapcheck.x12.parser import parse_transaction

PII = "850_pii.edi"


def _src(examples_dir: Path) -> Path:
    return examples_dir / "source" / PII


# ---------------------------------------------------------------------------
# profile loader
# ---------------------------------------------------------------------------


class TestProfileLoader:
    def test_bundled_pharma_default(self):
        p = load_profile("pharma")
        assert p.name == "pharma-default" and p.envelope is True
        assert any(r.segment == "N1" and r.element == 2 for r in p.rules)
        ref = next(r for r in p.rules if r.segment == "REF")
        assert ref.when_element == 1 and "DEA" in ref.when_in

    def test_default_is_pharma(self):
        assert load_profile().name == "pharma-default"

    def test_file_path(self, tmp_path):
        (tmp_path / "p.yaml").write_text(
            "name: t\nrules:\n  - {segment: N1, element: 2, strategy: name}\n"
        )
        p = load_profile(tmp_path / "p.yaml")
        assert p.name == "t" and len(p.rules) == 1

    def test_unknown_name(self):
        with pytest.raises(ProfileError, match="not found"):
            load_profile("nope")

    def test_unknown_strategy(self, tmp_path):
        (tmp_path / "p.yaml").write_text(
            "rules:\n  - {segment: N1, element: 2, strategy: bogus}\n"
        )
        with pytest.raises(ProfileError, match="unknown strategy"):
            load_profile(tmp_path / "p.yaml")

    def test_malformed_rule(self, tmp_path):
        (tmp_path / "p.yaml").write_text("rules:\n  - {segment: N1}\n")
        with pytest.raises(ProfileError, match="positive integer 'element'"):
            load_profile(tmp_path / "p.yaml")


# ---------------------------------------------------------------------------
# masking strategies
# ---------------------------------------------------------------------------


def _prof(*rules: Rule, envelope: bool = False) -> Profile:
    return Profile(name="t", rules=list(rules), envelope=envelope)


class TestStrategies:
    def test_name_length_and_class_preserving(self):
        s = Scrubber(_prof(Rule("N1", 2, "name")), seed="x")
        masked = s._mask_value("ALPINE STORE 118", "name")
        assert len(masked) == len("ALPINE STORE 118")
        assert masked != "ALPINE STORE 118"
        # letters stay letters, digits stay digits, spaces stay spaces
        for a, b in zip("ALPINE STORE 118", masked):
            assert a.isalpha() == b.isalpha()
            assert a.isdigit() == b.isdigit()
            assert a.isspace() == b.isspace()

    def test_id_preserves_separators(self):
        s = Scrubber(_prof(), seed="x")
        masked = s._mask_value("12345-678-90", "id")
        assert len(masked) == len("12345-678-90")
        assert masked[5] == "-" and masked[9] == "-"
        assert masked.replace("-", "").isdigit()

    def test_dea_shape_preserved(self):
        s = Scrubber(_prof(), seed="x")
        masked = s._mask_value("AB1234563", "id")
        assert masked[:2].isalpha() and masked[2:].isdigit() and len(masked) == 9

    def test_redact_is_filler(self):
        s = Scrubber(_prof(), seed="x")
        assert s._mask_value("SECRET-42", "redact") == "XXXXXX-XX"

    def test_referential_consistency(self):
        s = Scrubber(_prof(), seed="x")
        assert s._mask_value("ACME", "name") == s._mask_value("ACME", "name")


# ---------------------------------------------------------------------------
# determinism / seed
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_seed_reproduces(self, examples_dir):
        text = _src(examples_dir).read_text()
        a, _ = scrub_text(text, load_profile(), seed="fixed")
        b, _ = scrub_text(text, load_profile(), seed="fixed")
        assert a == b

    def test_no_seed_differs(self, examples_dir):
        text = _src(examples_dir).read_text()
        a, _ = scrub_text(text, load_profile())
        b, _ = scrub_text(text, load_profile())
        assert a != b  # random salt each run

    def test_repeated_value_masks_identically_in_file(self, examples_dir):
        # RIVERSIDE MARKET appears in both N1*ST and N1*BT
        text = _src(examples_dir).read_text()
        scrubbed, report = scrub_text(text, load_profile(), seed="x")
        segs = [ln.strip() for ln in scrubbed.split("~")]
        names = [ln.split("*")[2] for ln in segs if ln.startswith("N1*")]
        assert len(names) == 2 and names[0] == names[1]  # same masked token
        assert "RIVERSIDE MARKET" not in scrubbed


# ---------------------------------------------------------------------------
# fidelity
# ---------------------------------------------------------------------------


class TestFidelity:
    def test_delimiters_detected(self, examples_dir):
        text = _src(examples_dir).read_text()
        assert _delimiters(text) == ("*", "~")

    def test_non_standard_delimiters_round_trip(self):
        # element sep '|', segment terminator '\n'
        isa = "ISA|00|          |00|          |ZZ|SENDER         |ZZ|RECEIVER       " \
              "|260615|1200|U|00401|000000001|0|T|>\n"
        body = "GS|PO|APPSENDER|APPRCVR|20260615|1200|1|X|004010\nN1|ST|ACME CO|92|1\nSE|3|0001\n"
        text = isa + body
        scrubbed, _ = scrub_text(text, load_profile(), seed="x")
        assert "\n".join(scrubbed.split("\n"))  # still splits on newline
        assert "ACME CO" not in scrubbed
        assert scrubbed.count("\n") == text.count("\n")  # structure intact

    def test_control_numbers_and_counts_unchanged(self, examples_dir):
        text = _src(examples_dir).read_text()
        scrubbed, _ = scrub_text(text, load_profile(), seed="x")
        assert text.count("~") == scrubbed.count("~")
        # ISA control number (element 13) and lengths intact
        isa_before = text.split("~")[0].split("*")
        isa_after = scrubbed.split("~")[0].split("*")
        assert isa_before[13] == isa_after[13]  # interchange control number
        assert all(len(a) == len(b) for a, b in zip(isa_before, isa_after))

    def test_scrubbed_file_still_parses(self, examples_dir, tmp_path):
        text = _src(examples_dir).read_text()
        scrubbed, _ = scrub_text(text, load_profile(), seed="x")
        out = tmp_path / "s.edi"
        out.write_text(scrubbed)
        doc = parse_transaction(str(out))  # no X12ParseError
        orig = parse_transaction(str(_src(examples_dir)))
        assert len(list(doc.business_segments())) == len(list(orig.business_segments()))

    def test_envelope_off_leaves_isa(self, examples_dir):
        text = _src(examples_dir).read_text()
        prof = load_profile()
        prof.envelope = False
        scrubbed, _ = scrub_text(text, prof, seed="x")
        assert scrubbed.split("~")[0] == text.split("~")[0]  # ISA untouched

    def test_non_configured_elements_untouched(self, examples_dir):
        text = _src(examples_dir).read_text()
        scrubbed, _ = scrub_text(text, load_profile(), seed="x")
        # PO1 line and BEG po number are not in the profile
        assert "PO1*1*12*EA*8.5**UP*614141007349" in scrubbed
        assert "POPII001" in scrubbed


# ---------------------------------------------------------------------------
# qualifier gating + report
# ---------------------------------------------------------------------------


class TestQualifierAndReport:
    def test_ref_masked_only_under_dea_qualifier(self, examples_dir):
        text = _src(examples_dir).read_text()
        scrubbed, report = scrub_text(text, load_profile(), seed="x")
        assert "AB1234563" not in scrubbed  # DEA REF02 masked
        assert report.masked.get(("REF", 2)) == 1

    def test_report_counts(self, examples_dir):
        text = _src(examples_dir).read_text()
        _, report = scrub_text(text, load_profile(), seed="x")
        assert report.masked[("N1", 2)] == 2  # ST + BT names
        assert "Masked" in report.render()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_scrub_writes_default_output(self, examples_dir, tmp_path, capsys):
        src = tmp_path / "in.edi"
        src.write_text(_src(examples_dir).read_text())
        code = main(["scrub", str(src), "--seed", "s", "--report"])
        out = capsys.readouterr().out
        assert code == 0
        assert (tmp_path / "in.scrubbed.edi").exists()
        assert "Masked" in out
        assert "RIVERSIDE MARKET" not in (tmp_path / "in.scrubbed.edi").read_text()

    def test_missing_input(self, tmp_path, capsys):
        code = main(["scrub", str(tmp_path / "nope.edi")])
        assert code == 2
        assert "not found" in capsys.readouterr().err

    def test_unknown_profile(self, examples_dir, tmp_path, capsys):
        src = tmp_path / "in.edi"
        src.write_text(_src(examples_dir).read_text())
        code = main(["scrub", str(src), "--profile", "ghost"])
        assert code == 2
        assert "not found" in capsys.readouterr().err

    def test_explicit_output_is_not_overwritten(self, examples_dir, tmp_path, capsys):
        """A scrubbed file is the copy that leaves the building; replacing
        one silently is how an unmasked original travels in its place."""
        src = tmp_path / "in.edi"
        src.write_text(_src(examples_dir).read_text())
        out = tmp_path / "out.edi"
        assert main(["scrub", str(src), "-o", str(out), "--seed", "s"]) == 0
        kept = out.read_text()

        code = main(["scrub", str(src), "-o", str(out), "--seed", "other"])
        assert code == 2
        assert "already exists" in capsys.readouterr().err
        assert out.read_text() == kept

    def test_derived_default_output_is_not_overwritten(
        self, examples_dir, tmp_path, capsys
    ):
        src = tmp_path / "in.edi"
        src.write_text(_src(examples_dir).read_text())
        assert main(["scrub", str(src), "--seed", "s"]) == 0
        derived = tmp_path / "in.scrubbed.edi"
        kept = derived.read_text()

        code = main(["scrub", str(src), "--seed", "other"])
        assert code == 2
        assert "already exists" in capsys.readouterr().err
        assert derived.read_text() == kept
