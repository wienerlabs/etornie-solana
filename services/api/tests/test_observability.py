"""Tests for the observability layer (#51) — structured logging + tracing gate.

A real in-memory OpenTelemetry TracerProvider (no mocks) proves the JSON log
lines pick up the active trace/span ids, and that tracing init is a true no-op
when disabled.
"""

from __future__ import annotations

import json
import logging

import pytest

from app import observability
from app.observability import (
    JsonLogFormatter,
    _ContextFilter,
    _request_id_ctx,
    configure_logging,
    init_tracing,
)


def _record(msg: str = "hello") -> logging.LogRecord:
    return logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg=msg,
        args=(),
        exc_info=None,
    )


@pytest.mark.unit
class TestJsonFormatter:
    def test_required_fields_present(self) -> None:
        record = _record("payment confirmed")
        _ContextFilter().filter(record)
        data = json.loads(JsonLogFormatter().format(record))
        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["message"] == "payment confirmed"
        assert "timestamp" in data
        assert "request_id" in data
        # No span active → no trace fields should leak in.
        assert "trace_id" not in data

    def test_request_id_propagates(self) -> None:
        token = _request_id_ctx.set("req-123")
        try:
            record = _record()
            _ContextFilter().filter(record)
            data = json.loads(JsonLogFormatter().format(record))
        finally:
            _request_id_ctx.reset(token)
        assert data["request_id"] == "req-123"

    def test_extra_fields_surface(self) -> None:
        record = _record()
        record.case_number = "ETR-2026-0042"  # mimics logger.info(..., extra=)
        _ContextFilter().filter(record)
        data = json.loads(JsonLogFormatter().format(record))
        assert data["case_number"] == "ETR-2026-0042"

    def test_trace_ids_present_under_active_span(self) -> None:
        from opentelemetry.sdk.trace import TracerProvider

        tracer = TracerProvider().get_tracer("test")
        with tracer.start_as_current_span("unit-span"):
            record = _record()
            _ContextFilter().filter(record)
            data = json.loads(JsonLogFormatter().format(record))
        assert len(data["trace_id"]) == 32
        assert len(data["span_id"]) == 16


@pytest.mark.unit
class TestConfigureLogging:
    def test_idempotent_and_installs_context_handler(self) -> None:
        root = logging.getLogger()
        saved_handlers = root.handlers[:]
        saved_level = root.level
        try:
            configure_logging()
            configure_logging()  # second call must not raise
            assert root.handlers
            assert any(
                any(isinstance(f, _ContextFilter) for f in h.filters)
                for h in root.handlers
            )
        finally:
            root.handlers[:] = saved_handlers
            root.setLevel(saved_level)


@pytest.mark.unit
class TestTracingGate:
    def test_disabled_is_noop(self) -> None:
        from unittest.mock import patch

        with patch.object(observability.settings, "otel_enabled", False):
            result = init_tracing(app=None, engine=None)
        assert result is False
