import hashlib
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction
from app.audit.service import log_cancellation
from app.cases.models import Case, CaseNftState, CaseNote, CaseStatus
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


async def prepare_case_attestation(case: Case):
    """Build the attestation instruction payload for ``case``.

    Returns an ``AttestationInstructionPayload`` (program id, operator
    pubkey, PDA, base64 instruction data, fresh blockhash) that the
    frontend can feed into @solana/web3.js to construct and sign the
    sponsored attestation tx. Returns ``None`` if attestation is
    disabled or the build failed.
    """
    if not settings.solana_attestation_enabled:
        return None

    try:
        from solders.pubkey import Pubkey

        from app.solana.client import (
            build_attestation_instruction_payload,
            canonicalize_metadata,
        )

        metadata_hash = canonicalize_metadata(_case_metadata(case))
        client_pubkey = (
            Pubkey.from_string(case.client_wallet)
            if case.client_wallet
            else Pubkey.default()
        )

        return await build_attestation_instruction_payload(
            case_id=case.id.bytes,
            metadata_hash=metadata_hash,
            client_wallet=client_pubkey,
        )
    except Exception:  # noqa: BLE001 — attestation is best-effort; the
        # case itself has already been persisted and should still be
        # returned even if we cannot prepare the on-chain tx.
        logger.exception(
            "failed to prepare attestation tx for case %s", case.id
        )
        return None


async def prepare_case_event(case: Case, event_type: int):
    """Build an update_case_attestation ix payload for a lifecycle event.

    The metadata hash reflects the case's current state at the time of
    the event. Returns ``None`` if the case has never been attested
    on-chain (no prior create_case_attestation) or attestation is off.
    """
    if not settings.solana_attestation_enabled:
        return None
    if not case.attestation_tx:
        logger.info(
            "case %s has no on-chain attestation yet; skipping event %s",
            case.id,
            event_type,
        )
        return None

    try:
        from app.solana.client import (
            build_update_attestation_ix_payload,
            canonicalize_metadata,
        )

        metadata_hash = canonicalize_metadata(_case_metadata(case))
        return await build_update_attestation_ix_payload(
            case_id=case.id.bytes,
            metadata_hash=metadata_hash,
            event_type=event_type,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "failed to prepare event ix for case %s (event_type=%s)",
            case.id,
            event_type,
        )
        return None


async def record_case_event(
    db: AsyncSession,
    case: Case,
    *,
    event_type: int,
    tx_signature: str,
    actor_wallet: str,
    metadata_hash_hex: str,
) -> None:
    """Persist a confirmed on-chain event for ``case``."""
    from app.cases.models import CaseEvent

    event = CaseEvent(
        case_id=case.id,
        event_type=event_type,
        tx_signature=tx_signature,
        actor_wallet=actor_wallet,
        metadata_hash=metadata_hash_hex,
    )
    db.add(event)
    await db.flush()
    logger.info(
        "recorded case event: case=%s type=%s tx=%s",
        case.id,
        event_type,
        tx_signature,
    )


async def record_case_attestation(
    db: AsyncSession, case: Case, tx_signature: str, pda: str
) -> Case:
    """Persist the attestation tx signature + PDA on the case row."""
    case.attestation_tx = tx_signature
    case.attestation_pda = pda
    await db.commit()
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

    # ``lawyer_id`` parameter is preserved for API compatibility but no
    # longer filters anything — the lawyer role was removed in
    # 2026-05-02. See docs/REMOVED_LAWYER_LAYER.md.
    _ = lawyer_id

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


def _case_nft_metadata(case: Case) -> dict:
    """Token-2022 on-chain metadata for a case NFT."""
    uri = f"{settings.api_public_url.rstrip('/')}/case-metadata/{case.id.hex}.json"
    return {
        "name": f"Etornie Case {case.case_number}",
        "symbol": "ETRN",
        "uri": uri,
    }


def _metadata_uri_hash(uri: str) -> bytes:
    return hashlib.sha256(uri.encode("utf-8")).digest()


async def trigger_nft_setup_background(case_id: uuid.UUID) -> None:
    """Background-safe wrapper: opens own DB session, loads case, runs setup."""
    from app.database import async_session

    async with async_session() as db:
        case = await get_case(db, case_id)
        if case is not None:
            await trigger_nft_setup(db, case)
            await db.commit()


