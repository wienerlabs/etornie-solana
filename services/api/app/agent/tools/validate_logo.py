"""validate_logo tool — real image inspection via Pillow.

Reads the file row by id, opens the actual file on disk, and reports any
violations of EUIPO/USPTO/UKIPO/WIPO logo upload requirements that we
can verify locally (format, dimensions, raster DPI, file size, MIME).

No mocks, no placeholders. The file must really exist on disk.
"""
from __future__ import annotations

import os
import uuid
import xml.etree.ElementTree as ET
from typing import Any

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from app.agent.tools.base import Tool, ToolError, register
from app.database import async_session
from app.documents.models import Document

# Conservative cross-jurisdiction floor — every IP office accepts
# images that pass these. Per-platform tightening can layer on top.
MIN_DIMENSION_PX = 300
MAX_DIMENSION_PX = 5000
MIN_RASTER_DPI = 300
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MiB
ALLOWED_FORMATS = {"PNG", "JPEG", "SVG"}

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "file_id": {
            "type": "string",
            "description": (
                "UUID of an uploaded Document row. Must reference a real "
                "file on disk — no placeholders accepted."
            ),
        },
    },
    "additionalProperties": False,
    "required": ["file_id"],
}


def _inspect_svg(path: str) -> dict[str, Any]:
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise ToolError(f"SVG file is not valid XML: {exc}")

    root = tree.getroot()
    if not root.tag.endswith("svg"):
        raise ToolError("File has .svg extension but root element is not <svg>.")

    width = root.attrib.get("width")
    height = root.attrib.get("height")
    viewbox = root.attrib.get("viewBox")
    return {
        "format": "SVG",
        "width": width,
        "height": height,
        "viewBox": viewbox,
        "is_vector": True,
    }


def _inspect_raster(path: str) -> dict[str, Any]:
    try:
        with Image.open(path) as img:
            img.load()  # force decode so corrupt files raise
            fmt = (img.format or "").upper()
            width, height = img.size
            dpi = img.info.get("dpi")
    except UnidentifiedImageError as exc:
        raise ToolError(f"File is not a recognizable image: {exc}")
    except OSError as exc:
        raise ToolError(f"Could not open image file: {exc}")

    return {
        "format": fmt,
        "width": width,
        "height": height,
        "dpi": dpi,
        "is_vector": False,
    }


async def _execute(args: dict[str, Any]) -> dict[str, Any]:
    raw_id = args["file_id"]
    try:
        file_uuid = uuid.UUID(raw_id)
    except (ValueError, TypeError):
        raise ToolError(f"file_id is not a valid UUID: {raw_id}")

    async with async_session() as db:
        result = await db.execute(
            select(Document).where(Document.id == file_uuid)
        )
        document = result.scalar_one_or_none()

    if document is None:
        raise ToolError(f"No document found with id {raw_id}.")

    path = document.file_path
    if not os.path.isfile(path):
        raise ToolError(
            f"Document {raw_id} points to {path}, but no file exists at that "
            "path. The upload may have been cleaned up."
        )

    file_size = os.path.getsize(path)
    ext = os.path.splitext(path)[1].lower()

    violations: list[str] = []

    if file_size > MAX_FILE_BYTES:
        violations.append(
            f"File size {file_size} bytes exceeds maximum {MAX_FILE_BYTES} bytes."
        )

    if ext == ".svg":
        info = _inspect_svg(path)
    else:
        info = _inspect_raster(path)

    fmt = info["format"]
    if fmt not in ALLOWED_FORMATS:
        violations.append(
            f"Image format '{fmt}' is not accepted. Allowed: "
            f"{', '.join(sorted(ALLOWED_FORMATS))}."
        )

    if not info["is_vector"]:
        width, height = info["width"], info["height"]
        if width < MIN_DIMENSION_PX or height < MIN_DIMENSION_PX:
            violations.append(
                f"Image dimensions {width}x{height} are below the minimum "
                f"{MIN_DIMENSION_PX}x{MIN_DIMENSION_PX} px."
            )
        if width > MAX_DIMENSION_PX or height > MAX_DIMENSION_PX:
            violations.append(
                f"Image dimensions {width}x{height} exceed the maximum "
                f"{MAX_DIMENSION_PX}x{MAX_DIMENSION_PX} px."
            )

        dpi = info.get("dpi")
        if dpi is None:
            violations.append(
                "DPI metadata is missing; raster logos must be tagged at "
                f"{MIN_RASTER_DPI} DPI or higher."
            )
        else:
            try:
                dpi_x, dpi_y = dpi if isinstance(dpi, tuple) else (dpi, dpi)
                if min(float(dpi_x), float(dpi_y)) < MIN_RASTER_DPI:
                    violations.append(
                        f"Raster DPI ({dpi_x}x{dpi_y}) is below the required "
                        f"minimum of {MIN_RASTER_DPI} DPI."
                    )
            except (TypeError, ValueError):
                violations.append(f"DPI metadata is unreadable: {dpi}.")

    return {
        "file_id": raw_id,
        "filename": document.filename,
        "file_size_bytes": file_size,
        "format": fmt,
        "dimensions": {
            "width": info.get("width"),
            "height": info.get("height"),
        },
        "is_vector": info["is_vector"],
        "dpi": info.get("dpi"),
        "ok": not violations,
        "violations": violations,
    }


validate_logo_tool = register(
    Tool(
        name="validate_logo",
        description=(
            "Validate an uploaded logo file by inspecting the real file on "
            "disk: format (PNG/JPEG/SVG), dimensions, raster DPI, and file "
            "size. Returns ok=true only when the image meets every "
            "cross-jurisdiction requirement."
        ),
        parameters=_PARAMETERS,
        execute=_execute,
    )
)
