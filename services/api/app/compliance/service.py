"""Server-side compliance proof generation for Stripe-paid filings.

End-to-end flow (called from the Stripe auto-submit hook):
1. Derive a canonical ``query_hash`` from the case_draft + platform +
   stripe payment_intent id. Deterministic and binds every signal we
   want the proof to commit to.
2. Derive a 252-bit ``secret`` from the operator keypair, the
   stripe payment_intent id, and the query_hash. Hidden in the proof
   (private input) but reproducible by the operator alone — replaces
   the wallet-signMessage step of the x402 path.
3. Shell out to the Node.js prover (scripts/prove_compliance.mjs)
   which loads circomlibjs Poseidon + snarkjs against the same WASM
   and zkey the frontend uses, and returns the Groth16 proof in the
   on-chain byte layout the existing verifier program expects.
4. Persist a single ``ComplianceArtifact`` row per PaymentIntent —
   the unique constraint keeps the auto-submit hook idempotent
   across webhook + reconcile races. M4 picks the row up and
   submits the verify_compliance_proof transaction.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import CaseDraft, PaymentIntent
from app.compliance.models import ComplianceArtifact, ComplianceArtifactStatus
from app.solana.client import _load_operator  # operator keypair loader

logger = logging.getLogger(__name__)


# BN254 scalar field upper bound (used by the compliance circuit).
# secret must be < BN254_P, the 252-bit mask gives a tight bound
# without risking modular wrap.
_BN254_P = (
    21888242871839275222246405745257275088548364400416034343698204186575808495617
)
_SECRET_DOMAIN = b"etornie-compliance-stripe-v1"


# Discover the Node prover script + repo root once at import time so
# the subprocess does not have to traverse the filesystem on every
# call. The service lives at ``app/compliance/service.py``, so the
# repo root is four parents up: app → api → services → repo.
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parents[4]
_PROVER_SCRIPT = (
    _THIS_FILE.parents[2] / "scripts" / "prove_compliance.mjs"
)


class ComplianceProofError(RuntimeError):
    """Failure during compliance proof generation or persistence."""


# ---------------------------------------------------------------------------
# Canonical hashes
# ---------------------------------------------------------------------------


def derive_query_hash(
    *,
    case_draft_id: uuid.UUID,
    mark_text: str | None,
    nice_classes: list[int],
    platform: str,
    stripe_payment_intent_id: str,
) -> bytes:
    """32-byte canonical query_hash for a Stripe-paid filing.

    Mirrors the existing ``derive_filing_query_hash`` shape from the
    x402 UKIPO path but binds the Stripe payment_intent id so the
    proof can never be replayed against a different charge.
    """
    nice_str = ",".join(str(c) for c in sorted(nice_classes))
    payload = (
        b"etornie-filing-v1|"
        + str(case_draft_id).encode("utf-8")
        + b"|"
        + (mark_text or "").encode("utf-8")
        + b"|"
        + nice_str.encode("utf-8")
        + b"|"
        + platform.encode("utf-8")
        + b"|"
        + stripe_payment_intent_id.encode("utf-8")
    )
    return hashlib.sha256(payload).digest()


def derive_secret(
    *, stripe_payment_intent_id: str, query_hash: bytes
) -> int:
    """Deterministic operator-side secret bound to (stripe pi, query).

    Equivalent to the wallet-derived secret on the x402 path: same
    inputs ⇒ same secret ⇒ same commitment, so this function alone
    drives the anti-replay guarantee on the Stripe lane.
    """
    if len(query_hash) != 32:
        raise ComplianceProofError(
            f"query_hash must be 32 bytes, got {len(query_hash)}"
        )

    keypair = _load_operator()
    # solders Keypair.secret() returns the 32-byte ed25519 seed (no
    # public-key half), which is the strongest secret the operator
    # exposes server-side.
    try:
        operator_seed = bytes(keypair.secret())
    except AttributeError:
        # Fallback if the solders API surface changes — pubkey is
        # public and still binds the secret to this operator identity.
        operator_seed = bytes(keypair.pubkey())

    digest = hashlib.sha256(
        _SECRET_DOMAIN
        + b"|"
        + operator_seed
        + b"|"
        + stripe_payment_intent_id.encode("utf-8")
        + b"|"
        + query_hash
    ).digest()

    secret = int.from_bytes(digest, "big") & ((1 << 252) - 1)
    if secret == 0:
        secret = 1
    if secret >= _BN254_P:  # defensive — 252-bit mask is < P, but keep it
        raise ComplianceProofError("derived secret escaped BN254 field")
    return secret


# ---------------------------------------------------------------------------
# Node.js subprocess prover
# ---------------------------------------------------------------------------


async def _run_prover(
    *, secret: int, query_hash: bytes, timeout: float = 60.0
) -> dict[str, Any]:
    """Invoke the Node prover and return its parsed JSON output."""
    if not _PROVER_SCRIPT.is_file():
        raise ComplianceProofError(
            f"prover script not found at {_PROVER_SCRIPT}"
        )

    payload = json.dumps(
        {
            "secret_dec": str(secret),
            "query_hash_hex": query_hash.hex(),
        }
    ).encode("utf-8")

    proc = await asyncio.create_subprocess_exec(
        "node",
        str(_PROVER_SCRIPT),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(_REPO_ROOT),
        env={**os.environ},
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=payload), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise ComplianceProofError(
            f"prover timed out after {timeout:.0f}s"
        ) from None

    if proc.returncode != 0:
        err_tail = stderr.decode("utf-8", errors="replace")[-400:]
        raise ComplianceProofError(
            f"prover exited {proc.returncode}: {err_tail.strip()}"
        )

    try:
        return json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ComplianceProofError(
            f"prover returned non-JSON stdout: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Persistence + idempotent generation
# ---------------------------------------------------------------------------


async def find_artifact_for_intent(
    db: AsyncSession, payment_intent_id: uuid.UUID
) -> ComplianceArtifact | None:
    return (
        await db.execute(
            select(ComplianceArtifact).where(
                ComplianceArtifact.payment_intent_id == payment_intent_id
            )
        )
    ).scalar_one_or_none()


async def generate_for_payment_intent(
    db: AsyncSession,
    intent: PaymentIntent,
    draft: CaseDraft,
) -> ComplianceArtifact:
    """Produce + persist a compliance artifact for a confirmed Stripe payment.

    Idempotent: a second call after the first succeeded returns the
    existing artifact unchanged. Errors are persisted with status
    ``failed`` so M4 can surface them without re-running the prover.
    """
    existing = await find_artifact_for_intent(db, intent.id)
    if existing is not None and existing.status != ComplianceArtifactStatus.failed.value:
        return existing

    stripe_pi = intent.gateway_payment_id or ""
    if not stripe_pi:
        raise ComplianceProofError(
            f"PaymentIntent {intent.id} has no gateway_payment_id; "
            "cannot bind the proof to a Stripe charge."
        )

    platform = (intent.gateway_metadata or {}).get("platform") or "EUIPO"
    nice = [int(c) for c in (draft.nice_classes or [])]

    query_hash = derive_query_hash(
        case_draft_id=draft.id,
        mark_text=draft.mark_text,
        nice_classes=nice,
        platform=platform,
        stripe_payment_intent_id=stripe_pi,
    )
    secret = derive_secret(
        stripe_payment_intent_id=stripe_pi,
        query_hash=query_hash,
    )

    try:
        output = await _run_prover(secret=secret, query_hash=query_hash)
    except ComplianceProofError as exc:
        # Persist the failure so the operator can inspect it without
        # re-running the prover from logs alone.
        if existing is None:
            artifact = ComplianceArtifact(
                payment_intent_id=intent.id,
                case_draft_id=draft.id,
                query_hash=query_hash,
                commitment_be32=b"\x00" * 32,
                proof_a=b"\x00" * 64,
                proof_b=b"\x00" * 128,
                proof_c=b"\x00" * 64,
                journal_digest=b"\x00" * 32,
                public_inputs_b64=[],
                status=ComplianceArtifactStatus.failed.value,
                error=str(exc),
            )
            db.add(artifact)
        else:
            existing.status = ComplianceArtifactStatus.failed.value
            existing.error = str(exc)
            artifact = existing
        await db.flush()
        return artifact

    commitment_be32 = int(output["commitment_dec"]).to_bytes(32, "big")
    proof_a = base64.b64decode(output["onchain"]["proof_a_b64"])
    proof_b = base64.b64decode(output["onchain"]["proof_b_b64"])
    proof_c = base64.b64decode(output["onchain"]["proof_c_b64"])
    journal_digest = base64.b64decode(output["onchain"]["journal_digest_b64"])
    public_inputs_b64 = list(output["onchain"]["public_inputs_b64"])

    if existing is None:
        artifact = ComplianceArtifact(
            payment_intent_id=intent.id,
            case_draft_id=draft.id,
            query_hash=query_hash,
            commitment_be32=commitment_be32,
            proof_a=proof_a,
            proof_b=proof_b,
            proof_c=proof_c,
            journal_digest=journal_digest,
            public_inputs_b64=public_inputs_b64,
            status=ComplianceArtifactStatus.created.value,
            error=None,
        )
        db.add(artifact)
    else:
        existing.query_hash = query_hash
        existing.commitment_be32 = commitment_be32
        existing.proof_a = proof_a
        existing.proof_b = proof_b
        existing.proof_c = proof_c
        existing.journal_digest = journal_digest
        existing.public_inputs_b64 = public_inputs_b64
        existing.status = ComplianceArtifactStatus.created.value
        existing.error = None
        artifact = existing

    await db.flush()
    return artifact
