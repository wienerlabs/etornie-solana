"""OCR fallback for scanned PDFs (issue #66).

When a PDF page carries no text layer (a scanned filing), pypdf's
``extract_text`` returns nothing and the page never makes it into the
RAG index. This module renders such pages with PyMuPDF and runs
Tesseract over the image so the text becomes searchable.

OCR is local (no third party) — confidential filings never leave the
server. It is best-effort: if the ``tesseract`` binary is not installed
(or OCR is disabled in config), :func:`ocr_available` returns False and
callers fall back to text-layer extraction only.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from functools import lru_cache

from app.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _tesseract_on_path() -> bool:
    return shutil.which("tesseract") is not None


def ocr_available() -> bool:
    """True when OCR is enabled in config and usable on this host."""
    if not settings.ocr_enabled:
        return False
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return _tesseract_on_path()


def ocr_pdf_pages(
    file_path: str, page_indices: list[int] | None = None
) -> dict[int, str]:
    """OCR the given PDF pages; return ``{page_index: text}`` for hits.

    Renders each page to an image with PyMuPDF at ``settings.ocr_dpi`` and
    runs Tesseract. Pages that yield no text are omitted. Raises only on a
    catastrophic open failure; per-page errors are logged and skipped so
    one bad page never sinks the whole document.
    """
    import fitz  # PyMuPDF
    import pytesseract

    results: dict[int, str] = {}
    doc = fitz.open(file_path)
    try:
        indices = (
            page_indices
            if page_indices is not None
            else list(range(doc.page_count))
        )
        for index in indices:
            if index < 0 or index >= doc.page_count:
                continue
            try:
                page = doc.load_page(index)
                pix = page.get_pixmap(dpi=settings.ocr_dpi)
                # Pass a rendered PNG file PATH to Tesseract rather than a
                # PIL image object: some Pillow builds make pytesseract
                # misread the image stream and raise UnicodeDecodeError.
                tmp = tempfile.NamedTemporaryFile(
                    suffix=".png", delete=False
                )
                try:
                    tmp.write(pix.tobytes("png"))
                    tmp.close()
                    text = pytesseract.image_to_string(
                        tmp.name, lang=settings.ocr_languages
                    )
                finally:
                    try:
                        os.unlink(tmp.name)
                    except OSError:
                        pass
            except Exception:  # noqa: BLE001
                logger.warning(
                    "OCR failed on page %d of %s", index, file_path
                )
                continue
            cleaned = (text or "").replace("\x00", "").strip()
            if cleaned:
                results[index] = cleaned
    finally:
        doc.close()
    return results
