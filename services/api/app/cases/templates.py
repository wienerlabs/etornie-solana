"""Case templates (issue #65) — one-click starting points for common
IP workflows.

Templates are code-defined (not a DB table): the catalog is small,
versioned with the code, and needs no admin CRUD. Each template
pre-fills the fields a new case would otherwise require by hand
(case_type, a default title and description, and optional suggested
jurisdiction / Nice classes). The case-creation endpoint applies these
as DEFAULTS — any field the caller supplies overrides the template — and
the existing create_case pipeline still auto-generates the required
documents + proposal from the resulting jurisdiction/case_type.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.cases.models import CaseType


@dataclass(frozen=True)
class CaseTemplate:
    key: str
    name: str
    description: str  # shown in the picker
    case_type: CaseType
    default_title: str
    default_description: str
    # Optional starting points the caller can override. Left None when a
    # sensible default cannot be assumed (jurisdiction is country-specific
    # and Nice classes are mark-specific).
    default_jurisdiction: str | None = None
    default_nice_classes: str | None = None


CASE_TEMPLATES: tuple[CaseTemplate, ...] = (
    CaseTemplate(
        key="trademark-renewal",
        name="Trademark Renewal",
        description=(
            "Renew an existing trademark registration before its deadline."
        ),
        case_type=CaseType.trademark,
        default_title="Trademark Renewal",
        default_description=(
            "Renewal of an existing trademark registration."
        ),
    ),
    CaseTemplate(
        key="patent-filing",
        name="Patent Filing",
        description="File a new patent application.",
        case_type=CaseType.patent,
        default_title="Patent Filing",
        default_description="New patent application filing.",
    ),
    CaseTemplate(
        key="design-registration",
        name="Design Registration",
        description="Register a new industrial design.",
        case_type=CaseType.design,
        default_title="Design Registration",
        default_description="New industrial design registration.",
    ),
)

_BY_KEY: dict[str, CaseTemplate] = {t.key: t for t in CASE_TEMPLATES}


def get_template(key: str) -> CaseTemplate | None:
    return _BY_KEY.get(key)
