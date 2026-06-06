# ADR-0005: Dual payment rails — x402 (crypto) + Stripe (card)

- **Status:** Accepted
- **Date:** 2026-06-05 (documenting an established decision)
- **Deciders:** Etornie engineering

## Context

Etornie serves both crypto-native users (who hold a Solana wallet) and
conventional clients (who pay by card). Filing fees and platform fees
must be collectable from both audiences, and crypto-native flows want
on-chain, programmatic settlement rather than a redirect to a card
checkout.

## Decision

We will run **two parallel payment rails**, both converging on the same
domain model (`PaymentIntent` with a `provider` discriminator):

- **x402 (crypto):** wallet-signed, on-chain payments for the agent and
  EtornieGPT flows (e.g. `etorniegpt_payment_vault`, the UKIPO Solana
  filing-fee vault). Paired with the ZK compliance proof of ADR-0002.
- **Stripe (card):** hosted Checkout for fiat. The entire `/payments/stripe/*`
  surface fails closed when `stripe_secret_key` is empty. Stripe webhooks
  are signature-verified and drive the `PaymentIntent` state machine;
  refunds and EUIPO auto-submit hang off the confirmed state.

All money conversion (Decimal ↔ Stripe minor units) and the
event→state mapping live in `app/payments/service.py`; routers and tools
never call `stripe.*` directly.

## Consequences

- One `PaymentIntent` table + status machine serves both rails, so
  refunds, the admin panel, and reporting work uniformly.
- Each rail is independently disable-able (empty key/vault = fail
  closed), so a misconfigured provider degrades gracefully instead of
  erroring.
- This rail design is the foundation the recurring **subscription**
  lane extends (org-scoped Stripe subscriptions + EU VAT via Stripe Tax,
  issue #62), which reuses the same Stripe service + webhook dispatch.
