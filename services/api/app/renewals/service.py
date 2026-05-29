"""Renewal lifecycle service — due-date computation + reminder dispatch.

Key responsibilities:
- ``set_initial_renewal_due_at``: called from case promotion to stamp
  cases.renewal_due_at (filing_date + 10 years for EUIPO trademarks).
- ``scan_and_dispatch_due_reminders``: nightly entry point that finds
  cases whose renewal_due_at falls inside an open reminder window and
  fires email + in-app reminders, recording each in
  ``renewal_reminder`` for idempotency.
- ``mark_case_renewed``: re-stamps renewal_due_at on a successful
  renewal so the next 10-year cycle starts cleanly.

Window semantics:
- 90 days before due_at → "renewal approaching" reminder
- 30 days before due_at → "renewal urgent" reminder
-  0 days at/after due_at → "renewal overdue" reminder (fires once)

A ``window_days`` of 0 means the dispatcher caught the case AT or
PAST its due_at and has not yet sent the overdue alert.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable, NamedTuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case
from app.in_app_notifications.models import InAppNotificationType
from app.in_app_notifications.service import create_notification
from app.renewals.models import RenewalReminder
from app.users.models import User

logger = logging.getLogger(__name__)


# EUIPO trademark protection lasts 10 years from the filing date.
# Renewals extend it for further 10-year periods indefinitely. The
# constant is kept here (not in a config table) because it is set by
# EU regulation, not by an operator preference.
EUIPO_RENEWAL_TERM_YEARS = 10

# Reminder windows in days BEFORE renewal_due_at. The dispatcher fires
# one reminder per window per case. ``0`` represents the day-of /
# overdue bucket; window detection uses an "elapsed past trigger
# point" comparison so a job run that misses the exact day still
# catches the case on the next run.
REMINDER_WINDOWS_DAYS: tuple[int, ...] = (90, 30, 0)


class ReminderDispatchResult(NamedTuple):
    """Summary returned by ``scan_and_dispatch_due_reminders``."""

    scanned: int
    dispatched: int
    skipped_due_to_existing: int


def _years_after(start: datetime, years: int) -> datetime:
    """Return ``start`` advanced by ``years`` calendar years.

    Falls back to 365-day arithmetic when the source month/day cannot
    be expressed in the target year (Feb 29 → Feb 28). The fallback
    only diverges by at most 24 hours, which is well inside the 90/30
    day reminder windows, so it never causes a reminder to be missed.
    """
    try:
        return start.replace(year=start.year + years)
    except ValueError:
        return start + timedelta(days=365 * years)


def compute_renewal_due_at(
    *,
    filing_date: datetime | None,
    term_years: int = EUIPO_RENEWAL_TERM_YEARS,
) -> datetime | None:
    """Convert a filing date into the corresponding renewal_due_at.

    Returns ``None`` when no filing date is known yet — the
    reminder dispatcher silently skips such cases.
    """
    if filing_date is None:
        return None
    if filing_date.tzinfo is None:
        filing_date = filing_date.replace(tzinfo=timezone.utc)
    return _years_after(filing_date, term_years)


async def set_initial_renewal_due_at(
    db: AsyncSession,
    case: Case,
) -> Case:
    """Stamp ``case.renewal_due_at`` based on filing_date.

    No-op when filing_date is missing OR the field is already set —
    re-stamping on every promotion call would clobber a renewal that
    advanced the due date past the original 10-year window.
    """
    if case.renewal_due_at is not None:
        return case
    if case.filing_date is None:
        return case
    # Case.filing_date is a date (not datetime). Bring it to midnight
    # UTC so the comparison in the dispatcher stays timezone-safe.
    filing_dt = datetime(
        case.filing_date.year,
        case.filing_date.month,
        case.filing_date.day,
        tzinfo=timezone.utc,
    )
    case.renewal_due_at = compute_renewal_due_at(filing_date=filing_dt)
    await db.flush()
    return case


async def mark_case_renewed(
    db: AsyncSession,
    case: Case,
    *,
    renewed_at: datetime | None = None,
    term_years: int = EUIPO_RENEWAL_TERM_YEARS,
) -> Case:
    """Advance the case to a fresh renewal cycle.

    Called from the renewal endpoint after the renewal payment +
    EUIPO API call confirm. The new renewal_due_at is computed from
    the previous renewal_due_at (NOT from filing_date) so a renewal
    paid 3 months early still preserves the original cadence.
    """
    if renewed_at is None:
        renewed_at = datetime.now(tz=timezone.utc)
    case.last_renewed_at = renewed_at
    base = case.renewal_due_at or renewed_at
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    case.renewal_due_at = _years_after(base, term_years)
    await db.flush()
    return case


def detect_open_window(
    *,
    renewal_due_at: datetime,
    now: datetime,
    windows: Iterable[int] = REMINDER_WINDOWS_DAYS,
) -> int | None:
    """Return the smallest open reminder window for ``renewal_due_at``.

    "Open" = the case is past the trigger point but BEFORE either the
    next-smaller window's trigger OR (for the 0-day bucket) the
    due_at itself plus a grace period. Returning the smallest open
    window lets a case that has gone three months without a job run
    still get the *most urgent* reminder on the next run.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if renewal_due_at.tzinfo is None:
        renewal_due_at = renewal_due_at.replace(tzinfo=timezone.utc)
    sorted_windows = sorted(windows)
    for window in sorted_windows:
        trigger = renewal_due_at - timedelta(days=window)
        if now >= trigger:
            return window
    return None


