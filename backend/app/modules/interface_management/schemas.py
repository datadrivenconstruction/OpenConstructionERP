# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Interface-register Pydantic v2 schemas (request / response models).

Calendar dates cross the wire as ISO-8601 strings (``YYYY-MM-DD``) and are typed
as :class:`datetime.date` on create/update so Pydantic parses and validates them.
The register and work-package-health responses report their derived percentages
(``agreed_pct``, ``overall_health_score``, per-package ``health_score``) as plain
decimal strings (``None`` meaning "undefined", e.g. an empty register) via field
serialisers, so no float rounding is introduced at the API edge, mirroring the
money-as-string convention used across the platform. Other derived views (counts,
overdue and disputed lists) come straight from the dicts produced by the pure
:mod:`app.modules.interface_management.register` core.

The type / status / priority / action-status vocabularies are the single source
of truth in :mod:`app.modules.interface_management.register`; the ``Literal``
types below enumerate the same values so an out-of-vocabulary value is rejected
at the edge (422).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

# Vocabularies (kept in lock-step with app.modules.interface_management.register).
InterfaceTypeLiteral = Literal[
    "physical",
    "functional",
    "contractual",
    "spatial",
    "information",
    "schedule",
]
InterfaceStatusLiteral = Literal[
    "identified",
    "open",
    "in_progress",
    "agreed",
    "closed",
    "disputed",
    "on_hold",
]
PriorityLiteral = Literal["low", "medium", "high", "critical"]
ActionStatusLiteral = Literal["open", "done", "cancelled"]


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


# -- Interface ---------------------------------------------------------------


class InterfaceCreate(BaseModel):
    """Create an interface on a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reference: str = Field(..., min_length=1, max_length=40)
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    owner_party: str | None = Field(default=None, max_length=255)
    owner_subcontractor_id: UUID | None = None
    accepter_party: str | None = Field(default=None, max_length=255)
    accepter_subcontractor_id: UUID | None = None
    discipline_from: str | None = Field(default=None, max_length=60)
    discipline_to: str | None = Field(default=None, max_length=60)
    work_package_from: str | None = Field(default=None, max_length=120)
    work_package_to: str | None = Field(default=None, max_length=120)
    interface_type: InterfaceTypeLiteral | None = None
    status: InterfaceStatusLiteral = "identified"
    priority: PriorityLiteral | None = None
    need_by_date: date | None = None
    agreed_date: date | None = None
    closed_date: date | None = None
    # Must name an RFI of the same project (checked in the service, 422 otherwise).
    rfi_id: UUID | None = None
    schedule_activity_id: UUID | None = None
    location: str | None = Field(default=None, max_length=500)
    sort_order: int = Field(default=0, ge=0)
    notes: str | None = Field(default=None, max_length=20000)


class InterfaceUpdate(BaseModel):
    """Patch an interface. Only fields provided are changed.

    A field explicitly set to ``null`` clears it; an omitted field is left
    untouched (the service applies ``exclude_unset``).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    reference: str | None = Field(default=None, min_length=1, max_length=40)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    owner_party: str | None = Field(default=None, max_length=255)
    owner_subcontractor_id: UUID | None = None
    accepter_party: str | None = Field(default=None, max_length=255)
    accepter_subcontractor_id: UUID | None = None
    discipline_from: str | None = Field(default=None, max_length=60)
    discipline_to: str | None = Field(default=None, max_length=60)
    work_package_from: str | None = Field(default=None, max_length=120)
    work_package_to: str | None = Field(default=None, max_length=120)
    interface_type: InterfaceTypeLiteral | None = None
    status: InterfaceStatusLiteral | None = None
    priority: PriorityLiteral | None = None
    need_by_date: date | None = None
    agreed_date: date | None = None
    closed_date: date | None = None
    # Must name an RFI of the same project (checked in the service, 422 otherwise).
    rfi_id: UUID | None = None
    schedule_activity_id: UUID | None = None
    location: str | None = Field(default=None, max_length=500)
    # Optional note recorded in the status history when this patch moves the status.
    status_comment: str | None = Field(default=None, max_length=2000)
    sort_order: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=20000)


class InterfaceResponse(BaseModel):
    """An interface returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    reference: str
    title: str
    description: str | None = None
    owner_party: str | None = None
    owner_subcontractor_id: UUID | None = None
    accepter_party: str | None = None
    accepter_subcontractor_id: UUID | None = None
    discipline_from: str | None = None
    discipline_to: str | None = None
    work_package_from: str | None = None
    work_package_to: str | None = None
    interface_type: str | None = None
    status: str
    priority: str | None = None
    need_by_date: date | None = None
    agreed_date: date | None = None
    closed_date: date | None = None
    rfi_id: str | None = None
    schedule_activity_id: UUID | None = None
    location: str | None = None
    sort_order: int
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


# -- Action ------------------------------------------------------------------


class InterfaceActionCreate(BaseModel):
    """Add an action to an interface.

    The interface and project are taken from the path, never the body, so an
    action can only ever be attached to the interface named in the URL.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(..., min_length=1, max_length=20000)
    action_party: str | None = Field(default=None, max_length=255)
    due_date: date | None = None
    status: ActionStatusLiteral = "open"
    completed_date: date | None = None