async def trigger_nft_burn_background(case_id: uuid.UUID) -> None:
    """Background-safe wrapper: opens own DB session, loads case, runs burn."""
    from app.database import async_session

    async with async_session() as db:
        case = await get_case(db, case_id)
        if case is not None:
            await trigger_nft_burn(db, case)
            await db.commit()


async def trigger_nft_setup(db: AsyncSession, case: Case) -> Case:
    """Run the Token-2022 mint setup for a case (operator-only, autonomous).

    Called in the background after attestation confirms. Creates the
    mint with MetadataPointer + TokenMetadata + DefaultAccountState=Frozen
    + PermanentDelegate extensions, transfers mint/freeze authority to
    the program PDA, and records the mint + setup_tx on the case row.

    Safe to call once; subsequent calls no-op when nft_state != none.
    """
    if not settings.solana_nft_enabled:
        return case
    if case.nft_state != CaseNftState.none:
        return case

    from app.solana.client import SolanaClientError, run_nft_setup

    meta = _case_nft_metadata(case)
    try:
        mint, setup_tx = await run_nft_setup(
            name=meta["name"],
            symbol=meta["symbol"],
            uri=meta["uri"],
        )
    except SolanaClientError as exc:
        logger.exception("nft setup failed for case %s: %s", case.id, exc)
        return case
    except Exception:  # noqa: BLE001
        logger.exception("nft setup crashed for case %s", case.id)
        return case

    case.nft_mint = mint
    case.nft_setup_tx = setup_tx
    case.nft_state = CaseNftState.pending_claim
    await db.flush()
    await db.refresh(case)
    logger.info(
        "case %s nft setup: mint=%s tx=%s", case.id, mint, setup_tx
    )
    return case


async def prepare_nft_claim(case: Case, client_wallet: str):
    """Build the mint_case_nft claim payload for the frontend.

    Returns a ``MintClaimPayload`` (account metas + ix data for both ATA
    create and mint_case_nft). Caller must validate that
    ``client_wallet`` matches the case's bound client. Returns ``None``
    if the case is not in pending_claim state.
    """
    if case.nft_state != CaseNftState.pending_claim:
        return None
    if not case.nft_mint:
        return None

    from app.solana.client import build_mint_claim_payload

    meta = _case_nft_metadata(case)
    metadata_uri_hash = _metadata_uri_hash(meta["uri"])

    payload = await build_mint_claim_payload(
        case_id=case.id.bytes,
        mint=case.nft_mint,
        client_wallet=client_wallet,
        metadata_uri_hash=metadata_uri_hash,
    )
    return payload, meta["uri"], metadata_uri_hash


async def record_nft_claim(
    db: AsyncSession, case: Case, mint_tx: str
) -> Case:
    """Persist the mint_case_nft tx signature + advance state to minted."""
    case.nft_mint_tx = mint_tx
    case.nft_state = CaseNftState.minted
    await db.flush()
    await db.refresh(case)
    logger.info("case %s nft minted: tx=%s", case.id, mint_tx)
    return case


async def trigger_nft_burn(db: AsyncSession, case: Case) -> Case:
    """Burn a case NFT after the case is closed (operator-only)."""
    if not settings.solana_nft_enabled:
        return case
    if case.nft_state != CaseNftState.minted:
        return case
    if not case.nft_mint or not case.client_wallet:
        return case

    from app.solana.client import SolanaClientError, run_nft_burn

    try:
        burn_tx = await run_nft_burn(
            case_id=case.id.bytes,
            mint=case.nft_mint,
            client_wallet=case.client_wallet,
        )
    except SolanaClientError as exc:
        logger.exception("nft burn failed for case %s: %s", case.id, exc)
        return case
    except Exception:  # noqa: BLE001
        logger.exception("nft burn crashed for case %s", case.id)
        return case

    case.nft_burn_tx = burn_tx
    case.nft_burned_at = datetime.now(timezone.utc)
    case.nft_state = CaseNftState.burned
    await db.flush()
    await db.refresh(case)
    logger.info("case %s nft burned: tx=%s", case.id, burn_tx)
    return case


