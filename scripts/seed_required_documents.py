"""Seed required_document_templates from countries_parsed.json.

Usage:
    python -m scripts.seed_required_documents [path_to_json]

Defaults to /Users/makinci/Desktop/countries_parsed.json if no path given.
"""

import asyncio
import json
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, engine

# Import all models to register them with SQLAlchemy
from app.users.models import User  # noqa: F401
from app.cases.models import Case, CaseNote  # noqa: F401
from app.documents.models import Document  # noqa: F401
from app.ai.rag.models import DocumentChunk  # noqa: F401
from app.notifications.models import Notification  # noqa: F401
from app.agents.ip_agent.models import AgentConfig  # noqa: F401
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
        zorunlu = entry.get("zorunlu_evraklar")
        if not zorunlu:
            continue

        ulke_kodu = entry.get("ulke_kodu")
        if not ulke_kodu:
            continue

        # Skip entries where ulke_kodu is not a real code
        if len(ulke_kodu) > 10 or "EUTM" in ulke_kodu or "WIPO" in ulke_kodu:
            continue

        zorunlu = fix_encoding(zorunlu)
        ulke = fix_encoding(entry.get("ulke", ""))

        # Parse description from the zorunlu_evraklar field
        # Format: "Document Name (Approval Type)"
        doc_name = zorunlu.strip()
        description = f"Ülke: {ulke}"

        ozel_notlar = entry.get("ozel_notlar")
        if ozel_notlar:
            ozel_notlar = fix_encoding(ozel_notlar)
            # Filter out references to specific companies
            if "DESTEK PATENT" not in ozel_notlar and "Alfasoft" not in ozel_notlar:
                description += f" | Not: {ozel_notlar}"

        templates.append(
            {
                "jurisdiction": ulke_kodu.strip(),
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
    json_path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "/Users/makinci/Desktop/countries_parsed.json"
    )
    asyncio.run(seed(json_path))