class InterfaceActionUpdate(BaseModel):
    """Patch (or close) an action. Only fields provided are changed."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str | None = Field(default=None, min_length=1, max_length=20000)
    action_party: str | None = Field(default=None, max_length=255)
    due_date: date | None = None
    status: ActionStatusLiteral | None = None
    completed_date: date | None = None


class InterfaceActionResponse(BaseModel):
    """An action returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    interface_id: UUID
    description: str
    action_party: str | None = None
    due_date: date | None = None
    status: str
    completed_date: date | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


# -- Derived register views --------------------------------------------------


class InterfaceRef(BaseModel):
    """A lightweight reference to an interface, used in overdue / disputed lists."""

    interface_id: str | None = None
    reference: str
    title: str
    status: str
    priority: str | None = None
    interface_type: str | None = None
    owner_party: str | None = None
    accepter_party: str | None = None
    work_package_from: str | None = None
    need_by_date: str | None = None
    agreed_date: str | None = None
    open_action_count: int = 0
    # Days on the register and days past need-by at the report's as-of date.
    age_days: int | None = None
    days_overdue: int | None = None


class WorkPackageHealthResponse(BaseModel):
    """Health rollup for one originating work package."""

    work_package: str
    total: int
    open: int
    overdue: int
    agreed: int
    health_score: Decimal | None = None

    @field_serializer("health_score", when_used="json")
    def _ser_health(self, v: Decimal | None) -> str | None:
        return _serialise_pct(v)


class InterfaceRegisterResponse(BaseModel):
    """The full interface register rollup for a project."""

    project_id: UUID
    as_of: str
    total: int
    per_status: dict[str, int] = Field(default_factory=dict)
    per_priority: dict[str, int] = Field(default_factory=dict)
    per_type: dict[str, int] = Field(default_factory=dict)
    agreed_pct: Decimal | None = None
    overall_health_score: Decimal | None = None
    total_open_actions: int
    is_healthy: bool
    overdue: list[InterfaceRef] = Field(default_factory=list)
    disputed: list[InterfaceRef] = Field(default_factory=list)
    work_packages: list[WorkPackageHealthResponse] = Field(default_factory=list)
    # Ageing: open interfaces by days on the register (bands 0_7, 8_30, 31_60,
    # 61_90, over_90, unknown) and overdue ones by days past need-by (bands 1_7,
    # 8_30, 31_60, over_60), plus the mean and oldest open age and the worst lateness.
    open_count: int = 0
    overdue_count: int = 0
    ageing: dict[str, int] = Field(default_factory=dict)
    overdue_ageing: dict[str, int] = Field(default_factory=dict)
    average_open_age_days: Decimal | None = None
    oldest_open_age_days: int | None = None
    max_days_overdue: int | None = None

    @field_serializer("agreed_pct", "overall_health_score", "average_open_age_days", when_used="json")
    def _ser_pct(self, v: Decimal | None) -> str | None:
        return _serialise_pct(v)


# -- Status history ----------------------------------------------------------


class InterfaceHistoryResponse(BaseModel):
    """One entry in an interface's status history."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    interface_id: UUID
    event: str
    from_status: str | None = None
    to_status: str | None = None
    actor_id: UUID | None = None
    actor_name: str | None = None
    comment: str | None = None
    approval_instance_id: UUID | None = None
    changed_at: datetime


# -- Validation --------------------------------------------------------------


class InterfaceValidationResult(BaseModel):
    """One rule outcome from the ``interface_management`` rule set."""

    rule_id: str
    severity: str
    passed: bool
    message: str
    element_ref: str | None = None


class InterfaceValidationResponse(BaseModel):
    """Traffic-light result of the ``interface_management`` rule set for one project."""

    project_id: UUID
    status: str
    errors: int
    warnings: int
    passed: int
    results: list[InterfaceValidationResult] = Field(default_factory=list)


class WorkPackageHealthReportResponse(BaseModel):
    """The per-work-package health summary plus the overdue and disputed lists.

    Answers the question a coordinator asks when planning package coordination:
    which work packages are carrying overdue interfaces, and what is open, agreed
    or in dispute across each of them.
    """

    project_id: UUID
    as_of: str
    total: int
    is_healthy: bool
    work_packages: list[WorkPackageHealthResponse] = Field(default_factory=list)
    overdue: list[InterfaceRef] = Field(default_factory=list)
    disputed: list[InterfaceRef] = Field(default_factory=list)
