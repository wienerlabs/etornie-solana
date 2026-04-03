"""Proposal service: auto-generates proposals from country data and case info."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.etorniegpt.countries import find_country
from app.proposals.models import Proposal, ProposalStatus


async def generate_proposal(
    db: AsyncSession,
    case_id: uuid.UUID,
    jurisdiction: str,
    nice_classes: str,
    created_by: uuid.UUID,
) -> Proposal:
    """Generate a proposal from country data for the given case.

    Looks up the jurisdiction in the country database and populates
    all available fields. Returns the created proposal.
    """
    country = find_country(jurisdiction)

    if country is None:
        # Country not in DB — create proposal with minimal info
        proposal = Proposal(
            case_id=case_id,
            country_name=jurisdiction,
            country_code=None,
            nice_classes=nice_classes,
            required_documents=None,
            registration_period=None,
            protection_period=None,
            madrid_system=None,
            national_application=None,
            opposition_period=None,
            special_notes=None,
            price=None,
            currency=None,
            status=ProposalStatus.draft,
            created_by=created_by,
        )
    else:
        proposal = Proposal(
            case_id=case_id,
            country_name=country.get("ulke", jurisdiction),
            country_code=country.get("ulke_kodu"),
            nice_classes=nice_classes,
            required_documents=country.get("zorunlu_evraklar"),
            registration_period=country.get("tescil_suresi"),
            protection_period=country.get("koruma_suresi"),
            madrid_system=country.get("madrid"),
            national_application=country.get("ulkesel"),
            opposition_period=country.get("itiraz_suresi"),
            special_notes=country.get("ozel_notlar"),
            price=None,
            currency=None,
            status=ProposalStatus.draft,
            created_by=created_by,
        )

    db.add(proposal)
    await db.flush()
    await db.refresh(proposal)
    return proposal


async def get_proposal(
    db: AsyncSession,
    proposal_id: uuid.UUID,
) -> Proposal | None:
    """Fetch a single proposal by ID."""
    result = await db.execute(
        select(Proposal).where(Proposal.id == proposal_id)
    )
    return result.scalar_one_or_none()


async def get_proposal_by_case(
    db: AsyncSession,
    case_id: uuid.UUID,
) -> Proposal | None:
    """Fetch the latest proposal for a case."""
    result = await db.execute(
        select(Proposal)
        .where(Proposal.case_id == case_id)
        .order_by(Proposal.created_at.desc(), Proposal.id.desc())
    )
    return result.scalars().first()


async def list_proposals_by_case(
    db: AsyncSession,
    case_id: uuid.UUID,
) -> list[Proposal]:
    """List all proposals for a case, newest first."""
    result = await db.execute(
        select(Proposal)
        .where(Proposal.case_id == case_id)
        .order_by(Proposal.created_at.desc())
    )
    return list(result.scalars().all())


async def send_proposal(
    db: AsyncSession,
    proposal: Proposal,
) -> Proposal:
    """Mark proposal as sent."""
    proposal.status = ProposalStatus.sent
    proposal.sent_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(proposal)
    return proposal


async def respond_to_proposal(
    db: AsyncSession,
    proposal: Proposal,
    accepted: bool,
    rejection_reason: str | None = None,
) -> Proposal:
    """Mark proposal as accepted or rejected by client."""
    proposal.status = ProposalStatus.accepted if accepted else ProposalStatus.rejected
    proposal.responded_at = datetime.now(timezone.utc)
    if not accepted and rejection_reason:
        proposal.rejection_reason = rejection_reason
    await db.flush()
    await db.refresh(proposal)
    return proposal
