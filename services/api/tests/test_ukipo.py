"""Tests for the UK IPO trade mark filing robot pipeline.

Covers the four risk surfaces highlighted in the spec:

* UK postcode validation across the API → service → robot katmans
  (defense in depth — each layer must reject independently).
* ``is_uk`` normalisation (positive + edge cases like Gibraltar).
* CRUD: create_submission persists with status=pending.
* Proposal-acceptance trigger: UK proposals log a note instead of
  silently creating a submission with placeholder data; non-UK
  proposals are a no-op.
* ``build_robot_input`` parses flat snapshots and rejects broken ones.

The Playwright runner is replaced with a fake throughout — these are
unit tests, not browser integration tests.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case, CaseNote, CaseStatus, CaseType
from app.proposals.models import Proposal, ProposalStatus
from app.services.ukipo import service as ukipo_service
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
from app.services.ukipo.schemas import (
    NiceClassEntry,
    OwnerDetails,
    UKIPOSubmissionCreateRequest,
)
from app.users.models import User
from sqlalchemy import select


# ---------------------------------------------------------------------------
# is_uk helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "country",
    [
        "United Kingdom",
        "united kingdom",
        "uk",
        "UK",
        "GB",
        "gb",
        "Great Britain",
        "England",
        "Scotland",
        "Wales",
        "Northern Ireland",
    ],
)
def test_is_uk_jurisdiction_matches(country: str) -> None:
    assert ukipo_service.is_uk_jurisdiction(country) is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "country",
    [
        "Germany",
        "France",
        "",
        None,
        "US",
        "Gibraltar (United Kingdom)",
        "Jersey (United Kingdom)",
    ],
)
def test_is_uk_jurisdiction_rejects(country: str | None) -> None:
    assert ukipo_service.is_uk_jurisdiction(country) is False


# ---------------------------------------------------------------------------
# Pydantic OwnerDetails — UK postcode rule
# ---------------------------------------------------------------------------


def _valid_owner_kwargs(**overrides: object) -> dict[str, object]:
    base = dict(
        company_name="Acme Ltd",
        country="United Kingdom",
        address_line1="221B Baker Street",
        address_line2=None,
        city="London",
        postcode="NW1 6XE",
        email="ops@acme.example",
        phone="+44 20 1234 5678",
        entity_type=UKIPOOwnerEntityType.individuals,
        company_registration_number=None,
    )
    base.update(overrides)
    return base


@pytest.mark.unit
def test_owner_details_rejects_uk_country_without_postcode() -> None:
    with pytest.raises(ValueError, match="postcode is required"):
        OwnerDetails(**_valid_owner_kwargs(postcode=None))


@pytest.mark.unit
def test_owner_details_rejects_uk_country_with_blank_postcode() -> None:
    with pytest.raises(ValueError, match="postcode is required"):
        OwnerDetails(**_valid_owner_kwargs(postcode="   "))


@pytest.mark.unit
def test_owner_details_accepts_uk_with_postcode() -> None:
    owner = OwnerDetails(**_valid_owner_kwargs())
    assert owner.postcode == "NW1 6XE"


@pytest.mark.unit
def test_owner_details_accepts_non_uk_without_postcode() -> None:
    owner = OwnerDetails(
        **_valid_owner_kwargs(country="Germany", postcode=None, city="Berlin")
    )
    assert owner.postcode is None
    assert owner.country == "Germany"


@pytest.mark.unit
def test_owner_details_uk_registered_company_requires_company_number() -> None:
    with pytest.raises(ValueError, match="company_registration_number"):
        OwnerDetails(
            **_valid_owner_kwargs(
                entity_type=UKIPOOwnerEntityType.registered_company_or_llp,
                company_registration_number=None,
            )
        )


# ---------------------------------------------------------------------------
# OwnerData (robot dataclass) — second layer of validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_owner_data_rejects_uk_without_postcode() -> None:
    with pytest.raises(ValueError, match="postcode is required"):
        OwnerData(
            company_name="Acme",
            country="UK",
            address_line1="1 High St",
            address_line2=None,
            city="London",
            postcode=None,
            email=None,
            phone=None,
            entity_type=UKIPOOwnerEntityType.individuals,
            company_registration_number=None,
        )


# ---------------------------------------------------------------------------
# build_robot_input
# ---------------------------------------------------------------------------


def _representative() -> RepresentativeData:
    return RepresentativeData(
        entity_type="IP Professional",
        name="Jane Doe",
        email="jane@uk-rep.example",
        phone="+44 20 0000 0000",
        address_line1="10 Downing Street",
        address_line2=None,
        city="London",
        postcode="SW1A 2AA",
        country="United Kingdom",
    )


@pytest.mark.unit
def test_build_robot_input_builds_from_flat_fields() -> None:
    snapshot = {
        "id": uuid.uuid4(),
        "owner_company_name": "Acme",
        "owner_country": "United Kingdom",
        "owner_address_line1": "221B Baker St",
        "owner_address_line2": None,
        "owner_city": "London",
        "owner_postcode": "NW1 6XE",
        "owner_email": None,
        "owner_phone": None,
        "owner_entity_type": UKIPOOwnerEntityType.individuals.value,
        "owner_company_registration_number": None,
        "mark_type": UKIPOMarkType.word.value,
        "mark_text": "ACME",
        "mark_image_path": None,
        "nice_classes": [{"class_number": 25, "description": "T-shirts"}],
    }
    inp = ukipo_service.build_robot_input(
        snapshot,
        representative=_representative(),
        declarant_name="Jane Doe",
    )
    assert inp.owner.company_name == "Acme"
    assert inp.mark_type == UKIPOMarkType.word
    assert len(inp.nice_classes) == 1
    assert inp.nice_classes[0].class_number == 25


@pytest.mark.unit
def test_build_robot_input_rejects_empty_classes() -> None:
    snapshot = {
        "id": uuid.uuid4(),
        "owner_company_name": "Acme",
        "owner_country": "United Kingdom",
        "owner_address_line1": "221B Baker St",
        "owner_address_line2": None,
        "owner_city": "London",
        "owner_postcode": "NW1 6XE",
        "owner_email": None,
        "owner_phone": None,
        "owner_entity_type": UKIPOOwnerEntityType.individuals.value,
        "owner_company_registration_number": None,
        "mark_type": UKIPOMarkType.word.value,
        "mark_text": "ACME",
        "mark_image_path": None,
        "nice_classes": [],
    }
    with pytest.raises(ValueError, match="Nice class"):
        ukipo_service.build_robot_input(
            snapshot,
            representative=_representative(),
            declarant_name="Jane Doe",
        )


@pytest.mark.unit
def test_build_robot_input_rejects_broken_uk_snapshot() -> None:
    """A snapshot somehow saved without postcode (legacy migration etc.)
    must blow up at build time, before the robot starts typing."""
    snapshot = {
        "id": uuid.uuid4(),
        "owner_company_name": "Acme",
        "owner_country": "United Kingdom",
        "owner_address_line1": "221B Baker St",
        "owner_address_line2": None,
        "owner_city": "London",
        "owner_postcode": None,  # broken
        "owner_email": None,
        "owner_phone": None,
        "owner_entity_type": UKIPOOwnerEntityType.individuals.value,
        "owner_company_registration_number": None,
        "mark_type": UKIPOMarkType.word.value,
        "mark_text": "ACME",
        "mark_image_path": None,
        "nice_classes": [{"class_number": 25, "description": "T-shirts"}],
    }
    with pytest.raises(ValueError, match="postcode"):
        ukipo_service.build_robot_input(
            snapshot,
            representative=_representative(),
            declarant_name="Jane Doe",
        )


# ---------------------------------------------------------------------------
# UKIPOSubmissionCreateRequest — composite Pydantic validation
# ---------------------------------------------------------------------------


def _create_request_kwargs(**owner_overrides: object) -> dict[str, object]:
    return dict(
        case_id=uuid.uuid4(),
        owner=OwnerDetails(**_valid_owner_kwargs(**owner_overrides)),
        mark_type=UKIPOMarkType.word,
        mark_text="ACME",
        mark_image_path=None,
        nice_classes=[NiceClassEntry(class_number=25, description="T-shirts")],
    )


@pytest.mark.unit
def test_create_request_rejects_word_mark_without_text() -> None:
    with pytest.raises(ValueError, match="mark_text"):
        UKIPOSubmissionCreateRequest(
            **{**_create_request_kwargs(), "mark_text": None}
        )


@pytest.mark.unit
def test_create_request_rejects_figurative_without_image() -> None:
    with pytest.raises(ValueError, match="mark_image_path"):
        UKIPOSubmissionCreateRequest(
            **{
                **_create_request_kwargs(),
                "mark_type": UKIPOMarkType.figurative,
                "mark_text": None,
                "mark_image_path": None,
            }
        )


@pytest.mark.unit
def test_create_request_rejects_duplicate_classes() -> None:
    with pytest.raises(ValueError, match="duplicate Nice class"):
        UKIPOSubmissionCreateRequest(
            **{
                **_create_request_kwargs(),
                "nice_classes": [
                    NiceClassEntry(class_number=25, description="T-shirts"),
                    NiceClassEntry(class_number=25, description="Jeans"),
                ],
            }
        )


# ---------------------------------------------------------------------------
# create_submission service
# ---------------------------------------------------------------------------


@pytest.fixture
async def case_fixture_uk(
    db_session: AsyncSession, client_user: User, lawyer_user: User
) -> Case:
    case = Case(
        case_number="ETR-2026-9001",
        title="UK IPO Test Case",
        case_type=CaseType.trademark,
        status=CaseStatus.open,
        client_id=client_user.id,
        assigned_lawyer_id=lawyer_user.id,
        jurisdiction="United Kingdom",
        nice_classes="25",
    )
    db_session.add(case)
    await db_session.flush()
    await db_session.refresh(case)
    return case


@pytest.mark.integration
async def test_create_submission_persists_with_pending_status(
    db_session: AsyncSession, case_fixture_uk: Case
) -> None:
    submission = await ukipo_service.create_submission(
        db_session,
        case_id=case_fixture_uk.id,
        owner_company_name="Acme Ltd",
        owner_country="United Kingdom",
        owner_address_line1="221B Baker St",
        owner_address_line2=None,
        owner_city="London",
        owner_postcode="NW1 6XE",
        owner_email=None,
        owner_phone=None,
        owner_entity_type=UKIPOOwnerEntityType.individuals,
        owner_company_registration_number=None,
        mark_type=UKIPOMarkType.word,
        mark_text="ACME",
        mark_image_path=None,
        nice_classes=[{"class_number": 25, "description": "T-shirts"}],
    )
    assert submission.status == UKIPOSubmissionStatus.pending
    assert submission.case_id == case_fixture_uk.id
    assert json.loads(submission.nice_classes_json) == [
        {"class_number": 25, "description": "T-shirts"}
    ]


@pytest.mark.integration
async def test_create_submission_rejects_uk_without_postcode(
    db_session: AsyncSession, case_fixture_uk: Case
) -> None:
    """Even if Pydantic is bypassed, the service refuses to write a
    UK row without a postcode."""
    with pytest.raises(ValueError, match="postcode is required"):
        await ukipo_service.create_submission(
            db_session,
            case_id=case_fixture_uk.id,
            owner_company_name="Acme",
            owner_country="UK",
            owner_address_line1="221B Baker St",
            owner_address_line2=None,
            owner_city="London",
            owner_postcode=None,
            owner_email=None,
            owner_phone=None,
            owner_entity_type=UKIPOOwnerEntityType.individuals,
            owner_company_registration_number=None,
            mark_type=UKIPOMarkType.word,
            mark_text="ACME",
            mark_image_path=None,
            nice_classes=[{"class_number": 25, "description": "T-shirts"}],
        )


# ---------------------------------------------------------------------------
# run_submission with injected fake runner
# ---------------------------------------------------------------------------


def _fake_runner(result: RobotResult) -> Callable[..., Awaitable[RobotResult]]:
    async def _runner(_inp: RobotInput, **_kwargs: object) -> RobotResult:
        return result

    return _runner


@pytest.fixture(autouse=True)
def _set_robot_envs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide non-empty representative env so build_robot_input doesn't refuse."""
    from app.config import settings as live_settings

    monkeypatch.setattr(live_settings, "ukipo_rep_entity_type", "IP Professional")
    monkeypatch.setattr(live_settings, "ukipo_rep_name", "Jane Doe")
    monkeypatch.setattr(live_settings, "ukipo_rep_email", "jane@uk-rep.example")
    monkeypatch.setattr(live_settings, "ukipo_rep_phone", "+44 20 0000 0000")
    monkeypatch.setattr(live_settings, "ukipo_rep_address_line1", "10 Downing St")
    monkeypatch.setattr(live_settings, "ukipo_rep_address_line2", "")
    monkeypatch.setattr(live_settings, "ukipo_rep_city", "London")
    monkeypatch.setattr(live_settings, "ukipo_rep_postcode", "SW1A 2AA")
    monkeypatch.setattr(live_settings, "ukipo_rep_country", "United Kingdom")
    monkeypatch.setattr(live_settings, "ukipo_declarant_name", "Jane Doe")
    monkeypatch.setattr(live_settings, "ukipo_screenshot_dir", "/tmp/ukipo-tests")


