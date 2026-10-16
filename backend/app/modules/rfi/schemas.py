# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""RFI Pydantic schemas - request/response models."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.rfi.request_types import (
    CODE_PATTERN,
    DEFAULT_TYPE_CODE,
    MAX_DIGITS,
    MIN_DIGITS,
    PREFIX_PATTERN,
    REQUIRED_FIELD_CHOICES,
)


def _sanitise_rfi_text(value: str | None) -> str | None:
    """Strip XSS payloads from RFI free-text fields (BUG-389).

    RFIs are often rendered in email digests (raw HTML) and PDF reports,
    so a ``<script>`` / event-handler payload smuggled into a subject
    would turn into a real XSS vector. Sanitise at the schema layer so
    the DB never stores the payload.
    """
    if value is None:
        return value
    from app.core.sanitize import strip_dangerous_html

    return strip_dangerous_html(value)


def _validate_cost_impact_value(value: str | None) -> str | None:
    """Round-trip ``cost_impact_value`` through :class:`Decimal`.

    R5 / BUG-RFI-DEC: ``cost_impact_value`` is stored as a free-form
    string so the DB layer never accumulates IEEE-754 drift. The schema
    still has to reject garbage (``"definitely cheap"``) up front so the
    variation builder (which feeds the value into ChangeOrder.cost_impact)
    never sees a non-numeric blob.

    Empty / ``None`` passes through. Otherwise we parse via Decimal and
    re-serialise the canonical form so storage is always a clean number
    string. Inf / NaN are rejected because Decimal accepts them but they
    cannot become a valid currency amount.
    """
    if value is None or value == "":
        return value
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("cost_impact_value must be a numeric amount") from exc
    if not parsed.is_finite():
        raise ValueError("cost_impact_value must be a finite number")
    return format(parsed, "f")


class RFICreate(BaseModel):
    """Create a new RFI."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    subject: str = Field(..., min_length=1, max_length=500)
    question: str = Field(..., min_length=1, max_length=10000)
    request_type: str = Field(
        default=DEFAULT_TYPE_CODE,
        min_length=1,
        max_length=32,
        description="Code of a type in the project's request type catalogue (RFI, TQ, SQ, ...).",
    )

    @field_validator("subject", "question", mode="after")
    @classmethod
    def _sanitise(cls, v: str) -> str:
        return _sanitise_rfi_text(v) or ""

    @field_validator("request_type", mode="before")
    @classmethod
    def _upper_type(cls, v: object) -> object:
        return v.strip().upper() if isinstance(v, str) else v

    raised_by: UUID | None = None  # Auto-filled from authenticated user if not provided
    assigned_to: str | None = Field(default=None, max_length=36)
    status: str = Field(
        default="draft",
        pattern=r"^(draft|open|answered|closed|void)$",
    )
    ball_in_court: str | None = Field(default=None, max_length=100)
    cost_impact: bool = False
    cost_impact_value: str | None = Field(default=None, max_length=50)

    @field_validator("cost_impact_value", mode="after")
    @classmethod
    def _validate_cost(cls, v: str | None) -> str | None:
        return _validate_cost_impact_value(v)

    schedule_impact: bool = False
    schedule_impact_days: int | None = Field(default=None, ge=0)
    date_required: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    response_due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    linked_drawing_ids: list[str] = Field(default_factory=list)
    change_order_id: str | None = Field(default=None, max_length=36)
    priority: str | None = Field(
        default=None,
        pattern=r"^(low|normal|high|critical)$",
        description="Priority - low | normal | high | critical.",
    )
    discipline: str | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RFIUpdate(BaseModel):
    """Partial update for an RFI."""

    model_config = ConfigDict(str_strip_whitespace=True)

    subject: str | None = Field(default=None, min_length=1, max_length=500)
    question: str | None = Field(default=None, min_length=1, max_length=10000)

    @field_validator("subject", "question", mode="after")
    @classmethod
    def _sanitise(cls, v: str | None) -> str | None:
        return _sanitise_rfi_text(v)

    assigned_to: str | None = Field(default=None, max_length=36)
    status: str | None = Field(
        default=None,
        pattern=r"^(draft|open|answered|closed|void)$",
    )
    ball_in_court: str | None = Field(default=None, max_length=100)
    cost_impact: bool | None = None
    cost_impact_value: str | None = Field(default=None, max_length=50)

    @field_validator("cost_impact_value", mode="after")
    @classmethod
    def _validate_cost(cls, v: str | None) -> str | None:
        return _validate_cost_impact_value(v)

    schedule_impact: bool | None = None
    schedule_impact_days: int | None = Field(default=None, ge=0)
    date_required: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    response_due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    linked_drawing_ids: list[str] | None = None
    change_order_id: str | None = Field(default=None, max_length=36)
    priority: str | None = Field(
        default=None,
        pattern=r"^(low|normal|high|critical)$",
        description="Priority - low | normal | high | critical.",
    )
    discipline: str | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None


class RFIRespondRequest(BaseModel):
    """Request body for responding to an RFI."""

    official_response: str = Field(..., min_length=1, max_length=10000)

    @field_validator("official_response", mode="after")
    @classmethod
    def _sanitise(cls, v: str) -> str:
        return _sanitise_rfi_text(v) or ""


class StartApprovalRequest(BaseModel):
    """Request body for starting a routed approval workflow (feature 06).

    ``route_id`` may be left out when the request's type names a default
    approval route; the service then uses that one, and answers 422 when the
    type has none.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    route_id: UUID | None = None


