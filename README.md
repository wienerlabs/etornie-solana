# Etornie Solana

End-to-end intellectual-property filing platform built around a single
chat-first agent — **EtornieGPT** — that takes a user from a question
("can I trademark this?") all the way through an on-chain attestation,
a soul-bound Token-2022 NFT, a Groth16 compliance proof, and a
branded PDF/Word/Excel filing receipt. FastAPI backend on
PostgreSQL + pgvector + Redis; Next.js 16 frontend on TypeScript +
Tailwind v4; Solana devnet for everything that touches a key.

> The platform was originally a traditional attorney/client practice
> management tool. As of 2026-05-02 it has been consolidated into a
> two-tier model (admin + client) where every filing flows through the
> EtornieGPT agent and the official IP offices (UKIPO, EUIPO,
> WIPO via API key, IP Australia, …). The retired lawyer layer is
> archived in [`docs/REMOVED_LAWYER_LAYER.md`](docs/REMOVED_LAWYER_LAYER.md).

## Tech Stack

| Component        | Technology                                    |
|------------------|-----------------------------------------------|
| Backend          | FastAPI (Python 3.12+)                        |
| Frontend         | Next.js 16 + React 19, TypeScript, Tailwind v4|
| ORM              | SQLAlchemy 2.0 (async)                        |
| Database         | PostgreSQL 16 + pgvector                      |
| Cache / Queue    | Redis 7                                       |
| Migrations       | Alembic                                       |
| Auth             | JWT (python-jose), passlib + bcrypt, ed25519 wallet sign-in |
| LLM              | Together AI (Kimi K2.5) — text + vision in a single model |
| ZK proofs        | Circom 2.0 + snarkjs Groth16, on-chain BN254 pairing via Wiener Labs Mosaic (`mosaic-groth16`) |
| On-chain         | Solana devnet — Token-2022 (Etornie NFT program), attestation program, ZK verifier program |
| Payments         | x402 over Solana (SOL transfer + memo binding to Groth16 commitment) |
| Documents        | PyMuPDF, ReportLab, python-docx, openpyxl     |
| WhatsApp         | WhatsApp Business Cloud API (Meta)            |
| Email            | SMTP via aiosmtplib (SES / Postmark / any relay) |
| Containerization | Docker, Docker Compose                        |

## Features

### Authentication & Authorization
- JWT access + refresh token pair
- Two roles: **admin** and **client** (lawyer role retired —
  [`docs/REMOVED_LAWYER_LAYER.md`](docs/REMOVED_LAWYER_LAYER.md))
- Email + password registration with server-side SMTP-delivered OTP
- Solana wallet sign-in (Phantom / Solflare) — ed25519 nonce challenge
  with Redis-backed single-use nonces, public handles `etornie_<8>`
- Wallet sign-up restricted to `client` (admin cannot self-elevate)

### EtornieGPT — single chat surface for the whole platform
A multi-turn, tool-calling agent that owns every action a user can
take, instead of scattering the platform across many pages. Backed by
Together AI Kimi K2.5 (the same multimodal model handles text and
vision). Currently exposes 16 tools:

- `start_ukipo_filing` — Playwright robot for the UK IPO filing form
- `check_filing_progress` — poll robot status
- `create_case_draft`, `decide_platform`, `submit_filing`,
  `prepare_payment`, `quote_fees`
- `trademark_search` — EUIPO trademark search
- `goods_services_search`, `goods_services_validate` — EUIPO TMClass
- `design_search` — EUIPO Design (Locarno)
- `validate_logo` — Pillow-based logo file inspection
- `validate_uploaded_document` — Kimi K2.5 vision review of any uploaded
  PDF/image, returns a JSON verdict the agent can paraphrase
- `list_session_uploads` — what files the user has attached so far
- `get_case_by_number` — owner-gated lookup of an existing
  ETR-YYYY-NNNN case
- `export_case` — generate a PDF / Word / Excel filing receipt and
  return a signed download link

