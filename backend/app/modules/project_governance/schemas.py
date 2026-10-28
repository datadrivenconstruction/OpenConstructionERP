# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Request and response models of the project governance API.

Codes (catalogue ids, phase, gate, area and document type codes) are plain
strings: they are data from a catalogue, not enums. Outcomes and statuses are
closed vocabularies and are ``Literal``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

Outcome = Literal["go", "go_with_conditions", "hold", "recycle", "stop"]
Severity = Literal["critical", "essential", "recommended"]
CatalogueSource = Literal["shipped", "tenant", "pack"]


# Label of a catalogue item: {key, text}; both null when the catalogue no longer has the item.
_NO_LABEL: dict[str, Any] = {"key": None, "text": None}


class Page(BaseModel, Generic[T]):
    """The list envelope every collection endpoint answers with."""

    items: list[T]
    total: int
    offset: int = 0
    limit: int = 0


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── catalogues ──


class CatalogueCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    kind: str = Field(default="phase_model", min_length=1, max_length=40)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=255)
    based_on_source: CatalogueSource | None = None
    based_on_id: str | None = Field(default=None, max_length=64)
    based_on_version: int | None = Field(default=None, ge=1)


class CatalogueUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    body: dict[str, Any] | None = None


class CatalogueVersionOut(_Out):
    version: int
    content_hash: str
    published_by: UUID | None
    published_at: datetime


class TenantCatalogueOut(_Out):
    id: UUID
    kind: str
    code: str
    name: str
    based_on: str
    state: str
    draft_body: dict[str, Any]
    versions: list[CatalogueVersionOut] = []
    validation_errors: list[str] = []


# ── model ──


class ModelSet(BaseModel):
    catalogue_source: CatalogueSource = "shipped"
    catalogue_id: str = Field(min_length=1, max_length=64)
    catalogue_version: int | None = Field(default=None, ge=1)
    four_eyes: bool = True


class ModelChange(BaseModel):
    catalogue_source: CatalogueSource = "shipped"
    catalogue_id: str = Field(min_length=1, max_length=64)
    catalogue_version: int | None = Field(default=None, ge=1)
    mapping: dict[str, str]


class ModelSettings(BaseModel):
    four_eyes: bool | None = None
    decision_route_id: UUID | None = None
    change_route_id: UUID | None = None


class ModelOut(_Out):
    id: UUID
    project_id: UUID
    catalogue_source: str
    catalogue_id: str
    catalogue_version: int
    current_phase: str | None
    four_eyes: bool
    decision_route_id: UUID | None
    change_route_id: UUID | None
    stopped: bool
    stopped_at: datetime | None
    phases: list[dict[str, Any]] = []
    # What the caller may do: {manage}.
    can: dict[str, bool] = {}


# ── areas ──


class AreaUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    owner_user_id: UUID | None = None
    deputy_user_id: UUID | None = None
    applicable: bool | None = None
    na_rationale: str | None = Field(default=None, max_length=4000)
    name_override: str | None = Field(default=None, max_length=255)


class AreaOut(_Out):
    id: UUID
    code: str
    name_override: str
    sort_order: int
    owner_user_id: UUID | None
    deputy_user_id: UUID | None
    applicable: bool
    na_rationale: str
    retired: bool
    name: dict[str, Any] = _NO_LABEL
    # Document types the phase model defines for this area: [{code, name, required_at_gates, tracked}];
    # ``tracked`` says the project already has that document.
    document_types: list[dict[str, Any]] = []
    # What the caller may do in this area: {add_document, add_document_reason}; the reason is an
    # error code or null.
    can: dict[str, Any] = {}


# ── gates ──


class GateOut(_Out):
    id: UUID
    code: str
    catalogue_id: str
    from_phase: str
    to_phase: str
    sort_order: int
    status: str
    attempt_no: int
    target_date: str
    schedule_activity_id: UUID | None
    approval_instance_id: UUID | None
    hold_resume_date: str
    last_outcome: str
    historic: bool
    version: int
    name: dict[str, Any] = _NO_LABEL


class ConditionIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    area_code: str | None = Field(default=None, max_length=64)
    document_type: str | None = Field(default=None, max_length=64)
    text: str = Field(max_length=4000)
    owner_user_id: UUID | None = None
    due_date: date | None = None
    severity: Severity = "essential"


class EvidenceRef(BaseModel):
    """One evidence item of a gate: a provider's code in one area."""

    area_code: str = Field(max_length=64)
    code: str = Field(max_length=400)


class DecisionIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    outcome: Outcome
    rationale: str = Field(default="", max_length=8000)
    conditions: list[ConditionIn] = []
    proceed_at_risk_areas: list[str] = []
    accepted_not_applicable: list[str] = []
    hold_resume_date: date | None = None
    # A go names every item of ``can.acknowledge``; anything else in the list is ignored.
    acknowledged_evidence: list[EvidenceRef] = Field(default=[], max_length=500)


