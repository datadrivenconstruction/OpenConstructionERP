# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Temporary-works Pydantic v2 schemas (request / response models).

Calendar dates cross the wire as ISO-8601 strings (``YYYY-MM-DD``) and are typed
as :class:`datetime.date` on create/update so Pydantic parses and validates them.
The register rollup response reports the one derived percentage
(``design_clearance_pct``) as a plain decimal string (``None`` meaning
"undefined", e.g. an empty register) via a field serialiser, so no float rounding
is introduced at the API edge, mirroring the money-as-string convention used
across the platform. Other derived views (counts, gate statuses, breach and
overdue lists) come straight from the dicts produced by the pure
:mod:`app.modules.temporary_works.register` core.

The type / status / category / permit vocabularies are the single source of truth
in :mod:`app.modules.temporary_works.register`; the ``Literal`` types below
enumerate the same values so an out-of-vocabulary value is rejected at the edge
(422).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

# Vocabularies (kept in lock-step with app.modules.temporary_works.register).
TWTypeLiteral = Literal[
    "falsework",
    "formwork",
    "propping",
    "excavation_support",
    "scaffold",
    "facade_retention",
    "crane_base",
    "edge_protection",
    "dewatering",
    "hoarding",
    "other",
]
ItemStatusLiteral = Literal[
    "identified",
    "design_brief",
    "design_submitted",
    "design_checked",
    "approved_to_load",
    "loaded",
    "in_use",
    "approved_to_strike",
    "struck",
    "removed",
    "on_hold",
]
DesignCheckCategoryLiteral = Literal["0", "1", "2", "3"]
PermitTypeLiteral = Literal["permit_to_load", "permit_to_strike", "permit_to_dismantle"]
PermitStatusLiteral = Literal["draft", "issued", "active", "expired", "closed"]


def _serialise_pct(v: Decimal | None) -> str | None:
    """Render a percentage Decimal as a plain decimal string for JSON.

    Returns ``None`` when the value is ``None`` (undefined), ``"0"`` for a
    non-finite or unparseable value, and otherwise the value formatted with
    :func:`format` (``"f"``) so no scientific notation or float rounding leaks
    into the response.
    """
    if v is None:
        return None
    if not isinstance(v, Decimal):
        try:
            v = Decimal(str(v))
        except (InvalidOperation, ValueError):
            return "0"
    if not v.is_finite():
        return "0"
    return format(v, "f")


# -- Temporary-works item ----------------------------------------------------


class TemporaryWorksItemCreate(BaseModel):
    """Create a temporary-works item on a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reference: str = Field(..., min_length=1, max_length=40)
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    tw_type: TWTypeLiteral
    design_check_category: DesignCheckCategoryLiteral | None = None
    designer_name: str | None = Field(default=None, max_length=255)
    checker_name: str | None = Field(default=None, max_length=255)
    twc_name: str | None = Field(default=None, max_length=255)
    twc_user_id: UUID | None = None
    status: ItemStatusLiteral = "identified"
    required_load_date: date | None = None
    required_strike_date: date | None = None
    design_due_date: date | None = None
    location: str | None = Field(default=None, max_length=500)
    sort_order: int = Field(default=0, ge=0)
    notes: str | None = Field(default=None, max_length=20000)
    formwork_assignment_id: UUID | None = None
    design_document_id: UUID | None = None
    check_certificate_document_id: UUID | None = None
    schedule_activity_id: UUID | None = None


class TemporaryWorksItemUpdate(BaseModel):
    """Patch a temporary-works item. Only fields provided are changed.

    A field explicitly set to ``null`` clears it; an omitted field is left
    untouched (the service applies ``exclude_unset``).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    reference: str | None = Field(default=None, min_length=1, max_length=40)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    tw_type: TWTypeLiteral | None = None
    design_check_category: DesignCheckCategoryLiteral | None = None
    designer_name: str | None = Field(default=None, max_length=255)
    checker_name: str | None = Field(default=None, max_length=255)
    twc_name: str | None = Field(default=None, max_length=255)
    twc_user_id: UUID | None = None
    status: ItemStatusLiteral | None = None
    required_load_date: date | None = None
    required_strike_date: date | None = None
    design_due_date: date | None = None
    location: str | None = Field(default=None, max_length=500)
    sort_order: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=20000)
    formwork_assignment_id: UUID | None = None
    design_document_id: UUID | None = None
    check_certificate_document_id: UUID | None = None
    schedule_activity_id: UUID | None = None


