import base64
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.auth.service import get_user_by_id
from app.cases.models import CaseStatus
from app.cases.models import CaseEvent
from app.cases.schemas import (
    AttestationSubmitRequest,
    CaseCreate,
    CaseCreateResponse,
    CaseEventResponse,
    CaseListResponse,
    CaseNoteCreate,
    CaseNoteResponse,
    CaseResponse,
    CaseUpdate,
    EventPrepareRequest,
    EventSubmitRequest,
    MintClaimFinalizeRequest,
    MintClaimPrepareResponse,
    NftAccountMeta,
    NftInstructionPayload,
    PendingAttestation,
    PendingEventAttestation,
)
from app.cases.service import (
    cancel_case_note,
    create_case,
    create_case_note,
    get_case,
    get_case_note,
    list_case_notes,
    list_cases,
    prepare_case_attestation,
    prepare_case_event,
    prepare_nft_claim,
    record_case_attestation,
    record_case_event,
    record_nft_claim,
    trigger_nft_burn,
    trigger_nft_setup,
    update_case,
)
from sqlalchemy import select
from app.config import settings
from app.solana.client import (
    SolanaClientError,
    derive_attestation_pda,
    finalize_mint_claim_tx,
    finalize_sponsored_attestation_tx,
)
from fastapi import BackgroundTasks
from app.database import get_db
from app.notifications.case_notifications import (
    notify_case_created,
    send_case_created_email_to_guest,
    send_case_created_whatsapp_to_guest,
)
from app.users.models import User, UserRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cases", tags=["cases"])


def _can_access_case(user: User, case: object) -> bool:
    """Check whether a user may view/interact with a case."""
    if user.role == UserRole.admin:
        return True
    if user.id == getattr(case, "assigned_lawyer_id", None):
        return True
    if user.id == getattr(case, "client_id", None):
        return True
    return False


@router.post(
    "",
    response_model=CaseCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_case_endpoint(
    data: CaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.lawyer)),
) -> CaseCreateResponse:
    """Create a new case (admin or lawyer only).

    Returns the case plus, when the current user has a wallet_address and
    Solana attestation is enabled, a partially-signed attestation tx that
    the frontend can have the user sign via Phantom and submit to devnet.
    """
    # Auto-assign lawyer if current user is a lawyer and no lawyer specified
    assigned_lawyer_id = data.assigned_lawyer_id
    if assigned_lawyer_id is None and current_user.role == UserRole.lawyer:
        assigned_lawyer_id = current_user.id

    create_kwargs: dict[str, object] = {
        "title": data.title,
        "description": data.description,
        "case_type": data.case_type,
        "client_id": data.client_id,
        "assigned_lawyer_id": assigned_lawyer_id,
        "jurisdiction": data.jurisdiction,
        "nice_classes": data.nice_classes,
        "filing_date": data.filing_date,
        "deadline": data.deadline,
        "client_wallet": data.client_wallet,
    }

    if data.client_id is None:
        create_kwargs["guest_client_name"] = data.guest_client_name
        create_kwargs["guest_client_email"] = data.guest_client_email
        create_kwargs["guest_client_phone"] = data.guest_client_phone

    case = await create_case(db, **create_kwargs)

    # Auto-generate proposal if nice_classes and jurisdiction are set
    if case.nice_classes and case.jurisdiction:
        try:
            from app.proposals.service import generate_proposal

            await generate_proposal(
                db,
                case_id=case.id,
                jurisdiction=case.jurisdiction,
                nice_classes=case.nice_classes,
                created_by=current_user.id,
            )
            logger.info(
                "Auto-generated proposal for case %s (jurisdiction=%s, nice_classes=%s)",
                case.case_number,
                case.jurisdiction,
                case.nice_classes,
            )
        except Exception as exc:
            logger.warning("Failed to auto-generate proposal for case %s: %s", case.case_number, exc)
            await db.rollback()
            await db.refresh(case)

    # Send notifications to the client (non-blocking)
    if data.client_id:
        client_user = await get_user_by_id(db, case.client_id)
        if client_user:
            try:
                await notify_case_created(db, case, client_user, current_user.id)
            except Exception as exc:
                logger.warning("Failed to send case notifications: %s", exc)
    else:
        # Guest client notifications
        try:
            if data.guest_client_email:
                await send_case_created_email_to_guest(
                    email=data.guest_client_email,
                    name=data.guest_client_name or "Client",
                    case=case,
                )
        except Exception as exc:
            logger.warning("Failed to send guest email notification: %s", exc)

        try:
            if data.guest_client_phone:
                await send_case_created_whatsapp_to_guest(
                    db=db,
                    phone=data.guest_client_phone,
                    name=data.guest_client_name or "Client",
                    case=case,
                    created_by_id=current_user.id,
                )
        except Exception as exc:
            logger.warning("Failed to send guest WhatsApp notification: %s", exc)

    attestation_payload: PendingAttestation | None = None
    if (
        current_user.wallet_address
        and settings.solana_attestation_enabled
    ):
        prepared = await prepare_case_attestation(case)
        if prepared is not None:
            attestation_payload = PendingAttestation(
                program_id=prepared.program_id,
                operator=prepared.operator,
                pda=prepared.pda,
                ix_data_b64=prepared.ix_data_b64,
                recent_blockhash=prepared.recent_blockhash,
            )

    return CaseCreateResponse(
        case=CaseResponse.model_validate(case),
        attestation=attestation_payload,
    )


