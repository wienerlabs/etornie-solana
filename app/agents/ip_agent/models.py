from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentConfig(Base):
    __tablename__ = "agent_configs"

    agent_name: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reminder_days: Mapped[str] = mapped_column(
        String(100), nullable=False, default="30,7,1"
    )
    reminder_minutes: Mapped[str] = mapped_column(
        String(100), nullable=False, default="30,10,5,1"
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
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
