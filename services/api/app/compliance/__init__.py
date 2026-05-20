"""Compliance proof artifacts for Stripe-paid filings.

The x402 flow generates a Groth16 compliance proof in the browser
using the user's Solana wallet secret. Stripe customers have no
wallet to sign with, so this module produces an equivalent proof
server-side: the secret is derived deterministically from the
operator keypair plus the Stripe ``payment_intent`` id, the
commitment is computed via the same circomlibjs Poseidon as the
frontend, and a Groth16 proof is generated through a Node.js
subprocess that drives snarkjs against the existing compliance
circuit (``circuits/compliance/``).

The output is persisted as a ``ComplianceArtifact`` so M4 (on-chain
attestation) and M5 (NFT mint) can pick it up regardless of which
process happens to be running when the user finishes payment.
"""