class RFIResponse(BaseModel):
    """RFI returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    rfi_number: str
    request_type: str = DEFAULT_TYPE_CODE
    subject: str
    question: str
    raised_by: UUID
    assigned_to: str | None = None
    status: str = "draft"
    ball_in_court: str | None = None
    official_response: str | None = None
    responded_by: str | None = None
    responded_at: str | None = None
    cost_impact: bool = False
    cost_impact_value: str | None = None
    schedule_impact: bool = False
    schedule_impact_days: int | None = None
    date_required: str | None = None
    response_due_date: str | None = None
    linked_drawing_ids: list[str] = Field(default_factory=list)
    attachments: list[str] = Field(
        default_factory=list,
        description="Server-derived relative paths under uploads/rfi/attachments/.",
    )
    change_order_id: str | None = None
    created_by: str | None = None
    priority: str | None = None
    discipline: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    # Computed fields
    is_overdue: bool = Field(
        default=False,
        description="True when status is open/draft and response_due_date is past today",
    )
    days_open: int = Field(
        default=0,
        description="Number of days from created_at to now (or responded_at if answered/closed)",
    )


class RFIListResponse(BaseModel):
    """One page of a project's RFI register plus the size of the whole set.

    ``total`` counts the RFIs the status filter and the search term matched,
    not the length of ``items``. An RFI register is read to answer "what is
    still waiting on us", so a client that renders ``items`` alone shows the
    first fifty questions and gives the reader no way to tell that the
    hundredth one exists.

    Distinct from :class:`RFIStatsResponse`, whose ``total`` is a project-wide
    count that ignores paging and the filters entirely.
    """

    items: list[RFIResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


class RFITypeStats(BaseModel):
    """Counts for one request type inside a project's stats."""

    total: int = 0
    open: int = 0
    overdue: int = 0
    answered: int = 0
    closed: int = 0


class RFIStatsResponse(BaseModel):
    """Summary statistics for RFIs in a project."""

    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, RFITypeStats] = Field(
        default_factory=dict,
        description="Counts per request type code (RFI, TQ, SQ, ...); a type with no requests is absent.",
    )
    open: int = 0
    overdue: int = 0
    avg_days_to_response: float | None = Field(
        default=None,
        description="Average days from creation to official response (answered/closed RFIs only)",
    )
    cost_impact_count: int = 0
    schedule_impact_count: int = 0


class RFIVariationResponse(BaseModel):
    """Result of minting (or returning an existing) change order from an RFI.

    The ``POST /{rfi_id}/create-variation/`` endpoint previously returned an
    untyped ``dict``, so the wire contract was undocumented in the OpenAPI
    schema and the frontend had to hand-type it. This locks the exact shape
    the handler already emits (idempotent re-mints return the same fields).
    """

    change_order_id: str = Field(description="UUID of the linked change order.")
    code: str = Field(description="Human-readable change-order code, e.g. CO-007.")
    rfi_id: str = Field(description="UUID of the source RFI.")
    title: str = Field(description="Change-order title (pre-filled from the RFI subject).")


