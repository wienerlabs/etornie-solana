"""Response shapes for the admin operator panel.

These DTOs trim each underlying row to the fields the operator panel
actually needs (id, status, monetary value, last error). They never
echo full Stripe / EUIPO payloads or raw token blobs — operator
debugging happens through Sentry + Postgres directly.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AdminPaymentRow(_Base):
    id: uuid.UUID
    case_draft_id: uuid.UUID | None
    user_id: uuid.UUID | None
    user_email: str | None
    user_full_name: str | None
    provider: str
    payment_type: str
    status: str
    amount: Decimal
    currency: str
    gateway_payment_id: str | None
    idempotency_key: str | None
    refund_id: str | None
    refund_amount: Decimal | None
    refund_status: str | None
    filing_external_reference: str | None
    filing_status: str | None
    filing_error: str | None
    case_id: uuid.UUID | None
    case_number: str | None
    compliance_onchain_tx: str | None
    auto_submit_committed_at: str | None
    created_at: datetime
    confirmed_at: datetime | None


class AdminFilingRow(_Base):
    id: uuid.UUID
    case_draft_id: uuid.UUID
    platform: str
    status: str
    attempt_number: int
    external_reference: str | None
    error_message: str | None
    submitted_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    case_draft_mark_text: str | None
    case_draft_user_id: uuid.UUID | None
    case_draft_user_email: str | None


class AdminCaseRow(_Base):
    id: uuid.UUID
    case_number: str
    title: str | None
    case_type: str
    jurisdiction: str | None
    status: str
    client_id: uuid.UUID | None
    client_email: str | None
    client_wallet: str | None
    nft_state: str | None
    nft_mint: str | None
    attestation_tx: str | None
    filing_date: datetime | None
    deadline: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminOverviewCounts(_Base):
    """Snapshot counts surfaced on the admin overview cards.

    Every counter is computed by COUNT(*) GROUP BY, so the response
    stays O(distinct-status) regardless of how large the underlying
    tables grow.
    """

    users_total: int
    users_active: int
    cases_total: int
    cases_by_status: dict[str, int]
    payments_total: int
    payments_by_status: dict[str, int]
    payments_confirmed_amount: dict[str, Decimal]
    filings_total: int
    filings_by_status: dict[str, int]
    nft_states: dict[str, int]


class AdminListResponse(_Base):
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


class AdminRetryFilingResponse(_Base):
    filing_attempt_id: uuid.UUID
    status: str
    external_reference: str | None
    error: str | None


# ---------------------------------------------------------------------------
# Analytics (system-wide, admin-only)
# ---------------------------------------------------------------------------


class AdminUpcomingRenewal(_Base):
    case_id: uuid.UUID
    case_number: str
    client_email: str | None
    renewal_due_at: datetime
    days_remaining: int
    is_overdue: bool


class AdminAnalyticsSummary(_Base):
    """System-wide analytics across all users.

    The dashboard surfaces this on the operator Analytics tab. Money
    is kept per-currency (cross-currency sums are misleading); filing
    success rate excludes pending / retrying from the denominator.
    """

    cases_total: int
    cases_open: int
    cases_closed: int
    filings_total: int
    filings_successful: int
    filings_failed: int
    filing_success_rate: float | None
    total_revenue_by_currency: dict[str, Decimal]
    total_refunded_by_currency: dict[str, Decimal]
    nft_states: dict[str, int]
    upcoming_renewals: list[AdminUpcomingRenewal]


class AdminTimelineEvent(_Base):
    """One row in the system-wide chronological event feed."""

    kind: str
    case_id: uuid.UUID | None
    case_number: str | None
    client_email: str | None
    occurred_at: datetime
    summary: str
    payload: dict


class AdminAnalyticsTimeline(_Base):
    events: list[AdminTimelineEvent]
    total: int
    page: int
    page_size: int
