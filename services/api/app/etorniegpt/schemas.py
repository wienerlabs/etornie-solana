from pydantic import BaseModel, Field


class EtornieGPTRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    language: str = Field(default="tr", max_length=10)


class EtornieGPTResponse(BaseModel):
    answer: str
    country_detected: str | None = None
    model: str


class ComplianceProofPayload(BaseModel):
    """Groth16 proof + public inputs for verify_compliance_proof, base64."""

    proof_a_b64: str = Field(..., description="64-byte proof_a, base64")
    proof_b_b64: str = Field(..., description="128-byte proof_b, base64")
    proof_c_b64: str = Field(..., description="64-byte proof_c, base64")
    public_inputs_b64: list[str] = Field(
        ...,
        description=(
            "[qh_hi, qh_lo, commitment], each a 32-byte BE field element "
            "in base64, in circuit declaration order."
        ),
    )
    query_hash_b64: str = Field(
        ..., description="sha256(query), 32 bytes, base64"
    )


class EtornieGPTChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    language: str = Field(default="tr", max_length=10)
    payer_wallet: str = Field(
        ..., description="Base58 pubkey of the wallet that paid the x402 fee"
    )
    payment_tx: str = Field(
        ..., description="Base58 signature of the on-chain SOL transfer"
    )
    compliance_proof: ComplianceProofPayload


class EtornieGPTChatResponse(BaseModel):
    answer: str
    country_detected: str | None = None
    model: str
    query_hash_hex: str
    commitment_hex: str
    payment_tx: str
    compliance_tx: str
    compliance_pda: str
    payment_explorer_url: str
    compliance_explorer_url: str
    compliance_record_explorer_url: str


class PaymentRequirementsResponse(BaseModel):
    """x402-style payment requirements for a single AI query.

    The memo scheme is described as a human-readable string because the
    *exact* memo content is per-query: base58(sha256(query_hash || commitment)).
    The frontend computes it locally after deriving (secret, commitment).
    """

    network: str = "solana:devnet"
    asset: str = "SOL"
    recipient: str
    lamports: int
    memo_scheme: str = (
        "base58(sha256(query_hash || commitment)) - 32-byte binding"
    )


class ChatMessageOut(BaseModel):
    id: str
    question: str
    answer: str
    model: str
    country_detected: str | None
    language: str
    query_hash_hex: str | None
    payment_tx: str | None
    compliance_tx: str | None
    compliance_pda: str | None
    created_at: str
