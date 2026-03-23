"""IP Agent API endpoints for deadline scanning and configuration."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.ip_agent.models import AgentConfig
from app.agents.ip_agent.schemas import (
    AgentConfigResponse,
    AgentConfigureRequest,
    IPAgentRunResponse,
    UpcomingDeadlineItem,
    UpcomingDeadlinesResponse,
)
from app.agents.ip_agent.service import IP_AGENT_NAME, run_ip_agent
from app.auth.dependencies import get_current_user, require_role
from app.cases.models import Case, CaseStatus
from app.database import get_db
from app.users.models import User, UserRole

router = APIRouter(prefix="/agents/ip", tags=["agents"])


@router.post("/scan-deadlines", response_model=IPAgentRunResponse)
async def scan_deadlines_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> IPAgentRunResponse:
    """Trigger the IP agent manually (admin only).

    Scans all active cases for upcoming deadlines and creates WhatsApp
    notifications for lawyers and clients.
    """
    result = await run_ip_agent(db)
    return IPAgentRunResponse(**result)


@router.get("/upcoming-deadlines", response_model=UpcomingDeadlinesResponse)
async def upcoming_deadlines_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.admin, UserRole.lawyer)
    ),
) -> UpcomingDeadlinesResponse:
    """List cases with upcoming deadlines (next 30 days).

    Admin sees all cases; lawyers see only their assigned cases.
    """
    today = datetime.now(timezone.utc).date()
    end_date = today + timedelta(days=30)

    query = (
        select(Case)
        .where(
            and_(
                Case.status != CaseStatus.closed,
                Case.deadline.isnot(None),
                Case.deadline >= today,
                Case.deadline <= end_date,
            )
        )
        .options(
            selectinload(Case.client),
            selectinload(Case.assigned_lawyer),
        )
        .order_by(Case.deadline.asc())
    )

    if current_user.role == UserRole.lawyer:
        query = query.where(Case.assigned_lawyer_id == current_user.id)

    result = await db.execute(query)
    cases = list(result.scalars().all())

    items: list[UpcomingDeadlineItem] = []
    for case in cases:
        days_remaining = (case.deadline - today).days
        items.append(
            UpcomingDeadlineItem(
                case_id=case.id,
                case_number=case.case_number,
                case_title=case.title,
                deadline=case.deadline,
                days_remaining=days_remaining,
                status=case.status.value,
                lawyer_name=(
                    case.assigned_lawyer.full_name
                    if case.assigned_lawyer
                    else None
                ),
                client_name=case.client.full_name if case.client else None,
            )
        )

    return UpcomingDeadlinesResponse(deadlines=items, total=len(items))


@router.post(
    "/configure",
    response_model=AgentConfigResponse,
    status_code=status.HTTP_200_OK,
)
async def configure_agent_endpoint(
    data: AgentConfigureRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> AgentConfigResponse:
    """Update IP agent configuration (admin only)."""
    result = await db.execute(
        select(AgentConfig).where(AgentConfig.agent_name == IP_AGENT_NAME)
    )
    config = result.scalar_one_or_none()

    reminder_days_str = ",".join(str(d) for d in sorted(data.reminder_days, reverse=True))

    if config is None:
        config = AgentConfig(
            agent_name=IP_AGENT_NAME,
            is_enabled=data.enabled,
            reminder_days=reminder_days_str,
        )
        db.add(config)
        await db.flush()
        await db.refresh(config)
    else:
        config.is_enabled = data.enabled
        config.reminder_days = reminder_days_str
        await db.flush()
        await db.refresh(config)

    parsed_days = [int(d.strip()) for d in config.reminder_days.split(",") if d.strip()]
    return AgentConfigResponse(
        agent_name=config.agent_name,
        is_enabled=config.is_enabled,
        reminder_days=parsed_days,
    )
