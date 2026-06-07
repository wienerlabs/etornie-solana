# Architecture Decision Records (ADRs)

This folder is the single home for Etornie's significant architecture
decisions. Previously these were scattered across PR descriptions and
code comments; an ADR captures the **context**, the **decision**, and
its **consequences** in one durable place so future contributors can
understand *why* the system is the way it is.

## What is an ADR?

A short, immutable document describing one architecturally significant
decision. Once accepted, an ADR is not edited — if a decision changes,
write a new ADR that **supersedes** the old one (and link both ways).

See Michael Nygard's original article:
<https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions>

## When to write one

Write an ADR when a choice is expensive to reverse or shapes the system:
a new external dependency, a security/compliance model, an on-chain
program design, a data-model change with wide blast radius, or a
platform/runtime decision.

You do **not** need an ADR for routine feature work, bug fixes, or
choices that are cheap to change later.

## How to add one

1. Copy [`0000-adr-template.md`](./0000-adr-template.md) to
   `NNNN-short-title.md`, where `NNNN` is the next zero-padded number.
2. Fill in Status, Context, Decision, Consequences.
3. Open it as **Proposed**; flip to **Accepted** when merged. Use
   **Superseded by ADR-XXXX** when a later decision replaces it.
4. Add a row to the index below.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](./0001-onchain-case-attestation-on-solana.md) | On-chain case attestation on Solana via sponsored transactions | Accepted |
| [0002](./0002-zero-knowledge-compliance-proofs.md) | Zero-knowledge compliance proofs for paid filings | Accepted |
| [0003](./0003-two-tier-role-model.md) | Two-tier role model (retire the lawyer layer) | Accepted |
| [0004](./0004-agent-orchestrator-model.md) | Agent orchestrator LLM = Llama-3.3-70B-Instruct-Turbo | Accepted |
| [0005](./0005-dual-payment-rails.md) | Dual payment rails: x402 (crypto) + Stripe (card) | Accepted |