@router.post(
    "/{case_id}/attestation/submit",
    response_model=CaseResponse,
)
async def submit_case_attestation(
    case_id: uuid.UUID,
    data: AttestationSubmitRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseResponse:
    """Finalize a sponsored attestation tx and persist the result.

    The frontend has already had the user's wallet sign the tx via
    Phantom. We decode it here, add the backend operator's signature,
    submit to devnet, wait for confirmation, then record the tx
    signature and PDA on the case row.
    """
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    if not _can_access_case(current_user, case):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")

    try:
        signed_bytes = base64.b64decode(data.signed_tx_b64)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"invalid signed_tx_b64: {exc}"
        ) from exc

    try:
        tx_signature, _program_id = await finalize_sponsored_attestation_tx(
            signed_bytes
        )
    except SolanaClientError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("attestation submission failed for case %s", case.id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"attestation submission failed: {exc}",
        ) from exc

    pda, _ = derive_attestation_pda(case.id.bytes)
    case = await record_case_attestation(
        db, case, tx_signature, str(pda)
    )

    # Fire-and-forget: after attestation confirms, kick off the Token-2022
    # mint setup in the background. Operator signs alone; on completion the
    # case row advances to nft_state=pending_claim so the client can claim.
    from app.cases.service import trigger_nft_setup_background

    background_tasks.add_task(trigger_nft_setup_background, case.id)

    return CaseResponse.model_validate(case)


@router.post(
    "/{case_id}/attestation/event-prepare",
    response_model=PendingEventAttestation,
)
async def prepare_case_event_endpoint(
    case_id: uuid.UUID,
    data: EventPrepareRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PendingEventAttestation:
    """Prepare an update_case_attestation sponsored tx for a lifecycle event.

    The frontend receives this payload, has the user's wallet sign the
    assembled VersionedTransaction via Phantom, and sends the signed
    bytes back to POST /cases/{id}/attestation/event-submit.
    """
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    if not _can_access_case(current_user, case):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")

    if not current_user.wallet_address:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "current user has no wallet; cannot sign on-chain event",
        )

    payload = await prepare_case_event(case, data.event_type)
    if payload is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "case has no on-chain attestation or Solana is disabled",
        )
    return PendingEventAttestation(
        program_id=payload.program_id,
        operator=payload.operator,
        pda=payload.pda,
        ix_data_b64=payload.ix_data_b64,
        recent_blockhash=payload.recent_blockhash,
        event_type=payload.event_type,
        metadata_hash_hex=payload.metadata_hash_hex,
    )


@router.post(
    "/{case_id}/attestation/event-submit",
    response_model=CaseEventResponse,
)
async def submit_case_event_endpoint(
    case_id: uuid.UUID,
    data: EventSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseEventResponse:
    """Finalize a sponsored update tx and persist the event row."""
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    if not _can_access_case(current_user, case):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")

    try:
        signed_bytes = base64.b64decode(data.signed_tx_b64)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"invalid signed_tx_b64: {exc}"
        ) from exc

    try:
        tx_signature, _program_id = await finalize_sponsored_attestation_tx(
            signed_bytes
        )
    except SolanaClientError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc)
        ) from exc
    except Exception as exc:
        logger.exception(
            "event submission failed for case %s (event_type=%s)",
            case.id,
            data.event_type,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"event submission failed: {exc}",
        ) from exc

    await record_case_event(
        db,
        case,
        event_type=data.event_type,
        tx_signature=tx_signature,
        actor_wallet=data.actor_wallet,
        metadata_hash_hex=data.metadata_hash_hex,
    )
    # Fetch the just-inserted row to serialize
    result = await db.execute(
        select(CaseEvent)
        .where(CaseEvent.case_id == case.id)
        .order_by(CaseEvent.created_at.desc())
        .limit(1)
    )
    event_row = result.scalar_one()
    return CaseEventResponse.model_validate(event_row)


