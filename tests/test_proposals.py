"""Tests for proposal generation, lifecycle, and permissions."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case, CaseType, CaseStatus
from app.proposals.models import ProposalStatus
from app.proposals.service import generate_proposal, get_proposal_by_case, list_proposals_by_case
from app.users.models import User
from tests.conftest import auth_headers


@pytest.fixture
async def case_with_classes(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> Case:
    """Case with jurisdiction=DE and nice_classes=25,35."""
    case = Case(
        case_number="ETR-2026-8888",
        title="Proposal Test Case",
        case_type=CaseType.trademark,
        status=CaseStatus.open,
        client_id=client_user.id,
        assigned_lawyer_id=lawyer_user.id,
        jurisdiction="DE",
        nice_classes="25,35",
    )
    db_session.add(case)
    await db_session.flush()
    await db_session.refresh(case)
    return case


@pytest.fixture
async def case_no_jurisdiction(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> Case:
    """Case without jurisdiction."""
    case = Case(
        case_number="ETR-2026-7777",
        title="No Jurisdiction Case",
        case_type=CaseType.trademark,
        status=CaseStatus.open,
        client_id=client_user.id,
        assigned_lawyer_id=lawyer_user.id,
        nice_classes="25",
    )
    db_session.add(case)
    await db_session.flush()
    await db_session.refresh(case)
    return case


@pytest.fixture
async def case_no_classes(
    db_session: AsyncSession,
    client_user: User,
    lawyer_user: User,
) -> Case:
    """Case without nice_classes."""
    case = Case(
        case_number="ETR-2026-6666",
        title="No Classes Case",
        case_type=CaseType.trademark,
        status=CaseStatus.open,
        client_id=client_user.id,
        assigned_lawyer_id=lawyer_user.id,
        jurisdiction="DE",
    )
    db_session.add(case)
    await db_session.flush()
    await db_session.refresh(case)
    return case


# --- Service tests ---


class TestGenerateProposal:
    @pytest.mark.asyncio
    async def test_generate_with_known_country(
        self, db_session: AsyncSession, case_with_classes: Case, lawyer_user: User
    ):
        """Proposal is populated from country DB when jurisdiction is known."""
        proposal = await generate_proposal(
            db_session,
            case_id=case_with_classes.id,
            jurisdiction="DE",
            nice_classes="25,35",
            created_by=lawyer_user.id,
        )
        assert proposal.country_name == "ALMANYA"
        assert proposal.country_code == "DE"
        assert proposal.nice_classes == "25,35"
        assert proposal.registration_period is not None
        assert proposal.protection_period is not None
        assert proposal.status == ProposalStatus.draft
        assert proposal.price is None  # No pricing yet

    @pytest.mark.asyncio
    async def test_generate_with_unknown_country(
        self, db_session: AsyncSession, case_with_classes: Case, lawyer_user: User
    ):
        """Proposal is created with minimal info for unknown countries."""
        proposal = await generate_proposal(
            db_session,
            case_id=case_with_classes.id,
            jurisdiction="Atlantis",
            nice_classes="25",
            created_by=lawyer_user.id,
        )
        assert proposal.country_name == "Atlantis"
        assert proposal.country_code is None
        assert proposal.registration_period is None
        assert proposal.status == ProposalStatus.draft

    @pytest.mark.asyncio
    async def test_get_proposal_by_case(
        self, db_session: AsyncSession, case_with_classes: Case, lawyer_user: User
    ):
        """Fetching latest proposal for a case returns a proposal."""
        await generate_proposal(
            db_session, case_id=case_with_classes.id,
            jurisdiction="DE", nice_classes="25", created_by=lawyer_user.id,
        )
        await generate_proposal(
            db_session, case_id=case_with_classes.id,
            jurisdiction="DE", nice_classes="25,35", created_by=lawyer_user.id,
        )
        latest = await get_proposal_by_case(db_session, case_with_classes.id)
        assert latest is not None
        all_proposals = await list_proposals_by_case(db_session, case_with_classes.id)
        assert len(all_proposals) == 2


# --- API endpoint tests ---


class TestGenerateEndpoint:
    @pytest.mark.asyncio
    async def test_lawyer_can_generate(
        self, client: AsyncClient, case_with_classes: Case, lawyer_user: User
    ):
        resp = await client.post(
            f"/cases/{case_with_classes.id}/proposal/generate",
            headers=auth_headers(lawyer_user),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["country_name"] == "ALMANYA"
        assert data["nice_classes"] == "25,35"
        assert data["status"] == "draft"
        assert data["price"] is None

    @pytest.mark.asyncio
    async def test_admin_can_generate(
        self, client: AsyncClient, case_with_classes: Case, admin_user: User
    ):
        resp = await client.post(
            f"/cases/{case_with_classes.id}/proposal/generate",
            headers=auth_headers(admin_user),
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_client_cannot_generate(
        self, client: AsyncClient, case_with_classes: Case, client_user: User
    ):
        resp = await client.post(
            f"/cases/{case_with_classes.id}/proposal/generate",
            headers=auth_headers(client_user),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_no_jurisdiction_returns_400(
        self, client: AsyncClient, case_no_jurisdiction: Case, lawyer_user: User
    ):
        resp = await client.post(
            f"/cases/{case_no_jurisdiction.id}/proposal/generate",
            headers=auth_headers(lawyer_user),
        )
        assert resp.status_code == 400
        assert "jurisdiction" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_no_classes_returns_400(
        self, client: AsyncClient, case_no_classes: Case, lawyer_user: User
    ):
        resp = await client.post(
            f"/cases/{case_no_classes.id}/proposal/generate",
            headers=auth_headers(lawyer_user),
        )
        assert resp.status_code == 400
        assert "nice" in resp.json()["detail"].lower()


class TestGetProposal:
    @pytest.mark.asyncio
    async def test_get_latest_proposal(
        self, client: AsyncClient, case_with_classes: Case, lawyer_user: User
    ):
        await client.post(
            f"/cases/{case_with_classes.id}/proposal/generate",
            headers=auth_headers(lawyer_user),
        )
        resp = await client.get(
            f"/cases/{case_with_classes.id}/proposal",
            headers=auth_headers(lawyer_user),
        )
        assert resp.status_code == 200
        assert resp.json()["country_name"] == "ALMANYA"

    @pytest.mark.asyncio
    async def test_client_can_view_proposal(
        self, client: AsyncClient, case_with_classes: Case, lawyer_user: User, client_user: User
    ):
        await client.post(
            f"/cases/{case_with_classes.id}/proposal/generate",
            headers=auth_headers(lawyer_user),
        )
        resp = await client.get(
            f"/cases/{case_with_classes.id}/proposal",
            headers=auth_headers(client_user),
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_no_proposal_returns_404(
        self, client: AsyncClient, case_with_classes: Case, lawyer_user: User
    ):
        resp = await client.get(
            f"/cases/{case_with_classes.id}/proposal",
            headers=auth_headers(lawyer_user),
        )
        assert resp.status_code == 404


class TestProposalLifecycle:
    @pytest.mark.asyncio
    async def test_send_then_accept(
        self, client: AsyncClient, case_with_classes: Case, lawyer_user: User, client_user: User
    ):
        """Full lifecycle: generate -> send -> accept."""
        # Generate
        gen_resp = await client.post(
            f"/cases/{case_with_classes.id}/proposal/generate",
            headers=auth_headers(lawyer_user),
        )
        proposal_id = gen_resp.json()["id"]

        # Send
        send_resp = await client.patch(
            f"/proposals/{proposal_id}/send",
            headers=auth_headers(lawyer_user),
        )
        assert send_resp.status_code == 200
        assert send_resp.json()["status"] == "sent"
        assert send_resp.json()["sent_at"] is not None

        # Accept
        accept_resp = await client.patch(
            f"/proposals/{proposal_id}/respond?accepted=true",
            headers=auth_headers(client_user),
        )
        assert accept_resp.status_code == 200
        assert accept_resp.json()["status"] == "accepted"
        assert accept_resp.json()["responded_at"] is not None

    @pytest.mark.asyncio
    async def test_send_then_reject(
        self, client: AsyncClient, case_with_classes: Case, lawyer_user: User, client_user: User
    ):
        """Lifecycle: generate -> send -> reject."""
        gen_resp = await client.post(
            f"/cases/{case_with_classes.id}/proposal/generate",
            headers=auth_headers(lawyer_user),
        )
        proposal_id = gen_resp.json()["id"]

        await client.patch(
            f"/proposals/{proposal_id}/send",
            headers=auth_headers(lawyer_user),
        )

        reject_resp = await client.patch(
            f"/proposals/{proposal_id}/respond?accepted=false",
            headers=auth_headers(client_user),
        )
        assert reject_resp.status_code == 200
        assert reject_resp.json()["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_cannot_send_non_draft(
        self, client: AsyncClient, case_with_classes: Case, lawyer_user: User
    ):
        gen_resp = await client.post(
            f"/cases/{case_with_classes.id}/proposal/generate",
            headers=auth_headers(lawyer_user),
        )
        proposal_id = gen_resp.json()["id"]

        # Send once
        await client.patch(
            f"/proposals/{proposal_id}/send",
            headers=auth_headers(lawyer_user),
        )

        # Try send again
        resp = await client.patch(
            f"/proposals/{proposal_id}/send",
            headers=auth_headers(lawyer_user),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_cannot_respond_to_draft(
        self, client: AsyncClient, case_with_classes: Case, lawyer_user: User, client_user: User
    ):
        gen_resp = await client.post(
            f"/cases/{case_with_classes.id}/proposal/generate",
            headers=auth_headers(lawyer_user),
        )
        proposal_id = gen_resp.json()["id"]

        resp = await client.patch(
            f"/proposals/{proposal_id}/respond?accepted=true",
            headers=auth_headers(client_user),
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_client_cannot_send(
        self, client: AsyncClient, case_with_classes: Case, lawyer_user: User, client_user: User
    ):
        gen_resp = await client.post(
            f"/cases/{case_with_classes.id}/proposal/generate",
            headers=auth_headers(lawyer_user),
        )
        proposal_id = gen_resp.json()["id"]

        resp = await client.patch(
            f"/proposals/{proposal_id}/send",
            headers=auth_headers(client_user),
        )
        assert resp.status_code == 403


class TestListProposals:
    @pytest.mark.asyncio
    async def test_list_all_for_case(
        self, client: AsyncClient, case_with_classes: Case, lawyer_user: User
    ):
        await client.post(
            f"/cases/{case_with_classes.id}/proposal/generate",
            headers=auth_headers(lawyer_user),
        )
        await client.post(
            f"/cases/{case_with_classes.id}/proposal/generate",
            headers=auth_headers(lawyer_user),
        )
        resp = await client.get(
            f"/cases/{case_with_classes.id}/proposals",
            headers=auth_headers(lawyer_user),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 2
