# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Closeout Pydantic v2 request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SlotStatus(StrEnum):
    """Lifecycle of a single checklist slot."""

    EMPTY = "empty"  # no binding
    BOUND = "bound"  # has evidence, not yet human-verified
    VERIFIED = "verified"  # bound and human-confirmed


PROJECT_TYPE_PATTERN = r"^(residential|commercial|infrastructure|fitout|custom)$"
SOURCE_KIND_PATTERN = r"^(cde_document|generated|external_url|manual_upload)$"


# ── Bindings ────────────────────────────────────────────────────────────────


class CloseoutBindingResponse(BaseModel):
    """Evidence bound to a slot."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slot_id: uuid.UUID
    document_id: uuid.UUID | None = None
    document_name: str | None = None
    external_url: str | None = None
    is_verified: bool = False
    verified_by: str | None = None
    verified_at: str | None = None
    suggested_by_ai: bool = False
    ai_confidence: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


# ── Slots ─────────────────────────────────────────────────────────────────


class CloseoutSlotResponse(BaseModel):
    """A checklist requirement with its (optional) binding and derived status."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    package_id: uuid.UUID
    slot_key: str
    title: str
    category: str
    discipline: str | None = None
    is_required: bool
    source_kind: str
    generated_artifact: str | None = None
    ordinal: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: SlotStatus = SlotStatus.EMPTY
    binding: CloseoutBindingResponse | None = None


class CreateSlotRequest(BaseModel):
    """Add a custom slot to a package."""

    slot_key: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=255)
    category: str = Field(default="other", max_length=40)
    discipline: str | None = Field(default=None, max_length=50)
    is_required: bool = True
    source_kind: str = Field(default="cde_document", pattern=SOURCE_KIND_PATTERN)
    generated_artifact: str | None = Field(default=None, max_length=40)
    ordinal: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateSlotRequest(BaseModel):
    """Partial update of a slot (any subset of fields)."""

    title: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=40)
    discipline: str | None = Field(default=None, max_length=50)
    is_required: bool | None = None
    source_kind: str | None = Field(default=None, pattern=SOURCE_KIND_PATTERN)
    generated_artifact: str | None = Field(default=None, max_length=40)
    ordinal: int | None = None
    metadata: dict[str, Any] | None = None


class BindSlotRequest(BaseModel):
    """Bind a slot to a CDE document or an external URL.

    Exactly one of ``document_id`` / ``external_url`` should be supplied.
    ``mark_verified`` lets a manager bind and sign off in one call.
    """

    document_id: uuid.UUID | None = None
    external_url: str | None = Field(default=None, max_length=1024)
    mark_verified: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerifySlotRequest(BaseModel):
    """Flip a bound slot's verification flag (human sign-off)."""

    is_verified: bool = True


# ── Package ─────────────────────────────────────────────────────────────────


class CreatePackageRequest(BaseModel):
    """Create a package for a project; ``project_type`` chooses the template."""

    project_type: str = Field(default="commercial", pattern=PROJECT_TYPE_PATTERN)
    title: str | None = Field(default=None, max_length=255)


class OutstandingWork(BaseModel):
    """Live count of outstanding site work behind a genuine handover.

    Read from the owning register at request time; each figure is 0 when that
    module has no data for the project. ``punch`` and ``inspection`` also gate
    the matching generated certificate slot so a single past build cannot mark
    it delivered while the work is still open; ``commissioning`` and ``defects``
    are advisory readiness signals surfaced alongside.
    """

    punch: int = 0
    inspection: int = 0
    commissioning: int = 0
    defects: int = 0


