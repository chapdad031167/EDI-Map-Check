"""Design 013 guards: tokens, verdict strip, findings table, copy rules.

These tests pin the measurable parts of the interface identity so drift
fails loudly: WCAG contrast of the text tokens, the verdict strip's
readout format, dot-plus-word status cells (never color alone), escaped
HTML, offline fonts with no CDN reference anywhere, and the copy rules
(no emoji, no exclamation points in UI strings).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pandas as pd

import app
from mapcheck.engine.results import Status

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Tokens: every text token reads at WCAG AA (4.5:1) on both surfaces
# ---------------------------------------------------------------------------


def _luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


class TestTokens:
    def test_text_tokens_meet_wcag_aa_on_both_surfaces(self):
        for token in ("ink", "petrol", "pass", "fail", "warn", "slate"):
            for surface in ("paper", "panel"):
                ratio = _contrast(app.TOKENS[token], app.TOKENS[surface])
                assert ratio >= 4.5, f"{token} on {surface}: {ratio:.2f}:1"

    def test_tokens_match_streamlit_theme(self):
        config = (REPO / ".streamlit" / "config.toml").read_text(encoding="utf-8")
        assert f'backgroundColor = "{app.TOKENS["paper"]}"' in config
        assert f'secondaryBackgroundColor = "{app.TOKENS["panel"]}"' in config
        assert f'textColor = "{app.TOKENS["ink"]}"' in config
        assert f'primaryColor = "{app.TOKENS["petrol"]}"' in config


# ---------------------------------------------------------------------------
# Verdict strip
# ---------------------------------------------------------------------------


class TestVerdictStrip:
    COUNTS = {
        Status.PASS: 29,
        Status.FAIL: 15,
        Status.WARNING: 2,
        Status.NOT_TESTED: 0,
    }

    def test_readout_format(self):
        strip = app.render_verdict_strip(self.COUNTS, Status.FAIL)
        assert "29 PASS / 15 FAIL / 2 WARNING / 0 NOT TESTED" in strip
        assert "RESULT: FAIL" in strip

    def test_result_carries_tone_class(self):
        assert "verdict-fail" in app.render_verdict_strip(self.COUNTS, Status.FAIL)
        assert "verdict-pass" in app.render_verdict_strip(self.COUNTS, Status.PASS)
        assert "verdict-warning" in app.render_verdict_strip(
            self.COUNTS, Status.WARNING
        )


# ---------------------------------------------------------------------------
# Findings table
# ---------------------------------------------------------------------------


def _frame(**overrides) -> pd.DataFrame:
    row = {
        "Status": "FAIL",
        "Row ID": "M-004",
        "Source": "BEG03",
        "Target": "order.po_number",
        "Expected": "PO4400021",
        "Actual": "PO4400012",
        "Category": "value_mismatch",
        "Message": "expected 'PO4400021', output has 'PO4400012'",
    }
    row.update(overrides)
    return pd.DataFrame([row])


class TestFindingsTable:
    def test_status_cell_is_dot_plus_word(self):
        html_out = app.findings_table_html(_frame())
        assert '<span class="status-dot"></span>FAIL' in html_out
        assert "status-fail" in html_out

    def test_x12_reference_columns_are_mono(self):
        html_out = app.findings_table_html(_frame())
        # Row ID, Source, Target, Expected, Actual, Category all render mono.
        assert html_out.count('<td class="mono">') == 5 + 1  # 5 refs + category

    def test_cells_are_escaped(self):
        html_out = app.findings_table_html(
            _frame(Message="<script>alert('x')</script>")
        )
        assert "<script>" not in html_out
        assert "&lt;script&gt;" in html_out

    def test_every_status_has_a_class(self):
        for status, cls in app._STATUS_CLASS.items():
            html_out = app.findings_table_html(_frame(Status=status))
            assert cls in html_out


# ---------------------------------------------------------------------------
# Copy rules and offline fonts
# ---------------------------------------------------------------------------

_EMOJI = re.compile(
    "[\U0001f000-\U0001ffff☀-➿⬀-⯿️✅❌⚠]"
)


class TestCopyRules:
    def _ui_strings(self) -> list[str]:
        tree = ast.parse((REPO / "app.py").read_text(encoding="utf-8"))
        return [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]

    def test_no_exclamation_points_in_ui_strings(self):
        offenders = [s for s in self._ui_strings() if "!" in s]
        assert offenders == []

    def test_no_emoji_in_ui_strings(self):
        offenders = [s for s in self._ui_strings() if _EMOJI.search(s)]
        assert offenders == []


class TestOfflineFonts:
    FILES = [
        "IBMPlexSans-Regular.woff2",
        "IBMPlexSans-SemiBold.woff2",
        "IBMPlexMono-Regular.woff2",
        "IBMPlexMono-Medium.woff2",
    ]

    def test_fonts_bundled_in_both_locations(self):
        for name in self.FILES:
            for root in ("assets/fonts", "static/fonts"):
                path = REPO / root / name
                assert path.exists(), f"missing {path}"
                assert path.read_bytes()[:4] == b"wOF2", f"not woff2: {path}"

    def test_font_license_bundled(self):
        license_text = (REPO / "assets" / "fonts" / "LICENSE.txt").read_text(
            encoding="utf-8"
        )
        assert "SIL Open Font License" in license_text

    def test_zero_cdn_references(self):
        config = (REPO / ".streamlit" / "config.toml").read_text(encoding="utf-8")
        css = (REPO / "assets" / "styles.css").read_text(encoding="utf-8")
        for text, where in ((config, "config.toml"), (css, "styles.css")):
            assert "http://" not in text and "https://" not in text, where
            assert "fonts.googleapis" not in text, where
        # every declared font face is served from the app's own static dir
        for url in re.findall(r'url = "([^"]+)"', config):
            assert url.startswith("app/static/fonts/"), url
