"""End-to-end scenarios for the declarative IDoc definitions (design 003).

810 -> INVOIC02 and 856 -> DESADV01, each output in both flat and XML.
Baselines pass clean in both formats; defect files plant defects across
rule categories; the flat and XML renditions must produce identical
findings — the same guarantee the ORDERS05 scenario pins.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapcheck.engine import Category, RunResult, Status, validate_files

SCENARIOS = {
    "invoic02": ("invoic02_reference_spec.xlsx", "810_sap.edi", "invoic02"),
    "desadv01": ("desadv01_reference_spec.xlsx", "856_sap.edi", "desadv01"),
}


def _run(examples_dir: Path, spec: str, source: str, output: str) -> RunResult:
    return validate_files(
        str(examples_dir / "specs" / spec),
        str(examples_dir / "source" / source),
        str(examples_dir / "output" / output),
    )


def _fingerprint(result: RunResult):
    return [
        (f.row_id, f.status, f.category, f.target, f.expected, f.actual)
        for f in result.findings
    ]


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
@pytest.mark.parametrize("ext", ["txt", "xml"])
def test_baseline_clean(examples_dir, scenario, ext):
    spec, source, stem = SCENARIOS[scenario]
    result = _run(examples_dir, spec, source, f"{stem}_baseline.{ext}")
    assert result.overall is Status.PASS
    counts = result.counts
    assert counts[Status.FAIL] == 0
    assert counts[Status.WARNING] == 0
    assert counts[Status.NOT_TESTED] == 0


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
@pytest.mark.parametrize("kind", ["baseline", "defects"])
def test_flat_and_xml_identical_findings(examples_dir, scenario, kind):
    spec, source, stem = SCENARIOS[scenario]
    flat = _run(examples_dir, spec, source, f"{stem}_{kind}.txt")
    xml = _run(examples_dir, spec, source, f"{stem}_{kind}.xml")
    assert _fingerprint(flat) == _fingerprint(xml)
    assert flat.overall is xml.overall


@pytest.fixture(scope="module", params=["txt", "xml"])
def invoic02_result(examples_dir, request):
    return _run(examples_dir, "invoic02_reference_spec.xlsx", "810_sap.edi",
                f"invoic02_defects.{request.param}")


@pytest.fixture(scope="module", params=["txt", "xml"])
def desadv01_result(examples_dir, request):
    return _run(examples_dir, "desadv01_reference_spec.xlsx", "856_sap.edi",
                f"desadv01_defects.{request.param}")


class TestInvoic02Defects:
    @pytest.fixture()
    def result(self, invoic02_result):
        return invoic02_result

    def test_categories(self, result):
        cats = result.category_counts
        for cat in (Category.VALUE_MISMATCH, Category.CONDITION_LOGIC,
                    Category.CONSTANT_DEFAULT, Category.CODE_TRANSLATION,
                    Category.FORMAT, Category.COUNT_MISMATCH,
                    Category.MISSING_OUTPUT, Category.UNMAPPED_TARGET):
            assert cat in cats, cat

    def test_invoice_number_mismatch(self, result):
        f = next(f for f in result.findings if f.row_id == "V-001")
        assert f.category is Category.VALUE_MISMATCH
        assert (f.expected, f.actual) == ("INV5001", "INV5009")

    def test_untranslated_uom(self, result):
        f = next(f for f in result.findings
                 if f.row_id == "V-008" and f.target == "lines[0].menee")
        assert f.category is Category.CODE_TRANSLATION
        assert (f.expected, f.actual) == ("ST", "EA")

    def test_stray_ref_unmapped(self, result):
        f = next(f for f in result.findings if f.category is Category.UNMAPPED_TARGET)
        assert "refs.012" in f.target


class TestDesadv01Defects:
    @pytest.fixture()
    def result(self, desadv01_result):
        return desadv01_result

    def test_categories(self, result):
        cats = result.category_counts
        for cat in (Category.VALUE_MISMATCH, Category.FORMAT,
                    Category.CODE_TRANSLATION, Category.COUNT_MISMATCH,
                    Category.MISSING_OUTPUT, Category.UNMAPPED_TARGET):
            assert cat in cats, cat

    def test_asn_number_mismatch(self, result):
        f = next(f for f in result.findings if f.row_id == "D-001")
        assert f.category is Category.VALUE_MISMATCH
        assert (f.expected, f.actual) == ("SHIP0001", "SHIP9999")

    def test_po_number_from_hl_ancestor(self, result):
        # baseline proves it works; here the dropped 2nd item makes it missing
        f = next(f for f in result.findings
                 if f.row_id == "D-008" and "lines[1]" in f.target)
        assert f.category is Category.MISSING_OUTPUT

    def test_dropped_item_count(self, result):
        f = next(f for f in result.findings if f.category is Category.COUNT_MISMATCH)
        assert (f.expected, f.actual) == ("2", "1")


class TestUserDelimitedFormat:
    def test_onboarded_with_zero_python(self, examples_dir):
        # register the external YAML and validate a delimited staging file
        from mapcheck.output.idoc import register_output_definition

        defn = register_output_definition(
            examples_dir / "formats" / "acme_order_csv.yaml"
        )
        result = validate_files(
            str(examples_dir / "specs" / "usercsv_reference_spec.xlsx"),
            str(examples_dir / "source" / "850_usercsv.edi"),
            str(examples_dir / "output" / "order_staging.csv"),
            output_format=defn.format,
        )
        assert result.overall is Status.PASS
        assert result.counts[Status.FAIL] == 0
        assert result.counts[Status.WARNING] == 0


class TestDesadv01Baseline:
    def test_po_number_read_via_hl_ancestor(self, examples_dir):
        # the item-level rule D-008 reads PRF01 from the order-level ancestor
        result = _run(examples_dir, "desadv01_reference_spec.xlsx", "856_sap.edi",
                      "desadv01_baseline.txt")
        assert result.overall is Status.PASS
        # both lines carry the PO number folded from the shared order loop
        from mapcheck.output import load_output
        out = load_output(examples_dir / "output" / "desadv01_baseline.txt")
        assert out.get("lines[].refs.001.bstnr", 0) == "PO7700001"
        assert out.get("lines[].refs.001.bstnr", 1) == "PO7700001"
