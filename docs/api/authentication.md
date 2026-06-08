# Authentication

Etornie issues a **JWT access + refresh token pair**. Send the access
token as a bearer header on every authenticated request; mint a fresh
pair from the refresh token when the access token expires.

```http
Authorization: Bearer <access_token>
```

There are two ways in: **email + password** (this page) and
[**Solana wallet sign-in**](./wallet-signing.md).

## The token model

`POST /auth/login` and the wallet/refresh endpoints all return:

```json
{
  "access_token": "<jwt>",
  "refresh_token": "<jwt>",
  "token_type": "bearer"
}
```

- The **access token** is short-lived and carries the user id + role.
- The **refresh token** is longer-lived and only used to mint new pairs.
- Lifetimes are configurable: `ACCESS_TOKEN_EXPIRE_MINUTES`,
  `REFRESH_TOKEN_EXPIRE_DAYS`.

### Refresh

```http
POST /auth/refresh
Content-Type: application/json

{ "refresh_token": "<jwt>" }
```

Returns a new `{access_token, refresh_token}` pair. The dashboard does
this automatically on a `401` and replays the original request, so an
expired access token never logs the user out.

## Email + password registration

There are two registration paths.

### a) Direct register

```http
POST /auth/register
Content-Type: application/json

{ "email": "a@b.com", "password": "…", "full_name": "Ada" }
```

→ `201` with the created user (role `client`).

### b) OTP-verified register (two-step)

For flows that confirm the email first:

1. `POST /auth/register/request` — sends a one-time code (via EmailJS)
   to the address and stashes the pending signup in Redis.
2. `POST /auth/register/verify` — submit the code to finalise the
   account.

Admin accounts are provisioned via `POST /auth/register/admin`
(operator-only), never by self-service.

## Login

```http
POST /auth/login
Content-Type: application/json

{ "email": "a@b.com", "password": "…" }
```

→ `{access_token, refresh_token, token_type}`. Use the access token on
subsequent requests.

## Who am I

```http
GET /auth/me
Authorization: Bearer <access_token>
```

→ the current `UserResponse` (id, email, full_name, role,
wallet_address, public_handle, …). Handy for bootstrapping the UI and
checking the caller's role.

## Roles

`admin` and `client` only — see
[ADR-0003](../adr/0003-two-tier-role-model.md). Self-service signup
(email or wallet) always yields a `client`; admins cannot be created by
self-elevation.
