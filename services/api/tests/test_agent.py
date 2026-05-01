"""Tests for the agent orchestrator HTTP API.

Session/message CRUD tests do not call the LLM and run without
TOGETHER_API_KEY. The end-to-end turn test calls the real Together AI
service and is skipped when the key is absent — never mocked.
"""
from __future__ import annotations

import os
import uuid

import pytest
from httpx import AsyncClient

from app.users.models import User
from tests.conftest import auth_headers


# ---------------------------------------------------------------------------
# Session CRUD (no LLM)
# ---------------------------------------------------------------------------


class TestAgentSessionCrud:
    async def test_create_session_succeeds(
        self, client: AsyncClient, client_user: User
    ) -> None:
        resp = await client.post(
            "/agent/sessions",
            headers=auth_headers(client_user),
            json={"title": "Etornie marka başvurusu"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["title"] == "Etornie marka başvurusu"
        assert body["status"] == "active"
        assert body["model"]  # configured agent model is set
        assert body["total_input_tokens"] == 0
        assert body["total_output_tokens"] == 0

    async def test_list_sessions_returns_only_my_sessions(
        self,
        client: AsyncClient,
        client_user: User,
        lawyer_user: User,
    ) -> None:
        # Each user creates one session.
        await client.post(
            "/agent/sessions",
            headers=auth_headers(client_user),
            json={"title": "Client session"},
        )
        await client.post(
            "/agent/sessions",
            headers=auth_headers(lawyer_user),
            json={"title": "Lawyer session"},
        )

        client_list = await client.get(
            "/agent/sessions", headers=auth_headers(client_user)
        )
        lawyer_list = await client.get(
            "/agent/sessions", headers=auth_headers(lawyer_user)
        )

        assert client_list.status_code == 200
        assert lawyer_list.status_code == 200

        client_titles = [s["title"] for s in client_list.json()["sessions"]]
        lawyer_titles = [s["title"] for s in lawyer_list.json()["sessions"]]

        assert client_titles == ["Client session"]
        assert lawyer_titles == ["Lawyer session"]

    async def test_rename_session_updates_title(
        self, client: AsyncClient, client_user: User
    ) -> None:
        create = await client.post(
            "/agent/sessions",
            headers=auth_headers(client_user),
            json={},
        )
        session_id = create.json()["id"]

        rename = await client.patch(
            f"/agent/sessions/{session_id}",
            headers=auth_headers(client_user),
            json={"title": "Yeniden adlandırıldı"},
        )
        assert rename.status_code == 200
        assert rename.json()["title"] == "Yeniden adlandırıldı"

    async def test_rename_other_users_session_returns_404(
        self,
        client: AsyncClient,
        client_user: User,
        lawyer_user: User,
    ) -> None:
        create = await client.post(
            "/agent/sessions",
            headers=auth_headers(client_user),
            json={"title": "Mine"},
        )
        session_id = create.json()["id"]

        forbidden = await client.patch(
            f"/agent/sessions/{session_id}",
            headers=auth_headers(lawyer_user),
            json={"title": "stolen"},
        )
        assert forbidden.status_code == 404

    async def test_delete_session_soft_deletes_and_hides_from_list(
        self, client: AsyncClient, client_user: User
    ) -> None:
        create = await client.post(
            "/agent/sessions",
            headers=auth_headers(client_user),
            json={"title": "To delete"},
        )
        session_id = create.json()["id"]

        delete = await client.delete(
            f"/agent/sessions/{session_id}",
            headers=auth_headers(client_user),
        )
        assert delete.status_code == 204

        listing = await client.get(
            "/agent/sessions", headers=auth_headers(client_user)
        )
        assert listing.status_code == 200
        ids = [s["id"] for s in listing.json()["sessions"]]
        assert session_id not in ids

    async def test_delete_other_users_session_returns_404(
        self,
        client: AsyncClient,
        client_user: User,
        lawyer_user: User,
    ) -> None:
        create = await client.post(
            "/agent/sessions",
            headers=auth_headers(client_user),
            json={},
        )
        session_id = create.json()["id"]

        forbidden = await client.delete(
            f"/agent/sessions/{session_id}",
            headers=auth_headers(lawyer_user),
        )
        assert forbidden.status_code == 404

    async def test_list_messages_for_new_session_is_empty(
        self, client: AsyncClient, client_user: User
    ) -> None:
        create = await client.post(
            "/agent/sessions",
            headers=auth_headers(client_user),
            json={},
        )
        session_id = create.json()["id"]

        msgs = await client.get(
            f"/agent/sessions/{session_id}/messages",
            headers=auth_headers(client_user),
        )
        assert msgs.status_code == 200
        assert msgs.json()["messages"] == []

    async def test_list_messages_other_user_returns_404(
        self,
        client: AsyncClient,
        client_user: User,
        lawyer_user: User,
    ) -> None:
        create = await client.post(
            "/agent/sessions",
            headers=auth_headers(client_user),
            json={},
        )
        session_id = create.json()["id"]

        forbidden = await client.get(
            f"/agent/sessions/{session_id}/messages",
            headers=auth_headers(lawyer_user),
        )
        assert forbidden.status_code == 404


# ---------------------------------------------------------------------------
# Tool registry (no LLM)
# ---------------------------------------------------------------------------


def test_all_phase0_tools_are_registered() -> None:
    # Importing the orchestrator triggers tool registration as a side effect.
    from app.agent import orchestrator  # noqa: F401
    from app.agent.tools import TOOL_REGISTRY

    expected = {
        "trademark_search",
        "validate_logo",
        "decide_platform",
        "quote_fees",
        "create_case_draft",
        "prepare_payment",
        "submit_filing",
        "start_ukipo_filing",
        "check_filing_progress",
    }
    assert expected.issubset(set(TOOL_REGISTRY.keys()))

    for name in expected:
        schema = TOOL_REGISTRY[name].to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == name
        assert "properties" in schema["function"]["parameters"]


# ---------------------------------------------------------------------------
# decide_platform — exercises the real countries dataset (no mock)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decide_platform_returns_real_dataset_routes() -> None:
    from app.agent import orchestrator  # noqa: F401 — register tools
    from app.agent.tools import TOOL_REGISTRY

    result = await TOOL_REGISTRY["decide_platform"].execute(
        {"countries": ["Germany", "US", "GB", "Brazil", "Atlantis"]}
    )

    by_input = {row["input"]: row for row in result["per_country"]}

    assert by_input["Germany"]["matched"]["country_code"] == "DE"
    de_platforms = {o["platform"] for o in by_input["Germany"]["options"]}
    assert "EUIPO" in de_platforms
    assert "WIPO" in de_platforms

    assert {o["platform"] for o in by_input["US"]["options"]} >= {"USPTO", "WIPO"}
    assert {o["platform"] for o in by_input["GB"]["options"]} >= {"UKIPO", "WIPO"}
    assert {o["platform"] for o in by_input["Brazil"]["options"]} == {"WIPO"}

    # Unknown input is reported, not silently mapped.
    assert "Atlantis" in result["unknown_countries"]
    assert by_input["Atlantis"]["matched"] is None


# ---------------------------------------------------------------------------
# quote_fees — exercises the real EUIPO fee schedule file (no mock)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quote_fees_euipo_two_classes_matches_official_schedule() -> None:
    from app.agent import orchestrator  # noqa: F401
    from app.agent.tools import TOOL_REGISTRY

    quote = await TOOL_REGISTRY["quote_fees"].execute(
        {"platform": "EUIPO", "nice_classes": [9, 42]}
    )

    assert quote["platform"] == "EUIPO"
    assert quote["currency"] == "EUR"
    # Official EUIPO online schedule: 850 + 50 = 900.
    assert quote["total"] == 900
    assert quote["source"].startswith("https://www.euipo.europa.eu")


@pytest.mark.asyncio
async def test_quote_fees_other_platforms_are_explicit_about_being_unwired() -> None:
    from app.agent import orchestrator  # noqa: F401
    from app.agent.tools import TOOL_REGISTRY
    from app.agent.tools.base import ToolError

    for platform in ("WIPO", "USPTO", "UKIPO"):
        with pytest.raises(ToolError, match="not yet wired"):
            await TOOL_REGISTRY["quote_fees"].execute(
                {"platform": platform, "nice_classes": [9]}
            )


# ---------------------------------------------------------------------------
# submit_filing — without a real paid draft, must refuse cleanly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_filing_rejects_unwired_platforms() -> None:
    from app.agent import orchestrator  # noqa: F401
    from app.agent.tools import TOOL_REGISTRY
    from app.agent.tools.base import ToolError

    for platform in ("WIPO", "USPTO", "UKIPO"):
        with pytest.raises(ToolError, match="not yet wired"):
            await TOOL_REGISTRY["submit_filing"].execute(
                {
                    "case_draft_id": "00000000-0000-0000-0000-000000000000",
                    "platform": platform,
                }
            )


# ---------------------------------------------------------------------------
# End-to-end turn against the real Together AI service.
# ---------------------------------------------------------------------------


_HAS_TOGETHER_KEY = bool(os.environ.get("TOGETHER_API_KEY"))


@pytest.mark.skipif(
    not _HAS_TOGETHER_KEY,
    reason=(
        "TOGETHER_API_KEY not set — auto-title test calls the real "
        "Together AI service and is not mocked."
    ),
)
@pytest.mark.asyncio
async def test_generate_and_apply_session_title_writes_real_title(
    client: AsyncClient, client_user: User
) -> None:
    from app.agent.models import AgentSession
    from app.agent.service import generate_and_apply_session_title
    from sqlalchemy import select
    from tests.conftest import async_session_test

    create = await client.post(
        "/agent/sessions",
        headers=auth_headers(client_user),
        json={},
    )
    session_id = create.json()["id"]

    async with async_session_test() as db:
        result = await db.execute(
            select(AgentSession).where(AgentSession.id == uuid.UUID(session_id))
        )
        session = result.scalar_one()

        await generate_and_apply_session_title(
            db,
            session=session,
            first_user_message=(
                "EUIPO'da Etornie markası için Nice 9 ve 42 sınıflarında "
                "başvuru yapmak istiyorum."
            ),
        )
        await db.commit()

    async with async_session_test() as db:
        result = await db.execute(
            select(AgentSession).where(AgentSession.id == uuid.UUID(session_id))
        )
        refreshed = result.scalar_one()
        assert refreshed.title
        assert len(refreshed.title) <= 80
        assert refreshed.total_input_tokens > 0
        assert refreshed.total_output_tokens > 0


@pytest.mark.skipif(
    not _HAS_TOGETHER_KEY,
    reason=(
        "TOGETHER_API_KEY not set — the agent orchestrator integration "
        "test calls the real Together AI service and is not mocked."
    ),
)
class TestAgentTurnEndToEnd:
    async def test_user_message_round_trip(
        self,
        client: AsyncClient,
        client_user: User,
    ) -> None:
        create = await client.post(
            "/agent/sessions",
            headers=auth_headers(client_user),
            json={"title": "E2E sanity"},
        )
        session_id = create.json()["id"]

        send = await client.post(
            f"/agent/sessions/{session_id}/messages",
            headers=auth_headers(client_user),
            json={
                "content": (
                    "Selam. Sadece bir kelimelik tanışma cevabı ver, "
                    "tool çağırma."
                ),
            },
            timeout=120.0,
        )
        assert send.status_code == 200, send.text
        body = send.json()

        # Session counters incremented (real LLM tokens consumed).
        assert body["session"]["total_input_tokens"] > 0
        assert body["session"]["total_output_tokens"] > 0

        # Messages: at minimum one user + one assistant message.
        roles = [m["role"] for m in body["messages"]]
        assert roles[0] == "user"
        assert "assistant" in roles
        # The final message must be assistant text, not a dangling tool call.
        assert body["messages"][-1]["role"] == "assistant"
        assert body["messages"][-1]["content"]
