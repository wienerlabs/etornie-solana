"""Pydantic schemas for the agent orchestrator API."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.agent.models import (
    AgentMessageRole,
    AgentSessionStatus,
    AgentUploadStatus,
)


class SessionCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class SessionRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    status: AgentSessionStatus
    model: str
    total_input_tokens: int
    total_output_tokens: int
    started_at: datetime
    last_activity_at: datetime


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]


class MessageSendRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: AgentMessageRole
    content: str | None
    tool_call_id: str | None
    tool_name: str | None
    tool_arguments: dict | None
    tool_result: dict | None
    created_at: datetime


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]


class TurnResponse(BaseModel):
    """Result of a single user-message → agent-reply round trip.

    `messages` includes the user message, any intermediate tool calls/
    results, and the final assistant message — in chronological order.
    """

    session: SessionResponse
    messages: list[MessageResponse]


class AgentUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    original_filename: str
    mime_type: str | None
    size_bytes: int
    sha256_hex: str
    status: AgentUploadStatus
    expected_document_type: str | None
    detected_document_type: str | None
    validation_summary: str | None
    validated_at: datetime | None
    file_hash_hex: str | None
    ownership_commitment_hex: str | None
    ownership_proof_pda: str | None
    ownership_verified_at: datetime | None
    linked_case_id: uuid.UUID | None
    linked_document_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class AgentUploadListResponse(BaseModel):
    uploads: list[AgentUploadResponse]


class AttachUploadOwnershipRequest(BaseModel):
    proof_pda: str = Field(
        ...,
        min_length=32,
        max_length=44,
        description=(
            "FileOwnershipRecord PDA (base58) returned by "
            "/zk/file-ownership/submit. Backend re-fetches the on-chain "
            "record and verifies the file_hash + commitment match the "
            "values stored on this upload row at upload time."
        ),
    )


class FilingComplianceProofPayload(BaseModel):
    """Groth16 compliance proof shipped with a filing payment confirmation.

    Encoding mirrors the EtornieGPT chat handshake byte-for-byte so the
    same circuits, the same on-chain verifier, and the same browser
    pipeline serve both surfaces.
    """

    proof_a_b64: str = Field(..., description="64-byte proof_a, base64")
    proof_b_b64: str = Field(..., description="128-byte proof_b, base64")
    proof_c_b64: str = Field(..., description="64-byte proof_c, base64")
    public_inputs_b64: list[str] = Field(
        ...,
        min_length=3,
        max_length=3,
        description=(
            "Three 32-byte BE field elements: [qh_hi, qh_lo, commitment]. "
            "Each entry is base64."
        ),
    )
    query_hash_b64: str = Field(
        ...,
        description=(
            "Canonical filing-context query hash (32 bytes, base64). Must "
            "match the hash the backend re-derives from the submission."
        ),
    )


class FilingPaymentConfirmRequest(BaseModel):
    """Body of POST /agent/filings/{submission_id}/confirm-payment."""

    payer_wallet: str = Field(
        ..., description="Solana pubkey of the wallet that signed the payment tx"
    )
    payment_tx: str = Field(
        ..., description="Confirmed Solana payment tx signature (base58)"
    )
    compliance_proof: FilingComplianceProofPayload


class FilingPaymentConfirmResponse(BaseModel):
    submission_id: uuid.UUID
    case_id: uuid.UUID
    case_number: str
    status: str
    payer_wallet: str
    payment_tx: str
    payment_lamports: int
    payment_at: datetime
    query_hash_hex: str
    commitment_hex: str
    compliance_tx: str
    compliance_pda: str
    payment_explorer_url: str
    compliance_explorer_url: str
    compliance_record_explorer_url: str
