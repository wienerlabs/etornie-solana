import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    lawyer = "lawyer"
    client = "client"


class User(Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        nullable=False,
        default=UserRole.client,
    )
    phone: Mapped[str | None] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(default=True)
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
    )
    documents: Mapped[list["Document"]] = relationship(  # noqa: F821
        back_populates="uploaded_by_user",
        foreign_keys="Document.uploaded_by",
    )