class RFIBatchDeleteResponse(BaseModel):
    """Outcome of a bulk RFI delete.

    ``deleted`` can be less than ``requested`` when some ids fall outside the
    caller's accessible projects or no longer exist - the contract never
    raises for partial matches.
    """

    requested: int = Field(ge=0, description="Number of ids supplied in the request.")
    deleted: int = Field(ge=0, description="Number of RFIs actually deleted.")


class RFIBatchStatusResponse(BaseModel):
    """Outcome of a bulk RFI status update."""

    requested: int = Field(ge=0, description="Number of ids supplied in the request.")
    updated: int = Field(ge=0, description="Number of RFIs whose status changed.")
    status: str = Field(description="The status value that was applied.")


class RFIActivityEntry(BaseModel):
    """One row from an RFI's activity journal (``oe_activity_log``).

    Read-only projection of :class:`app.core.audit_log.ActivityLog`, used by
    the ``GET /{rfi_id}/activity/`` timeline. The RFI service already writes a
    row here on every status transition (respond / close / reopen), so the
    journal reconstructs the RFI's lifecycle (useful for FIDIC / ISO 9001
    contemporary records) without any new storage.

    Follows the per-module activity-response pattern the other modules already
    expose (documents' ``DocumentActivityResponse``, boq's
    ``ActivityLogResponse``) instead of leaking the raw ORM row. The
    ``metadata`` alias mirrors :class:`RFIResponse` so the ``metadata_`` column
    name never reaches the wire.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    actor_id: UUID | None = None
    action: str
    from_status: str | None = None
    to_status: str | None = None
    reason: str | None = None
    module: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime


class RFIActivityListResponse(BaseModel):
    """One page of an RFI's activity journal plus the length of the journal.

    The journal is ordered oldest first, so a truncated page is the START of
    the RFI's life and the recent transitions are the ones left out. ``total``
    is what lets the timeline say so rather than presenting the opening
    entries as the whole history.
    """

    items: list[RFIActivityEntry] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


# ── Request type catalogue ────────────────────────────────────────────────


def _check_i18n(value: dict[str, str] | None, *, need_english: bool) -> dict[str, str]:
    """Keep non-empty texts under short language tags; demand English where asked."""
    out: dict[str, str] = {}
    for tag, text in (value or {}).items():
        tag_s = str(tag).strip()
        text_s = _sanitise_rfi_text(str(text).strip()) or ""
        if not tag_s or len(tag_s) > 16:
            raise ValueError(f"invalid language tag: {tag!r}")
        if len(text_s) > 500:
            raise ValueError(f"text for {tag_s!r} is longer than 500 characters")
        if text_s:
            out[tag_s] = text_s
    if need_english and not out.get("en"):
        raise ValueError("an English name is required (name_i18n.en)")
    return out


def _check_required_fields(value: list[str] | None) -> list[str]:
    fields = list(dict.fromkeys(value or []))
    unknown = [f for f in fields if f not in REQUIRED_FIELD_CHOICES]
    if unknown:
        raise ValueError("unknown required fields: " + ", ".join(unknown))
    return fields


class RequestTypeCreate(BaseModel):
    """Add one request type to a project's catalogue."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    code: str = Field(..., pattern=CODE_PATTERN)
    name_i18n: dict[str, str]
    description_i18n: dict[str, str] = Field(default_factory=dict)
    number_prefix: str = Field(..., pattern=PREFIX_PATTERN)
    number_digits: int = Field(default=4, ge=MIN_DIGITS, le=MAX_DIGITS)
    default_response_days: int | None = Field(default=None, ge=1, le=365)
    required_fields: list[str] = Field(default_factory=list)
    default_route_id: UUID | None = None
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=100000)

    @field_validator("code", "number_prefix", mode="before")
    @classmethod
    def _upper(cls, v: object) -> object:
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("name_i18n", mode="after")
    @classmethod
    def _names(cls, v: dict[str, str]) -> dict[str, str]:
        return _check_i18n(v, need_english=True)

    @field_validator("description_i18n", mode="after")
    @classmethod
    def _descriptions(cls, v: dict[str, str]) -> dict[str, str]:
        return _check_i18n(v, need_english=False)

    @field_validator("required_fields", mode="after")
    @classmethod
    def _fields(cls, v: list[str]) -> list[str]:
        return _check_required_fields(v)


