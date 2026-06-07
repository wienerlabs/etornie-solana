"""Tests for the OCR fallback on scanned PDFs (issue #66).

No mocks: real PDFs are generated (one with a text layer, one image-only
"scanned" page) and run through the real extraction path. The actual
Tesseract OCR assertion is skipped when the binary is not installed
(skip != mock); the OCR-disabled and text-layer paths are deterministic
and always run.
"""
import io

import pytest

from app.ai.rag import ocr
from app.ai.rag.service import _read_pdf_pages, extract_text_from_file
from app.config import settings

_SCANNED_TEXT = "SCANNED OCR TEXT 12345"


def _make_text_layer_pdf(path: str) -> None:
    """A PDF whose page carries a real text layer (no OCR needed)."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello text layer world", fontsize=14)
    doc.save(path)
    doc.close()


def _make_scanned_pdf(path: str) -> None:
    """A PDF whose only content is a rasterised image of text.

    pypdf's extract_text returns nothing for this — it needs OCR.
    """
    import fitz
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (900, 250), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default(size=48)
    except TypeError:  # older Pillow without size kwarg
        font = ImageFont.load_default()
    draw.text((30, 90), _SCANNED_TEXT, fill="black", font=font)
    buf = io.BytesIO()
    image.save(buf, format="PNG")

    doc = fitz.open()
    page = doc.new_page(width=900, height=250)
    page.insert_image(fitz.Rect(0, 0, 900, 250), stream=buf.getvalue())
    doc.save(path)
    doc.close()


class TestOcrAvailability:
    def test_disabled_in_config_means_unavailable(self) -> None:
        saved = settings.ocr_enabled
        settings.ocr_enabled = False
        try:
            assert ocr.ocr_available() is False
        finally:
            settings.ocr_enabled = saved


class TestTextLayerExtraction:
    async def test_text_layer_pdf_extracted_without_ocr(self, tmp_path) -> None:
        pdf = str(tmp_path / "text.pdf")
        _make_text_layer_pdf(pdf)
        text = await extract_text_from_file(pdf)
        assert "text layer world" in text.lower()

    def test_scanned_pdf_has_no_text_layer(self, tmp_path) -> None:
        # Sanity: the generated scanned PDF really has no text layer, so
        # OCR is the only way to recover it.
        from pypdf import PdfReader

        pdf = str(tmp_path / "scan_probe.pdf")
        _make_scanned_pdf(pdf)
        reader = PdfReader(pdf)
        raw = "".join((p.extract_text() or "") for p in reader.pages)
        assert raw.strip() == ""


class TestScannedPdfOcrDisabled:
    async def test_no_ocr_when_disabled(self, tmp_path) -> None:
        # With OCR disabled, a scanned PDF yields no extractable text.
        pdf = str(tmp_path / "scan.pdf")
        _make_scanned_pdf(pdf)
        saved = settings.ocr_enabled
        settings.ocr_enabled = False
        try:
            assert _read_pdf_pages(pdf) == []
            assert (await extract_text_from_file(pdf)).strip() == ""
        finally:
            settings.ocr_enabled = saved


@pytest.mark.skipif(
    not ocr.ocr_available(),
    reason="Tesseract binary not installed (real OCR call)",
)
class TestScannedPdfOcr:
    async def test_ocr_recovers_scanned_text(self, tmp_path) -> None:
        pdf = str(tmp_path / "scan.pdf")
        _make_scanned_pdf(pdf)
        text = await extract_text_from_file(pdf)
        assert "SCANNED" in text.upper()

    def test_ocr_pdf_pages_direct(self, tmp_path) -> None:
        pdf = str(tmp_path / "scan2.pdf")
        _make_scanned_pdf(pdf)
        result = ocr.ocr_pdf_pages(pdf, page_indices=[0])
        assert 0 in result
        assert "SCANNED" in result[0].upper()
