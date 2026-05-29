"""AI cost / token aggregation tests."""
from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import AgentSession
from app.cost.pricing import (
    DEFAULT_RATE,
    TOGETHER_PRICING,
    compute_cost_usd,
    rate_for_model,
)
from app.users.models import User
from tests.conftest import auth_headers


# ---------------------------------------------------------------------------
# Pricing helpers
# ---------------------------------------------------------------------------


def test_rate_for_model_matches_known_id() -> None:
    rate = rate_for_model("meta-llama/Llama-3.3-70B-Instruct-Turbo")
    assert rate is TOGETHER_PRICING[
        "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    ]


def test_rate_for_model_is_case_insensitive() -> None:
    rate = rate_for_model("META-LLAMA/Llama-3.3-70B-Instruct-Turbo")
    assert rate is TOGETHER_PRICING[
        "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    ]


def test_rate_for_model_falls_back_to_default() -> None:
    rate = rate_for_model("does-not-exist")
    assert rate is DEFAULT_RATE


def test_rate_for_missing_model() -> None:
    assert rate_for_model(None) is DEFAULT_RATE
    assert rate_for_model("") is DEFAULT_RATE


def test_compute_cost_known_model() -> None:
    # Llama-3.3-70B-Instruct-Turbo: 0.88 / 0.88 per 1M tokens.
    # 100k input + 50k output → (0.1 * 0.88) + (0.05 * 0.88) = 0.132.
    cost = compute_cost_usd(
        model_name="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        input_tokens=100_000,
        output_tokens=50_000,
    )
    assert cost == Decimal("0.132")


def test_compute_cost_zero_tokens() -> None:
    assert compute_cost_usd(
        model_name="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        input_tokens=0,
        output_tokens=0,
    ) == Decimal(0)


# ---------------------------------------------------------------------------
# Admin endpoint
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_ai_usage_aggregates_by_model(
    client: AsyncClient,
    admin_user: User,
    client_user: User,
    db_session: AsyncSession,
) -> None:
    db_session.add_all(
        [
            AgentSession(
                user_id=client_user.id,
                model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
                total_input_tokens=100_000,
                total_output_tokens=50_000,
            ),
            AgentSession(
                user_id=client_user.id,
                model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
                total_input_tokens=50_000,
                total_output_tokens=10_000,
            ),
            AgentSession(
                user_id=client_user.id,
                model="meta-llama/Llama-4-Scout-17B-16E-Instruct",
                total_input_tokens=200_000,
                total_output_tokens=80_000,
            ),
        ]
    )
    await db_session.commit()

    res = await client.get(
        "/admin/ai-usage", headers=auth_headers(admin_user)
    )
    assert res.status_code == 200
    body = res.json()
    per_model = {row["model"]: row for row in body["per_model"]}
    llama33 = per_model[
        "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    ]
    assert llama33["sessions"] == 2
    assert llama33["input_tokens"] == 150_000
    assert llama33["output_tokens"] == 60_000
    # Cost: (150_000 * 0.88 + 60_000 * 0.88) / 1_000_000 = 0.1848
    assert Decimal(llama33["estimated_cost_usd"]) == Decimal("0.1848")
    assert body["totals"]["input_tokens"] == 350_000
    assert body["totals"]["output_tokens"] == 140_000


@pytest.mark.integration
async def test_ai_usage_forbidden_for_client(
    client: AsyncClient, client_user: User
) -> None:
    res = await client.get(
        "/admin/ai-usage", headers=auth_headers(client_user)
    )
    assert res.status_code == 403