The chat surface adds:
- File attach button next to the message input. Multipart upload to
  `/agent/sessions/{id}/uploads`; backend stores under
  `<upload_dir>/agent/<session_id>/<uuid>_<name>` and computes its
  own SHA-256.
- Optional **on-chain ZK ownership proof** for every uploaded file
  (Circom + Groth16, `circuits/file_ownership/`). Two wallet popups
  produce a Poseidon commitment + Groth16 proof; the chip badge
  flips to `ZK ok` once the verify_file_ownership_proof tx confirms
  on devnet.
- A `FilingProgressPanel` that takes over once a robot reaches
  `awaiting_payment`. Pay button runs the **real x402 + Groth16
  compliance proof** handshake (see below) and persists the full proof
  trail on `ukipo_submissions`.
- A `NftClaimPanel` that opens once the filing is recorded — the
  three steps (attest → setup → claim) finish with a soul-bound
  Token-2022 NFT in the user's wallet, branded with the Etornie logo
  and carrying the filing's hash trail in its metadata attributes.

### Real x402 + Groth16 compliance proof
[`app/services/x402_core.py`](services/api/app/services/x402_core.py)
provides one shared core that the EtornieGPT chat *and* the agent
filing flow both consume:

- `derive_filing_query_hash(submission_id, mark_text, nice_classes_json)`
  — canonical hash both sides re-derive
- `decode_compliance_proof(...)` — strict base64 + canonical-halves
  validation
- `compute_expected_memo(query_hash, commitment)` →
  `base58(sha256(query_hash || commitment))`
- `verify_payment_tx` (in `solana/client.py`) — on-chain check of
  recipient, lamports, memo, finality
- `submit_compliance_proof_tx` (sponsored, operator signs) — initialises
  the on-chain `ComplianceRecord` PDA via the
  `etornie-zk-verifier` program

The frontend pipeline is in
[`dashboard/src/lib/zk/compliance.ts`](dashboard/src/lib/zk/compliance.ts)
and the agent's pay button glue lives in
[`dashboard/src/app/dashboard/etorniegpt/page.tsx`](dashboard/src/app/dashboard/etorniegpt/page.tsx).
**No mocks, no fixed amounts, no skipped verifications.**

### Soul-bound Case NFT (Token-2022)
- Auto-mint setup runs in the background after the case attestation
  is confirmed on devnet
- Mint extensions: `MetadataPointer`, `TokenMetadata`,
  `DefaultAccountState=Frozen`, `PermanentDelegate`. Mint and freeze
  authorities are transferred to the program PDA, so the NFT is
  permanently soul-bound.
- Metadata is generated dynamically from live DB state — every wallet
  fetch returns up-to-date status badges + the on-chain proof trail
  (attestation, payment, compliance, query hash, commitment, nft state)
  as `attributes`.
- Cover renders as an SVG with the **Etornie logo embedded as a
  base64 PNG** so wallets like Phantom and Solflare display it the
  same way regardless of the asset path.
- When a case transitions to `closed`, the NFT is automatically
  burned by the operator — the `nft_burn_tx` and `nft_burned_at`
  columns persist the audit trail.

### Cases / Filings
- Auto-numbered `ETR-YYYY-NNNN` (one row per filing engagement)
- Status workflow: `open / in_progress / under_review / closed`
- UK IPO filing robot (Playwright) drives the official site up to the
  payment step; the platform's x402 settlement happens on Solana, the
  GBP fee is paid off-platform from the corporate card
- Per-case export to PDF / Word / Excel via
  [`app/cases/export.py`](services/api/app/cases/export.py) — Etornie
  branded, with the full on-chain trail (attestation tx, NFT mint,
  payment tx, compliance tx, compliance PDA)

### User Profile
- `GET /users/me/timeline` — cross-jurisdiction filing history with
  every on-chain reference inline (one call drives the whole profile
  page)