@pytest.mark.integration
async def test_run_submission_marks_awaiting_payment_on_success(
    db_session: AsyncSession, case_fixture_uk: Case
) -> None:
    submission = await ukipo_service.create_submission(
        db_session,
        case_id=case_fixture_uk.id,
        owner_company_name="Acme",
        owner_country="United Kingdom",
        owner_address_line1="221B Baker St",
        owner_address_line2=None,
        owner_city="London",
        owner_postcode="NW1 6XE",
        owner_email=None,
        owner_phone=None,
        owner_entity_type=UKIPOOwnerEntityType.individuals,
        owner_company_registration_number=None,
        mark_type=UKIPOMarkType.word,
        mark_text="ACME",
        mark_image_path=None,
        nice_classes=[{"class_number": 25, "description": "T-shirts"}],
    )
    success = RobotResult(
        success=True,
        current_step="declaration",
        ipo_application_url="https://trademarks.ipo.gov.uk/.../declaration",
        screenshot_path="/tmp/ukipo-tests/abc/post_declaration.png",
    )
    updated = await ukipo_service.run_submission(
        db_session, submission, runner=_fake_runner(success)
    )
    assert updated.status == UKIPOSubmissionStatus.awaiting_payment
    assert updated.ipo_application_url == success.ipo_application_url
    assert updated.error_step is None
    assert updated.finished_at is not None


