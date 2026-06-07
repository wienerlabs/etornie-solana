import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.cases.models import (
    CaseNftState,
    CaseStatus,
    CaseType,
    ChainRouting,
    MocaStatus,
)


class CaseCreate(BaseModel):
    # title + case_type are required UNLESS a template_key is supplied,
    # in which case the create endpoint fills them from the template
    # (issue #65). Validated below.
    title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    case_type: CaseType | None = None
    template_key: str | None = Field(
        default=None,
        max_length=64,
        description="One-click case template key; supplies title / "
        "case_type / description defaults the request omits.",
    )
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

    # Cross-chain routing (#73). None -> system default (solana).
    chain_routing: ChainRouting | None = None
    # Optional explicit wallet binding. When set, overrides the linked
    # user's wallet_address as the on-chain client pubkey.
    client_wallet: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_template_or_required(self) -> "CaseCreate":
        """Without a template_key, title + case_type are mandatory."""
        if self.template_key is None:
            if not self.title or not self.title.strip():
                raise ValueError("title is required when no template_key is given.")
            if self.case_type is None:
                raise ValueError(
                    "case_type is required when no template_key is given."
                )
        return self

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


class BulkImportRowResult(BaseModel):
    row: int = Field(..., description="1-based data-row number.")
    status: str = Field(..., description="'created' or 'failed'.")
    case_id: uuid.UUID | None = None
    case_number: str | None = None
    error: str | None = None


class BulkImportResponse(BaseModel):
    total: int
    created: int
    failed: int
    results: list[BulkImportRowResult]


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
    chain_routing: ChainRouting | None = None


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
    nft_mint: str | None = None
    nft_state: CaseNftState = CaseNftState.none
    nft_setup_tx: str | None = None
    nft_mint_tx: str | None = None
    nft_burn_tx: str | None = None
    nft_burned_at: datetime | None = None
    chain_routing: ChainRouting = ChainRouting.solana
    moca_status: MocaStatus = MocaStatus.not_routed
    moca_attestation_tx: str | None = None


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


class PendingEventAttestation(BaseModel):
    """Payload to finalize an update_case_attestation sponsored tx."""

    program_id: str
    operator: str
    pda: str
    ix_data_b64: str
    recent_blockhash: str
    event_type: int
    metadata_hash_hex: str


class EventPrepareRequest(BaseModel):
    event_type: int = Field(ge=1, le=255)


class EventSubmitRequest(BaseModel):
    signed_tx_b64: str
    event_type: int = Field(ge=1, le=255)
    metadata_hash_hex: str = Field(min_length=64, max_length=64)
    actor_wallet: str = Field(min_length=32, max_length=64)


class CaseEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    event_type: int
    tx_signature: str
    actor_wallet: str
    metadata_hash: str
    created_at: datetime


class NftAccountMeta(BaseModel):
    pubkey: str
    is_signer: bool
    is_writable: bool


class NftInstructionPayload(BaseModel):
    program_id: str
    accounts: list[NftAccountMeta]
    data_b64: str


class MintClaimPrepareResponse(BaseModel):
    """Payload for the client to build + sign the mint_case_nft tx.

    Frontend assembles a VersionedTransaction from ``ata_ix`` and
    ``mint_ix`` (in that order), has Phantom sign (client signature), and
    posts the serialized signed tx bytes back to finalize-claim.
    """

    program_id: str
    operator: str
    client: str
    mint: str
    client_token_account: str
    nft_authority: str
    case_nft_record: str
    ata_ix: NftInstructionPayload
    mint_ix: NftInstructionPayload
    recent_blockhash: str
    metadata_uri: str
    metadata_uri_hash_hex: str


class MintClaimFinalizeRequest(BaseModel):
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