class TemporaryWorksItemResponse(BaseModel):
    """A temporary-works item returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    reference: str
    title: str
    description: str | None = None
    tw_type: str
    design_check_category: str | None = None
    designer_name: str | None = None
    checker_name: str | None = None
    twc_name: str | None = None
    twc_user_id: UUID | None = None
    status: str
    required_load_date: date | None = None
    required_strike_date: date | None = None
    design_due_date: date | None = None
    location: str | None = None
    sort_order: int
    notes: str | None = None
    formwork_assignment_id: UUID | None = None
    design_document_id: UUID | None = None
    check_certificate_document_id: UUID | None = None
    schedule_activity_id: UUID | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


# -- Permit ------------------------------------------------------------------


class TemporaryWorksPermitCreate(BaseModel):
    """Issue a permit against a temporary-works item.

    The item and project are taken from the path, never the body, so a permit
    can only ever be attached to the item named in the URL.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    permit_number: str = Field(..., min_length=1, max_length=40)
    permit_type: PermitTypeLiteral
    status: PermitStatusLiteral = "draft"
    issued_by: str | None = Field(default=None, max_length=255)
    issued_at: date | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    closed_at: date | None = None
    closed_by: UUID | None = None
    inspection_id: str | None = Field(default=None, max_length=36)
    prereq_design_check_accepted: bool = False
    prereq_inspection_passed: bool = False
    conditions: str | None = Field(default=None, max_length=20000)


class TemporaryWorksPermitUpdate(BaseModel):
    """Patch (or close) a permit. Only fields provided are changed."""

    model_config = ConfigDict(str_strip_whitespace=True)

    permit_number: str | None = Field(default=None, min_length=1, max_length=40)
    permit_type: PermitTypeLiteral | None = None
    status: PermitStatusLiteral | None = None
    issued_by: str | None = Field(default=None, max_length=255)
    issued_at: date | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    closed_at: date | None = None
    closed_by: UUID | None = None
    inspection_id: str | None = Field(default=None, max_length=36)
    prereq_design_check_accepted: bool | None = None
    prereq_inspection_passed: bool | None = None
    conditions: str | None = Field(default=None, max_length=20000)


class TemporaryWorksPermitResponse(BaseModel):
    """A permit returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    item_id: UUID
    permit_number: str
    permit_type: str
    status: str
    issued_by: str | None = None
    issued_at: date | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    closed_at: date | None = None
    closed_by: UUID | None = None
    inspection_id: str | None = None
    prereq_design_check_accepted: bool
    prereq_inspection_passed: bool
    conditions: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


# -- Derived register views --------------------------------------------------


class TemporaryWorksItemRef(BaseModel):
    """A lightweight reference to an item, used in overdue lists."""

    item_id: str | None = None
    reference: str
    title: str
    tw_type: str
    status: str
    required_load_date: str | None = None
    required_strike_date: str | None = None


class ComplianceBreachRef(BaseModel):
    """One compliance breach: an item bearing load with no valid permit to load."""

    item_id: str | None = None
    reference: str
    title: str
    reason: str


class ItemGateStatusResponse(BaseModel):
    """Per-item load / strike clearance."""

    item_id: str | None = None
    reference: str
    cleared_to_load: bool
    cleared_to_strike: bool


class TemporaryWorksRegisterResponse(BaseModel):
    """The full temporary-works register rollup for a project."""

    project_id: UUID
    as_of: str
    total: int
    status_counts: dict[str, int] = Field(default_factory=dict)
    category_counts: dict[str, int] = Field(default_factory=dict)
    design_clearance_pct: Decimal | None = None
    is_compliant: bool
    overdue_to_load: list[TemporaryWorksItemRef] = Field(default_factory=list)
    overdue_to_strike: list[TemporaryWorksItemRef] = Field(default_factory=list)
    compliance_breaches: list[ComplianceBreachRef] = Field(default_factory=list)
    gate_statuses: list[ItemGateStatusResponse] = Field(default_factory=list)

    @field_serializer("design_clearance_pct", when_used="json")
    def _ser_pct(self, v: Decimal | None) -> str | None:
        return _serialise_pct(v)


class TemporaryWorksLoadStatusResponse(BaseModel):
    """The per-item load / strike gate summary plus the safety breach list.

    Answers the single question a Temporary Works Coordinator asks before any
    load or strike: which items are cleared, and is anything bearing load with no
    valid permit to load in force.
    """

    project_id: UUID
    as_of: str
    total: int
    is_compliant: bool
    gate_statuses: list[ItemGateStatusResponse] = Field(default_factory=list)
    compliance_breaches: list[ComplianceBreachRef] = Field(default_factory=list)