class CloseoutPackageResponse(BaseModel):
    """Full package view with nested slots, completeness and gap list."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    project_type: str
    status: str
    checklist_template: str
    required_slot_count: int
    delivered_slot_count: int
    completeness_pct: int
    last_built_job_id: uuid.UUID | None = None
    last_built_at: str | None = None
    has_built_package: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Set when the package has been issued to the client (terminal state).
    issued_at: str | None = None
    issued_by: str | None = None

    slots: list[CloseoutSlotResponse] = Field(default_factory=list)
    # Titles of required slots not yet bound + verified.
    gaps: list[str] = Field(default_factory=list)
    # True when every required slot is bound and verified.
    ready: bool = False
    # Live outstanding-work rollup from the source registers.
    outstanding_work: OutstandingWork | None = None


class BuildPackageResponse(BaseModel):
    """The JobRun id + status to poll after a build is requested."""

    job_id: uuid.UUID
    status: str
    progress_percent: int = 0
    package_id: uuid.UUID


class BindingSuggestion(BaseModel):
    """An AI-suggested binding (never auto-applied)."""

    slot_id: uuid.UUID
    slot_key: str
    document_id: uuid.UUID
    document_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class SuggestBindingsResponse(BaseModel):
    """Suggestions only - the human confirms each binding explicitly."""

    suggestions: list[BindingSuggestion] = Field(default_factory=list)


# ── Handover dossier ─────────────────────────────────────────────────────────


class DossierConfig(BaseModel):
    """The dossier checklist of a package (every field optional on update)."""

    required_categories: list[str] | None = None
    require_punch_resolved: bool | None = None
    require_punch_photos: bool | None = None
    require_commissioning_complete: bool | None = None
    require_signed_acceptance: bool | None = None
    require_verified_evidence: bool | None = None
    share_expires_in_days: int | None = Field(default=None, ge=1, le=365)


class DossierFinding(BaseModel):
    """One failed checklist rule."""

    rule_id: str
    severity: str
    message: str
    element_ref: str | None = None
    suggestion: str | None = None


class DossierCheckResponse(BaseModel):
    """Result of checking a dossier against its checklist, before assembling it."""

    check_status: str
    results: list[DossierFinding] = Field(default_factory=list)
    scope: dict[str, Any] = Field(default_factory=dict)
    punch_total: int = 0
    punch_open: int = 0
    commissioning_systems: int = 0
    acceptance_bound: bool = False
    acceptance_signed: bool = False
    categories: dict[str, dict[str, Any]] = Field(default_factory=dict)


class DossierDeliveryTarget(BaseModel):
    """Where to send a built dossier."""

    channel: str = Field(..., pattern=r"^(download|webhook|connector|email)$")
    target_id: uuid.UUID | None = None
    recipient: str | None = Field(default=None, max_length=320)
    message: str | None = Field(default=None, max_length=2000)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)
    password: str | None = Field(default=None, max_length=128)


class DossierRequest(BaseModel):
    """Assemble (and optionally deliver) a handover dossier in one action."""

    scope_kind: str = Field(default="project", pattern=r"^(project|area|asset)$")
    scope_value: str | None = Field(default=None, max_length=255)
    allow_incomplete: bool = False
    deliveries: list[DossierDeliveryTarget] = Field(default_factory=list, max_length=10)


class DossierDeliveryResponse(BaseModel):
    """One delivery log row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dossier_id: uuid.UUID
    channel: str
    target_id: str | None = None
    target_label: str | None = None
    recipient: str | None = None
    status: str
    status_code: int | None = None
    detail: str | None = None
    share_url: str | None = None
    share_expires_at: str | None = None
    resend_of: uuid.UUID | None = None
    delivered_by: str | None = None
    delivered_at: str | None = None
    created_at: datetime


class DossierResponse(BaseModel):
    """A handover dossier with its delivery log."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    package_id: uuid.UUID
    project_id: uuid.UUID
    status: str
    scope: dict[str, Any] = Field(default_factory=dict)
    check_status: str | None = None
    check_results: list[dict[str, Any]] = Field(default_factory=list)
    job_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    file_name: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    file_count: int | None = None
    built_at: str | None = None
    requested_by: str | None = None
    error: str | None = None
    created_at: datetime
    deliveries: list[DossierDeliveryResponse] = Field(default_factory=list)


class DossierTarget(BaseModel):
    """A webhook endpoint or chat connector a dossier can be sent to."""

    id: uuid.UUID
    channel: str
    name: str
    kind: str | None = None


class DossierListResponse(BaseModel):
    """A page of DossierResponse with the count of rows the filters matched."""

    items: list[DossierResponse]
    total: int
    offset: int = 0
    limit: int = 50


class DossierTargetListResponse(BaseModel):
    """A page of DossierTarget with the count of rows the filters matched."""

    items: list[DossierTarget]
    total: int
    offset: int = 0
    limit: int = 50
