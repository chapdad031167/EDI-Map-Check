#!/usr/bin/env python3
"""Regenerate the PDF twins of the synthetic guide fixtures.

The guide parser accepts .txt and text-extractable .pdf inputs; each
fixture pair must stay content-identical so tests can assert extraction
parity. The .txt files are the source of truth — this script renders
them into text PDFs (fpdf2, from the dev extra) at a width that keeps
every fixture line unwrapped, because a wrapped element row would change
what pdfplumber extracts. Form feeds in the .txt become page breaks, so
the PDF twin exercises the same page structure (headers, footers,
furniture stripping) as the text original.

Usage:
    python scripts/generate_guide_fixture.py
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "guides"
PAIRS = [
    ("acme_pharma_850_guide.txt", "acme_pharma_850_guide.pdf"),
    ("bluewater_medical_850_guide.txt", "bluewater_medical_850_guide.pdf"),
    ("northstar_components_850_guide.txt", "northstar_components_850_guide.pdf"),
]


def render(txt_name: str, pdf_name: str) -> None:
    text = (FIXTURES / txt_name).read_text(encoding="utf-8")
    pdf = FPDF(orientation="landscape", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.set_margins(left=10, top=10, right=10)
    pdf.set_font("Courier", size=9)
    for page_text in text.split("\f"):
        pdf.add_page()
        for line in page_text.splitlines():
            pdf.cell(0, 4.5, text=line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(FIXTURES / pdf_name))
    print(f"PDF fixture written to {FIXTURES / pdf_name}")


def main() -> None:
    for txt_name, pdf_name in PAIRS:
        render(txt_name, pdf_name)


if __name__ == "__main__":
    main()