@pytest.mark.integration
async def test_run_submission_marks_failed_on_robot_error(
    db_session: AsyncSession, case_fixture_uk: Case
) -> None:
    submission = await ukipo_service.create_submission(
        db_session,
        case_id=case_fixture_uk.id,
        owner_company_name="Acme",
        owner_country="United Kingdom",
        owner_address_line1="221B Baker St",
        owner_address_line2=None,
        owner_city="London",
        owner_postcode="NW1 6XE",
        owner_email=None,
        owner_phone=None,
        owner_entity_type=UKIPOOwnerEntityType.individuals,
        owner_company_registration_number=None,
        mark_type=UKIPOMarkType.word,
        mark_text="ACME",
        mark_image_path=None,
        nice_classes=[{"class_number": 25, "description": "T-shirts"}],
    )
    failure = RobotResult(
        success=False,
        current_step="fill_owner_details",
        error_step="fill_owner_details",
        error_message="UK IPO validation error: postcode invalid",
    )
    updated = await ukipo_service.run_submission(
        db_session, submission, runner=_fake_runner(failure)
    )
    assert updated.status == UKIPOSubmissionStatus.failed
    assert updated.error_step == "fill_owner_details"
    assert updated.error_message and "postcode" in updated.error_message


# ---------------------------------------------------------------------------
# trigger_from_proposal_acceptance
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_uk_proposal_acceptance_logs_case_note_no_submission(
    db_session: AsyncSession, case_fixture_uk: Case, lawyer_user: User
) -> None:
    proposal = Proposal(
        case_id=case_fixture_uk.id,
        country_name="United Kingdom",
        country_code="GB",
        nice_classes="25",
        status=ProposalStatus.accepted,
        responded_at=datetime.now(timezone.utc),
        created_by=lawyer_user.id,
    )
    db_session.add(proposal)
    await db_session.flush()
    await db_session.refresh(proposal)

    result = await ukipo_service.trigger_from_proposal_acceptance(db_session, proposal)
    assert result is None

    notes_q = await db_session.execute(
        select(CaseNote).where(CaseNote.case_id == case_fixture_uk.id)
    )
    notes = list(notes_q.scalars().all())
    assert len(notes) == 1
    assert "UK IPO" in notes[0].content

    submissions_q = await db_session.execute(
        select(UKIPOSubmission).where(UKIPOSubmission.case_id == case_fixture_uk.id)
    )
    assert submissions_q.scalar_one_or_none() is None


