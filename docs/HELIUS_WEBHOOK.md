# Helius webhook + on-chain state reconciliation (#19)

The backend writes intents (a case attestation, an NFT mint/burn) and confirms
them synchronously. If that confirmation is dropped — a lost RPC response, a
slot rollback, a restart mid-flow — the DB and the chain drift. This webhook
closes the gap: Helius pushes every transaction touching our three programs,
and we reconcile DB rows against what actually landed on-chain.

## How it works

1. **Helius → us.** A Helius *raw* webhook is registered for the three program
   IDs. On every matching transaction Helius POSTs the raw tx (including
   `meta.logMessages`) to `POST /solana/webhooks/helius`.
2. **Decode.** `app/solana/events.py` decodes the Anchor events from the log
   messages (`Program data: <base64>` → 8-byte discriminator + Borsh fields).
   The schemas mirror the committed IDLs and are cross-checked against them in
   the test suite. Three events are modelled:
   - `CaseAttestationUpdated` (etornie-attestation)
   - `CaseNftMinted`, `CaseNftBurned` (etornie-ip-token)
3. **Reconcile (idempotent).** Each event carries the 16-byte `case_id`
   (a UUID), so we look up the `Case` and apply:
   - attestation → back-fill `attestation_tx` if missing and append a
     `case_events` row (deduped on case + tx + event_type);
   - mint → `nft_state=minted`, `nft_mint`, `nft_mint_tx`, `client_wallet`;
   - burn → `nft_state=burned`, `nft_burn_tx`, `nft_burned_at`.
   Re-delivery is a no-op. A tx with `meta.err` set is ignored.

## Security

Fail-closed. The endpoint rejects every request unless the `Authorization`
header matches `HELIUS_WEBHOOK_AUTH` (constant-time compare), so it is inert
until configured. Authorised calls always return `200` — a single malformed tx
is logged and skipped, never `500`'d, so Helius does not retry-storm.

## Configuration

| Variable | Purpose |
|----------|---------|
| `HELIUS_WEBHOOK_AUTH` | Shared secret required in the webhook's `Authorization` header. Empty ⇒ endpoint disabled. |
| `HELIUS_API_KEY` | Helius API key, for the registration script. |
| `HELIUS_WEBHOOK_URL` | Public URL of the endpoint. Defaults to `API_PUBLIC_URL` + `/solana/webhooks/helius`. |

## Register the webhook

With the backend env loaded:

```bash
cd services/api
python scripts/register_helius_webhook.py
```

The script registers a raw webhook for the three program IDs pointing at the
endpoint, with `HELIUS_WEBHOOK_AUTH` as the auth header. It skips creation if a
webhook already targets that URL. Without `HELIUS_API_KEY` it prints setup
instructions and exits.

## Metrics

Per-program counters (`received` / `reconciled` / `skipped` / `failed`) are
accumulated across deliveries, logged (structured) on every webhook call, and
exposed to admins at `GET /solana/webhooks/helius/metrics`.

## Local testing

A live Helius webhook needs a public URL + a Helius account. To exercise the
decoder + reconciler without Helius, POST a raw-tx-shaped payload to the
endpoint with the right `Authorization` header (see `tests/test_solana_events.py`
for payloads), or run the test suite.
