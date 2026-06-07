# ADR-0002: Zero-knowledge compliance proofs for paid filings

- **Status:** Accepted
- **Date:** 2026-06-05 (documenting an established decision)
- **Deciders:** Etornie engineering

## Context

When a filing is paid for and auto-submitted, we want to prove on-chain
that the payment was bound to a specific, compliant filing request —
without publishing the client's private filing details (mark text, Nice
classes, applicant) on a public ledger. We need *verifiable compliance*
and *privacy* at the same time.

A plain on-chain record of the filing payload would leak confidential
client data. A purely off-chain claim would not be independently
verifiable.

## Decision

We will generate a **Groth16 zero-knowledge proof** per paid filing and
verify it on-chain with a dedicated Anchor verifier program
(`programs/etornie-zk-verifier`, id `GCnpSrJ1W8SXPZ94FbYy4xs5kNZEAQuiDD7Nqk4nwSk5`).

- A canonical `query_hash` binds the filing (draft id, mark, Nice
  classes, platform) and the payment id; a secret derived from the
  operator key + payment id makes the commitment reproducible and
  replay-resistant (`app/compliance/service.py`).
- Proof generation shells out to a Node prover
  (`services/api/scripts/prove_compliance.mjs`) sharing the same circuit WASM/zkey as
  the frontend (`circuits/`), returning the proof in the on-chain byte
  layout the verifier expects.
- One `ComplianceArtifact` row is persisted per `PaymentIntent`
  (idempotent), then `verify_compliance_proof` is submitted on-chain.

Paid filings **require** a real compliance proof + on-chain verification;
this is not optional for the agent payment path.

## Consequences

- Confidential filing details stay off-chain; only the proof and
  commitments are public — privacy and verifiability together.
- Adds a Node prover dependency and a multi-step pipeline (prove →
  persist → on-chain verify) with its own failure modes; artifacts
  record `failed` status with the error so the operator can inspect
  without re-running from logs.
- The verifier program and circuit verifying key must stay in lockstep;
  changing the circuit requires redeploying the verifier and re-pinning
  the VK.