@pytest.mark.integration
async def test_non_uk_proposal_acceptance_is_noop(
    db_session: AsyncSession, case_fixture_uk: Case, lawyer_user: User
) -> None:
    proposal = Proposal(
        case_id=case_fixture_uk.id,
        country_name="Germany",
        country_code="DE",
        nice_classes="25",
        status=ProposalStatus.accepted,
        responded_at=datetime.now(timezone.utc),
        created_by=lawyer_user.id,
    )
    db_session.add(proposal)
    await db_session.flush()
    await db_session.refresh(proposal)

    result = await ukipo_service.trigger_from_proposal_acceptance(db_session, proposal)
    assert result is None

    notes_q = await db_session.execute(
        select(CaseNote).where(CaseNote.case_id == case_fixture_uk.id)
    )
    assert notes_q.scalar_one_or_none() is None


@pytest.mark.integration
async def test_unaccepted_proposal_is_noop(
    db_session: AsyncSession, case_fixture_uk: Case, lawyer_user: User
) -> None:
    proposal = Proposal(
        case_id=case_fixture_uk.id,
        country_name="United Kingdom",
        country_code="GB",
        nice_classes="25",
        status=ProposalStatus.sent,
        created_by=lawyer_user.id,
    )
    db_session.add(proposal)
    await db_session.flush()
    await db_session.refresh(proposal)

    result = await ukipo_service.trigger_from_proposal_acceptance(db_session, proposal)
    assert result is None

    notes_q = await db_session.execute(
        select(CaseNote).where(CaseNote.case_id == case_fixture_uk.id)
    )
    assert notes_q.scalar_one_or_none() is None


@pytest.mark.unit
def test_robot_runner_module_lazy_imports_playwright() -> None:
    """Importing app.services.ukipo.robot must not pull Playwright in.

    Playwright isn't a hard runtime dependency for the API server (only
    for the worker that actually runs the form). Importing the robot
    module from anywhere — including this test process — must work
    even if playwright is absent."""
    import importlib

    module = importlib.import_module("app.services.ukipo.robot")
    assert hasattr(module, "run_submission")