- Avatar upload (`POST /users/me/avatar`, multipart) — bytes go to
  `<upload_dir>/avatars/<user_id>.<ext>`, JPEG/PNG/WebP/GIF, 5 MiB cap
- Edit name / email / phone in place

### Notifications
- WhatsApp Business Cloud API (Meta) for case + filing alerts
- Server-side SMTP (aiosmtplib) for OTP + case-creation notices
- Scheduled notifications with retry logic

## Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+
- Docker + Docker Compose (for Postgres + Redis)

### Backend
```bash
cp .env.example services/api/.env
docker compose up -d etornie-solana-db etornie-solana-redis
cd services/api
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
```

The host ports are intentionally shifted (`5433` Postgres, `6380`
Redis) so the stack can coexist with the original `etornie` stack.

API docs: <http://localhost:8000/docs>.

### Frontend
```bash
cd dashboard
npm install
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm run dev
```
Dev server defaults to <http://localhost:3000>.

### Public domain for NFT metadata (optional, dev only)
Solflare / Phantom fetch metadata server-side, so they cannot reach
`localhost`. For a fully-rendered NFT cover during local testing,
expose the API through a tunnel and update `API_PUBLIC_URL`:
```bash
ngrok http 8000
# copy the https URL, then:
sed -i '' "s|^API_PUBLIC_URL=.*$|API_PUBLIC_URL=<the-ngrok-url>|" services/api/.env
# restart the backend
```

### Pre-commit hooks
Local lint / format / type-check before every commit
([`.pre-commit-config.yaml`](.pre-commit-config.yaml)): **ruff** (Python
lint + format) and **mypy** on `services/api`, **eslint** on the
dashboard (the same `npm run lint` CI runs), **prettier** on the Anchor /
ZK TypeScript under `tests/`, `scripts/`, `migrations/`, plus generic
whitespace / YAML / JSON hygiene.

```bash
pipx install pre-commit   # or: pip install pre-commit
pre-commit install        # run from the repo root — installs the git hook
```

Hooks only check **staged** files, so the existing backlog never blocks a
commit — linting is adopted file by file. To sweep the whole repo (e.g.
in CI): `pre-commit run --all-files`.

The `ruff` hook is self-contained, but the others use the project's own
toolchains, so install those first:
- **mypy** → backend dev env on `PATH` (`pip install -e ".[dev]"`, venv active)
- **eslint** → `cd dashboard && npm ci`
- **prettier** → root `yarn install`

mypy is intentionally lenient for now (see the `[tool.mypy]` block in
[`services/api/pyproject.toml`](services/api/pyproject.toml)); tighten it
as the codebase gets annotated.

## Frontend Pages

| Route                       | Access | Purpose                                          |
|-----------------------------|--------|--------------------------------------------------|
| `/`                         | Public | Marketing landing page                           |
| `/login`                    | Public | Email + password or wallet sign-in               |
| `/register`                 | Public | Client registration with email OTP               |
| `/dashboard`                | Auth   | Overview tiles                                   |
| `/dashboard/etorniegpt`     | Auth   | The agent — chat, attach, vision, ZK, x402, NFT  |
| `/dashboard/profile`        | Auth   | Avatar, edit profile, filings timeline + exports |
| `/dashboard/cases`          | Admin  | Admin override view of all cases                 |
| `/dashboard/users`          | Admin  | User CRUD                                        |
| `/dashboard/notifications`  | Admin  | Notification center                              |
| `/dashboard/braid`          | Admin  | BRAID compliance / audit log                     |
| `/dashboard/agent`          | →      | 308 redirect to `/dashboard/etorniegpt`          |

## API Surface (highlights)

