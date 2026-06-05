# Etornie API — curated reference

The exhaustive, always-current endpoint reference is the auto-generated
**OpenAPI / Swagger UI at `/docs`** (and the raw schema at
`/openapi.json`) on a running backend. These pages do **not** repeat
every endpoint — they are the *narrative* docs Swagger can't give you:
the multi-step flows, the auth model, and the conventions that tie the
surface together.

## Start here

- [Authentication](./authentication.md) — email/password + OTP, the
  JWT access/refresh model, roles.
- [Wallet sign-in](./wallet-signing.md) — the ed25519 nonce-challenge
  flow for Solana wallets.
- [RAG pipeline](./rag.md) — indexing documents and asking questions
  about a case (`/ai/*`).

## Base URL

| Environment | Base URL |
|-------------|----------|
| Local dev | `http://localhost:8000` |

## Conventions

### Authentication

Most endpoints require a bearer token:

```http
Authorization: Bearer <access_token>
```

Obtain one via [Authentication](./authentication.md) or
[Wallet sign-in](./wallet-signing.md). Access tokens are short-lived;
refresh them with `POST /auth/refresh` (see Authentication). Lifetimes
are configurable (`ACCESS_TOKEN_EXPIRE_MINUTES`,
`REFRESH_TOKEN_EXPIRE_DAYS`).

### Roles

Two system roles: **admin** (platform operator) and **client** (case
owner). Most write endpoints on `/cases`, `/payments`, etc. are
admin-only; a client can read/act only on resources they own. See
[ADR-0003](../adr/0003-two-tier-role-model.md).

### Errors

| Shape | When |
|-------|------|
| `{"detail": "..."}` | `HTTPException` (404, 403, 400, …). |
| `{"detail": [ {loc, msg, type}, … ]}` | `422` request-validation errors. |
| `{"error": "...", "category": "..."}` | Domain errors (`UserFacingError`) — a safe user message; the technical detail is logged server-side, never returned. |

### Resource surface

Top-level routers (see `/docs` for the full list of operations):

| Prefix | Area |
|--------|------|
| `/auth`, `/auth/wallet` | Authentication, wallet sign-in |
| `/users` | Profile, avatar, timeline, GDPR export |
| `/cases` | Cases, notes, attestation, NFT claim, export — plus nested document upload/review, renewals, and required-documents |
| `/ai` | RAG index / search / chat |
| `/agent`, `/etorniegpt` | EtornieGPT agent sessions + chat + tools |
| `/payments` | Stripe + x402 payments, webhooks |
| `/organizations` | Multi-tenant orgs, memberships, invites |
| `/euipo`, `/ukipo` | IP-office filing integrations |
| `/zk` | Zero-knowledge ownership proofs |
| `/notifications`, `/in-app-notifications` | Outbound + in-app notifications |

Document, renewal, and required-document endpoints are nested under
`/cases` (e.g. `/cases/{id}/documents`); see `/docs` for exact paths.
