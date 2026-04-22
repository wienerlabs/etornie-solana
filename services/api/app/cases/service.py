import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction
from app.audit.service import log_cancellation
from app.cases.models import Case, CaseNote, CaseStatus
from app.config import settings

logger = logging.getLogger(__name__)


async def _next_case_number(db: AsyncSession) -> str:
    """Generate the next case number in ETR-YYYY-NNNN format."""
    year = datetime.now(timezone.utc).year
    prefix = f"ETR-{year}-"

    result = await db.execute(
        select(func.count(Case.id)).where(Case.case_number.like(f"{prefix}%"))
    )
    count = result.scalar_one()
    sequence = count + 1
    return f"{prefix}{sequence:04d}"


async def create_case(
    db: AsyncSession,
    **kwargs: object,
) -> Case:
    """Create a new case with auto-generated case_number.

    Auto-generates required documents if jurisdiction and case_type are
    provided. On-chain attestation is no longer triggered here: the
    attestation tx is prepared by ``prepare_case_attestation`` and
    submitted by the user's wallet through the frontend.
    """
    # Resolve the client wallet from the linked user BEFORE inserting the
    # case so it lands on the initial INSERT. This avoids a later UPDATE
    # whose onupdate=func.now() trigger would expire case.updated_at in
    # memory and break pydantic serialization outside the async greenlet.
    if kwargs.get("client_wallet") is None and kwargs.get("client_id") is not None:
        resolved = await _resolve_client_wallet_from_user(db, kwargs["client_id"])  # type: ignore[arg-type]
        if resolved:
            kwargs["client_wallet"] = resolved

    case_number = await _next_case_number(db)
    case = Case(case_number=case_number, **kwargs)
    db.add(case)
    await db.flush()
    await db.refresh(case)

    # Auto-generate required documents from templates
    if case.jurisdiction and case.case_type:
        from app.required_documents.service import generate_case_required_documents

        await generate_case_required_documents(
            db,
            case_id=case.id,
            jurisdiction=case.jurisdiction,
            case_type=case.case_type.value,
        )

    return case


async def prepare_case_attestation(
    case: Case, creator_wallet: str
) -> tuple[bytes, str] | None:
    """Build a partially-signed attestation tx for ``case``.

    The tx is co-signed by the backend operator; the creator signature
    slot is left empty for the frontend wallet to fill. Returns
    ``(tx_bytes, pda_address)`` or ``None`` if attestation is disabled or
    the build failed.
    """
    if not settings.solana_attestation_enabled:
        return None

    try:
        from solders.pubkey import Pubkey

        from app.solana.client import (
            build_create_case_attestation_tx,
            canonicalize_metadata,
        )

        metadata_hash = canonicalize_metadata(_case_metadata(case))
        creator_pubkey = Pubkey.from_string(creator_wallet)
        client_pubkey = (
            Pubkey.from_string(case.client_wallet)
            if case.client_wallet
            else Pubkey.default()
        )

        tx_bytes, pda = await build_create_case_attestation_tx(
            case_id=case.id.bytes,
            metadata_hash=metadata_hash,
            creator=creator_pubkey,
            client_wallet=client_pubkey,
        )
        return tx_bytes, pda
    except Exception:  # noqa: BLE001 — attestation is best-effort; the
        # case itself has already been persisted and should still be
        # returned even if we cannot prepare the on-chain tx.
        logger.exception(
            "failed to prepare attestation tx for case %s", case.id
        )
        return None


async def record_case_attestation(
    db: AsyncSession, case: Case, tx_signature: str, pda: str
) -> Case:
    """Persist the attestation tx signature + PDA on the case row."""
    case.attestation_tx = tx_signature
    case.attestation_pda = pda
    await db.flush()
    await db.refresh(case)
    logger.info(
        "case %s attestation recorded: tx=%s pda=%s",
        case.id,
        tx_signature,
        pda,
    )
    return case


