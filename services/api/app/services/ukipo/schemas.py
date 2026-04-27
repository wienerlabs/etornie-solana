"""Pydantic schemas for UK IPO submission HTTP layer.

The API layer is the first of three validation katmans (API → service →
robot). Each owns the same UK postcode rule independently — defense in
depth, no shared module so the layers can fail independently if one is
ever bypassed.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.ukipo.models import (
    UKIPOMarkType,
    UKIPOOwnerEntityType,
    UKIPOSubmissionStatus,
)

# Local UK normalisation set — duplicated in robot.py and service.py
# on purpose so each layer can validate without coupling.
_UK_COUNTRY_VALUES = frozenset({
    "united kingdom",
    "uk",
    "gb",
    "great britain",
    "england",
    "scotland",
    "wales",
    "northern ireland",
})


def _is_uk(country: str | None) -> bool:
    if not country:
        return False
    return country.strip().lower() in _UK_COUNTRY_VALUES


class NiceClassEntry(BaseModel):
    class_number: int = Field(ge=1, le=45)
    description: str = Field(min_length=1, max_length=10000)


class OwnerDetails(BaseModel):
    company_name: str = Field(min_length=1, max_length=500)
    country: str = Field(min_length=1, max_length=100)
    address_line1: str = Field(min_length=1, max_length=500)
    address_line2: str | None = Field(default=None, max_length=500)
    city: str = Field(min_length=1, max_length=255)
    postcode: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    entity_type: UKIPOOwnerEntityType
    company_registration_number: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _validate_uk_postcode(self) -> "OwnerDetails":
        if _is_uk(self.country):
            if not self.postcode or not self.postcode.strip():
                raise ValueError(
                    "postcode is required when country is in the United Kingdom"
                )
        if (
            self.entity_type == UKIPOOwnerEntityType.registered_company_or_llp
            and _is_uk(self.country)
            and not (
                self.company_registration_number
                and self.company_registration_number.strip()
            )
        ):
            raise ValueError(
                "company_registration_number is required for UK Registered Company or LLP"
            )
        return self


class UKIPOSubmissionCreateRequest(BaseModel):
    case_id: uuid.UUID
    owner: OwnerDetails
    mark_type: UKIPOMarkType
    mark_text: str | None = Field(default=None, max_length=1000)
    mark_image_path: str | None = Field(default=None, max_length=1000)
    nice_classes: list[NiceClassEntry] = Field(min_length=1)

    @field_validator("nice_classes")
    @classmethod
    def _no_duplicate_classes(cls, value: list[NiceClassEntry]) -> list[NiceClassEntry]:
        seen: set[int] = set()
        for entry in value:
            if entry.class_number in seen:
                raise ValueError(
                    f"duplicate Nice class {entry.class_number} in submission"
                )
            seen.add(entry.class_number)
        return value

    @model_validator(mode="after")
    def _validate_mark_payload(self) -> "UKIPOSubmissionCreateRequest":
        if self.mark_type in (UKIPOMarkType.word, UKIPOMarkType.combined):
            if not self.mark_text or not self.mark_text.strip():
                raise ValueError(
                    f"mark_text is required for mark_type={self.mark_type.value}"
                )
        if self.mark_type in (
            UKIPOMarkType.figurative,
            UKIPOMarkType.combined,
            UKIPOMarkType.unusual,
        ):
            if not self.mark_image_path or not self.mark_image_path.strip():
                raise ValueError(
                    f"mark_image_path is required for mark_type={self.mark_type.value}"
                )
        return self


class UKIPOSubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    owner_company_name: str
    owner_country: str
    owner_address_line1: str
    owner_address_line2: str | None
    owner_city: str
    owner_postcode: str | None
    owner_email: str | None
    owner_phone: str | None
    owner_entity_type: UKIPOOwnerEntityType
    owner_company_registration_number: str | None
    mark_type: UKIPOMarkType
    mark_text: str | None
    mark_image_path: str | None
    nice_classes_json: str
    status: UKIPOSubmissionStatus
    current_step: str | None
    error_step: str | None
    error_message: str | None
    ipo_reference: str | None
    ipo_application_url: str | None
    screenshot_path: str | None
    solana_payment_tx: str | None
    solana_payer_wallet: str | None
    solana_payment_lamports: int | None
    solana_payment_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UKIPOSubmissionListResponse(BaseModel):
    submissions: list[UKIPOSubmissionResponse]
    total: int


class UKIPOPaymentRequirementsResponse(BaseModel):
    """Solana payment requirements for the UK IPO filing fee.

    Frontend builds SystemProgram.transfer(payer → recipient) +
    Memo("ukipo:<submission_id>") from these values, then sends from
    the user's wallet. UK IPO itself never sees this — it stays as an
    audit record on Solana proving the client funded the filing.
    """

    network: str
    asset: str
    recipient: str
    lamports: int
    memo: str
    cluster_url: str


class UKIPOPaymentRecordRequest(BaseModel):
    payment_tx: str = Field(min_length=1, max_length=128)
    payer_wallet: str = Field(min_length=1, max_length=64)
