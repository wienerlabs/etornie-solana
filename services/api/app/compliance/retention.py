"""GDPR Article 17 data-retention & erasure policy.

This module is the single, declarative source of truth for **what
happens to each user-scoped table when a data subject is erased**. It is
deliberately data, not logic, so a reviewing lawyer (this issue is
``needs-lawyer``) can read the classification without reading the
execution code in :mod:`app.compliance.erasure`.

The inventory mirrors :mod:`app.compliance.data_export` (the Article-20
export), which documents itself as "the one place to extend when a new
user-scoped table is added". Every table exported there is classified
here, so the two stay in lock-step.

Three dispositions
------------------
* **DELETE** — pure personal data with no overriding retention basis;
  rows are physically removed (and any backing files on disk deleted).
* **ANONYMISE** — the subject's ``users`` row itself: identifying columns
  are overwritten with a tombstone so every retained row that still
  references the user id becomes pseudonymous.
* **RETAIN** — rows kept under a GDPR Art. 17(3) exception (legal
  obligation, or establishment/exercise/defence of legal claims). They
  keep pointing at the now-anonymised user id, so no identifying data
  survives in them.

Erasure is **blocked** while the subject has a case in an active legal
proceeding (Art. 17(3)(e)); see :data:`ERASURE_BLOCKING_STATUSES`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case, CaseStatus


class Disposition(str, Enum):
    delete = "delete"
    anonymise = "anonymise"
    retain = "retain"


@dataclass(frozen=True)
class TablePolicy:
    """How one user-scoped table is treated on erasure."""

    name: str
    disposition: Disposition
    # Human-readable basis — surfaced in the retention doc & API summary.
    reason: str


# Cases in any of these statuses mean an active legal proceeding, so the
# whole erasure request is refused under GDPR Art. 17(3)(e) until they
# close. ``closed`` is the only non-blocking status.
ERASURE_BLOCKING_STATUSES: frozenset[CaseStatus] = frozenset(
    {CaseStatus.open, CaseStatus.in_progress, CaseStatus.under_review}
)


# Tombstone written over the ``users`` row. The synthetic email + a
# locked (unknowable) password keep the ``ck_users_authenticatable``
# CHECK satisfied while carrying no real personal data — the local-part
# is just the internal UUID, which is the primary key, not PII. The
# account is also deactivated, so it can never authenticate regardless.
#
# ``avatar_data`` (deferred LargeBinary) is set to None too; assigning
# does not trigger a lazy load.
def user_tombstone(user_id: uuid.UUID) -> dict[str, object]:
    return {
        "email": f"erased-{user_id}@deleted.etornie.invalid",
        "full_name": "Erased user",
        "phone": None,
        "wallet_address": None,
        "public_handle": None,
        "notification_email": None,
        "email_notifications_enabled": False,
        "avatar_path": None,
        "avatar_mime": None,
        "avatar_data": None,
        "default_organization_id": None,
        "is_active": False,
    }


# Full classification of every user-scoped table from the Art-20 export.
# Keyed by the export's collection name so the mapping is auditable
# side-by-side with data_export.build_user_export.
TABLE_POLICIES: tuple[TablePolicy, ...] = (
    TablePolicy("profile", Disposition.anonymise, "Subject row — tombstoned"),
    # --- deleted: conversational / notification / ancillary PII --------
    TablePolicy(
        "etorniegpt_chat_messages", Disposition.delete,
        "Conversational personal data; no retention basis",
    ),
    TablePolicy(
        "agent_messages", Disposition.delete,
        "AI assistant conversation content; no retention basis",
    ),
    TablePolicy(
        "agent_uploads", Disposition.delete,
        "User-uploaded working files (+ on-disk bytes); no retention basis",
    ),
    TablePolicy(
        "case_notes", Disposition.delete,
        "Free-text notes authored by the subject; no retention basis",
    ),
    TablePolicy(
        "in_app_notifications", Disposition.delete,
        "Delivered notifications addressed to the subject",
    ),
    TablePolicy(
        "notifications", Disposition.delete,
        "Notifications created by the subject",
    ),
    TablePolicy(
        "proposals", Disposition.delete,
        "Proposals authored by the subject; no retention basis",
    ),
    TablePolicy(
        "braid_feedback_events", Disposition.delete,
        "Model-calibration feedback tied to the subject",
    ),
    TablePolicy(
        "organization_memberships", Disposition.delete,
        "Severs the subject's organisation links",
    ),
    # --- retained: legal-claim / financial / on-chain / audit basis ----
    TablePolicy(
        "organization_invites", Disposition.retain,
        "Invite history retained; subject FKs nulled (SET NULL)",
    ),
    TablePolicy(
        "cases", Disposition.retain,
        "IP legal records, often on-chain attested (Art. 17(3)(b)/(e))",
    ),
    TablePolicy(
        "case_events", Disposition.retain,
        "Immutable case audit trail tied to retained cases",
    ),
    TablePolicy(
        "agent_sessions", Disposition.retain,
        "Session shells retained (messages deleted) to preserve the "
        "draft → payment chain; no identifying data remains",
    ),
    TablePolicy(
        "case_drafts", Disposition.retain,
        "Filing drafts backing financial/filing records",
    ),
    TablePolicy(
        "filing_attempts", Disposition.retain,
        "Official IP-office filing record",
    ),
    TablePolicy(
        "payment_intents", Disposition.retain,
        "Financial record — statutory retention (CH CO 958f / EU VAT, ~10y)",
    ),
    TablePolicy(
        "documents", Disposition.retain,
        "Evidence attached to retained IP cases (Art. 17(3)(e))",
    ),
    TablePolicy(
        "audit_logs", Disposition.retain,
        "Security/compliance audit trail — legal obligation",
    ),
)


def policies_by_disposition(disposition: Disposition) -> list[TablePolicy]:
    return [p for p in TABLE_POLICIES if p.disposition is disposition]


async def find_erasure_blockers(
    db: AsyncSession, user_id: uuid.UUID
) -> list[Case]:
    """Return the subject's cases that block erasure (active proceedings)."""

    rows = await db.execute(
        select(Case).where(
            Case.client_id == user_id,
            Case.status.in_(ERASURE_BLOCKING_STATUSES),
        )
    )
    return list(rows.scalars().all())
