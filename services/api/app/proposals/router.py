import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.cases.service import get_case
from app.database import get_db
from app.proposals.schemas import ProposalListResponse, ProposalRespondRequest, ProposalResponse
from app.proposals.service import (
    generate_proposal,
    get_proposal,
    list_proposals_by_case,
    respond_to_proposal,
    send_proposal,
)
from app.users.models import User, UserRole

router = APIRouter(tags=["proposals"])


def _can_access_case(user: User, case: object) -> bool:
    if user.role == UserRole.admin:
        return True
    if user.id == getattr(case, "client_id", None):
        return True
    return False


@router.post(
    "/cases/{case_id}/proposal/generate",
    response_model=ProposalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_proposal_endpoint(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProposalResponse:
    """Generate a proposal for a case based on jurisdiction and Nice classes."""
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    if not _can_access_case(current_user, case):
        raise HTTPException(status_code=403, detail="Access denied")

    if current_user.role == UserRole.client:
        raise HTTPException(
            status_code=403,
            detail="Only admin or lawyer can generate proposals",
        )

    if not case.jurisdiction:
        raise HTTPException(
            status_code=400,
            detail="Case jurisdiction is required to generate a proposal",
        )

    if not case.nice_classes:
        raise HTTPException(
            status_code=400,
            detail="Nice classes must be set on the case to generate a proposal",
        )

    proposal = await generate_proposal(
        db,
        case_id=case_id,
        jurisdiction=case.jurisdiction,
        nice_classes=case.nice_classes,
        created_by=current_user.id,
    )
    return ProposalResponse.model_validate(proposal)


@router.get(
    "/cases/{case_id}/proposal",
    response_model=ProposalResponse,
)
async def get_case_proposal_endpoint(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProposalResponse:
    """Get the latest proposal for a case."""
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    if not _can_access_case(current_user, case):
        raise HTTPException(status_code=403, detail="Access denied")

    from app.proposals.service import get_proposal_by_case

    proposal = await get_proposal_by_case(db, case_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="No proposal found for this case")

    return ProposalResponse.model_validate(proposal)


@router.get(
    "/cases/{case_id}/proposals",
    response_model=ProposalListResponse,
)
async def list_case_proposals_endpoint(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProposalListResponse:
    """List all proposals for a case."""
    case = await get_case(db, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    if not _can_access_case(current_user, case):
        raise HTTPException(status_code=403, detail="Access denied")

    proposals = await list_proposals_by_case(db, case_id)
    return ProposalListResponse(
        proposals=[ProposalResponse.model_validate(p) for p in proposals],
        total=len(proposals),
    )


@router.patch(
    "/proposals/{proposal_id}/send",
    response_model=ProposalResponse,
)
async def send_proposal_endpoint(
    proposal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProposalResponse:
    """Send a draft proposal to the client. Admin or lawyer only."""
    if current_user.role == UserRole.client:
        raise HTTPException(status_code=403, detail="Only admin or lawyer can send proposals")

    proposal = await get_proposal(db, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.status != "draft":
        raise HTTPException(status_code=400, detail="Only draft proposals can be sent")

    updated = await send_proposal(db, proposal)
    return ProposalResponse.model_validate(updated)


@router.patch(
    "/proposals/{proposal_id}/respond",
    response_model=ProposalResponse,
)
async def respond_proposal_endpoint(
    proposal_id: uuid.UUID,
    data: ProposalRespondRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProposalResponse:
    """Accept or reject a sent proposal. Client, admin, or lawyer.

    When rejecting, rejection_reason is required.
    """
    proposal = await get_proposal(db, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.status != "sent":
        raise HTTPException(status_code=400, detail="Only sent proposals can be responded to")

    if not data.accepted and not (data.rejection_reason and data.rejection_reason.strip()):
        raise HTTPException(
            status_code=400,
            detail="Rejection reason is required when rejecting a proposal",
        )

    case = await get_case(db, proposal.case_id)
    if case is None or not _can_access_case(current_user, case):
        raise HTTPException(status_code=403, detail="Access denied")

    rejection_reason = data.rejection_reason.strip() if data.rejection_reason else None
    updated = await respond_to_proposal(db, proposal, data.accepted, rejection_reason)
    return ProposalResponse.model_validate(updated)
