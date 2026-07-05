"""Shared x402 helpers used by both the EtornieGPT chat and the agent
filing flow.

The point of this module is to keep the proof-binding rules in exactly
one place: the same memo scheme, the same canonical-halves check, the
same base64 decoding rules. Everything that needs an on-chain payment
+ Groth16 compliance proof imports from here so the two surfaces can
never silently disagree on what counts as a valid handshake.
"""
from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

import base58
from fastapi import HTTPException, status
from solders.pubkey import Pubkey

from app.config import settings

# Compliance circuit shape — kept in sync with the on-chain verifier.
# 3 entries: [query_hash_hi, query_hash_lo, commitment], each 32 bytes BE.
COMPLIANCE_PUBLIC_INPUT_COUNT = 3
COMPLIANCE_PUBLIC_INPUT_BYTES = 32


@dataclass(frozen=True)
class DecodedComplianceProof:
    proof_a: bytes
    proof_b: bytes
    proof_c: bytes
    public_inputs: list[bytes]
    query_hash: bytes
    commitment: bytes


def b64_decode_strict(
    field_name: str,
    value: str,
    *,
    expected_len: int | None = None,
) -> bytes:
    """Strict base64 decode — raises HTTP 400 on invalid input.

    Used at HTTP boundaries (request bodies). The payload is
    user-supplied so any encoding error must surface as a 4xx, not a
    500.
    """
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid base64 for {field_name}: {exc}",
        ) from exc
    if expected_len is not None and len(raw) != expected_len:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{field_name}: expected {expected_len} bytes, got {len(raw)}",
        )
    return raw


def compute_expected_memo(query_hash: bytes, commitment: bytes) -> str:
    """Memo scheme: ``base58(sha256(query_hash || commitment))``.

    The memo is what the payment tx must carry so the on-chain
    payment irrevocably commits to the proof's commitment.
    """
    if len(query_hash) != 32:
        raise ValueError(f"query_hash must be 32 bytes, got {len(query_hash)}")
    if len(commitment) != 32:
        raise ValueError(f"commitment must be 32 bytes, got {len(commitment)}")
    digest = hashlib.sha256(query_hash + commitment).digest()
    return base58.b58encode(digest).decode("ascii")


def decode_compliance_proof(
    *,
    proof_a_b64: str,
    proof_b_b64: str,
    proof_c_b64: str,
    public_inputs_b64: list[str],
    query_hash_b64: str,
    expected_query_hash: bytes,
    field_prefix: str = "compliance_proof",
) -> DecodedComplianceProof:
    """Decode + sanity-check a compliance proof submitted over HTTP.

    Validates:
      * Proof byte lengths match the on-chain verifier expectations
        (64/128/64).
      * Exactly :data:`COMPLIANCE_PUBLIC_INPUT_COUNT` public inputs of
        :data:`COMPLIANCE_PUBLIC_INPUT_BYTES` bytes each.
      * ``query_hash`` matches the caller-derived expected hash.
      * Public inputs ``[0]`` and ``[1]`` are the canonical zero-padded
        halves of the query hash. The on-chain program enforces this
        too; we surface the error with a 400 before paying the pairing
        cost.

    Returns the decoded structure; raises HTTPException on failure.
    """
    proof_a = b64_decode_strict(f"{field_prefix}.proof_a_b64", proof_a_b64, expected_len=64)
    proof_b = b64_decode_strict(f"{field_prefix}.proof_b_b64", proof_b_b64, expected_len=128)
    proof_c = b64_decode_strict(f"{field_prefix}.proof_c_b64", proof_c_b64, expected_len=64)

    if len(public_inputs_b64) != COMPLIANCE_PUBLIC_INPUT_COUNT:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{field_prefix}.public_inputs_b64 must have exactly "
            f"{COMPLIANCE_PUBLIC_INPUT_COUNT} entries [qh_hi, qh_lo, commitment]",
        )
    public_inputs = [
        b64_decode_strict(
            f"{field_prefix}.public_inputs_b64[{i}]",
            v,
            expected_len=COMPLIANCE_PUBLIC_INPUT_BYTES,
        )
        for i, v in enumerate(public_inputs_b64)
    ]

    query_hash = b64_decode_strict(
        f"{field_prefix}.query_hash_b64",
        query_hash_b64,
        expected_len=32,
    )
    if expected_query_hash != query_hash:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{field_prefix}: query_hash does not match the expected "
            "hash for this request",
        )

    expected_qh_hi = b"\x00" * 16 + query_hash[:16]
    expected_qh_lo = b"\x00" * 16 + query_hash[16:]
    if public_inputs[0] != expected_qh_hi or public_inputs[1] != expected_qh_lo:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{field_prefix}: public_inputs[0]/[1] do not match canonical "
            "zero-padded halves of query_hash",
        )

    commitment = public_inputs[2]
    return DecodedComplianceProof(
        proof_a=proof_a,
        proof_b=proof_b,
        proof_c=proof_c,
        public_inputs=public_inputs,
        query_hash=query_hash,
        commitment=commitment,
    )


def build_explorer_urls(
    *,
    payment_tx: str,
    compliance_tx: str,
    compliance_pda: Pubkey | str,
    cluster: str = settings.solana_cluster,
) -> dict[str, str]:
    """Return solana explorer URLs for the user-facing payment summary."""
    pda_str = str(compliance_pda)
    return {
        "payment_explorer_url": (
            f"https://explorer.solana.com/tx/{payment_tx}?cluster={cluster}"
        ),
        "compliance_explorer_url": (
            f"https://explorer.solana.com/tx/{compliance_tx}?cluster={cluster}"
        ),
        "compliance_record_explorer_url": (
            f"https://explorer.solana.com/address/{pda_str}?cluster={cluster}"
        ),
    }


def derive_filing_query_hash(*, submission_id: str, mark_text: str | None, nice_classes_json: str) -> bytes:
    """Compute the canonical filing-context query hash.

    ``query_hash = sha256("etornie-filing-v1|" + submission_id + "|" + mark_text + "|" + nice_classes_json)``

    Both sides (frontend and backend) compute the same string so the
    proof's commitment binds 1:1 to the submission. Any mismatch in
    submission id, mark text, or nice classes invalidates the proof.
    """
    payload = (
        "etornie-filing-v1|"
        + submission_id
        + "|"
        + (mark_text or "")
        + "|"
        + (nice_classes_json or "")
    )
    return hashlib.sha256(payload.encode("utf-8")).digest()
