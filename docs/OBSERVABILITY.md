# Observability (#51)

Three correlated pillars for production triage, all wired in
`services/api/app/observability.py` and bootstrapped from `app.main`:

1. **Structured logging** — JSON logs, one object per line.
2. **Error tracking** — Sentry.
3. **Distributed tracing** — OpenTelemetry, exported over OTLP.

A single `request_id` and the active `trace_id` / `span_id` thread through all
three, so an error in Sentry, the log line that produced it, and the trace it
belongs to can be pivoted between freely.

## 1. Structured logging

`configure_logging()` installs a `dictConfig` on the root + uvicorn loggers.

- `LOG_FORMAT=json` (default) → one JSON object per line: `timestamp`, `level`,
  `logger`, `message`, `request_id`, and — when a span is active — `trace_id` /
  `span_id`. Any `logger.info(..., extra={...})` fields are merged in.
- `LOG_FORMAT=console` → human-readable single line for local dev.
- `LOG_LEVEL` (default `INFO`) applies to the app + uvicorn loggers.

Every request is tagged with a `request_id` by `RequestContextMiddleware`
(reusing an inbound `X-Request-ID` from a proxy if present, otherwise minting
one) and the id is echoed on the response `X-Request-ID` header. The middleware
is **pure ASGI** on purpose — `BaseHTTPMiddleware` runs the app in a separate
context, so a `ContextVar` set there would not reach the route handlers.

```json
{"timestamp":"2026-06-02T10:20:01.123456+00:00","level":"INFO","logger":"app.payments.service","message":"payment confirmed","request_id":"a1b2c3…","trace_id":"4bf92f…","span_id":"00f067…"}
```

## 2. Error tracking (Sentry)

`init_sentry()` initialises Sentry only when `SENTRY_DSN` is set (empty → the
SDK stays uninitialised and the app runs unchanged). Integrations: FastAPI,
Starlette, SQLAlchemy, httpx, asyncio, and logging (warnings+ as breadcrumbs,
errors as events). Secrets are scrubbed in `_before_send`; `send_default_pii`
is off. Tune with `SENTRY_TRACES_SAMPLE_RATE`.

## 3. Distributed tracing (OpenTelemetry)

`init_tracing(app, engine)` is a **real no-op when `OTEL_ENABLED=false`** (the
same posture as an empty `SENTRY_DSN`). When enabled it builds a
`TracerProvider` (resource `service.name=OTEL_SERVICE_NAME`,
`deployment.environment=ENVIRONMENT`; `ParentBased(TraceIdRatioBased(...))`
sampler) and auto-instruments the whole request path:

- **FastAPI** — a server span per request, across every route;
- **SQLAlchemy** — a span per query (instruments `engine.sync_engine`);
- **httpx** — a client span per outbound call (EUIPO, Solana RPC, SMTP relay …);
- **Redis** — a span per command.

Spans export over **OTLP/HTTP** to `OTEL_EXPORTER_OTLP_ENDPOINT`
(`…/v1/traces` is appended). With `OTEL_CONSOLE_EXPORT=true` they also print to
stdout. If tracing is enabled but no endpoint is set, spans fall back to stdout
rather than being silently dropped.

### Run a local collector

Any OTLP-compatible backend works. Jaeger all-in-one is the quickest:

```bash
docker run --rm -p 16686:16686 -p 4318:4318 \
  jaegertracing/all-in-one:latest
```

Then in `services/api/.env`:

```bash
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
OTEL_SERVICE_NAME=etornie-api
```

Restart the backend, make a few requests, and open the Jaeger UI at
<http://localhost:16686> — you should see `etornie-api` traces with nested
FastAPI → SQLAlchemy / httpx / Redis spans, and the matching `trace_id` in the
JSON logs.

## Configuration reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `LOG_FORMAT` | `json` | `json` or `console` |
| `LOG_LEVEL` | `INFO` | root / app / uvicorn level |
| `SENTRY_DSN` | _empty_ | error tracking (empty disables) |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.1` | Sentry perf sampling |
| `OTEL_ENABLED` | `false` | master switch for tracing |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | _empty_ | OTLP/HTTP collector base URL |
| `OTEL_SERVICE_NAME` | `etornie-api` | `service.name` resource attr |
| `OTEL_CONSOLE_EXPORT` | `false` | also print spans to stdout |
| `OTEL_TRACES_SAMPLE_RATE` | `1.0` | head-based trace sampling ratio |