| Group | Endpoint | Auth |
|-------|----------|------|
| Auth | `/auth/login`, `/auth/refresh`, `/auth/me`, `/auth/wallet/{nonce,verify}` | mixed |
| Users | `GET/PATCH/DELETE /users/{id}`, `GET /users/me/timeline`, `POST/DELETE /users/me/avatar`, `GET /users/{id}/avatar` | self / admin |
| Cases | `GET/POST/PATCH /cases`, `GET /cases/{id}/export?format=pdf\|docx\|xlsx`, `GET /case-metadata/{hex}.{json,svg,png}` | role-filtered |
| Cases on-chain | `GET /cases/{id}/attestation/prepare`, `POST /cases/{id}/attestation/{submit,event-prepare,event-submit}`, `GET /cases/{id}/events`, `POST /cases/{id}/nft/{prepare-claim,finalize-claim}` | participants |
| Documents | `POST /cases/{id}/documents`, `POST /documents/{id}/attach-ownership-proof` | participants |
| Agent | `POST /agent/sessions`, `POST /agent/sessions/{id}/messages`, `POST /agent/sessions/{id}/uploads`, `GET /agent/uploads/{id}/download?token=…`, `POST /agent/uploads/{id}/attach-ownership-proof`, `GET/POST /agent/filings/{id}/{payment-requirements,confirm-payment,progress}` | logged in |
| ZK | `POST /zk/{verify-prepare,verify-submit,file-ownership/prepare,file-ownership/submit}`, `GET /zk/{proof-record,file-ownership/record}/{...}` | logged in |
| EtornieGPT chat (legacy x402 endpoint) | `POST /etorniegpt/chat`, `GET /etorniegpt/chat/{payment-requirements,history,cache-lookup,compliance-record/...}` | logged in |
| EUIPO | `/euipo/trademark-search`, `/euipo/goods-services/{search,validate,...}`, `/euipo/design-search` | server creds |
| BRAID | admin audit + capability endpoints | admin |

## Environment Variables

Required:
| Var | Description |
|-----|-------------|
| `DATABASE_URL` | PostgreSQL DSN (asyncpg) |
| `JWT_SECRET` | Secret for JWT signing |
| `CORS_ORIGINS` | JSON array of allowed origins |
| `TOGETHER_API_KEY` | Together AI key for the agent + vision + RAG |

LLM models (defaults shown):
- `TOGETHER_AGENT_MODEL=moonshotai/Kimi-K2.5`
- `TOGETHER_TITLE_MODEL=meta-llama/Llama-3.3-70B-Instruct-Turbo`
- `TOGETHER_EMBEDDING_MODEL=intfloat/multilingual-e5-large-instruct`

Solana:
- `SOLANA_CLUSTER_URL=https://api.devnet.solana.com`
- `SOLANA_OPERATOR_KEY_PATH` / `SOLANA_OPERATOR_KEY_JSON`
- Program IDs: `SOLANA_ATTESTATION_PROGRAM_ID`,
  `SOLANA_NFT_PROGRAM_ID`, `SOLANA_ZK_VERIFIER_PROGRAM_ID`
- Vaults: `ETORNIEGPT_PAYMENT_VAULT`, `ETORNIEGPT_PAYMENT_LAMPORTS`,
  `UKIPO_PAYMENT_VAULT`, `UKIPO_PAYMENT_LAMPORTS`

UKIPO robot (Playwright):
- `UKIPO_REP_ENTITY_TYPE`, `UKIPO_REP_NAME`, `UKIPO_REP_EMAIL`,
  `UKIPO_REP_PHONE`, `UKIPO_REP_ADDRESS_LINE1`,
  `UKIPO_REP_ADDRESS_LINE2`, `UKIPO_REP_CITY`,
  `UKIPO_REP_POSTCODE`, `UKIPO_REP_COUNTRY`,
  `UKIPO_DECLARANT_NAME`, `UKIPO_SCREENSHOT_DIR`