def _case_metadata(case: Case) -> dict:
    """Canonical metadata dict used as pre-image of the on-chain hash."""
    return {
        "case_id": str(case.id),
        "case_number": case.case_number,
        "title": case.title,
        "description": case.description,
        "case_type": case.case_type.value,
        "client_id": str(case.client_id) if case.client_id else None,
        "assigned_lawyer_id": (
            str(case.assigned_lawyer_id) if case.assigned_lawyer_id else None
        ),
        "jurisdiction": case.jurisdiction,
        "nice_classes": case.nice_classes,
        "client_wallet": case.client_wallet,
        "filing_date": (
            case.filing_date.isoformat() if case.filing_date else None
        ),
        "deadline": case.deadline.isoformat() if case.deadline else None,
        "created_at": case.created_at.isoformat(),
    }


async def _resolve_client_wallet_from_user(
    db: AsyncSession, user_id: uuid.UUID
) -> str | None:
    """Look up a registered user's wallet_address, if any."""
    from app.users.models import User

    result = await db.execute(
        select(User.wallet_address).where(User.id == user_id)
    )
    return result.scalar_one_or_none()


async def get_case(db: AsyncSession, case_id: uuid.UUID) -> Case | None:
    """Fetch a single case by ID."""
    result = await db.execute(select(Case).where(Case.id == case_id))
    return result.scalar_one_or_none()


async def list_cases(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
    client_id: uuid.UUID | None = None,
    lawyer_id: uuid.UUID | None = None,
    status: CaseStatus | None = None,
) -> tuple[list[Case], int]:
    """List cases with optional filters. Returns (cases, total_count)."""
    query = select(Case)
    count_query = select(func.count(Case.id))

    if client_id is not None:
        query = query.where(Case.client_id == client_id)
        count_query = count_query.where(Case.client_id == client_id)

    if lawyer_id is not None:
        query = query.where(Case.assigned_lawyer_id == lawyer_id)
        count_query = count_query.where(Case.assigned_lawyer_id == lawyer_id)

    if status is not None:
        query = query.where(Case.status == status)
        count_query = count_query.where(Case.status == status)

    count_result = await db.execute(count_query)
    total = count_result.scalar_one()

    result = await db.execute(
        query.offset(skip).limit(limit).order_by(Case.created_at.desc())
    )
    cases = list(result.scalars().all())
    return cases, total


async def update_case(db: AsyncSession, case: Case, **kwargs: object) -> Case:
    """Update case fields. Only non-None values are applied."""
    for key, value in kwargs.items():
        if value is not None:
            setattr(case, key, value)
    await db.flush()
    await db.refresh(case)
    return case


async def create_case_note(
    db: AsyncSession,
    case_id: uuid.UUID,
    author_id: uuid.UUID,
    content: str,
) -> CaseNote:
    """Create a note on a case."""
    note = CaseNote(case_id=case_id, author_id=author_id, content=content)
    db.add(note)
    await db.flush()
    await db.refresh(note)
    return note


async def list_case_notes(db: AsyncSession, case_id: uuid.UUID) -> list[CaseNote]:
    """List all notes for a case, newest first."""
    result = await db.execute(
        select(CaseNote)
        .where(CaseNote.case_id == case_id)
        .order_by(CaseNote.created_at.desc())
    )
    return list(result.scalars().all())


async def get_case_note(db: AsyncSession, note_id: uuid.UUID) -> CaseNote | None:
    """Fetch a single case note by ID."""
    result = await db.execute(select(CaseNote).where(CaseNote.id == note_id))
    return result.scalar_one_or_none()


async def cancel_case_note(
    db: AsyncSession,
    note: CaseNote,
    cancelled_by_id: uuid.UUID,
) -> CaseNote:
    """Cancel a case note (soft-delete). Irreversible."""
    note.is_cancelled = True
    note.cancelled_at = datetime.now(timezone.utc)
    note.cancelled_by = cancelled_by_id
    await db.flush()
    await db.refresh(note)

    await log_cancellation(
        db,
        actor_id=cancelled_by_id,
        action=AuditAction.note_cancelled,
        target_type="case_note",
        target_id=note.id,
        case_id=note.case_id,
        details=f"Note cancelled (first 100 chars): {note.content[:100]}",
    )

    return note
