from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Etornie Solana Backend"
    debug: bool = False
    # ``environment`` tags every Sentry event + structured log entry so
    # production noise does not mix with local dev traces. Free-text;
    # typical values: "development", "staging", "production".
    environment: str = "development"

    # Sentry monitoring (optional). When ``sentry_dsn`` is empty the
    # SDK is not initialised — the app keeps working unchanged, just
    # without remote error tracking. ``sentry_traces_sample_rate``
    # controls the percentage of requests that emit performance
    # transactions (set to 0 to disable, 1.0 to capture everything).
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1
    sentry_profiles_sample_rate: float = 0.0

    # Structured logging. ``log_format`` is "json" for machine-readable
    # production logs (one JSON object per line, carrying trace_id / span_id
    # + request_id) or "console" for human-readable local dev. ``log_level``
    # is applied to the root, app and uvicorn loggers.
    log_format: str = "json"
    log_level: str = "INFO"

    # OpenTelemetry tracing. Disabled by default so local dev needs no
    # collector — init is then a real no-op (same posture as an empty
    # SENTRY_DSN). When enabled, spans export over OTLP/HTTP to
    # ``otel_exporter_otlp_endpoint`` (e.g. http://localhost:4318); set
    # ``otel_console_export`` to also print spans to stdout for debugging.
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "etornie-api"
    otel_console_export: bool = False
    otel_traces_sample_rate: float = 1.0

    # Database
    database_url: str

    # JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Together AI (embeddings for RAG)
    together_api_key: str = ""
    together_model: str = "meta-llama/Llama-3-70b-chat-hf"
    together_embedding_model: str = "intfloat/multilingual-e5-large-instruct"
    # Agent orchestrator (chat-first surface). Tool-calling capable,
    # non-reasoning model. Picked for sub-10s response latency and
    # reliable structured tool-call output.
    #
    # History — do not regress without re-checking on a 16-tool prompt:
    # - moonshotai/Kimi-K2.5: reasoning, 60-180s per turn (too slow).
    # - openai/gpt-oss-120b: harmony channels leak as plain text on
    #   Together's serving; the model emits `assistantcommentary
    #   to=functions.X json{...}` as content instead of structured
    #   tool_calls, then hallucinates the tool result. Unusable as the
    #   primary agent today (2026-05-20). Re-evaluate if Together fixes
    #   the harmony-to-tool_calls translation.
    # - meta-llama/Llama-3.3-70B-Instruct-Turbo: Meta-native function
    #   calling, ~3-6s on tool-using turns, no harmony leaks. Current
    #   default.
    together_agent_model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    # Vision-capable model for the document intake pipeline
    # (services/api/app/agent/vision.py). Must accept image_url content
    # parts; gpt-oss-120b is text-only so vision lives on a separate
    # model. Llama-4-Scout: 1M ctx, $0.18/$0.59 per M, fast 16-expert MoE.
    together_vision_model: str = "meta-llama/Llama-4-Scout-17B-16E-Instruct"
    # Auxiliary model for cheap one-shot tasks like session title
    # generation. Non-reasoning, serverless on Together.
    together_title_model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

    # WhatsApp Business API
    whatsapp_api_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_business_account_id: str = ""
    whatsapp_api_version: str = "v22.0"

    # Email (SMTP) — server-side transactional mail: registration OTP, case
    # and payment/filing/NFT notifications. Provider-agnostic; point these at
    # Amazon SES, Postmark, Mailgun, Gmail, or any relay's SMTP endpoint.
    # An empty ``smtp_host`` leaves email sending disabled, so local dev runs
    # without an email account (see app/notifications/email_transport.py).
    # Deliverability (SPF/DKIM/DMARC): docs/EMAIL_DELIVERABILITY.md.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    # Port 587 uses STARTTLS (default). For port 465 set smtp_use_tls=True;
    # it implies smtp_starttls is ignored (the two are mutually exclusive).
    smtp_starttls: bool = True
    smtp_use_tls: bool = False
    smtp_from_email: str = ""
    smtp_from_name: str = "Etornie"

    # Groq (EtornieGPT)
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # EUIPO API
    euipo_api_key: str = ""
    euipo_api_secret: str = ""
    euipo_base_url: str = "https://api-sandbox.euipo.europa.eu"
    euipo_auth_url: str = "https://auth-sandbox.euipo.europa.eu/oidc/accessToken"

    # OCR fallback for scanned PDFs (issue #66). When a PDF page has no
    # text layer, the RAG extractor renders it and runs Tesseract. Needs
    # the system ``tesseract`` binary; if it is absent, OCR is skipped and
    # text-layer extraction still works. ``ocr_languages`` is a Tesseract
    # lang spec (e.g. "eng" or "eng+tur").
    ocr_enabled: bool = True
    ocr_languages: str = "eng"
    ocr_dpi: int = 200

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # File storage
    upload_dir: str = "./uploads"

    # ClamAV malware scanning for untrusted uploads (#55). Disabled by
    # default so local dev needs no daemon. When enabled, an unreachable or
    # erroring daemon fails CLOSED — the upload is rejected rather than waved
    # through, so this P0 control cannot be silently bypassed by taking the
    # scanner offline. The docker-compose `clamav` service listens on 3310.
    clamav_enabled: bool = False
    clamav_host: str = "clamav"
    clamav_port: int = 3310
    clamav_timeout: float = 30.0

    # CORS
    cors_origins: list[str]
    # Optional regex for additional allowed origins — useful for
    # Cloudflare Pages preview deployments where the subdomain
    # changes per build (e.g. https://abc123.etornie-solana.pages.dev).
    # Empty value disables the regex check.
    cors_origin_regex: str = ""

    # Solana
    solana_cluster_url: str = "https://api.devnet.solana.com"
    solana_operator_key_path: str = "keys/operator.json"
    # Inline operator keypair as a JSON byte array (e.g. "[12,34,...]").
    # When set, takes precedence over solana_operator_key_path so the
    # backend can run on platforms without filesystem persistence
    # (Railway, Fly, etc.). Treat as a secret — never commit.
    solana_operator_key_json: str = ""
    solana_attestation_program_id: str = (
        "CpLYWQn39xw1Qei1fqcDF8NkJGiJsME2dKpAfzkN1T2X"
    )
    solana_attestation_enabled: bool = True
    solana_nft_program_id: str = (
        "6WrZ6NmuQtfpufrLbk5prQCKuF4isX1JwbrvxGFxT2gF"
    )
    solana_nft_enabled: bool = True
    solana_zk_verifier_program_id: str = (
        "GCnpSrJ1W8SXPZ94FbYy4xs5kNZEAQuiDD7Nqk4nwSk5"
    )
    solana_zk_verifier_enabled: bool = True
    api_public_url: str = "http://localhost:8000"

    # Helius webhook for on-chain event reconciliation (#19). Helius POSTs
    # transactions touching the 3 program IDs to /solana/webhooks/helius;
    # ``helius_webhook_auth`` is the shared secret we require in the webhook's
    # Authorization header (empty → the endpoint rejects every call,
    # fail-closed). ``helius_api_key`` + ``helius_webhook_url`` are used by
    # scripts/register_helius_webhook.py. See docs/HELIUS_WEBHOOK.md.
    helius_webhook_auth: str = ""
    helius_api_key: str = ""
    helius_webhook_url: str = ""

    # EtornieGPT x402 payment flow (Faz 5.6)
    etorniegpt_payment_vault: str = ""
    etorniegpt_payment_lamports: int = 100_000  # 0.0001 SOL ~ $0.02

    # BRAID agent (services/braid) internal auth — shared bearer token
    # required on every X-Braid-Auth header to /braid/* endpoints.
    # Empty value disables the entire braid router (fail-closed).
    braid_internal_token: str = ""

    # UK IPO trade mark filing robot (Playwright)
    # The robot fills the UK IPO online form up to the payment step;
    # representative details below are typed verbatim into the form.
    # Empty values cause the robot to refuse to start (validated at runtime).
    ukipo_rep_entity_type: str = ""
    ukipo_rep_name: str = ""
    ukipo_rep_email: str = ""
    ukipo_rep_phone: str = ""
    ukipo_rep_address_line1: str = ""
    ukipo_rep_address_line2: str = ""
    ukipo_rep_city: str = ""
    ukipo_rep_postcode: str = ""
    ukipo_rep_country: str = ""
    ukipo_declarant_name: str = ""
    ukipo_screenshot_dir: str = "/tmp/ukipo-screenshots"

    # UK IPO Solana filing-fee payment vault. Empty value disables the
    # /ukipo/.../payment-requirements endpoint (fail-closed).
    # ukipo_payment_lamports defaults to ~1 SOL — fine for devnet
    # testing; tune per-cluster before mainnet rollout.
    ukipo_payment_vault: str = ""
    ukipo_payment_lamports: int = 1_000_000_000

    # Stripe (card / wallet payments — parallel to x402)
    # Empty `stripe_secret_key` disables the entire /payments/stripe/*
    # surface (fail-closed). Publishable key is exposed to the frontend
    # via /payments/stripe/config and is not a secret.
    stripe_publishable_key: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_api_version: str = "2024-12-18.acacia"
    # Where Stripe Checkout sends the user after a successful or
    # cancelled session. Must be absolute URLs reachable from the user's
    # browser. Trailing `{CHECKOUT_SESSION_ID}` is templated by Stripe.
    stripe_success_url: str = (
        "http://localhost:3000/payments/success?session_id={CHECKOUT_SESSION_ID}"
    )
    stripe_cancel_url: str = "http://localhost:3000/payments/cancelled"

    # Yousign e-signature (issue #63). Empty ``yousign_api_key`` disables
    # the entire /esign/* surface (fail-closed). The sandbox base URL is
    # the default; switch to https://api.yousign.app/v3 for production.
    # ``yousign_webhook_secret`` verifies the X-Yousign-Signature-256
    # header (HMAC-SHA256); empty value makes the webhook fail closed.
    yousign_api_key: str = ""
    yousign_base_url: str = "https://api-sandbox.yousign.app/v3"
    yousign_webhook_secret: str = ""


settings = Settings()  # type: ignore[call-arg]
