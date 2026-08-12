#!/usr/bin/env python3
"""Regenerate the PDF twin of the synthetic guide fixture.

The guide parser accepts .txt and text-extractable .pdf inputs; the two
fixtures must stay content-identical so tests can assert extraction
parity. The .txt file is the source of truth — this script renders it
into a text PDF (fpdf2, from the dev extra) at a width that keeps every
fixture line unwrapped, because a wrapped element row would change what
pdfplumber extracts.

Usage:
    python scripts/generate_guide_fixture.py
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "guides"
TXT = FIXTURES / "acme_pharma_850_guide.txt"
PDF = FIXTURES / "acme_pharma_850_guide.pdf"


def main() -> None:
    text = TXT.read_text(encoding="utf-8")
    pdf = FPDF(orientation="landscape", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.set_margins(left=10, top=10, right=10)
    pdf.add_page()
    pdf.set_font("Courier", size=9)
    for line in text.splitlines():
        pdf.cell(0, 4.5, text=line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(PDF))
    print(f"PDF fixture written to {PDF}")


if __name__ == "__main__":
    main()