EUIPO API (sandbox by default — see [Sandbox env docs](https://dev-sandbox.euipo.europa.eu/)):
- `EUIPO_API_KEY`, `EUIPO_API_SECRET`, `EUIPO_BASE_URL`,
  `EUIPO_AUTH_URL`

Notifications:
- `WHATSAPP_API_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
  `WHATSAPP_BUSINESS_ACCOUNT_ID`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`,
  `SMTP_STARTTLS`, `SMTP_USE_TLS`, `SMTP_FROM_EMAIL`, `SMTP_FROM_NAME`
  — see [`docs/EMAIL_DELIVERABILITY.md`](docs/EMAIL_DELIVERABILITY.md) for
  the SPF / DKIM / DMARC records

Uploads / security:
- `CLAMAV_ENABLED`, `CLAMAV_HOST`, `CLAMAV_PORT`, `CLAMAV_TIMEOUT` — ClamAV
  malware scan on every upload (#55). Disabled by default; when enabled an
  unreachable daemon fails closed. The `clamav` compose service provides it.

Observability (#51):
- `LOG_FORMAT` (`json` | `console`), `LOG_LEVEL` — structured logging; JSON
  lines carry `trace_id` / `span_id` + `request_id`.
- `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE` — error tracking (empty disables it).
- `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`,
  `OTEL_CONSOLE_EXPORT`, `OTEL_TRACES_SAMPLE_RATE` — OpenTelemetry traces across
  FastAPI / SQLAlchemy / httpx / Redis (disabled by default). See
  [`docs/OBSERVABILITY.md`](docs/OBSERVABILITY.md).

On-chain reconciliation (#19):
- `HELIUS_WEBHOOK_AUTH`, `HELIUS_API_KEY`, `HELIUS_WEBHOOK_URL` — Helius pushes
  transactions touching the 3 program IDs to `/solana/webhooks/helius`, which
  decodes the Anchor events and reconciles DB rows against the chain
  (fail-closed; disabled until the auth secret is set). See
  [`docs/HELIUS_WEBHOOK.md`](docs/HELIUS_WEBHOOK.md).

Public-facing URL (used by NFT metadata so wallets fetch the right
host):
- `API_PUBLIC_URL=http://localhost:8000` (set to a tunnel for
  Solflare / Phantom rendering)

## Docker

The compose project name is `etornie-solana`. All services and host
ports are namespaced so the stack can run alongside the original
`etornie` stack:

| Service | Host port | Container port |
|---------|-----------|----------------|
| `etornie-solana-db` | 5433 | 5432 |
| `etornie-solana-redis` | 6380 | 6379 |
| `etornie-solana-clamav` | 3310 | 3310 |
| `etornie-solana-app` | 8001 | 8000 |

```bash
docker compose up -d              # full stack
docker compose up -d etornie-solana-db etornie-solana-redis  # infra only
```

Uploaded files are bind-mounted from `services/api/uploads/`. Postgres
data lives in `etornie_solana_pgdata`, Redis data in
`etornie_solana_redisdata`.

## Roadmap

- [x] Fork and rebrand to `etornie-solana` namespace
- [x] Beige / RWA theme across the dashboard
- [x] Wallet sign-in (Phantom + Solflare, ed25519 nonce flow)
- [x] ZK toolchain bootstrap (Circom + snarkjs Groth16)
- [x] AI-agent payment compliance circuit + x402 settlement
- [x] File ownership attestation circuit, on-chain via
  `etornie-zk-verifier` (Wiener Labs [Mosaic](https://github.com/wienerlabs/mosaic), `mosaic-groth16`)
- [x] Solana on-chain attestation program with lifecycle events
- [x] Soul-bound Token-2022 case NFT (auto setup, Phantom claim,
  auto-burn on close)
- [x] Branded case exports (PDF / Word / Excel) carrying the on-chain
  trail
- [x] EtornieGPT consolidation — file upload, vision validation, real
  x402, NFT panel, all behind one chat surface
- [x] Two-tier role model (admin + client); lawyer layer retired
- [ ] WIPO API filing tool (pending API key)
- [ ] IP Australia, USPTO filing robots
- [ ] Programmable licensing and collateralization primitives

## License

See `LICENSE`.
