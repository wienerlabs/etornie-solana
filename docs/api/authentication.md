# Authentication

Etornie issues an **access token (JWT) + opaque refresh token pair**. Send
the access token as a bearer header on every authenticated request; mint a
fresh pair from the refresh token when the access token expires.

```http
Authorization: Bearer <access_token>
```

There are two ways in: **email + password** (this page) and
[**Solana wallet sign-in**](./wallet-signing.md).

## The token model

`POST /auth/login`, `POST /auth/login/mfa`, `POST /auth/wallet/verify` and
`POST /auth/refresh` all return a token pair:

```json
{
  "access_token": "<jwt>",
  "refresh_token": "<opaque string>",
  "token_type": "bearer"
}
```

- The **access token** is a short-lived JWT that carries the user id +
  role.
- The **refresh token** is longer-lived and only used to mint new pairs.
  It is an opaque random string, not a JWT, and it is **single-use**:
  every successful refresh returns a new refresh token and invalidates the
  one you sent. Always store the token from the latest response.
- Lifetimes are configurable: `ACCESS_TOKEN_EXPIRE_MINUTES`,
  `REFRESH_TOKEN_EXPIRE_DAYS`.

### Refresh

```http
POST /auth/refresh
Content-Type: application/json

{ "refresh_token": "<refresh_token>" }
```

Returns a new `{access_token, refresh_token}` pair and invalidates the
refresh token you sent.

Refresh tokens belong to a *family* (one login session). If an
already-used refresh token is presented again, it is treated as a sign of
theft: the whole family is revoked and the call returns `401`, so the user
has to sign in again. Two concurrent sessions for the same user are
separate families and do not affect each other.

The dashboard refreshes automatically on a `401`, replays the original
request, and stores the new refresh token from each response. Clients that
cache the refresh token must do the same, otherwise they are signed out
after one refresh cycle.

### Logout

```http
POST /auth/logout
Content-Type: application/json

{ "refresh_token": "<refresh_token>" }
```

Revokes the refresh token's whole family and returns `204`. It is
idempotent and also returns `204` for an unknown or already-revoked
token. Access tokens that were already issued remain valid until they
expire.

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

If the account has two-factor authentication enabled, the response instead
carries `mfa_required: true` and a short-lived `mfa_token`; exchange it
together with a TOTP or recovery code at `POST /auth/login/mfa` to receive
the token pair.

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