def build_case_metadata_json(case: Case, latest_submission=None) -> dict:
    """Dynamic Token-2022 off-chain metadata (the URI target).

    Phantom / wallets fetch this JSON when rendering the NFT. Regenerates
    on every request from the current DB state, so status-dependent
    attributes (badge, updated_at) stay live without on-chain updates.
    Filing-time x402 hash trail (query_hash, commitment, payment_tx,
    compliance_tx, compliance_pda) is pulled in from the latest UKIPO
    submission (passed in by the caller) so a wallet rendering the NFT
    can verify the on-chain proof lineage straight from the metadata.
    """
    meta = _case_nft_metadata(case)
    status_badge_color = {
        CaseStatus.open: "#22c55e",
        CaseStatus.in_progress: "#3b82f6",
        CaseStatus.under_review: "#eab308",
        CaseStatus.closed: "#ef4444",
    }.get(case.status, "#6b7280")

    attributes: list[dict] = [
        {"trait_type": "case_number", "value": case.case_number},
        {"trait_type": "case_type", "value": case.case_type.value},
        {"trait_type": "status", "value": case.status.value},
        {"trait_type": "jurisdiction", "value": case.jurisdiction or ""},
        {"trait_type": "nft_state", "value": case.nft_state.value},
        {"trait_type": "badge_color", "value": status_badge_color},
        {"trait_type": "attestation_tx", "value": case.attestation_tx or ""},
        {"trait_type": "attestation_pda", "value": case.attestation_pda or ""},
        {"trait_type": "client_wallet", "value": case.client_wallet or ""},
        {"trait_type": "nft_mint", "value": case.nft_mint or ""},
        {"trait_type": "created_at", "value": case.created_at.isoformat()},
        {"trait_type": "updated_at", "value": case.updated_at.isoformat()},
    ]

    submission = latest_submission
    if submission is not None:
        attributes.extend(
            [
                {
                    "trait_type": "filing_payment_tx",
                    "value": submission.solana_payment_tx or "",
                },
                {
                    "trait_type": "filing_payment_lamports",
                    "value": submission.solana_payment_lamports or 0,
                },
                {
                    "trait_type": "filing_compliance_tx",
                    "value": submission.solana_compliance_tx or "",
                },
                {
                    "trait_type": "filing_compliance_pda",
                    "value": submission.solana_compliance_pda or "",
                },
                {
                    "trait_type": "filing_query_hash",
                    "value": submission.solana_query_hash_hex or "",
                },
                {
                    "trait_type": "filing_commitment",
                    "value": submission.solana_commitment_hex or "",
                },
                {
                    "trait_type": "filing_jurisdiction",
                    "value": "UKIPO",
                },
                {
                    "trait_type": "filing_status",
                    "value": submission.status.value,
                },
                {
                    "trait_type": "ipo_application_url",
                    "value": submission.ipo_application_url or "",
                },
            ]
        )

    return {
        "name": meta["name"],
        "symbol": meta["symbol"],
        "description": (
            f"Soul-bound Etornie Case NFT for {case.case_number}. "
            f"Proof of on-chain attested legal engagement, "
            f"with the x402 payment + Groth16 compliance proof "
            f"hashes embedded as metadata attributes."
        ),
        "image": (
            f"{settings.api_public_url.rstrip('/')}/case-metadata/"
            f"{case.id.hex}.png"
        ),
        "external_url": f"{settings.api_public_url.rstrip('/')}/cases/{case.id}",
        "attributes": attributes,
    }


async def fetch_latest_filed_submission(db, case_id):
    """Async helper to grab the freshest UKIPOSubmission for a case.

    Returns the row with status=filed when one exists; otherwise the most
    recent attempt regardless of state; or ``None`` if the case has
    nothing on file. Used by the metadata router so the off-chain JSON
    can carry the x402 hash trail.
    """
    from sqlalchemy import select

    from app.services.ukipo.models import UKIPOSubmission, UKIPOSubmissionStatus

    filed = await db.execute(
        select(UKIPOSubmission)
        .where(
            UKIPOSubmission.case_id == case_id,
            UKIPOSubmission.status == UKIPOSubmissionStatus.filed,
        )
        .order_by(UKIPOSubmission.created_at.desc())
        .limit(1)
    )
    row = filed.scalar_one_or_none()
    if row is not None:
        return row
    any_row = await db.execute(
        select(UKIPOSubmission)
        .where(UKIPOSubmission.case_id == case_id)
        .order_by(UKIPOSubmission.created_at.desc())
        .limit(1)
    )
    return any_row.scalar_one_or_none()


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
