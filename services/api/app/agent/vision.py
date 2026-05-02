"""Document vision pipeline for the agent (Together AI / Kimi K2.5).

Takes a real file on disk (image or PDF) and asks the same Together AI
LLM that powers the chat to identify the document and decide whether it
matches an expected document type. Output is a structured dict the
calling tool persists on ``agent_upload``.

PDFs are rendered to PNG pages with PyMuPDF; the first ``MAX_PDF_PAGES``
pages are sent to the model so a multi-page document does not blow up
the context. Raster/vector images go straight through.

No mocks, no placeholders — the file must exist and the call to
Together must succeed (otherwise the caller surfaces the failure to the
user as a tool error so they can retry).
"""
from __future__ import annotations

import base64
import io
import json
import logging
import mimetypes
import os
from dataclasses import dataclass
from typing import Any

import fitz  # PyMuPDF
from PIL import Image, UnidentifiedImageError
from together import AsyncTogether

from app.config import settings

logger = logging.getLogger(__name__)


# Render PDFs at 200 DPI — high enough for OCR-quality classification,
# low enough to keep base64 payloads under the model's image budget.
PDF_RENDER_DPI = 200
# Vision context budget: enough for cover/identity/excerpts, not the
# full long-form contract. The agent can ask the user for a specific
# page if it needs more.
MAX_PDF_PAGES = 4
# Hard ceiling on per-image base64 payload (3.5 MiB image-side, ≈4.7 MiB
# base64) to avoid hitting Together's 413 limit on individual messages.
MAX_IMAGE_BYTES = 3_500_000

ALLOWED_IMAGE_FORMATS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff"}


class VisionError(RuntimeError):
    """Raised when the vision pipeline cannot complete (I/O, API, decode)."""


@dataclass(frozen=True)
class DocumentVisionResult:
    """Structured findings the LLM returns about an uploaded document."""

    detected_document_type: str
    matches_expected: bool
    confidence: float
    summary: str
    key_fields: dict[str, Any]
    issues: list[str]
    raw_response: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected_document_type": self.detected_document_type,
            "matches_expected": self.matches_expected,
            "confidence": self.confidence,
            "summary": self.summary,
            "key_fields": self.key_fields,
            "issues": self.issues,
            "raw_response": self.raw_response,
        }


def _detect_kind(file_path: str, mime_type: str | None) -> str:
    """Return ``'pdf'``, ``'image'``, or raise :class:`VisionError`."""
    if mime_type:
        mt = mime_type.lower().strip()
        if mt == "application/pdf":
            return "pdf"
        if mt.startswith("image/"):
            return "image"
    ext = os.path.splitext(file_path)[1].lower().lstrip(".")
    if ext == "pdf":
        return "pdf"
    if ext in ALLOWED_IMAGE_FORMATS:
        return "image"
    guessed, _ = mimetypes.guess_type(file_path)
    if guessed == "application/pdf":
        return "pdf"
    if guessed and guessed.startswith("image/"):
        return "image"
    raise VisionError(
        f"Unsupported file type for vision validation (mime={mime_type}, ext={ext}). "
        "Supported: PDF and common raster images (png/jpg/gif/webp/bmp/tiff)."
    )


def _encode_image_bytes(data: bytes, mime_type: str) -> str:
    """Re-encode oversized images as JPEG, keep small ones as-is."""
    if len(data) <= MAX_IMAGE_BYTES:
        return f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=80, optimize=True)
            recompressed = buffer.getvalue()
    except UnidentifiedImageError as exc:
        raise VisionError(f"Could not decode image for re-compression: {exc}") from exc
    encoded = base64.b64encode(recompressed).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _load_image_data_url(file_path: str, mime_type: str | None) -> str:
    with open(file_path, "rb") as f:
        data = f.read()
    if not mime_type:
        guessed, _ = mimetypes.guess_type(file_path)
        mime_type = guessed or "image/png"
    return _encode_image_bytes(data, mime_type)


def _render_pdf_pages(file_path: str) -> list[str]:
    """Render up to MAX_PDF_PAGES pages of the PDF to base64-PNG data URLs."""
    out: list[str] = []
    try:
        doc = fitz.open(file_path)
    except Exception as exc:  # noqa: BLE001
        raise VisionError(f"Could not open PDF: {exc}") from exc
    try:
        page_count = doc.page_count
        if page_count == 0:
            raise VisionError("PDF contains no pages.")
        for index in range(min(page_count, MAX_PDF_PAGES)):
            page = doc.load_page(index)
            pix = page.get_pixmap(dpi=PDF_RENDER_DPI, alpha=False)
            png_bytes = pix.tobytes("png")
            out.append(_encode_image_bytes(png_bytes, "image/png"))
    finally:
        doc.close()
    return out


_SYSTEM_PROMPT = (
    "You are an IP filing intake reviewer. You receive one document at a time "
    "(an image, or up to four pages of a PDF rendered as images) and decide "
    "what kind of document it is and whether it matches what the user was "
    "asked to provide. You ground every claim in what is actually visible in "
    "the supplied images. You never fabricate text, signatures, dates, or "
    "stamps that are not visible. Reply with strict JSON only — no Markdown, "
    "no commentary, no code fences."
)