@router.get(
    "/{case_id}/events",
    response_model=list[CaseEventResponse],
)
async def list_case_events(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CaseEventResponse]:
    """Timeline of on-chain lifecycle events for a case (newest first)."""
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    if not _can_access_case(current_user, case):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")

    result = await db.execute(
        select(CaseEvent)
        .where(CaseEvent.case_id == case.id)
        .order_by(CaseEvent.created_at.desc())
    )
    rows = result.scalars().all()
    return [CaseEventResponse.model_validate(r) for r in rows]


@router.get("", response_model=CaseListResponse)
async def list_cases_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status_filter: CaseStatus | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseListResponse:
    """List cases with role-based filtering.

    - Admin: all cases
    - Lawyer: only assigned cases
    - Client: only own cases
    """
    client_id: uuid.UUID | None = None
    lawyer_id: uuid.UUID | None = None

    if current_user.role == UserRole.client:
        client_id = current_user.id
    elif current_user.role == UserRole.lawyer:
        lawyer_id = current_user.id

    cases, total = await list_cases(
        db,
        skip=skip,
        limit=limit,
        client_id=client_id,
        lawyer_id=lawyer_id,
        status=status_filter,
    )
    return CaseListResponse(
        cases=[CaseResponse.model_validate(c) for c in cases],
        total=total,
    )


@router.get("/{case_id}", response_model=CaseResponse)
async def get_case_endpoint(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseResponse:
    """Get case detail. Must be admin, assigned lawyer, or case client."""
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )

    if not _can_access_case(current_user, case):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this case",
        )

    return CaseResponse.model_validate(case)


@router.patch("/{case_id}", response_model=CaseResponse)
async def update_case_endpoint(
    case_id: uuid.UUID,
    data: CaseUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseResponse:
    """Update a case. Admin can update any; assigned lawyer can update theirs."""
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )

    is_admin = current_user.role == UserRole.admin
    is_assigned_lawyer = current_user.id == case.assigned_lawyer_id

    if not (is_admin or is_assigned_lawyer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin or assigned lawyer can update this case",
        )

    old_jurisdiction = case.jurisdiction
    old_status = case.status
    update_data = data.model_dump(exclude_unset=True)
    case = await update_case(db, case, **update_data)

    # Autonomous burn when a minted NFT's case transitions to closed.
    if (
        old_status != CaseStatus.closed
        and case.status == CaseStatus.closed
        and case.nft_mint
    ):
        from app.cases.service import trigger_nft_burn_background

        background_tasks.add_task(trigger_nft_burn_background, case.id)

    # Regenerate required documents if jurisdiction changed
    new_jurisdiction = case.jurisdiction
    if (
        new_jurisdiction
        and old_jurisdiction != new_jurisdiction
        and case.case_type
    ):
        from app.required_documents.service import regenerate_on_jurisdiction_change

        await regenerate_on_jurisdiction_change(
            db,
            case_id=case.id,
            new_jurisdiction=new_jurisdiction,
            case_type=case.case_type.value,
        )

    return CaseResponse.model_validate(case)


@router.post(
    "/{case_id}/notes",
    response_model=CaseNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_note_endpoint(
    case_id: uuid.UUID,
    data: CaseNoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseNoteResponse:
    """Add a note to a case. Admin, assigned lawyer, or case client."""
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )

    if not _can_access_case(current_user, case):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this case",
        )

    note = await create_case_note(
        db, case_id=case_id, author_id=current_user.id, content=data.content
    )

    # Send in-app notification to case participants (except author)
    from app.in_app_notifications.service import notify_note_added

    recipients = set()
    if case.assigned_lawyer_id and case.assigned_lawyer_id != current_user.id:
        recipients.add(case.assigned_lawyer_id)
    if case.client_id and case.client_id != current_user.id:
        recipients.add(case.client_id)

    for rid in recipients:
        try:
            await notify_note_added(
                db,
                case_id=case_id,
                case_title=case.title,
                author_name=current_user.full_name,
                author_id=current_user.id,
                recipient_id=rid,
            )
        except Exception:
            pass

    return CaseNoteResponse.model_validate(note)