class GatePlan(BaseModel):
    """When a gate is planned. Only the fields sent are changed; null unlinks or clears."""

    target_date: date | None = None
    schedule_activity_id: UUID | None = None


class ReopenIn(BaseModel):
    rationale: str = Field(max_length=8000)
    # Accepted and ignored: the server rewinds the phase whenever the reopened decision had advanced it.
    rewind_phase: bool | None = None


class DecisionOut(_Out):
    id: UUID
    gate_id: UUID
    gate_code: str
    attempt_no: int
    outcome: str
    rationale: str
    decided_by: UUID
    decided_at: datetime
    snapshot: dict[str, Any]
    proceed_at_risk_areas: list[str]
    accepted_not_applicable: list[str]
    hold_resume_date: str
    approval_instance_id: UUID | None


class GateDetailOut(BaseModel):
    gate: GateOut
    blockers: list[dict[str, Any]]
    areas: list[dict[str, Any]]
    decisions: list[DecisionOut]
    # What the caller may do. Reasons are error codes and are present only when the flag is false:
    # {edit, decide, decide_reason?, go, go_reason?,
    #  outcomes: {<outcome>: {allowed, reason}}, resume, resume_reason?, reopen, reopen_reason?,
    #  add_condition, add_condition_reason?,
    #  acknowledge: [{area_code, code, provider}] the unknown evidence a go has to name}
    can: dict[str, Any] = {}


class MatrixOut(BaseModel):
    gates: list[GateOut]
    next_gate: dict[str, Any] | None
    areas: list[dict[str, Any]]


# ── checks ──


class CheckConfirm(BaseModel):
    status: Literal["ready", "ready_with_risks", "not_ready", "not_assessed"]
    rag: Literal["", "red", "amber", "green"] = ""
    note: str = Field(default="", max_length=4000)


class NotApplicableIn(BaseModel):
    rationale: str = Field(max_length=4000)


class CriterionTick(BaseModel):
    """One line of an area's readiness checklist. Who and when come from the server."""

    model_config = ConfigDict(str_strip_whitespace=True)

    met: bool
    note: str = Field(default="", max_length=2000)


class CheckOut(_Out):
    id: UUID
    gate_id: UUID
    attempt_no: int
    area_id: UUID
    status: str
    rag: str
    note: str
    confirmed_by: UUID | None
    confirmed_at: datetime | None
    confirmed_revisions: dict[str, str]
    stale: bool
    na_rationale: str
    # {criterion code: {met, note, by, at}}; the gate detail serves the same as a list.
    criteria: dict[str, Any] = {}


# ── documents ──


class DocumentCreate(BaseModel):
    area_id: UUID
    doc_type: str = Field(min_length=1, max_length=64)


class AttachIn(BaseModel):
    container_id: UUID


class DocumentOut(_Out):
    id: UUID
    area_id: UUID
    doc_type: str
    required_at_gates: list[str]
    status: str
    container_id: UUID | None
    bound_revision_id: UUID | None
    bound_content_hash: str | None
    approved_gate_id: UUID | None
    read_only: bool
    name: dict[str, Any] = _NO_LABEL
    # What the caller may do with this document: {attach, submit, return, change_request}, each with
    # a ``<name>_reason`` that is an error code or null.
    can: dict[str, Any] = {}


class ChangeRequestIn(BaseModel):
    reason: str = Field(max_length=8000)
    impact: str = Field(default="", max_length=8000)
    proposed_revision_id: UUID | None = None


class ChangeRequestOut(_Out):
    id: UUID
    document_id: UUID
    previous_revision_id: UUID | None
    proposed_revision_id: UUID
    proposed_content_hash: str | None
    reason: str
    impact: str
    status: str
    approval_instance_id: UUID | None
    requested_by: UUID | None
    decided_by: UUID | None
    decided_at: datetime | None
    created_at: datetime


class DocumentHistoryOut(BaseModel):
    document_id: UUID
    revisions: list[dict[str, Any]]
    change_requests: list[ChangeRequestOut]


# ── conditions ──


class ConditionOut(_Out):
    id: UUID
    decision_id: UUID
    gate_id: UUID
    gate_code: str
    area_code: str | None
    document_type: str | None
    text: str
    owner_user_id: UUID | None
    due_date: str
    severity: str
    status: str
    evidence: str
    cleared_by: UUID | None
    cleared_at: datetime | None
    waiver_rationale: str
    waived_by: UUID | None
    waived_at: datetime | None
    escalated_at: datetime | None
    # What the caller may do with this row: {clear, clear_reason, waive, waive_reason}; reasons are
    # error codes or null.
    can: dict[str, Any] = {}


class ClearIn(BaseModel):
    evidence: str = Field(default="", max_length=8000)


class WaiveIn(BaseModel):
    rationale: str = Field(max_length=8000)


class FindingOut(BaseModel):
    rule_id: str
    passed: bool
    severity: str
    message: str
    element_ref: str | None = None
    suggestion: str | None = None
