"""Service layer that bridges DB rows to the Playwright robot.

The service is the only module that knows about both ``UKIPOSubmission``
SQLAlchemy rows and the robot's ``RobotInput`` dataclass — the robot
itself stays DB-unaware so it can be unit-tested or run from a CLI.

The runner is injected (``runner`` parameter on ``run_submission``) so
tests can substitute a fake without touching Playwright.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case, CaseNote
from app.config import settings
from app.database import async_session
from app.proposals.models import Proposal, ProposalStatus
from app.services.ukipo import robot as robot_module
from app.services.ukipo.models import (
    UKIPOMarkType,
    UKIPOOwnerEntityType,
    UKIPOSubmission,
    UKIPOSubmissionStatus,
)
from app.services.ukipo.robot import (
    NiceClassInput,
    OwnerData,
    RepresentativeData,
    RobotInput,
    RobotResult,
)

logger = logging.getLogger(__name__)

RobotRunner = Callable[..., Awaitable[RobotResult]]

# In-process registry of in-flight robot tasks keyed by submission id.
# Lets the run endpoint refuse a duplicate kick-off and gives the
# operator a hook to cancel later if needed. The map is per-process
# (single-replica deployments are fine; for multi-replica we'd need a
# Redis lock instead).
_RUNNING_TASKS: dict[uuid.UUID, asyncio.Task[None]] = {}


# Local UK normalisation set — duplicated in schemas.py and robot.py
# on purpose so each layer can validate without coupling.
_UK_COUNTRY_VALUES = frozenset({
    "united kingdom",
    "uk",
    "gb",
    "great britain",
    "england",
    "scotland",
    "wales",
    "northern ireland",
})


def is_uk_jurisdiction(country: str | None) -> bool:
    if not country:
        return False
    return country.strip().lower() in _UK_COUNTRY_VALUES


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def create_submission(
    db: AsyncSession,
    *,
    case_id: uuid.UUID,
    owner_company_name: str,
    owner_country: str,
    owner_address_line1: str,
    owner_address_line2: str | None,
    owner_city: str,
    owner_postcode: str | None,
    owner_email: str | None,
    owner_phone: str | None,
    owner_entity_type: UKIPOOwnerEntityType,
    owner_company_registration_number: str | None,
    mark_type: UKIPOMarkType,
    mark_text: str | None,
    mark_image_path: str | None,
    nice_classes: list[dict[str, Any]],
) -> UKIPOSubmission:
    """Persist a new submission in pending state.

    Performs the same UK postcode check as the API and robot layers —
    if any caller bypasses Pydantic, we still refuse to write a broken
    snapshot.
    """
    if is_uk_jurisdiction(owner_country) and not (
        owner_postcode and owner_postcode.strip()
    ):
        raise ValueError(
            "owner_postcode is required when owner_country is in the United Kingdom"
        )

    submission = UKIPOSubmission(
        case_id=case_id,
        owner_company_name=owner_company_name,
        owner_country=owner_country,
        owner_address_line1=owner_address_line1,
        owner_address_line2=owner_address_line2,
        owner_city=owner_city,
        owner_postcode=owner_postcode,
        owner_email=owner_email,
        owner_phone=owner_phone,
        owner_entity_type=owner_entity_type,
        owner_company_registration_number=owner_company_registration_number,
        mark_type=mark_type,
        mark_text=mark_text,
        mark_image_path=mark_image_path,
        nice_classes_json=json.dumps(nice_classes),
        status=UKIPOSubmissionStatus.pending,
    )
    db.add(submission)
    await db.flush()
    await db.refresh(submission)

    # Fire-and-forget conflict check. UK IPO has its own search but a
    # 2nd-opinion BRAID audit lets the lawyer see external matches
    # before the robot starts typing — strictly an audit signal.
    if mark_text and mark_text.strip():
        try:
            from app.braid.hooks import check_conflict_for_filing

            await check_conflict_for_filing(
                db,
                submission_id=submission.id,
                case_id=case_id,
                mark_text=mark_text.strip(),
                nice_classes=[
                    int(c["class_number"])
                    for c in nice_classes
                    if isinstance(c.get("class_number"), int)
                ],
                jurisdiction="uk",
            )
        except Exception:  # noqa: BLE001
            pass

    return submission


async def get_submission(
    db: AsyncSession, submission_id: uuid.UUID
) -> UKIPOSubmission | None:
    result = await db.execute(
        select(UKIPOSubmission).where(UKIPOSubmission.id == submission_id)
    )
    return result.scalar_one_or_none()


async def list_submissions_for_case(
    db: AsyncSession, case_id: uuid.UUID
) -> list[UKIPOSubmission]:
    result = await db.execute(
        select(UKIPOSubmission)
        .where(UKIPOSubmission.case_id == case_id)
        .order_by(UKIPOSubmission.created_at.desc())
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Robot input construction
# ---------------------------------------------------------------------------


def _require_env(name: str, value: str) -> str:
    if not value or not value.strip():
        raise RuntimeError(
            f"environment variable {name} is required to run the UK IPO robot"
        )
    return value


def build_representative_from_settings() -> RepresentativeData:
    """Read representative details from settings — fail loudly if unset."""
    return RepresentativeData(
        entity_type=_require_env("UKIPO_REP_ENTITY_TYPE", settings.ukipo_rep_entity_type),
        name=_require_env("UKIPO_REP_NAME", settings.ukipo_rep_name),
        email=_require_env("UKIPO_REP_EMAIL", settings.ukipo_rep_email),
        phone=_require_env("UKIPO_REP_PHONE", settings.ukipo_rep_phone),
        address_line1=_require_env(
            "UKIPO_REP_ADDRESS_LINE1", settings.ukipo_rep_address_line1
        ),
        address_line2=settings.ukipo_rep_address_line2 or None,
        city=_require_env("UKIPO_REP_CITY", settings.ukipo_rep_city),
        postcode=_require_env("UKIPO_REP_POSTCODE", settings.ukipo_rep_postcode),
        country=_require_env("UKIPO_REP_COUNTRY", settings.ukipo_rep_country),
    )


def build_robot_input(
    submission_dict: dict[str, Any],
    *,
    representative: RepresentativeData | None = None,
    declarant_name: str | None = None,
) -> RobotInput:
    """Translate a flat submission snapshot into a ``RobotInput``.

    ``submission_dict`` is plucked from a SQLAlchemy row (see
    ``_submission_to_dict``) so we don't keep a session-bound entity
    alive across the long Playwright run.
    """
    classes_raw = submission_dict["nice_classes"]
    if not classes_raw:
        raise ValueError("at least one Nice class is required")
    classes = [
        NiceClassInput(
            class_number=int(c["class_number"]),
            description=str(c["description"]),
        )
        for c in classes_raw
    ]
    owner = OwnerData(
        company_name=submission_dict["owner_company_name"],
        country=submission_dict["owner_country"],
        address_line1=submission_dict["owner_address_line1"],
        address_line2=submission_dict.get("owner_address_line2"),
        city=submission_dict["owner_city"],
        postcode=submission_dict.get("owner_postcode"),
        email=submission_dict.get("owner_email"),
        phone=submission_dict.get("owner_phone"),
        entity_type=UKIPOOwnerEntityType(submission_dict["owner_entity_type"]),
        company_registration_number=submission_dict.get(
            "owner_company_registration_number"
        ),
    )
    rep = representative or build_representative_from_settings()
    decl = declarant_name or _require_env(
        "UKIPO_DECLARANT_NAME", settings.ukipo_declarant_name
    )
    return RobotInput(
        owner=owner,
        representative=rep,
        declarant_name=decl,
        mark_type=UKIPOMarkType(submission_dict["mark_type"]),
        mark_text=submission_dict.get("mark_text"),
        mark_image_path=submission_dict.get("mark_image_path"),
        nice_classes=classes,
        submission_id=str(submission_dict["id"]),
    )


def _submission_to_dict(submission: UKIPOSubmission) -> dict[str, Any]:
    return {
        "id": submission.id,
        "owner_company_name": submission.owner_company_name,
        "owner_country": submission.owner_country,
        "owner_address_line1": submission.owner_address_line1,
        "owner_address_line2": submission.owner_address_line2,
        "owner_city": submission.owner_city,
        "owner_postcode": submission.owner_postcode,
        "owner_email": submission.owner_email,
        "owner_phone": submission.owner_phone,
        "owner_entity_type": submission.owner_entity_type.value,
        "owner_company_registration_number": (
            submission.owner_company_registration_number
        ),
        "mark_type": submission.mark_type.value,
        "mark_text": submission.mark_text,
        "mark_image_path": submission.mark_image_path,
        "nice_classes": json.loads(submission.nice_classes_json),
    }


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


async def _mark_failed(
    db: AsyncSession,
    submission: UKIPOSubmission,
    step: str,
    message: str,
) -> None:
    submission.status = UKIPOSubmissionStatus.failed
    submission.error_step = step
    submission.error_message = message[:5000] if message else None
    submission.finished_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(submission)


async def _update_step(submission_id: uuid.UUID, step: str) -> None:
    """Persist ``current_step`` from inside the background robot task.

    The background task owns its own session — separate from the HTTP
    request that scheduled it — because the request-scoped session is
    closed long before the robot finishes.
    """
    async with async_session() as session:
        submission = await session.get(UKIPOSubmission, submission_id)
        if submission is None:
            logger.warning(
                "ukipo: progress update for missing submission %s", submission_id
            )
            return
        submission.current_step = step
        await session.commit()


async def _execute_robot(
    submission_id: uuid.UUID,
    *,
    runner: RobotRunner | None,
    headless: bool,
    screenshot_dir: str | None,
) -> None:
    """Body of the background task that drives the Playwright robot.

    Runs in its own session and writes the final state directly. Never
    raises out of the task (that would just become an unhandled
    asyncio warning); turns every failure into a ``status=failed`` row.
    """
    base_dir = screenshot_dir or settings.ukipo_screenshot_dir
    use_runner: RobotRunner = runner or robot_module.run_submission

    try:
        async with async_session() as session:
            submission = await session.get(UKIPOSubmission, submission_id)
            if submission is None:
                logger.warning("ukipo: background task lost submission %s", submission_id)
                return
            snapshot = _submission_to_dict(submission)
        try:
            robot_input = build_robot_input(snapshot)
        except Exception as exc:
            async with async_session() as session:
                submission = await session.get(UKIPOSubmission, submission_id)
                if submission is not None:
                    await _mark_failed(session, submission, "build_input", str(exc))
                    await session.commit()
            return

        async def progress(step: str) -> None:
            await _update_step(submission_id, step)

        try:
            result = await use_runner(
                robot_input,
                headless=headless,
                screenshot_dir=base_dir,
                on_step_start=progress,
            )
        except Exception as exc:
            async with async_session() as session:
                submission = await session.get(UKIPOSubmission, submission_id)
                if submission is not None:
                    await _mark_failed(session, submission, "robot_runtime", str(exc))
                    await session.commit()
            return

        async with async_session() as session:
            submission = await session.get(UKIPOSubmission, submission_id)
            if submission is None:
                return
            submission.current_step = result.current_step
            submission.screenshot_path = result.screenshot_path
            submission.ipo_application_url = result.ipo_application_url
            submission.finished_at = datetime.now(timezone.utc)
            if result.success:
                submission.status = UKIPOSubmissionStatus.awaiting_payment
                submission.error_step = None
                submission.error_message = None
            else:
                submission.status = UKIPOSubmissionStatus.failed
                submission.error_step = result.error_step or result.current_step
                submission.error_message = (
                    result.error_message[:5000] if result.error_message else None
                )
            await _log_case_note(session, submission)
            await session.commit()
    finally:
        _RUNNING_TASKS.pop(submission_id, None)


async def start_submission_run(
    db: AsyncSession,
    submission: UKIPOSubmission,
    *,
    runner: RobotRunner | None = None,
    headless: bool = True,
    screenshot_dir: str | None = None,
) -> UKIPOSubmission:
    """Mark the submission running and dispatch the robot in the background.

    Returns the submission immediately so the HTTP layer can respond
    fast; the actual Playwright drive runs as an asyncio task and writes
    its own progress and outcome via ``async_session``.
    """
    if submission.status not in (
        UKIPOSubmissionStatus.pending,
        UKIPOSubmissionStatus.failed,
    ):
        raise ValueError(
            f"submission {submission.id} cannot be run from status="
            f"{submission.status.value}"
        )
    if submission.id in _RUNNING_TASKS:
        existing = _RUNNING_TASKS[submission.id]
        if not existing.done():
            raise ValueError(
                f"submission {submission.id} is already running"
            )

    submission.status = UKIPOSubmissionStatus.running
    submission.started_at = datetime.now(timezone.utc)
    submission.finished_at = None
    submission.error_step = None
    submission.error_message = None
    submission.current_step = None
    submission.ipo_application_url = None
    submission.screenshot_path = None
    await db.flush()
    await db.commit()
    await db.refresh(submission)

    submission_id = submission.id

    async def _runner() -> None:
        await _execute_robot(
            submission_id,
            runner=runner,
            headless=headless,
            screenshot_dir=screenshot_dir,
        )

    task = asyncio.create_task(_runner(), name=f"ukipo-run-{submission_id}")
    _RUNNING_TASKS[submission_id] = task
    return submission


async def run_submission(
    db: AsyncSession,
    submission: UKIPOSubmission,
    *,
    runner: RobotRunner | None = None,
    headless: bool = True,
    screenshot_dir: str | None = None,
) -> UKIPOSubmission:
    """Synchronous run used by tests + CLI tooling.

    Production HTTP traffic should call :func:`start_submission_run`
    instead so the robot runs in the background and the request can
    return immediately.
    """
    if submission.status not in (
        UKIPOSubmissionStatus.pending,
        UKIPOSubmissionStatus.failed,
    ):
        raise ValueError(
            f"submission {submission.id} cannot be run from status="
            f"{submission.status.value}"
        )

    submission.status = UKIPOSubmissionStatus.running
    submission.started_at = datetime.now(timezone.utc)
    submission.error_step = None
    submission.error_message = None
    submission.current_step = None
    await db.flush()

    snapshot = _submission_to_dict(submission)
    try:
        robot_input = build_robot_input(snapshot)
    except Exception as exc:
        await _mark_failed(db, submission, "build_input", str(exc))
        return submission

    use_runner: RobotRunner = runner or robot_module.run_submission
    base_dir = screenshot_dir or settings.ukipo_screenshot_dir

    async def progress(step: str) -> None:
        submission.current_step = step
        await db.flush()

    try:
        result = await use_runner(
            robot_input,
            headless=headless,
            screenshot_dir=base_dir,
            on_step_start=progress,
        )
    except Exception as exc:
        await _mark_failed(db, submission, "robot_runtime", str(exc))
        return submission

    submission.current_step = result.current_step
    submission.screenshot_path = result.screenshot_path
    submission.ipo_application_url = result.ipo_application_url
    submission.finished_at = datetime.now(timezone.utc)
    if result.success:
        submission.status = UKIPOSubmissionStatus.awaiting_payment
        submission.error_step = None
        submission.error_message = None
    else:
        submission.status = UKIPOSubmissionStatus.failed
        submission.error_step = result.error_step or result.current_step
        submission.error_message = (
            result.error_message[:5000] if result.error_message else None
        )

    await db.flush()
    await db.refresh(submission)
    await _log_case_note(db, submission)
    return submission


async def _log_case_note(
    db: AsyncSession, submission: UKIPOSubmission
) -> None:
    """Append a human-readable case note for the operator timeline."""
    case = await db.get(Case, submission.case_id)
    if case is None:
        return
    actor = case.assigned_lawyer_id or case.client_id
    if actor is None:
        return
    if submission.status == UKIPOSubmissionStatus.awaiting_payment:
        body = (
            f"UK IPO robot reached the payment screen. "
            f"Application URL (session-bound): {submission.ipo_application_url}"
        )
    else:
        body = (
            f"UK IPO robot failed at step={submission.error_step!r}: "
            f"{submission.error_message}"
        )
    note = CaseNote(case_id=case.id, author_id=actor, content=body)
    db.add(note)
    await db.flush()


# ---------------------------------------------------------------------------
# Proposal-acceptance trigger
# ---------------------------------------------------------------------------


async def build_payment_requirements(
    submission: UKIPOSubmission,
) -> dict[str, Any]:
    """Return the Solana payment requirements for ``submission``.

    Raises ``RuntimeError`` if the vault wallet isn't configured —
    fail-closed so a misconfigured deploy never asks a client to send
    SOL into a black hole.
    """
    if not settings.ukipo_payment_vault.strip():
        raise RuntimeError(
            "UKIPO_PAYMENT_VAULT is not configured; refusing to issue "
            "payment requirements"
        )
    return {
        "network": "solana",
        "asset": "SOL",
        "recipient": settings.ukipo_payment_vault,
        "lamports": settings.ukipo_payment_lamports,
        "memo": f"ukipo:{submission.id}",
        "cluster_url": settings.solana_cluster_url,
    }


async def record_solana_payment(
    db: AsyncSession,
    submission: UKIPOSubmission,
    *,
    payment_tx: str,
    payer_wallet: str,
) -> UKIPOSubmission:
    """Verify the on-chain SOL payment and stamp it onto the submission.

    Only acceptable from ``awaiting_payment`` state — any other status
    means the robot hasn't reached the pay screen, the row is stale,
    or someone is replaying. Idempotent on the same tx signature.
    """
    if submission.status != UKIPOSubmissionStatus.awaiting_payment:
        raise ValueError(
            f"submission must be in awaiting_payment state to record "
            f"a Solana payment (current={submission.status.value})"
        )
    if (
        submission.solana_payment_tx
        and submission.solana_payment_tx != payment_tx
    ):
        raise ValueError(
            "submission already has a different Solana payment recorded"
        )
    if not settings.ukipo_payment_vault.strip():
        raise RuntimeError("UKIPO_PAYMENT_VAULT is not configured")

    # Verify the on-chain tx using the existing solana helper. We
    # import here to avoid pulling solana-py into module import
    # graph (ukipo modules can be imported in environments where
    # solana isn't installed, e.g. unit tests).
    from solders.pubkey import Pubkey

    from app.solana.client import SolanaClientError, verify_payment_tx

    try:
        recipient = Pubkey.from_string(settings.ukipo_payment_vault)
    except Exception as exc:
        raise RuntimeError(f"invalid UKIPO_PAYMENT_VAULT: {exc}") from exc

    expected_memo = f"ukipo:{submission.id}"
    try:
        await verify_payment_tx(
            payment_tx,
            expected_recipient=recipient,
            min_lamports=settings.ukipo_payment_lamports,
            expected_memo=expected_memo,
        )
    except SolanaClientError as exc:
        raise ValueError(f"Solana payment verification failed: {exc}") from exc

    submission.solana_payment_tx = payment_tx
    submission.solana_payer_wallet = payer_wallet
    submission.solana_payment_lamports = settings.ukipo_payment_lamports
    submission.solana_payment_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(submission)

    case = await db.get(Case, submission.case_id)
    actor = (
        (case.assigned_lawyer_id or case.client_id) if case is not None else None
    )
    if case is not None and actor is not None:
        note = CaseNote(
            case_id=case.id,
            author_id=actor,
            content=(
                f"Client funded UK IPO filing on Solana. Tx: {payment_tx} "
                f"({settings.ukipo_payment_lamports} lamports from "
                f"{payer_wallet}). Etornie will now complete the £265 IPO "
                f"payment off-platform."
            ),
        )
        db.add(note)
        await db.flush()

    return submission


async def trigger_from_proposal_acceptance(
    db: AsyncSession,
    proposal: Proposal,
) -> UKIPOSubmission | None:
    """Hook for proposal acceptance.

    Logs a case note when a UK proposal is accepted but does NOT create
    a submission row automatically — Case rows don't carry owner address
    fields, so the operator must start the form manually with real data.
    Non-UK proposals are a no-op.
    """
    if proposal.status != ProposalStatus.accepted:
        return None
    if not is_uk_jurisdiction(proposal.country_name):
        return None

    case = await db.get(Case, proposal.case_id)
    if case is None:
        return None
    actor = case.assigned_lawyer_id or proposal.created_by
    if actor is None:
        return None
    note = CaseNote(
        case_id=case.id,
        author_id=actor,
        content=(
            "UK proposal accepted — start the UK IPO filing robot from the "
            "case workspace once the owner address is collected. Automatic "
            "submission was skipped because the case profile does not yet "
            "carry the owner postal address required by IPO."
        ),
    )
    db.add(note)
    await db.flush()
    return None
