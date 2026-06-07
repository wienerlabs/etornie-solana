import enum
from datetime import datetime

import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserRole(str, enum.Enum):
    """Two-tier role model.

    The ``lawyer`` value still exists in the Postgres ``user_role``
    enum (historical migrations reference it) but has been retired
    from the application layer on 2026-05-02 — see
    docs/REMOVED_LAWYER_LAYER.md. Nothing in the runtime path emits
    or accepts it any more, so any code that needs to handle
    legacy rows should treat them as ``client``.
    """

    admin = "admin"
    client = "client"


class AuthMethod(str, enum.Enum):
    email = "email"
    wallet = "wallet"
    both = "both"


class User(Base):
    __tablename__ = "users"

    __table_args__ = (
        CheckConstraint(
            "auth_method IN ('email', 'wallet', 'both')",
            name="ck_users_auth_method_values",
        ),
        CheckConstraint(
            "(email IS NOT NULL AND hashed_password IS NOT NULL) "
            "OR wallet_address IS NOT NULL",
            name="ck_users_authenticatable",
        ),
    )

    email: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        nullable=False,
        default=UserRole.client,
    )
    phone: Mapped[str | None] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(default=True)

    wallet_address: Mapped[str | None] = mapped_column(
        String(44), unique=True, index=True, nullable=True
    )
    # Unified identity (#74): an EVM (Ethereum/Moca) address linked to this
    # same account, verified by an EIP-191 signature. Stored lowercase so a
    # human keeps one etornie handle across Solana + EVM. Nullable until
    # the user links an EVM wallet.
    evm_address: Mapped[str | None] = mapped_column(
        String(42), unique=True, index=True, nullable=True
    )
    public_handle: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    auth_method: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=AuthMethod.email.value,
    )

    # Opt-in notification settings. ``notification_email`` is a separate
    # address the user can supply from their settings page (useful for
    # wallet-only accounts that never collected an email at signup).
    # ``email_notifications_enabled`` is the master toggle the
    # notification dispatcher checks before sending anything — false
    # by default, so wallet-only users never receive surprise mail.
    notification_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    email_notifications_enabled: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false"
    )

    # Multi-tenancy: a user can join many orgs via
    # OrganizationMembership rows. ``default_organization_id`` is the
    # org /auth/me echoes back as ``current_organization``, so a fresh
    # login lands somewhere sensible without the frontend having to
    # pick. Nullable for legacy rows; the install-time backfill
    # populates a default org and stamps this column.
    default_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Profile picture. The bytes live in the DB (avatar_data) so the avatar
    # survives container restarts and redeploys on ephemeral hosting;
    # avatar_data is deferred so it is never loaded on ordinary user queries.
    # avatar_path is the legacy on-disk location, kept only so pre-migration
    # avatars can still be served as a fallback.
    avatar_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    avatar_mime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar_data: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True, deferred=True
    )

    # Calendar (ICS) subscription feed. When set, this unguessable token
    # authorises an unauthenticated read-only iCalendar feed of the
    # user's case deadlines and renewals at
    # GET /calendar/feed/<token>.ics, which Google/Outlook/Apple can
    # subscribe to. Null until the user enables the feed; rotating the
    # token revokes the previous URL.
    calendar_feed_token: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    client_cases: Mapped[list["Case"]] = relationship(  # noqa: F821
        back_populates="client",
        foreign_keys="Case.client_id",
    )
    assigned_cases: Mapped[list["Case"]] = relationship(  # noqa: F821
        back_populates="assigned_lawyer",
        foreign_keys="Case.assigned_lawyer_id",
    )
    case_notes: Mapped[list["CaseNote"]] = relationship(  # noqa: F821
        back_populates="author",
        foreign_keys="CaseNote.author_id",
    )
    documents: Mapped[list["Document"]] = relationship(  # noqa: F821
        back_populates="uploaded_by_user",
        foreign_keys="Document.uploaded_by",
    )
