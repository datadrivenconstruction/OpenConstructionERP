# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Request schemas of the staffing API.

FTE and money travel as strings, never floats. Platform vocabularies are
closed literals; catalogue codes (roles, organisations, document kinds, leave
types) are open strings checked against the pinned catalogue by the service,
because a tenant catalogue may add codes. Inputs forbid unknown fields, so a
client cannot smuggle a ``diagnosis`` or a full ``passport_number`` into a row.

No write request carries the date of the action itself (ending a file or a
fill): the server's day is used. An explicit null on a field the row cannot
leave empty is a validation error, not a database error.

``number_last4`` accepts up to 64 characters on purpose: a full number must
reach the service to be refused with ``full_number_rejected`` (rule 12) rather
than a generic schema error, and it is never stored.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Phase = Literal["development", "execution", "operation"]
Channel = Literal["internal", "agency", "direct", "framework", "consultant_contract"]
EmploymentBasis = Literal["employee", "posted_worker", "contractor_staff", "consultant", "agency"]
LawfulBasis = Literal["contract", "legal_obligation", "legitimate_interest"]
TravelKind = Literal["mobilisation", "rotation", "business", "demobilisation"]
FitForRole = Literal["yes", "with_restrictions", "no"]
_CODE = r"^[a-z0-9][a-z0-9_]*$"


def _no_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("send decimals as strings")
    return value


class _In(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class Page[T](BaseModel):
    items: list[T]
    total: int
    offset: int = 0
    limit: int = 0


class PlanSet(_In):
    catalogue_source: Literal["shipped", "tenant"] = "shipped"
    catalogue_id: str | None = Field(default=None, max_length=64)
    catalogue_version: int | None = None
    requires_accommodation: bool = False
    commissioning_date: date | None = None


class PlanPatch(_In):
    requires_accommodation: bool | None = None
    commissioning_date: date | None = None


class CatalogueChange(_In):
    catalogue_source: Literal["shipped", "tenant"] = "shipped"
    catalogue_id: str = Field(max_length=64)
    catalogue_version: int | None = None
    # old role code -> new role code; unmapped positions become ``custom`` (rule 21).
    role_mapping: dict[str, str] = Field(default_factory=dict)


# Columns of a position that cannot be NULL: a PATCH may omit them, never null them.
POSITION_REQUIRED = (
    "custom_label",
    "organisation",
    "title",
    "fte",
    "headcount",
    "key_role",
    "handover_role",
    "notes",
    "sort_order",
    "role_code",
    "phase",
)


class _PositionFields(_In):
    custom_label: str | None = Field(default=None, max_length=255)
    organisation: str | None = Field(default=None, pattern=_CODE, max_length=40)
    title: str | None = Field(default=None, max_length=255)
    fte: Any = None
    headcount: int | None = Field(default=None, ge=1, le=999)
    entry_date: date | None = None
    exit_date: date | None = None
    # What the phase this role is needed before must enable (a governance phase tag), never a gate code.
    required_before: str | None = Field(default=None, pattern=_CODE, max_length=64)
    key_role: bool | None = None
    handover_role: bool | None = None
    recruiting_channel: Channel | None = None
    owner_user_id: uuid.UUID | None = None
    contract_id: uuid.UUID | None = None
    rfq_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=4000)
    sort_order: int | None = Field(default=None, ge=0, le=100000)

    _fte = field_validator("fte", mode="before")(_no_float)


class PositionIn(_PositionFields):
    role_code: str = Field(pattern=_CODE, max_length=64)
    phase: Phase


class PositionPatch(_PositionFields):
    role_code: str | None = Field(default=None, pattern=_CODE, max_length=64)
    phase: Phase | None = None
    # Accepted only to answer ``status_is_derived`` for ``filled`` (rule 2); other values go through the FSM.
    status: str | None = Field(default=None, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def _no_null_on_required(cls, data: Any) -> Any:
        if isinstance(data, dict):
            empty = sorted(k for k in POSITION_REQUIRED if k in data and data[k] is None)
            if empty:
                raise ValueError(f"null is not allowed for: {', '.join(empty)}")
        return data


class PositionStatusIn(_In):
    status: str = Field(max_length=20)


class PositionsFromCatalogue(_In):
    phase: Phase
    role_codes: list[str] | None = None
    entry_date: date | None = None


class FillIn(_In):
    roster_member_id: uuid.UUID
    fte_share: Any = "1"
    from_date: date
    to_date: date | None = None

    _share = field_validator("fte_share", mode="before")(_no_float)


class HandoverIn(_In):
    from_fill_id: uuid.UUID
    to_position_id: uuid.UUID
    overlap_days: int = Field(default=0, ge=0, le=3650)
    scope: str = Field(default="", max_length=4000)


class HandoverPatch(_In):
    overlap_days: int | None = Field(default=None, ge=0, le=3650)
    scope: str | None = Field(default=None, max_length=4000)
    status: Literal["planned", "done"] | None = None


class FileIn(_In):
    roster_member_id: uuid.UUID
    employer_organisation: str = Field(default="", max_length=255)
    employment_basis: EmploymentBasis = "employee"
    nationality_required: bool = False
    lawful_basis: LawfulBasis = "contract"


class FilePatch(_In):
    employer_organisation: str | None = Field(default=None, max_length=255)
    employment_basis: EmploymentBasis | None = None
    nationality_required: bool | None = None
    lawful_basis: LawfulBasis | None = None


class RationaleIn(_In):
    rationale: str = Field(min_length=1, max_length=4000)


class DocumentLink(_In):
    """Record a document of the file. The validity record behind it is created by the service for this
    person; a request cannot point at somebody else's credential."""

    document_kind: str = Field(pattern=_CODE, max_length=64)
    issued_at: date | None = None
    valid_until: date | None = None
    number_last4: str | None = Field(default=None, max_length=64)
    fit_for_role: FitForRole | None = None


class TravelIn(_In):
    kind: TravelKind
    from_place: str = Field(default="", max_length=120)
    to_place: str = Field(default="", max_length=120)
    depart_date: date
    return_date: date | None = None
    booking_ref: str = Field(default="", max_length=64)
    cost: Any = None
    currency: str = Field(default="", max_length=3)

    _cost = field_validator("cost", mode="before")(_no_float)


class TravelPatch(_In):
    kind: TravelKind | None = None
    from_place: str | None = Field(default=None, max_length=120)
    to_place: str | None = Field(default=None, max_length=120)
    depart_date: date | None = None
    return_date: date | None = None
    booking_ref: str | None = Field(default=None, max_length=64)
    cost: Any = None
    currency: str | None = Field(default=None, max_length=3)

    _cost = field_validator("cost", mode="before")(_no_float)


class StatusIn(_In):
    status: str = Field(max_length=20)


class LeaveIn(_In):
    leave_type: str = Field(pattern=_CODE, max_length=30)
    from_date: date
    to_date: date


class LeavePatch(_In):
    leave_type: str | None = Field(default=None, pattern=_CODE, max_length=30)
    from_date: date | None = None
    to_date: date | None = None


class FindingOut(BaseModel):
    rule_id: str
    passed: bool
    severity: str
    message: str
    element_ref: str | None = None
    suggestion: str | None = None
