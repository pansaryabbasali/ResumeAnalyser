"""PDF text extraction against real corpus files — offline, no network."""

import harness
import pytest

from resume_analyzer import pdfio


def test_extracts_known_strings_from_classic_layout() -> None:
    text = pdfio.extract_text(
        harness.DATASET_DIR / "resumes/HOY-2026-011/Karthik_Raghavan_Resume_2026.pdf"
    )
    assert "Aurus Pay Technologies" in text
    assert "karthik.raghavan89@gmail.com" in text
    # PDF text layers wrap mid-phrase ("... Notice\nperiod: 30 days.") — anything
    # asserting on multi-word phrases must normalize whitespace first, and the
    # LLM extraction prompt has to cope with the same wrapping.
    assert "Notice period: 30 days" in " ".join(text.split())


def test_extracts_traditional_cv_blocks() -> None:
    text = pdfio.extract_text(
        harness.DATASET_DIR / "resumes/HOY-2026-014/Suresh_Gowda_CV_2026.pdf"
    )
    assert "suresh.gowda.ops@yahoo.co.in" in text
    assert "Declaration" in text
    assert "14-06-1991" in text


def test_empty_pdf_is_an_error(tmp_path) -> None:
    import pdfplumber.utils  # noqa: F401  (ensures pdfplumber importable before writing junk)

    blank = tmp_path / "blank.pdf"
    # Minimal valid single-page PDF with no text layer.
    blank.write_bytes(
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF"
    )
    with pytest.raises(pdfio.EmptyPdfError):
        pdfio.extract_text(blank)
