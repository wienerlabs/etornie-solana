import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.cases.models import CaseStatus, CaseType


class CaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    case_type: CaseType
    client_id: uuid.UUID | None = None
    assigned_lawyer_id: uuid.UUID | None = None
    jurisdiction: str | None = Field(default=None, max_length=255)
    nice_classes: str | None = Field(default=None, max_length=500)
    filing_date: date | None = None
    deadline: date | None = None
    deadline_time: time | None = None
    # Guest client fields (used when client is not registered)
    guest_client_name: str | None = Field(default=None, max_length=255)
    guest_client_email: str | None = None
    guest_client_phone: str | None = Field(default=None, max_length=30)
    # Optional explicit wallet binding. When set, overrides the linked
    # user's wallet_address as the on-chain client pubkey.
    client_wallet: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_client_info(self) -> "CaseCreate":
        """One of: registered client_id, guest info, or explicit wallet."""
        if self.client_id is not None:
            return self
        if self.client_wallet:
            return self
        if self.guest_client_name and (
            self.guest_client_email or self.guest_client_phone
        ):
            return self
        msg = (
            "Provide one of: client_id (registered user), client_wallet "
            "(Solana pubkey), or guest_client_name with email/phone."
        )
        raise ValueError(msg)


class CaseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    case_type: CaseType | None = None
    status: CaseStatus | None = None
    assigned_lawyer_id: uuid.UUID | None = None
    jurisdiction: str | None = Field(default=None, max_length=255)
    nice_classes: str | None = Field(default=None, max_length=500)
    filing_date: date | None = None
    deadline: date | None = None
    deadline_time: time | None = None


class CaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    case_number: str
    case_type: CaseType
    status: CaseStatus
    client_id: uuid.UUID | None
    assigned_lawyer_id: uuid.UUID | None
    jurisdiction: str | None
    nice_classes: str | None = None
    filing_date: date | None
    deadline: date | None
    deadline_time: time | None
    guest_client_name: str | None = None
    guest_client_email: str | None = None
    guest_client_phone: str | None = None
    created_at: datetime
    updated_at: datetime
    attestation_tx: str | None = None
    attestation_pda: str | None = None
    client_wallet: str | None = None


class CaseListResponse(BaseModel):
    cases: list[CaseResponse]
    total: int


class PendingAttestation(BaseModel):
    """Sponsored attestation payload returned when a case is created.

    Contains the ingredients for the frontend to assemble and sign the
    create_case_attestation tx via @solana/web3.js: program/operator/PDA
    pubkeys, the base64-encoded Anchor instruction data, and a fresh
    recent blockhash. The user's Phantom wallet signs, the frontend
    sends the signed tx back to POST /cases/{id}/attestation/submit,
    the backend adds its operator signature and submits to devnet.
    """

    program_id: str
    operator: str
    pda: str
    ix_data_b64: str
    recent_blockhash: str


class CaseCreateResponse(BaseModel):
    case: CaseResponse
    attestation: PendingAttestation | None = None


class AttestationSubmitRequest(BaseModel):
    """Signed (creator-only) VersionedTransaction base64 from the frontend."""

    signed_tx_b64: str


class CaseNoteCreate(BaseModel):
    content: str = Field(min_length=1)


class CaseNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    author_id: uuid.UUID
    content: str
    is_cancelled: bool
    cancelled_at: datetime | None = None
    cancelled_by: uuid.UUID | None = None
    created_at: datetime
