"""Partner overrides (design 005): base spec + per-partner delta merge.

Covers the delta loader (REMOVE), merge semantics (add / replace / remove /
remove-absent warning / code-list shadow), the meta guards, origin
provenance on rules and findings, the merged-spec export round-trip, and
the base-vs-ACME-vs-GLOBEX reference scenario.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapcheck.engine import Category, Status, validate_files
from mapcheck.spec.overrides import (
    export_spec,
    load_delta,
    merge_specs,
    resolve_spec,
)
from mapcheck.spec.parser import SpecLoadError, load_spec

BASE = "partner_base_spec.xlsx"
ACME = "partner_acme_delta.xlsx"
GLOBEX = "partner_globex_delta.xlsx"


def _spec(examples_dir: Path, name: str) -> str:
    return str(examples_dir / "specs" / name)


def _rule(spec, row_id):
    return next((r for r in spec.rules if r.row_id == row_id), None)


# ---------------------------------------------------------------------------
# delta loading
# ---------------------------------------------------------------------------


class TestDeltaLoader:
    def test_acme_delta(self, examples_dir):
        delta = load_delta(_spec(examples_dir, ACME))
        assert {r.row_id for r in delta.rules} == {"P-002", "P-100"}
        assert delta.removals == []
        assert delta.label == "partner:acme"
        assert "UOM" in delta.code_lists

    def test_globex_delta_remove(self, examples_dir):
        delta = load_delta(_spec(examples_dir, GLOBEX))
        assert delta.removals == ["P-004"]
        assert {r.row_id for r in delta.rules} == {"P-200"}
        assert delta.label == "partner:globex"


# ---------------------------------------------------------------------------
# merge semantics
# ---------------------------------------------------------------------------


class TestMerge:
    def test_replace_add_shadow(self, examples_dir):
        merged, warnings = resolve_spec(_spec(examples_dir, BASE), _spec(examples_dir, ACME))
        assert warnings == []
        # replace keeps position, changes content + origin
        p002 = _rule(merged, "P-002")
        assert p002.origin == "partner:acme"
        assert p002.condition.raw == "N103 = '91'"
        # add appends with origin
        p100 = _rule(merged, "P-100")
        assert p100 is not None and p100.origin == "partner:acme"
        # untouched base rule keeps base origin
        assert _rule(merged, "P-001").origin == "base"
        # code-list shadow: ACME's UOM (3 entries incl DOZEN) replaces base's
        assert "DZ" in merged.code_lists["UOM"].entries

    def test_remove(self, examples_dir):
        merged, warnings = resolve_spec(_spec(examples_dir, BASE), _spec(examples_dir, GLOBEX))
        assert warnings == []
        assert _rule(merged, "P-004") is None  # removed
        assert _rule(merged, "P-200").origin == "partner:globex"  # added

    def test_remove_of_absent_warns(self, examples_dir, tmp_path):
        base = load_spec(_spec(examples_dir, BASE))
        from mapcheck.spec.template import build_template

        wb = build_template()
        wb["Mapping"].append(
            ["Z-999", "", "", "", "REMOVE", "", "", "", "", "", "", "", "", "gone"]
        )
        wb["Meta"].cell(row=2, column=2, value="850")
        p = tmp_path / "d.xlsx"
        wb.save(p)
        merged, warnings = merge_specs(base, load_delta(p))
        assert any("Z-999" in w for w in warnings)
        assert len(merged.rules) == len(base.rules)  # nothing removed

    def test_direction_mismatch_errors(self, examples_dir, tmp_path):
        base = load_spec(_spec(examples_dir, BASE))  # inbound
        from mapcheck.spec.template import build_template

        wb = build_template(direction="outbound")
        wb["Mapping"].append(
            ["P-001", "order.po", "", "BEG03", "DIRECT", "", "", "", "", "", "", "string", "", ""]
        )
        wb["Meta"].cell(row=2, column=2, value="850")
        p = tmp_path / "out.xlsx"
        wb.save(p)
        with pytest.raises(SpecLoadError, match="direction"):
            merge_specs(base, load_delta(p))

    def test_transaction_set_mismatch_errors(self, examples_dir, tmp_path):
        base = load_spec(_spec(examples_dir, BASE))  # 850
        from mapcheck.spec.template import build_template

        wb = build_template()
        wb["Mapping"].append(
            ["P-001", "BAK03", "", "order.po", "DIRECT", "", "", "", "", "", "", "string", "", ""]
        )
        wb["Meta"].cell(row=2, column=2, value="855")
        p = tmp_path / "855.xlsx"
        wb.save(p)
        with pytest.raises(SpecLoadError, match="transaction set"):
            merge_specs(base, load_delta(p))


# ---------------------------------------------------------------------------
# merged-spec export round-trip
# ---------------------------------------------------------------------------


class TestExportRoundTrip:
    def test_effective_spec_loads_with_origins(self, examples_dir, tmp_path):
        merged, _ = resolve_spec(_spec(examples_dir, BASE), _spec(examples_dir, ACME))
        out = export_spec(merged, tmp_path / "effective.xlsx")
        reloaded = load_spec(out)
        # same rules survive
        assert {r.row_id for r in reloaded.rules} == {r.row_id for r in merged.rules}
        # origin recorded in Notes so the sheet is auditable
        p100 = _rule(reloaded, "P-100")
        assert "partner:acme" in (p100.notes or "")


# ---------------------------------------------------------------------------
# reference scenario: base vs ACME vs GLOBEX
# ---------------------------------------------------------------------------


def _run(examples_dir, delta=None):
    return validate_files(
        _spec(examples_dir, BASE),
        str(examples_dir / "source" / "850_partner.edi"),
        str(examples_dir / "output" / "partner_order.json"),
        spec=(resolve_spec(_spec(examples_dir, BASE), _spec(examples_dir, delta))[0]
              if delta else None),
    )


class TestScenario:
    def test_base_is_clean_pass(self, examples_dir):
        result = _run(examples_dir)
        assert result.overall is Status.PASS
        assert result.counts[Status.FAIL] == 0
        assert result.counts[Status.WARNING] == 0

    def test_acme_override_failures_are_tagged(self, examples_dir):
        result = _run(examples_dir, ACME)
        by_row = {f.row_id: f for f in result.findings if f.status is Status.FAIL}
        # replaced rule: qualifier 91 not sent, so the ACME condition is false
        # and the still-present ship_to.id is a condition-logic failure
        assert by_row["P-002"].category is Category.CONDITION_LOGIC
        assert by_row["P-002"].origin == "partner:acme"
        assert by_row["P-002"].actual == "118"
        # added rule: hardcoded channel missing from output
        assert by_row["P-100"].category is Category.CONSTANT_DEFAULT
        assert by_row["P-100"].origin == "partner:acme"

    def test_globex_removal_and_tagged_add(self, examples_dir):
        result = _run(examples_dir, GLOBEX)
        # the removed promo rule means order.promo is now unmapped output
        unmapped = [f for f in result.findings if f.category is Category.UNMAPPED_TARGET]
        assert any("promo" in f.target for f in unmapped)
        # the added constant fails, tagged to GLOBEX
        p200 = next(f for f in result.findings if f.row_id == "P-200")
        assert p200.origin == "partner:globex"
        assert p200.category is Category.CONSTANT_DEFAULT

    def test_base_rules_stay_base_origin(self, examples_dir):
        result = _run(examples_dir, ACME)
        base_pass = [f for f in result.findings if f.row_id == "P-001"]
        assert base_pass and base_pass[0].origin == "base"
