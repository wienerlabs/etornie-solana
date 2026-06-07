"""E-signature models (issue #63).

A ``SignatureRequest`` tracks one document sent to one signer (the case
client) through an external provider (Yousign today). It links the
source PDF document, the signer, the provider's request id, and — once
signed — the stored signed PDF document. The status mirrors the
provider's lifecycle so the UI can show progress without a round-trip.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SignatureRequestStatus(str, enum.Enum):
    draft = "draft"          # created locally, not yet sent to provider
    ongoing = "ongoing"      # sent; awaiting the signer
    signed = "signed"        # completed; signed PDF stored
    declined = "declined"    # signer refused
    expired = "expired"      # provider expiry reached
    cancelled = "cancelled"  # cancelled before completion
    error = "error"          # provider/integration failure


class SignatureProvider(str, enum.Enum):
    yousign = "yousign"


class SignatureRequest(Base):
    __tablename__ = "signature_requests"

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The PDF being signed. SET NULL on delete so a cancelled source
    # document does not cascade-delete the signature audit trail.
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The resulting signed PDF, stored as its own Document once the
    # provider reports completion.
    signed_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    signer_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    provider: Mapped[SignatureProvider] = mapped_column(
        Enum(SignatureProvider, name="signature_provider"),
        nullable=False,
        default=SignatureProvider.yousign,
        server_default=SignatureProvider.yousign.value,
    )
    status: Mapped[SignatureRequestStatus] = mapped_column(
        Enum(SignatureRequestStatus, name="signature_request_status"),
        nullable=False,
        default=SignatureRequestStatus.draft,
        server_default=SignatureRequestStatus.draft.value,
    )

    # Provider correlation ids (Yousign signature_request / document /
    # signer). Nullable until the provider calls return.
    provider_request_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    provider_document_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    provider_signer_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )

    signer_email: Mapped[str] = mapped_column(String(255), nullable=False)
    signer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Hosted signing link the signer opens (also emailed by the provider).
    signing_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Free-text title shown in the provider dashboard + signer email.
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    source_document = relationship(
        "Document", foreign_keys=[source_document_id]
    )
    signed_document = relationship(
        "Document", foreign_keys=[signed_document_id]
    )
