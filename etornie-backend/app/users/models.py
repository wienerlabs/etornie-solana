import enum
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    lawyer = "lawyer"
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
    public_handle: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    auth_method: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=AuthMethod.email.value,
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
