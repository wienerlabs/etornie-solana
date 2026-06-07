"""Typed models mirroring the Etornie API response shapes.

Each model is a frozen dataclass with a ``from_dict`` constructor that
ignores unknown keys, so the SDK keeps working when the API adds fields.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, TypeVar

T = TypeVar("T", bound="_Base")


@dataclass(frozen=True)
class _Base:
    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass(frozen=True)
class TokenResponse(_Base):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@dataclass(frozen=True)
class User(_Base):
    id: str
    full_name: str
    role: str
    is_active: bool
    auth_method: str
    created_at: str
    updated_at: str
    email: str | None = None
    phone: str | None = None
    wallet_address: str | None = None
    public_handle: str | None = None


@dataclass(frozen=True)
class Case(_Base):
    id: str
    title: str
    case_number: str
    case_type: str
    status: str
    created_at: str
    updated_at: str
    description: str | None = None
    client_id: str | None = None
    assigned_lawyer_id: str | None = None
    jurisdiction: str | None = None
    nice_classes: str | None = None
    filing_date: str | None = None
    deadline: str | None = None
    deadline_time: str | None = None
    attestation_tx: str | None = None
    attestation_pda: str | None = None
    client_wallet: str | None = None
    nft_mint: str | None = None
    nft_state: str = "none"


@dataclass(frozen=True)
class CaseDocument(_Base):
    id: str
    case_id: str
    uploaded_by: str
    filename: str
    status: str
    created_at: str
    file_type: str | None = None
    file_size: int | None = None
    document_type: str | None = None


@dataclass(frozen=True)
class RenewalStatus(_Base):
    case_id: str
    renewal_due_at: str | None = None
    days_remaining: int | None = None
    is_overdue: bool = False
    open_window: int | None = None
    reminders: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class CalendarFeedStatus(_Base):
    enabled: bool
    url: str | None = None
