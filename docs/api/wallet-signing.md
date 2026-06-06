# Wallet sign-in

Users can authenticate with a Solana wallet (Phantom / Solflare) instead
of a password, using an **ed25519 nonce-challenge**: the server issues a
one-time message, the wallet signs it, and the server verifies the
signature and returns a normal JWT pair. The wallet's private key never
leaves the browser.

Endpoints live under `/auth/wallet`.

## Flow

```
1. POST /auth/wallet/nonce   { wallet_address }
        → { wallet_address, nonce, message, expires_at }
2. Wallet signs `message` (ed25519)   ← in the browser
3. POST /auth/wallet/verify  { wallet_address, message, signature }
        → { access_token, refresh_token, token_type, user }
```

### 1. Request a nonce

```http
POST /auth/wallet/nonce
Content-Type: application/json

{ "wallet_address": "<base58 pubkey>" }
```

Response:

```json
{
  "wallet_address": "<base58 pubkey>",
  "nonce": "<random>",
  "message": "<the exact string to sign>",
  "expires_at": "2026-06-05T12:00:00Z"
}
```

The `nonce` is **single-use** and stored in Redis with a short TTL, so a
captured signature cannot be replayed. Always sign the returned
`message` verbatim.

### 2. Sign the message

In the browser, have the wallet sign `message` (e.g. Phantom's
`signMessage`) to produce an ed25519 `signature`. This is the only step
that touches the private key.

### 3. Verify

```http
POST /auth/wallet/verify
Content-Type: application/json

{
  "wallet_address": "<base58 pubkey>",
  "message": "<the message from step 1>",
  "signature": "<ed25519 signature>",
  "full_name": "Ada",        // optional, used on first sign-up
  "role": "client"            // optional; sign-up is client-only
}
```

On success:

```json
{
  "access_token": "<jwt>",
  "refresh_token": "<jwt>",
  "token_type": "bearer",
  "user": { "id": "…", "wallet_address": "…", "public_handle": "etornie_ab12cd34", "role": "client" }
}
```

- First sign-in **creates** the account (a `client`); later sign-ins log
  in to the existing one. A `public_handle` like `etornie_<8>` is
  assigned.
- Wallet sign-up is restricted to the `client` role — an admin cannot
  self-elevate through this path.
- A missing/expired nonce returns `400` ("Nonce missing or expired…") —
  request a fresh one and retry.

From here, use the `access_token` exactly as in
[Authentication](./authentication.md), including `POST /auth/refresh`.