class RequestTypeUpdate(BaseModel):
    """Partial update of a request type.

    ``code`` and ``number_prefix`` are not editable: requests already store the
    code and carry the prefix in their number, so renaming either would orphan
    them. Retire a type with ``is_active = false`` and add a new one instead.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name_i18n: dict[str, str] | None = None
    description_i18n: dict[str, str] | None = None
    number_digits: int | None = Field(default=None, ge=MIN_DIGITS, le=MAX_DIGITS)
    default_response_days: int | None = Field(default=None, ge=1, le=365)
    required_fields: list[str] | None = None
    default_route_id: UUID | None = None
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100000)

    @field_validator("name_i18n", mode="after")
    @classmethod
    def _names(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        return None if v is None else _check_i18n(v, need_english=True)

    @field_validator("description_i18n", mode="after")
    @classmethod
    def _descriptions(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        return None if v is None else _check_i18n(v, need_english=False)

    @field_validator("required_fields", mode="after")
    @classmethod
    def _fields(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _check_required_fields(v)


class RequestTypeResponse(BaseModel):
    """One type of a project's catalogue as the register reads it.

    ``id`` is ``None`` for the built-in RFI type a project has before it loads
    a catalogue: it numbers and behaves like a row but is not one, and it
    becomes a row the moment a preset with an RFI type is loaded.
    """

    id: UUID | None = None
    project_id: UUID
    code: str
    name: str = Field(description="English name, the fallback when the reader's language has none.")
    name_i18n: dict[str, str] = Field(default_factory=dict)
    description_i18n: dict[str, str] = Field(default_factory=dict)
    number_prefix: str
    number_digits: int
    default_response_days: int | None = None
    response_days: int = Field(description="The SLA applied: the type's own, else the platform default.")
    required_fields: list[str] = Field(default_factory=list)
    default_route_id: UUID | None = None
    is_active: bool = True
    is_builtin: bool = False
    sort_order: int = 0
    preset_code: str | None = None
    request_count: int = 0


class RequestTypeCatalogueResponse(BaseModel):
    """A project's request types plus the field names a type may require."""

    items: list[RequestTypeResponse] = Field(default_factory=list)
    total: int = 0
    required_field_choices: list[str] = Field(default_factory=lambda: list(REQUIRED_FIELD_CHOICES))


class RequestTypePresetType(BaseModel):
    """One type inside a shipped preset."""

    code: str
    number_prefix: str
    number_digits: int
    name_i18n: dict[str, str] = Field(default_factory=dict)
    default_response_days: int | None = None
    required_fields: list[str] = Field(default_factory=list)


class RequestTypePresetResponse(BaseModel):
    """A shipped preset a project can load."""

    code: str
    name_i18n: dict[str, str] = Field(default_factory=dict)
    description_i18n: dict[str, str] = Field(default_factory=dict)
    types: list[RequestTypePresetType] = Field(default_factory=list)


class RequestTypePresetListResponse(BaseModel):
    """Every shipped preset; total is the whole set, which is never paged."""

    items: list[RequestTypePresetResponse] = Field(default_factory=list)
    total: int = 0


class RequestTypePresetLoadResponse(BaseModel):
    """What loading a preset into a project did.

    A type whose code or prefix the project already has is skipped, never
    overwritten: the project's edits to its own catalogue win over the preset.
    """

    preset_code: str
    created: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)


class RFIValidationResult(BaseModel):
    """One rule outcome of the register's validation run."""

    rule_id: str
    severity: str
    passed: bool
    message: str
    element_ref: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class RFIValidationResponse(BaseModel):
    """Traffic-light result of the ``rfi`` rule set over one project's register."""

    status: str
    score: float | None = None
    errors: int = 0
    warnings: int = 0
    results: list[RFIValidationResult] = Field(default_factory=list)