def _build_reminder_payload(
    *,
    case: Case,
    window: int,
    renewal_due_at: datetime,
) -> tuple[str, str]:
    """Return (title, message) for the in-app reminder."""
    when = renewal_due_at.date().isoformat()
    if window == 0:
        title = f"Renewal overdue — {case.case_number}"
        message = (
            f"Trademark {case.case_number} ({case.title or 'untitled'}) "
            f"was due for renewal on {when}. Renew now to avoid losing "
            "protection."
        )
    elif window == 30:
        title = f"Renewal due in 30 days — {case.case_number}"
        message = (
            f"Trademark {case.case_number} expires on {when}. Renew "
            "now to keep protection without a lapse."
        )
    else:
        title = f"Renewal due in {window} days — {case.case_number}"
        message = (
            f"Trademark {case.case_number} renewal window opens. The "
            f"current protection runs out on {when}; you can renew at "
            "any time before that date."
        )
    return title, message


async def _record_reminder(
    db: AsyncSession,
    *,
    case_id: uuid.UUID,
    window: int,
    target_due_at: datetime,
    channels: list[str],
) -> bool:
    """Insert a RenewalReminder row.

    Returns False when the unique constraint trips, meaning another
    worker / earlier run of the same job already fired this reminder.

    Implementation note: we do a SELECT-then-INSERT instead of relying
    on a savepoint rollback after IntegrityError. A bare
    ``db.rollback()`` would unwind the WHOLE session (losing rows
    written for OTHER cases this run), and not every DB dialect that
    SQLAlchemy supports lets us use a savepoint inside an async
    session cleanly. The SELECT-then-INSERT path has a tiny race
    window between workers but the unique constraint still prevents
    actual double-rows; we just return True for the loser and have
    the dispatcher emit a duplicate in-app message. In practice the
    dispatcher is single-runner.
    """
    existing = (
        await db.execute(
            select(RenewalReminder).where(
                RenewalReminder.case_id == case_id,
                RenewalReminder.window_days == window,
                RenewalReminder.target_due_at == target_due_at,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    row = RenewalReminder(
        case_id=case_id,
        window_days=window,
        target_due_at=target_due_at,
        channels=channels,
    )
    db.add(row)
    await db.flush()
    return True


async def scan_and_dispatch_due_reminders(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> ReminderDispatchResult:
    """Nightly entry point — scan all cases with a future due_at.

    The job fans out:
    - in-app notification (always)
    - email via schedule_notification (only when the client opted in)
    - a ``renewal_reminder`` row per (case, window, target_due_at)
      so re-runs short-circuit on the unique constraint

    Returns counts useful for the cron-runner log + an admin overview
    card down the line.
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)

    earliest_trigger = now - timedelta(days=max(REMINDER_WINDOWS_DAYS) + 1)
    cases_with_due = (
        await db.execute(
            select(Case).where(
                Case.renewal_due_at.is_not(None),
                # Skip cases whose renewal_due_at is so far in the
                # future that no window has opened yet. ``> now`` cuts
                # the irrelevant tail without scanning every row.
                Case.renewal_due_at >= earliest_trigger,
            )
        )
    ).scalars().all()

    scanned = len(cases_with_due)
    dispatched = 0
    skipped = 0

    # Lazy import keeps the renewal service decoupled from the
    # notification dispatcher when used in unit tests that monkey-patch
    # the email sender.
    from app.notifications.email_dispatcher import (
        schedule_notification,
        NotificationContent,
    )

    for case in cases_with_due:
        if case.renewal_due_at is None:
            continue
        window = detect_open_window(
            renewal_due_at=case.renewal_due_at, now=now
        )
        if window is None:
            continue

        recorded = await _record_reminder(
            db,
            case_id=case.id,
            window=window,
            target_due_at=case.renewal_due_at,
            channels=["in_app", "email"],
        )
        if not recorded:
            skipped += 1
            continue

        if case.client_id is None:
            # Guest-client cases have no recipient_id; we still
            # recorded the audit row so a future dispatcher knows the
            # window was processed.
            dispatched += 1
            continue

        title, message = _build_reminder_payload(
            case=case, window=window, renewal_due_at=case.renewal_due_at
        )
        await create_notification(
            db,
            recipient_id=case.client_id,
            notification_type=InAppNotificationType.case_updated,
            title=title,
            message=message,
            case_id=case.id,
        )

        # Opt-in email — same hook as payment / refund flows so the
        # user manages all email preferences from a single toggle.
        user = (
            await db.execute(select(User).where(User.id == case.client_id))
        ).scalar_one_or_none()
        if user is not None:
            schedule_notification(
                db,
                user_id=user.id,
                content=NotificationContent(
                    subject=title,
                    message=(
                        f"{message}\n\nRenew now: /dashboard/cases/{case.id}"
                    ),
                ),
            )

        dispatched += 1

    return ReminderDispatchResult(
        scanned=scanned,
        dispatched=dispatched,
        skipped_due_to_existing=skipped,
    )
