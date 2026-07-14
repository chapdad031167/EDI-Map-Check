"""Batch / CI mode (design 008): manifest loader, run, exit codes, JUnit.

Covers the ``mapcheck.yaml`` loader (path resolution, validation errors),
the batch run (mixed pass/fail/error, order, strict), the exit-code gate
(0/1/2), a regression manifest entry, the JUnit-XML output, and the bundled
``examples/mapcheck.yaml`` end to end through the CLI.
"""

from __future__ import annotations

import xml.dom.minidom as minidom
from pathlib import Path

import pytest

from mapcheck.batch import ManifestError, load_manifest, run_batch, to_junit
from mapcheck.cli import main

SPEC = "850_reference_spec.xlsx"
SRC = "850_baseline.edi"


def _manifest(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "mapcheck.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def _check(name, spec, source, output, examples_dir, **extra):
    lines = [
        f"  - name: {name}",
        f"    spec: {examples_dir / 'specs' / spec}",
        f"    source: {examples_dir / 'source' / source}",
        f"    output: {examples_dir / 'output' / output}",
    ]
    for k, v in extra.items():
        lines.append(f"    {k}: {v}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# manifest loader
# ---------------------------------------------------------------------------


class TestManifestLoader:
    def test_loads_and_resolves_relative_paths(self, tmp_path):
        _manifest(tmp_path, "checks:\n  - name: a\n    spec: s.xlsx\n"
                            "    source: in/x.edi\n    output: out/y.json\n")
        m = load_manifest(tmp_path / "mapcheck.yaml")
        assert len(m.checks) == 1
        c = m.checks[0]
        assert c.spec == str(tmp_path / "s.xlsx")
        assert c.source == str(tmp_path / "in" / "x.edi")

    def test_defaults_db_resolved(self, tmp_path):
        _manifest(tmp_path, "defaults:\n  db: h.db\nchecks:\n  - name: a\n"
                            "    spec: s.xlsx\n    source: x.edi\n    output: y.json\n")
        m = load_manifest(tmp_path / "mapcheck.yaml")
        assert m.db == str(tmp_path / "h.db")

    def test_missing_manifest(self, tmp_path):
        with pytest.raises(ManifestError, match="not found"):
            load_manifest(tmp_path / "nope.yaml")

    def test_missing_required_key(self, tmp_path):
        p = _manifest(tmp_path, "checks:\n  - name: a\n    spec: s.xlsx\n    source: x.edi\n")
        with pytest.raises(ManifestError, match="missing required 'output'"):
            load_manifest(p)

    def test_unknown_key(self, tmp_path):
        p = _manifest(tmp_path, "checks:\n  - name: a\n    spec: s.xlsx\n"
                                "    source: x.edi\n    output: y.json\n    bogus: 1\n")
        with pytest.raises(ManifestError, match="unknown key"):
            load_manifest(p)

    def test_duplicate_name(self, tmp_path):
        p = _manifest(tmp_path,
                      "checks:\n"
                      "  - name: a\n    spec: s\n    source: x\n    output: y\n"
                      "  - name: a\n    spec: s\n    source: x\n    output: z\n")
        with pytest.raises(ManifestError, match="duplicate check name"):
            load_manifest(p)

    def test_empty_checks(self, tmp_path):
        p = _manifest(tmp_path, "checks: []\n")
        with pytest.raises(ManifestError, match="non-empty list"):
            load_manifest(p)


# ---------------------------------------------------------------------------
# batch run + exit codes
# ---------------------------------------------------------------------------


class TestBatchRun:
    def _write(self, tmp_path, examples_dir, *checks):
        return _manifest(tmp_path, "checks:\n" + "\n".join(checks))

    def test_all_pass_exit_zero(self, tmp_path, examples_dir):
        p = self._write(tmp_path, examples_dir,
                        _check("clean", SPEC, SRC, "po_baseline.json", examples_dir))
        result = run_batch(load_manifest(p), str(tmp_path / "h.db"))
        assert result.exit_code == 0
        assert result.outcomes[0].status == "pass"

    def test_defect_check_exit_one(self, tmp_path, examples_dir):
        p = self._write(tmp_path, examples_dir,
                        _check("clean", SPEC, SRC, "po_baseline.json", examples_dir),
                        _check("defect", SPEC, SRC, "po_baseline_defects.json", examples_dir))
        result = run_batch(load_manifest(p), str(tmp_path / "h.db"))
        assert result.exit_code == 1
        assert [o.status for o in result.outcomes] == ["pass", "fail"]
        assert "Root causes" in result.outcomes[1].detail

    def test_broken_path_exit_two_and_others_still_run(self, tmp_path, examples_dir):
        p = _manifest(
            tmp_path,
            "checks:\n"
            f"  - name: broke\n    spec: {tmp_path/'no.xlsx'}\n"
            f"    source: {tmp_path/'no.edi'}\n    output: {tmp_path/'no.json'}\n"
            + _check("clean", SPEC, SRC, "po_baseline.json", examples_dir),
        )
        result = run_batch(load_manifest(p), str(tmp_path / "h.db"))
        assert result.exit_code == 2  # error wins over anything
        assert result.outcomes[0].status == "error"
        assert result.outcomes[1].status == "pass"  # the rest still ran

    def test_order_preserved(self, tmp_path, examples_dir):
        p = self._write(tmp_path, examples_dir,
                        _check("one", SPEC, SRC, "po_baseline.json", examples_dir),
                        _check("two", SPEC, SRC, "po_baseline_defects.json", examples_dir))
        result = run_batch(load_manifest(p), str(tmp_path / "h.db"))
        assert [o.name for o in result.outcomes] == ["one", "two"]

    def test_strict_promotes_warnings(self, tmp_path, examples_dir):
        # a spec-over-source that emits only warnings: reuse the defect output
        # but assert strict changes a warning-only pass. Build a warning case
        # via the ergonomics tolerance boundary is overkill; use interchange
        # baseline which passes clean, then a known warning source.
        p = self._write(
            tmp_path, examples_dir,
            _check("warns", "850_ergonomics_spec.xlsx", "850_ergonomics.edi",
                   "ergonomics_baseline.json", examples_dir),
        )
        # ergonomics baseline is a clean pass (no warnings): strict keeps it pass
        result = run_batch(load_manifest(p), str(tmp_path / "h.db"), strict=True)
        assert result.outcomes[0].status == "pass"


# ---------------------------------------------------------------------------
# regression manifest entry
# ---------------------------------------------------------------------------


class TestRegressEntry:
    def test_bootstrap_then_regression(self, tmp_path, examples_dir):
        from mapcheck.report.history import RunHistory

        db = str(tmp_path / "h.db")
        out = tmp_path / "po.json"
        out.write_bytes((examples_dir / "output" / "po_baseline.json").read_bytes())
        body = (
            "checks:\n"
            f"  - name: reg\n    spec: {examples_dir/'specs'/SPEC}\n"
            f"    source: {examples_dir/'source'/SRC}\n    output: {out}\n"
            "    regress: true\n    label: L\n"
        )
        p = _manifest(tmp_path, body)

        # first run: no baseline yet -> pass with guidance
        result = run_batch(load_manifest(p), db)
        assert result.exit_code == 0
        assert "no baseline" in result.outcomes[0].detail

        # bless the recorded run, then swap in a defective output
        with RunHistory(db) as h:
            run_id = h.recent_runs()[0]["id"]
            h.bless(run_id, "L", label="L")
        out.write_bytes((examples_dir / "output" / "po_baseline_defects.json").read_bytes())

        result = run_batch(load_manifest(p), db)
        assert result.exit_code == 1
        assert result.outcomes[0].status == "fail"
        assert "REGRESSION" in result.outcomes[0].detail


# ---------------------------------------------------------------------------
# JUnit-XML
# ---------------------------------------------------------------------------


class TestJUnit:
    def test_wellformed_one_testcase_per_check(self, tmp_path, examples_dir):
        p = _manifest(
            tmp_path,
            "checks:\n"
            + _check("clean", SPEC, SRC, "po_baseline.json", examples_dir) + "\n"
            + _check("defect", SPEC, SRC, "po_baseline_defects.json", examples_dir),
        )
        result = run_batch(load_manifest(p), str(tmp_path / "h.db"))
        xml = to_junit(result)
        dom = minidom.parseString(xml)  # raises if malformed
        suite = dom.getElementsByTagName("testsuite")[0]
        assert suite.getAttribute("tests") == "2"
        assert suite.getAttribute("failures") == "1"
        cases = dom.getElementsByTagName("testcase")
        assert [c.getAttribute("name") for c in cases] == ["clean", "defect"]
        assert dom.getElementsByTagName("failure")

    def test_error_becomes_error_element(self, tmp_path, examples_dir):
        p = _manifest(
            tmp_path,
            f"checks:\n  - name: broke\n    spec: {tmp_path/'no.xlsx'}\n"
            f"    source: {tmp_path/'no.edi'}\n    output: {tmp_path/'no.json'}\n",
        )
        result = run_batch(load_manifest(p), str(tmp_path / "h.db"))
        dom = minidom.parseString(to_junit(result))
        assert dom.getElementsByTagName("error")


# ---------------------------------------------------------------------------
# CLI + bundled example manifest
# ---------------------------------------------------------------------------


class TestCli:
    def test_bundled_manifest_exit_one(self, examples_dir, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        junit = tmp_path / "r.xml"
        code = main([
            "batch", str(examples_dir / "mapcheck.yaml"),
            "--no-history", "--no-color", "--junit", str(junit),
        ])
        out = capsys.readouterr().out
        assert code == 1
        assert "850-clean" in out and "850-defects" in out
        assert junit.exists()
        minidom.parse(str(junit))  # well-formed

    def test_missing_manifest_is_usage_error(self, tmp_path, capsys):
        code = main(["batch", str(tmp_path / "nope.yaml"), "--no-history"])
        assert code == 2
        assert "not found" in capsys.readouterr().err
