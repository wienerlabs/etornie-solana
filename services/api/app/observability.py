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

import json
import logging
import logging.config
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

import sentry_sdk
from opentelemetry import trace as otel_trace
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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


# ---------------------------------------------------------------------------
# Structured logging — JSON lines correlated to traces + a per-request id.
# ---------------------------------------------------------------------------

# Bound for the lifetime of one request by ``RequestContextMiddleware`` so
# every log line emitted while handling it carries the same id.
_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

# Attributes the stdlib sets on every LogRecord. Anything else a call site
# attaches via ``logger.info(..., extra={...})`` is surfaced in the JSON log.
_RESERVED_LOG_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",
        "asctime",
        "request_id",
        "otel_trace_id",
        "otel_span_id",
    }
)


class _ContextFilter(logging.Filter):
    """Attach request_id + the active OTel trace/span ids to every record.

    Runs on the handler before formatting, so both the JSON and console
    formatters can rely on these attributes always being present.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_ctx.get()
        span = otel_trace.get_current_span()
        ctx = span.get_span_context() if span is not None else None
        if ctx is not None and ctx.is_valid:
            record.otel_trace_id = format(ctx.trace_id, "032x")
            record.otel_span_id = format(ctx.span_id, "016x")
        else:
            record.otel_trace_id = ""
            record.otel_span_id = ""
        return True


class JsonLogFormatter(logging.Formatter):
    """Render each record as one JSON object — stable keys for a log store,
    trace_id/span_id for trace correlation, plus any ``extra=`` fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        trace_id = getattr(record, "otel_trace_id", "")
        if trace_id:
            payload["trace_id"] = trace_id
            payload["span_id"] = getattr(record, "otel_span_id", "")
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
        for key, value in record.__dict__.items():
            if key not in _RESERVED_LOG_FIELDS and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging() -> None:
    """Install structured logging on the root + uvicorn loggers.

    ``LOG_FORMAT=json`` (default) emits one JSON object per line; ``console``
    is human-readable for local dev. Idempotent — safe to call repeatedly.
    """
    use_json = settings.log_format.lower() == "json"
    level = settings.log_level.upper()
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"context": {"()": _ContextFilter}},
            "formatters": {
                "json": {"()": JsonLogFormatter},
                "console": {
                    "format": (
                        "%(asctime)s %(levelname)-7s %(name)s "
                        "[req=%(request_id)s trace=%(otel_trace_id)s] %(message)s"
                    ),
                    "defaults": {"request_id": "-", "otel_trace_id": ""},
                },
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "json" if use_json else "console",
                    "filters": ["context"],
                }
            },
            "root": {"level": level, "handlers": ["default"]},
            "loggers": {
                name: {
                    "level": level,
                    "handlers": ["default"],
                    "propagate": False,
                }
                for name in ("uvicorn", "uvicorn.error", "uvicorn.access")
            },
        }
    )


class RequestContextMiddleware:
    """Pure-ASGI middleware that binds a request_id for the whole request.

    Implemented as raw ASGI (not ``BaseHTTPMiddleware``) on purpose: the
    latter runs the downstream app in a separate context, so a ContextVar set
    there would be invisible to the route handlers. Setting it here — in the
    same context that calls ``self.app(...)`` — propagates it everywhere the
    request touches, so every log line gets the id. An inbound ``X-Request-ID``
    (e.g. from a proxy) is reused so one id ties logs together across services;
    otherwise a fresh one is minted. The id is echoed on the response.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        header_map = dict(scope.get("headers") or [])
        incoming = header_map.get(b"x-request-id")
        request_id = incoming.decode("latin-1") if incoming else uuid.uuid4().hex
        token = _request_id_ctx.set(request_id)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            _request_id_ctx.reset(token)


# ---------------------------------------------------------------------------
# OpenTelemetry tracing — whole-app auto-instrumentation.
# ---------------------------------------------------------------------------


def init_tracing(app: Any, engine: Any) -> bool:
    """Set up OTel tracing + instrument FastAPI / SQLAlchemy / httpx / Redis.

    No-op (returns False) when ``OTEL_ENABLED`` is false — a real off switch,
    the same posture as an empty ``SENTRY_DSN``. When enabled with no OTLP
    endpoint configured, spans go to stdout rather than being silently
    dropped, so "enabled" never means "lost".
    """
    if not settings.otel_enabled:
        logger.info("OpenTelemetry disabled (OTEL_ENABLED=false)")
        return False

    # Heavy SDK + instrumentation imports are local so they only load when
    # tracing is actually switched on.
    from opentelemetry import trace
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SimpleSpanProcessor,
    )
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "deployment.environment": settings.environment,
        }
    )
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(settings.otel_traces_sample_rate)),
    )

    exported = False
    if settings.otel_exporter_otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        )
        exported = True
    if settings.otel_console_export or not exported:
        if not exported:
            logger.warning(
                "OTEL_ENABLED but no OTLP endpoint set; exporting spans to stdout"
            )
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    SQLAlchemyInstrumentor().instrument(
        engine=engine.sync_engine, tracer_provider=provider
    )
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    RedisInstrumentor().instrument(tracer_provider=provider)

    logger.info(
        "OpenTelemetry initialised (service=%s, endpoint=%s, sample_rate=%s)",
        settings.otel_service_name,
        settings.otel_exporter_otlp_endpoint or "stdout",
        settings.otel_traces_sample_rate,
    )
    return True
