"""Seed required_document_templates from countries_parsed.json.

Usage:
    python -m scripts.seed_required_documents [path_to_json]

Defaults to the bundled services/api/data/countries_parsed.json.
"""

import asyncio
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, engine

# Import all models to register them with SQLAlchemy
from app.users.models import User  # noqa: F401
from app.cases.models import Case, CaseNote  # noqa: F401
from app.documents.models import Document  # noqa: F401
from app.ai.rag.models import DocumentChunk  # noqa: F401
from app.notifications.models import Notification  # noqa: F401
from app.required_documents.models import RequiredDocumentTemplate, CaseRequiredDocument  # noqa: F401


def fix_encoding(text: str) -> str:
    """Fix double-encoded UTF-8 strings."""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


def parse_country_data(json_path: str) -> list[dict]:
    """Parse JSON and extract countries with required documents."""
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    templates = []
    for entry in data:
        required_docs = entry.get("required_documents")
        if not required_docs:
            continue

        country_code = entry.get("country_code")
        if not country_code:
            continue

        # Skip entries where country_code is not a real code
        if len(country_code) > 10 or "EUTM" in country_code or "WIPO" in country_code:
            continue

        required_docs = fix_encoding(required_docs)
        country = fix_encoding(entry.get("country", ""))

        # Parse description from the required_documents field
        # Format: "Document Name (Approval Type)"
        doc_name = required_docs.strip()
        description = f"Country: {country}"

        special_notes = entry.get("special_notes")
        if special_notes:
            special_notes = fix_encoding(special_notes)
            # Filter out references to specific companies
            if "DESTEK PATENT" not in special_notes and "Alfasoft" not in special_notes:
                description += f" | Note: {special_notes}"

        templates.append(
            {
                "jurisdiction": country_code.strip(),
                "document_name": doc_name,
                "description": description,
            }
        )

    return templates


async def seed(json_path: str) -> None:
    """Insert templates into the database."""
    templates = parse_country_data(json_path)
    print(f"Found {len(templates)} required document templates to seed.")

    async with async_session() as db:
        inserted = 0
        for tmpl in templates:
            # Check if already exists
            result = await db.execute(
                select(RequiredDocumentTemplate).where(
                    RequiredDocumentTemplate.jurisdiction == tmpl["jurisdiction"],
                    RequiredDocumentTemplate.document_name == tmpl["document_name"],
                    RequiredDocumentTemplate.case_type.is_(None),
                )
            )
            if result.scalar_one_or_none() is not None:
                print(f"  SKIP (exists): {tmpl['jurisdiction']} -> {tmpl['document_name']}")
                continue

            record = RequiredDocumentTemplate(
                id=uuid.uuid4(),
                jurisdiction=tmpl["jurisdiction"],
                case_type=None,  # applies to all case types
                document_name=tmpl["document_name"],
                description=tmpl["description"],
                is_active=True,
            )
            db.add(record)
            inserted += 1

        await db.commit()
        print(f"Inserted {inserted} new templates.")


if __name__ == "__main__":
    default_path = Path(__file__).resolve().parent.parent / "data" / "countries_parsed.json"
    json_path = sys.argv[1] if len(sys.argv) > 1 else str(default_path)
    asyncio.run(seed(json_path))