@router.get("/{case_id}/notes", response_model=list[CaseNoteResponse])
async def list_notes_endpoint(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CaseNoteResponse]:
    """List notes for a case. Admin, assigned lawyer, or case client."""
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )

    if not _can_access_case(current_user, case):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this case",
        )

    notes = await list_case_notes(db, case_id)
    return [CaseNoteResponse.model_validate(n) for n in notes]


@router.patch(
    "/{case_id}/notes/{note_id}/cancel",
    response_model=CaseNoteResponse,
)
async def cancel_note_endpoint(
    case_id: uuid.UUID,
    note_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseNoteResponse:
    """Cancel a note. Only the author or admin can cancel. Irreversible."""
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )

    note = await get_case_note(db, note_id)
    if note is None or note.case_id != case_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )

    if note.is_cancelled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Note is already cancelled",
        )

    is_admin = current_user.role == UserRole.admin
    is_author = current_user.id == note.author_id

    if not (is_admin or is_author):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin or the note author can cancel this note",
        )

    cancelled = await cancel_case_note(db, note, current_user.id)
    return CaseNoteResponse.model_validate(cancelled)


def _instruction_payload_to_schema(ix) -> NftInstructionPayload:
    """Convert the service-layer dataclass to the Pydantic response schema."""
    return NftInstructionPayload(
        program_id=ix.program_id,
        accounts=[
            NftAccountMeta(
                pubkey=a.pubkey,
                is_signer=a.is_signer,
                is_writable=a.is_writable,
            )
            for a in ix.accounts
        ],
        data_b64=ix.data_b64,
    )


@router.post(
    "/{case_id}/nft/prepare-claim",
    response_model=MintClaimPrepareResponse,
)
async def prepare_nft_claim_endpoint(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MintClaimPrepareResponse:
    """Build the payload the client signs via Phantom to claim their Case NFT.

    Requires that the backend has already completed the Token-2022 mint
    setup (nft_state = pending_claim). Returns account metas + ix data for
    an ATA idempotent create + mint_case_nft instruction pair.
    """
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    if not _can_access_case(current_user, case):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")

    if not current_user.wallet_address:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "current user has no wallet; connect Phantom first",
        )
    if case.client_wallet and case.client_wallet != current_user.wallet_address:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "only the bound client wallet can claim this NFT",
        )

    try:
        result = await prepare_nft_claim(case, current_user.wallet_address)
    except SolanaClientError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc)
        ) from exc
    except Exception as exc:
        logger.exception(
            "prepare_nft_claim failed for case %s", case.id
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"claim preparation failed: {exc}",
        ) from exc

    if result is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "case NFT is not ready for claim (setup may still be pending)",
        )
    payload, metadata_uri, metadata_uri_hash = result

    return MintClaimPrepareResponse(
        program_id=payload.program_id,
        operator=payload.operator,
        client=payload.client,
        mint=payload.mint,
        client_token_account=payload.client_token_account,
        nft_authority=payload.nft_authority,
        case_nft_record=payload.case_nft_record,
        ata_ix=_instruction_payload_to_schema(payload.ata_ix),
        mint_ix=_instruction_payload_to_schema(payload.mint_ix),
        recent_blockhash=payload.recent_blockhash,
        metadata_uri=metadata_uri,
        metadata_uri_hash_hex=metadata_uri_hash.hex(),
    )


@router.post(
    "/{case_id}/nft/finalize-claim",
    response_model=CaseResponse,
)
async def finalize_nft_claim_endpoint(
    case_id: uuid.UUID,
    data: MintClaimFinalizeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseResponse:
    """Add the operator signature to a client-signed claim tx, submit to devnet."""
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    if not _can_access_case(current_user, case):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")

    try:
        signed_bytes = base64.b64decode(data.signed_tx_b64)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"invalid signed_tx_b64: {exc}"
        ) from exc

    try:
        mint_tx = await finalize_mint_claim_tx(signed_bytes)
    except SolanaClientError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(exc)
        ) from exc
    except Exception as exc:
        logger.exception(
            "finalize_mint_claim_tx failed for case %s", case.id
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"claim finalize failed: {exc}",
        ) from exc

    case = await record_nft_claim(db, case, mint_tx)
    return CaseResponse.model_validate(case)
