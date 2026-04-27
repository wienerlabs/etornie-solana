"""SQLAlchemy models for UK IPO trade mark filing robot submissions.

A submission row is the durable snapshot of one application attempt:
the inputs the robot will type into https://trademarks.ipo.gov.uk/ipo-apply,
plus the lifecycle state (pending → running → awaiting_payment / failed).
The row is created once on POST /ukipo/submissions and never re-typed by
the user; replays go straight back to the same row so the audit trail
matches what the robot actually filed.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UKIPOMarkType(str, enum.Enum):
    word = "word"
    figurative = "figurative"
    combined = "combined"
    unusual = "unusual"


class UKIPOOwnerEntityType(str, enum.Enum):
    registered_company_or_llp = "Registered Company or LLP"
    individuals = "Individual(s)"
    partnership = "Partnership"
    trust = "Trust"
    other = "Other"


class UKIPOSubmissionStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    awaiting_payment = "awaiting_payment"
    filed = "filed"
    failed = "failed"


def _enum_values(enum_cls: type) -> list[str]:
    """Tell SQLAlchemy to store the enum's *value* in postgres, not its
    name. Our migrations create the postgres enum types with the
    user-facing values ("Registered Company or LLP", "awaiting_payment",
    etc.) but SQLAlchemy's default is to write the python attribute name
    instead — for ``UKIPOOwnerEntityType.registered_company_or_llp`` that
    would be "registered_company_or_llp", which postgres rejects.
    """
    return [member.value for member in enum_cls]


class UKIPOSubmission(Base):
    __tablename__ = "ukipo_submissions"

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Owner (the trade mark applicant; can be any country)
    owner_company_name: Mapped[str] = mapped_column(String(500), nullable=False)
    owner_country: Mapped[str] = mapped_column(String(100), nullable=False)
    owner_address_line1: Mapped[str] = mapped_column(String(500), nullable=False)
    owner_address_line2: Mapped[str | None] = mapped_column(String(500))
    owner_city: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_postcode: Mapped[str | None] = mapped_column(String(50))
    owner_email: Mapped[str | None] = mapped_column(String(255))
    owner_phone: Mapped[str | None] = mapped_column(String(50))
    owner_entity_type: Mapped[UKIPOOwnerEntityType] = mapped_column(
        Enum(
            UKIPOOwnerEntityType,
            name="ukipo_owner_entity_type",
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    owner_company_registration_number: Mapped[str | None] = mapped_column(String(50))

    # Mark
    mark_type: Mapped[UKIPOMarkType] = mapped_column(
        Enum(
            UKIPOMarkType,
            name="ukipo_mark_type",
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    mark_text: Mapped[str | None] = mapped_column(String(1000))
    mark_image_path: Mapped[str | None] = mapped_column(String(1000))

    # Nice classes — JSON encoded list[{"class_number": int, "description": str}]
    nice_classes_json: Mapped[str] = mapped_column(Text, nullable=False)

    # Lifecycle
    status: Mapped[UKIPOSubmissionStatus] = mapped_column(
        Enum(
            UKIPOSubmissionStatus,
            name="ukipo_submission_status",
            values_callable=_enum_values,
        ),
        nullable=False,
        default=UKIPOSubmissionStatus.pending,
    )
    current_step: Mapped[str | None] = mapped_column(String(100))
    error_step: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)

    # Outcome (populated when robot reaches awaiting_payment / failed)
    ipo_reference: Mapped[str | None] = mapped_column(String(100))
    ipo_application_url: Mapped[str | None] = mapped_column(String(2000))
    screenshot_path: Mapped[str | None] = mapped_column(String(1000))

    # Solana SOL payment from the client (cluster follows
    # ``settings.solana_cluster_url`` — devnet for testing,
    # mainnet-beta for production). UK IPO itself does not accept
    # crypto: the actual £265 GBP is paid by Etornie's corporate card
    # off-platform once this field is set.
    solana_payment_tx: Mapped[str | None] = mapped_column(String(128))
    solana_payer_wallet: Mapped[str | None] = mapped_column(String(64))
    solana_payment_lamports: Mapped[int | None] = mapped_column(BigInteger)
    solana_payment_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