def _build_user_prompt(
    *,
    expected_document_type: str | None,
    original_filename: str,
    mime_type: str | None,
) -> str:
    expected_block = (
        f"The user was asked to upload: \"{expected_document_type}\".\n"
        if expected_document_type
        else "The user was not asked to upload a specific document type.\n"
    )
    return (
        f"File name: {original_filename}\n"
        f"MIME type: {mime_type or 'unknown'}\n"
        f"{expected_block}"
        "\n"
        "Inspect every page image provided and return JSON with this shape:\n"
        "{\n"
        '  "detected_document_type": string  // your label, in English,\n'
        "                                    // e.g. \"power of attorney\",\n"
        "                                    // \"national id card\", \"trade\n"
        "                                    // register gazette\", \"logo\",\n"
        "                                    // \"invoice\", \"unknown\".\n"
        '  "matches_expected": boolean       // true only when detected_document_type\n'
        "                                    // genuinely satisfies the request\n"
        "                                    // above. If no expectation was set,\n"
        "                                    // set to true unless the file is\n"
        "                                    // unreadable or off-topic.\n"
        '  "confidence": number              // 0.0 to 1.0\n'
        '  "summary": string                 // 1-3 sentences in English describing\n'
        "                                    // what the document is and what is\n"
        "                                    // visibly on it.\n"
        '  "key_fields": object              // map of human field name to visible\n'
        "                                    // value, e.g. {\"holder_name\": \"...\",\n"
        "                                    // \"issue_date\": \"...\"}. Empty object\n"
        "                                    // if nothing useful is visible.\n"
        '  "issues": [string]                // list of concrete problems for\n'
        "                                    // filing (e.g. \"page is blurry\",\n"
        "                                    // \"signature missing\", \"wrong\n"
        "                                    // jurisdiction\", \"expired\"). Empty\n"
        "                                    // list when none.\n"
        "}\n"
        "\n"
        "Return only the JSON object."
    )


def _parse_response(payload: str) -> dict[str, Any]:
    """Best-effort JSON extract from the model's reply."""
    text = (payload or "").strip()
    # Common pre/post wrappers: ```json ... ``` or stray prose.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise VisionError(f"Vision response did not contain a JSON object: {payload!r}")
    candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise VisionError(f"Vision response was not valid JSON: {exc}: {candidate!r}") from exc


def _coerce_result(parsed: dict[str, Any], raw: str) -> DocumentVisionResult:
    detected = str(parsed.get("detected_document_type", "unknown")).strip() or "unknown"
    matches = bool(parsed.get("matches_expected", False))
    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    summary = str(parsed.get("summary", "")).strip()

    key_fields_raw = parsed.get("key_fields", {})
    if isinstance(key_fields_raw, dict):
        key_fields = {str(k): key_fields_raw[k] for k in key_fields_raw}
    else:
        key_fields = {}

    issues_raw = parsed.get("issues", [])
    if isinstance(issues_raw, list):
        issues = [str(item) for item in issues_raw if str(item).strip()]
    else:
        issues = []

    return DocumentVisionResult(
        detected_document_type=detected,
        matches_expected=matches,
        confidence=confidence,
        summary=summary,
        key_fields=key_fields,
        issues=issues,
        raw_response=raw,
    )


async def classify_document(
    *,
    file_path: str,
    mime_type: str | None,
    original_filename: str,
    expected_document_type: str | None,
) -> DocumentVisionResult:
    """Run vision validation against a real file.

    Loads the file from disk (or rasterises it if PDF), forwards it to
    the configured Together vision model alongside an instruction prompt
    and the expected document type, and parses the strict JSON reply.
    """
    if not settings.together_api_key:
        raise VisionError("TOGETHER_API_KEY is not configured")
    if not os.path.isfile(file_path):
        raise VisionError(f"File not found on disk: {file_path}")

    kind = _detect_kind(file_path, mime_type)

    if kind == "image":
        image_data_urls = [_load_image_data_url(file_path, mime_type)]
    else:
        image_data_urls = _render_pdf_pages(file_path)

    if not image_data_urls:
        raise VisionError("No images extracted from the uploaded file.")

    user_text = _build_user_prompt(
        expected_document_type=expected_document_type,
        original_filename=original_filename,
        mime_type=mime_type,
    )

    user_content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    for url in image_data_urls:
        user_content.append({"type": "image_url", "image_url": {"url": url}})

    client = AsyncTogether(api_key=settings.together_api_key, timeout=180.0)
    try:
        response = await client.chat.completions.create(
            model=settings.together_agent_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
            # Kimi K2.5 spends a large share of its budget on hidden
            # reasoning tokens; 1024 was not enough to leave room for the
            # JSON answer. 4096 covers thinking + response comfortably.
            max_tokens=4096,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vision call failed: %s", exc)
        raise VisionError(f"Vision model call failed: {exc}") from exc

    if not response.choices:
        raise VisionError("Vision model returned no choices")

    msg = response.choices[0].message
    # Together AI surfaces Kimi K2.5 output in `message.reasoning` rather
    # than `message.content` for some model variants. Read whichever has
    # text — the agent orchestrator does the same fallback.
    raw = (
        getattr(msg, "content", None)
        or getattr(msg, "reasoning", None)
        or ""
    )
    if not raw.strip():
        raise VisionError("Vision model returned an empty reply")

    parsed = _parse_response(raw)
    return _coerce_result(parsed, raw)
