# Developer onboarding

Get a local Etornie environment running end to end. The repo's top-level
`README.md` is product-facing; **this** is the guide for contributors.

You can be running the backend + dashboard in ~15 minutes. The Solana
programs are only needed if you work on the on-chain layer.

---

## 1. What's in the repo

Etornie is a monorepo:

| Path | What it is | Stack |
|------|------------|-------|
| `services/api/` | Backend API | Python 3.12, FastAPI, SQLAlchemy (async), Alembic, Postgres + pgvector, Redis |
| `dashboard/` | Web app | Next.js, React, TypeScript, Tailwind |
| `programs/` | On-chain programs (`etornie-attestation`, `etornie-ip-token`, `etornie-zk-verifier`) | Rust, Anchor, Solana |
| `circuits/` | Zero-knowledge circuits | Circom / snarkjs |
| `services/braid/` | BRAID reasoning agent | — |
| `docs/` | Docs incl. [ADRs](./adr/) | Markdown |

The two services you'll touch most are `services/api` (backend) and
`dashboard` (frontend).

---

## 2. Prerequisites

- **Docker** + Docker Compose — for local Postgres (pgvector) and Redis.
- **Python ≥ 3.12** — backend.
- **Node.js 20** — dashboard.
- **(on-chain work only)** Rust, the Solana CLI, and Anchor — see §6.

macOS install hints:

```bash
brew install python@3.12 node@20
# Docker Desktop from docker.com
```

---

## 3. Clone + start the databases

```bash
git clone https://github.com/wienerlabs/etornie-solana.git
cd etornie-solana

# Postgres (pgvector) on :5433 and Redis on :6380
docker compose up -d etornie-solana-db etornie-solana-redis
```

The compose ports are deliberately non-standard (`5433`, `6380`) so they
don't clash with a local Postgres/Redis.

---

## 4. Backend (`services/api`)

```bash
cd services/api

# 4.1 Virtualenv + dependencies (editable install + dev/test extras)
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 4.2 Environment — the defaults already point at the compose DB/Redis
cp .env.example .env

# 4.3 Apply migrations
alembic upgrade head

# 4.4 Run (http://localhost:8000, OpenAPI docs at /docs)
uvicorn app.main:app --reload --port 8000
```

Only three settings are strictly required (the rest fail closed when
empty): `DATABASE_URL`, `JWT_SECRET`, `CORS_ORIGINS`. The provided
`.env.example` sets sensible local values for all three.

Sanity check: open <http://localhost:8000/health> → `{"status":"ok"}`,
and <http://localhost:8000/docs> for the interactive API.

---

## 5. Dashboard (`dashboard`)

```bash
cd dashboard
npm install
cp .env.local.example .env.local   # points at http://localhost:8000
npm run dev                        # http://localhost:3000
```

> Next.js may warn about multiple lockfiles — the dashboard uses npm
> (`package-lock.json`); it's harmless.

---

## 6. Solana programs (on-chain work only)

Skip this unless you're changing the Anchor programs or circuits.

Pinned toolchain (see `.github/workflows/anchor.yml`):
**Solana CLI `3.0.15`**, **Anchor `0.31.1`** (via `avm`).

```bash
# Solana CLI
sh -c "$(curl -sSfL https://release.anza.xyz/v3.0.15/install)"

# Anchor via avm
cargo install --git https://github.com/coral-xyz/anchor avm --locked --force
avm install 0.31.1 && avm use 0.31.1

# Target devnet + a funded keypair (devnet faucet)
solana config set --url devnet
solana-keygen new -o services/api/keys/operator.json   # operator keypair
solana airdrop 2 "$(solana-keygen pubkey services/api/keys/operator.json)"

# Build / test the programs
anchor build
anchor test
```

If the faucet rate-limits, retry or use <https://faucet.solana.com>.
Program ids are pinned in `Anchor.toml`.

---

## 7. Running the tests

**Backend** (needs Redis from §3 running; the test DB is in-memory
SQLite, so Postgres is not required for tests):

```bash
cd services/api
source .venv/bin/activate
pytest                 # whole suite
pytest tests/test_cases.py -v        # one file
pytest -k bulk_import                # by keyword
```

Some tests `skip` when an external key is absent (e.g. live Stripe /
Yousign / Tesseract) — that's expected, not a failure.

**Dashboard:**

```bash
cd dashboard
npm test               # vitest
npm run lint           # eslint
```

---

## 8. Day-to-day

- Backend auto-reloads with `--reload`; the dashboard hot-reloads.
- After editing models, create a migration:
  `alembic revision -m "..."` then `alembic upgrade head`.
- New env var? Add it to `app/config.py` **and** `.env.example`.
- Architecture decisions are recorded as [ADRs](./adr/).

---

## 9. Troubleshooting

| Symptom | Fix |
|---------|-----|
| Backend won't boot / pydantic error | `.env` missing or `DATABASE_URL`/`JWT_SECRET`/`CORS_ORIGINS` unset — `cp .env.example .env`. |
| `connection refused` to DB/Redis | `docker compose up -d etornie-solana-db etornie-solana-redis`. |
| `alembic upgrade` can't find a revision | Your DB is ahead of the branch (e.g. after testing another branch). Use a fresh DB volume: `docker compose down -v` then up + `alembic upgrade head`. |
| Tests error on Redis | Redis must be running on `:6380` (§3). |
| Dashboard 401s then redirects to /login | Backend not running on `:8000` or `NEXT_PUBLIC_API_URL` wrong. |
| Port already in use (5433/6380/8000/3000) | Stop the conflicting process or change the port. |
