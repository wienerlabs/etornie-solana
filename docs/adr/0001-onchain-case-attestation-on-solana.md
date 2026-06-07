# ADR-0001: On-chain case attestation on Solana via sponsored transactions

- **Status:** Accepted
- **Date:** 2026-06-05 (documenting an established decision)
- **Deciders:** Etornie engineering

## Context

Etornie's core value proposition is a tamper-evident record that an IP
matter (a case) exists, who owns it, and what has happened to it. A
centralised database row alone cannot prove to a third party that the
record was not altered after the fact.

We needed an immutable, independently verifiable anchor for each case
without (a) asking non-crypto clients to fund gas, or (b) custodying
client private keys. The platform already targets Solana for its low
fees and fast finality.

Alternatives considered: a private/permissioned ledger (no independent
verifiability), hashing into a public L1 like Ethereum (higher fees,
slower), or skipping on-chain entirely (loses the trust guarantee).

## Decision

We will attest each case on Solana using a dedicated Anchor program
(`programs/etornie-attestation`, program id `CpLYWQn39xw1Qei1fqcDF8NkJGiJsME2dKpAfzkN1T2X`,
devnet today) and a **sponsored, co-signed** transaction model:

- The backend builds a partially-prepared attestation transaction
  (`prepare_case_attestation`) and returns it to the frontend.
- The client signs it with their own wallet (Phantom); the **operator
  keypair co-signs** as fee payer and submits it
  (`finalize_sponsored_attestation_tx`).
- Case lifecycle events are recorded the same way (`update_case_attestation`),
  and the resulting tx signature + PDA are stored on the case row.

The operator key is loaded from `solana_operator_key_path` or, on
filesystem-less hosts, the inline `solana_operator_key_json`.

## Consequences

- Clients get a verifiable on-chain record without paying gas or
  surrendering keys; the operator sponsors fees.
- The operator keypair is sensitive — it co-signs every attestation.
  It must be treated as a secret and is a natural future target for
  multisig hardening (see issue #17, Squads upgrade authority).
- On-chain data is **immutable**: anything attested cannot later be
  redacted, which has privacy implications captured in the data-export
  / erasure work (GDPR). Only non-personal hashes/ids belong on-chain.
- Devnet today; promoting to mainnet requires a verifiable build
  pipeline and key custody review before launch.
