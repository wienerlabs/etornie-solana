"""Bulk case import from CSV / XML (issue #67).

Enterprise prospects arrive with hundreds of existing matters; this turns
a CSV or XML export into cases in one upload. Parsing is tolerant
(case-insensitive headers, BOM-safe) and XXE-safe (defusedxml). Each row
is validated and created inside its own savepoint, so one bad row never
sinks the rest — every row comes back in the report as created or failed
with a reason.

Recognised columns (CSV headers / XML <case> child tags or attributes):
    title*          case title
    case_type*      trademark | patent | design | copyright
    jurisdiction    free text (e.g. "DE", "European Union")
    nice_classes    comma-separated, e.g. "25,35"
    filing_date     ISO date (YYYY-MM-DD)
    deadline        ISO date (YYYY-MM-DD)
    description     free text
    client_email    links to a registered user; otherwise used as guest email
    client_name     guest client name (when client_email is unregistered)
    client_wallet   Solana pubkey to bind as the on-chain client
(* required)
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import get_user_by_email
from app.cases.models import CaseType
from app.cases.service import create_case

_VALID_CASE_TYPES = {t.value for t in CaseType}

# Map many real-world column headers onto our canonical fields. Keys are
# header names after lower-casing and collapsing ``_``/``-``/space to a
# single space, so "Mark Text", "mark_text" and "mark-text" all match.
# The canonical names map to themselves (e.g. "case type" -> case_type).
_HEADER_ALIASES: dict[str, str] = {
    # title
    "title": "title", "name": "title", "mark": "title",
    "mark text": "title", "mark name": "title", "trademark": "title",
    "trade mark": "title", "trademark name": "title", "brand": "title",
    "matter": "title", "matter name": "title", "case title": "title",
    "case name": "title", "ip name": "title",
    # case_type
    "case type": "case_type", "type": "case_type", "ip type": "case_type",
    "matter type": "case_type", "category": "case_type",
    "rights type": "case_type", "right type": "case_type", "kind": "case_type",
    # jurisdiction
    "jurisdiction": "jurisdiction", "country": "jurisdiction",
    "territory": "jurisdiction", "region": "jurisdiction",
    "office": "jurisdiction", "country code": "jurisdiction",
    "ipo": "jurisdiction",
    # nice_classes
    "nice classes": "nice_classes", "nice": "nice_classes",
    "classes": "nice_classes", "class": "nice_classes",
    "nice class": "nice_classes", "classification": "nice_classes",
    # filing_date
    "filing date": "filing_date", "filed": "filing_date",
    "filing": "filing_date", "application date": "filing_date",
    "date filed": "filing_date", "filed date": "filing_date",
    # deadline
    "deadline": "deadline", "due": "deadline", "due date": "deadline",
    "renewal date": "deadline", "renewal": "deadline", "expiry": "deadline",
    "expiration": "deadline", "next deadline": "deadline",
    # description
    "description": "description", "notes": "description", "note": "description",
    "remarks": "description", "details": "description", "comment": "description",
    "comments": "description",
    # client_email
    "client email": "client_email", "email": "client_email",
    "owner email": "client_email", "applicant email": "client_email",
    "contact email": "client_email", "e mail": "client_email",
    # client_name
    "client name": "client_name", "client": "client_name",
    "owner": "client_name", "applicant": "client_name", "holder": "client_name",
    "proprietor": "client_name", "owner name": "client_name",
    "applicant name": "client_name", "company": "client_name",
    # client_wallet
    "client wallet": "client_wallet", "wallet": "client_wallet",
    "wallet address": "client_wallet", "pubkey": "client_wallet",
    "solana wallet": "client_wallet",
}

# Common case_type values seen in exports -> our enum value.
_CASE_TYPE_ALIASES: dict[str, str] = {
    "tm": "trademark", "trade mark": "trademark", "trademark": "trademark",
    "mark": "trademark", "word mark": "trademark", "wordmark": "trademark",
    "pat": "patent", "patent": "patent", "utility patent": "patent",
    "design": "design", "registered design": "design", "design patent": "design",
    "copyright": "copyright", "©": "copyright",
}


def _canon_header(key: Any) -> str | None:
    k = str(key).strip().lower().replace("_", " ").replace("-", " ")
    k = " ".join(k.split())
    return _HEADER_ALIASES.get(k)


class BulkImportParseError(ValueError):
    """The uploaded file could not be parsed into rows."""


@dataclass
class RowResult:
    row: int
    status: str  # "created" | "failed"
    case_id: str | None = None
    case_number: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _normalise(row: dict[str, Any]) -> dict[str, str]:
    """Map known headers (incl. aliases) to canonical fields, strip
    values, and drop unknown/empty columns."""
    out: dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            continue
        canon = _canon_header(key)
        if canon is None:
            continue
        v = "" if value is None else str(value).strip()
        if v and canon not in out:
            out[canon] = v
    return out


def parse_csv(content: bytes) -> list[dict[str, str]]:
    try:
        text = content.decode("utf-8-sig")  # tolerate a BOM
    except UnicodeDecodeError as exc:
        raise BulkImportParseError(
            "CSV is not valid UTF-8 text."
        ) from exc
    # Auto-detect the delimiter so European exports (semicolon) and
    # tab/pipe-separated files parse without manual conversion.
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if reader.fieldnames is None:
        raise BulkImportParseError("CSV has no header row.")
    return [_normalise(row) for row in reader]


def parse_xml(content: bytes) -> list[dict[str, str]]:
    from defusedxml.ElementTree import fromstring

    try:
        root = fromstring(content)
    except Exception as exc:  # noqa: BLE001 — any parse failure is user error
        raise BulkImportParseError(f"Invalid XML: {exc}") from exc

    rows: list[dict[str, str]] = []
    # Accept either a single <case> root, <case> elements anywhere under
    # the root, or (as a fallback) the root's direct children.
    if root.tag.lower() == "case":
        elements = [root]
    else:
        elements = root.findall(".//case") or list(root)
    for case_el in elements:
        raw: dict[str, Any] = {}
        for child in case_el:
            raw[child.tag] = (child.text or "")
        for attr_key, attr_val in case_el.attrib.items():
            raw.setdefault(attr_key, attr_val)
        rows.append(_normalise(raw))
    return rows


def parse_upload(filename: str, content: bytes) -> list[dict[str, str]]:
    name = (filename or "").lower()
    if name.endswith(".csv"):
        return parse_csv(content)
    if name.endswith(".xml"):
        return parse_xml(content)
    raise BulkImportParseError(
        "Unsupported file type — upload a .csv or .xml file."
    )


# ---------------------------------------------------------------------------
# Row -> case
# ---------------------------------------------------------------------------


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"{field} '{value}' is not a valid ISO date (YYYY-MM-DD)."
        ) from exc


async def _row_to_kwargs(
    db: AsyncSession,
    row: dict[str, str],
    default_case_type: str | None = None,
) -> dict[str, Any]:
    """Validate one row and build create_case kwargs (raises ValueError).

    ``default_case_type`` applies to rows whose file carries no type
    column (e.g. a trademark-only portfolio export).
    """
    title = row.get("title")
    if not title:
        raise ValueError("title is required.")

    raw_type = (row.get("case_type") or default_case_type or "").strip().lower()
    case_type = _CASE_TYPE_ALIASES.get(raw_type, raw_type)
    if case_type not in _VALID_CASE_TYPES:
        raise ValueError(
            f"case_type must be one of {sorted(_VALID_CASE_TYPES)}; "
            f"got '{row.get('case_type', '')}'. Tip: set a default type "
            "for the whole file if it has no type column."
        )

    kwargs: dict[str, Any] = {
        "title": title,
        "case_type": CaseType(case_type),
        "description": row.get("description"),
        "jurisdiction": row.get("jurisdiction"),
        "nice_classes": row.get("nice_classes"),
    }
    if "filing_date" in row:
        kwargs["filing_date"] = _parse_date(row["filing_date"], "filing_date")
    if "deadline" in row:
        kwargs["deadline"] = _parse_date(row["deadline"], "deadline")

    # Client resolution: a registered email links the case to that user;
    # an unregistered email becomes a guest contact; a wallet binds the
    # on-chain client. All optional — an unassigned imported matter is
    # valid and can be assigned later.
    client_email = row.get("client_email")
    if client_email:
        user = await get_user_by_email(db, client_email)
        if user is not None:
            kwargs["client_id"] = user.id
        else:
            kwargs["guest_client_email"] = client_email
            kwargs["guest_client_name"] = row.get("client_name") or client_email
    elif row.get("client_name"):
        kwargs["guest_client_name"] = row["client_name"]
    if row.get("client_wallet"):
        kwargs["client_wallet"] = row["client_wallet"]

    return kwargs


async def import_cases(
    db: AsyncSession,
    rows: list[dict[str, str]],
    default_case_type: str | None = None,
) -> list[RowResult]:
    """Create a case per row inside a savepoint; report each outcome.

    Row numbering is 1-based and counts data rows (the CSV header is not
    a row). A failing row is rolled back to its savepoint and recorded;
    successful rows persist when the caller commits. ``default_case_type``
    fills in rows whose file has no type column.
    """
    results: list[RowResult] = []
    for index, row in enumerate(rows, start=1):
        try:
            kwargs = await _row_to_kwargs(db, row, default_case_type)
            async with db.begin_nested():
                case = await create_case(db, **kwargs)
            results.append(
                RowResult(
                    row=index,
                    status="created",
                    case_id=str(case.id),
                    case_number=case.case_number,
                )
            )
        except Exception as exc:  # noqa: BLE001 — per-row isolation
            results.append(
                RowResult(row=index, status="failed", error=str(exc))
            )
    return results
