"""SQLAlchemy model for EtornieGPT chat history.

Each row captures a single question / answer exchange plus the x402 payment
tx signature and the on-chain ZK compliance PDA that authorized it.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    country_detected: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    language: Mapped[str] = mapped_column(
        String(10), nullable=False, default="tr"
    )

    # x402 + compliance binding (nullable for non-paid admin/preview rows)
    query_hash_hex: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    commitment_hex: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    payer_wallet: Mapped[str | None] = mapped_column(
        String(44), nullable=True
    )
    payment_tx: Mapped[str | None] = mapped_column(
        String(90), nullable=True, index=True
    )
    compliance_tx: Mapped[str | None] = mapped_column(
        String(90), nullable=True
    )
    compliance_pda: Mapped[str | None] = mapped_column(
        String(44), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    user = relationship("User", foreign_keys=[user_id])
