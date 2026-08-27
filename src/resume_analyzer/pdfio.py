"""PDF-to-text extraction (M3).

pdfplumber pulls the text layer page by page; pages are joined with newlines.
Resumes in this corpus are text-based PDFs (no OCR path — a documented scope
cut in the build plan). An empty result is an error: it means the PDF has no
text layer, and silently returning "" would surface later as a mysterious
0-fact extraction instead of a clear failure at the source.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber


class EmptyPdfError(ValueError):
    """The PDF produced no extractable text (likely scanned/image-only)."""


def extract_text(pdf_path: str | Path) -> str:
    """Return the full text of a PDF, pages joined by newlines."""
    pages: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    text = "\n".join(pages).strip()
    if not text:
        raise EmptyPdfError(f"no text layer in {pdf_path}")
    return text
