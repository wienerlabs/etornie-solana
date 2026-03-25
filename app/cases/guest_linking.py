"""Link guest cases to newly registered users."""

import logging

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case
from app.users.models import User

logger = logging.getLogger(__name__)


async def link_guest_cases(db: AsyncSession, user: User) -> int:
    """Find cases with matching guest email/phone and link them to this user.

    Returns the number of cases linked.
    """
    conditions = []
    if user.email:
        conditions.append(Case.guest_client_email == user.email)
    if user.phone:
        conditions.append(Case.guest_client_phone == user.phone)

    if not conditions:
        return 0

    result = await db.execute(
        select(Case).where(
            Case.client_id.is_(None),
            or_(*conditions),
        )
    )
    cases = list(result.scalars().all())

    linked = 0
    for case in cases:
        case.client_id = user.id
        linked += 1
        logger.info("Linked guest case %s to user %s", case.case_number, user.email)

    if linked > 0:
        await db.flush()

    return linked
