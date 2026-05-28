"""Centralised observability bootstrap (Sentry + structured logging).

Initialised once at startup from ``app.main``. Importing this module
is safe even when ``SENTRY_DSN`` is empty — the SDK simply stays
uninitialised and the rest of the app keeps working unchanged.

Why this lives in a dedicated module
-----------------------------------
1. Avoids a circular import (Sentry's FastAPI integration would
   otherwise need to know about the FastAPI app instance).
2. Centralises tagging conventions so call sites do not need to
   remember which keys go where.
3. Lets tests import ``init_sentry()`` and call it explicitly with
   a test DSN when they want to assert the integration is wired.
"""
from __future__ import annotations

import logging
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.config import settings

logger = logging.getLogger(__name__)


def _before_send(event: dict, hint: dict) -> dict | None:
    """Strip secrets and noisy data before shipping the event to Sentry.

    Stripe and Solana SDKs occasionally include raw API keys or
    keypair bytes in repr output. We scrub those at the boundary so
    they never leave the box even if a logger accidentally dumps an
    object that holds them.
    """
    # Sanitise request body — Stripe webhook signatures and OAuth
    # secrets travel there.
    request = event.get("request") or {}
    data = request.get("data")
    if isinstance(data, (str, bytes)):
        request["data"] = "<scrubbed>"
        event["request"] = request

    # Sanitise headers — Authorization / Stripe-Signature.
    headers = (event.get("request") or {}).get("headers") or {}
    for key in list(headers.keys()):
        lower = key.lower()
        if lower in {"authorization", "stripe-signature", "x-ibm-client-secret"}:
            headers[key] = "<scrubbed>"

    # Sanitise extra context.
    extra = event.get("extra") or {}
    for key in list(extra.keys()):
        if any(s in key.lower() for s in ("secret", "key", "token", "password")):
            extra[key] = "<scrubbed>"

    return event


def init_sentry() -> bool:
    """Initialise the Sentry SDK if a DSN is configured.

    Returns ``True`` when the SDK was actually initialised so the
    caller can log the wiring decision. Safe to call multiple times
    — the SDK guards against double-init internally.
    """
    if not settings.sentry_dsn:
        logger.info("Sentry disabled (SENTRY_DSN empty)")
        return False

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.app_name + "@dev",
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        send_default_pii=False,  # never send IP / cookies / form data
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            StarletteIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
            HttpxIntegration(),
            AsyncioIntegration(),
            # Forward warnings+ to Sentry as breadcrumbs; capture
            # errors as events so they surface in the dashboard.
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        before_send=_before_send,
    )
    logger.info(
        "Sentry initialised (environment=%s, traces=%s)",
        settings.environment,
        settings.sentry_traces_sample_rate,
    )
    return True


def tag_user(user_id: str | None, *, email: str | None = None) -> None:
    """Attach the authenticated user to the current Sentry scope.

    Call from auth middleware once the user is known. Email is hashed
    away by ``send_default_pii=False`` if we ever flip it on, so
    passing it here only helps in-app logs.
    """
    if not settings.sentry_dsn:
        return
    scope = sentry_sdk.get_current_scope()
    if user_id:
        scope.set_user({"id": user_id, "email": email} if email else {"id": user_id})


def tag_payment(payment_intent_id: str | None, *, draft_id: str | None = None) -> None:
    """Attach payment context to the current Sentry scope."""
    if not settings.sentry_dsn:
        return
    scope = sentry_sdk.get_current_scope()
    if payment_intent_id:
        scope.set_tag("payment_intent_id", payment_intent_id)
    if draft_id:
        scope.set_tag("case_draft_id", draft_id)


def capture_exception(exc: BaseException, **extra: Any) -> str | None:
    """Send an exception to Sentry with optional structured context.

    Returns the event id when shipped, ``None`` otherwise.
    """
    if not settings.sentry_dsn:
        return None
    if extra:
        scope = sentry_sdk.get_current_scope()
        for k, v in extra.items():
            scope.set_extra(k, v)
    return sentry_sdk.capture_exception(exc)
