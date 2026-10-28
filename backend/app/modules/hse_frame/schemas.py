# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Request and response schemas of the HSE frame."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Audience = Literal["owner", "designer", "contractor", "coordinator", "operator"]
ItemStatus = Literal["open", "in_progress", "met", "waived", "not_applicable"]
Obligation = Literal["mandatory", "recommended"]
RoleStatus = Literal["proposed", "appointed", "ended"]
PlanStatus = Literal["not_started", "draft", "issued", "in_force"]
LaterWorksStatus = Literal["not_started", "draft", "complete"]
_CODE = r"^[a-z0-9][a-z0-9_]*$"


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── frame ──────────────────────────────────────────────────────────────────


class FramePatch(_In):
    """The facts that decide which duties apply, and the plan state. ``None`` leaves a field alone."""

    planned_start: date | None = None
    duration_working_days: int | None = Field(default=None, ge=0, le=100000)
    peak_workers: int | None = Field(default=None, ge=0, le=100000)
    person_days: int | None = Field(default=None, ge=0, le=10000000)
    employers_count: int | None = Field(default=None, ge=0, le=1000)
    hazardous_work_codes: list[str] | None = None
    hazardous_works_assessed: bool | None = None
    advance_notice_sent_on: date | None = None
    advance_notice_reference: str | None = Field(default=None, max_length=120)
    plan_status: PlanStatus | None = None
    plan_issued_on: date | None = None
    plan_document_id: uuid.UUID | None = None
    later_works_status: LaterWorksStatus | None = None
    notes: str | None = Field(default=None, max_length=10000)


class FrameOut(_Out):
    id: uuid.UUID
    project_id: uuid.UUID
    catalogue_source: str
    catalogue_id: str
    catalogue_version: int
    state: str
    governance_doc_id: uuid.UUID | None
    planned_start: date | None
    duration_working_days: int | None
    peak_workers: int | None
    person_days: int | None
    employers_count: int | None
    hazardous_work_codes: list[str]
    hazardous_works_assessed: bool
    advance_notice_sent_on: date | None
    advance_notice_reference: str
    plan_status: str
    plan_issued_on: date | None
    plan_document_id: uuid.UUID | None
    later_works_status: str
    notes: str
    submitted_by: uuid.UUID | None
    submitted_at: datetime | None
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    version: int


class PinCatalogue(_In):
    source: Literal["shipped", "pack", "tenant"]
    catalogue_id: str = Field(min_length=1, max_length=64)
    version: int | None = Field(default=None, ge=1)


# ── items ──────────────────────────────────────────────────────────────────


class ItemCreate(_In):
    topic: str = Field(pattern=_CODE, max_length=64)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=10000)
    audience: list[Audience] = Field(default_factory=list)
    obligation: Obligation = "mandatory"
    legal_basis: str = Field(default="", max_length=255)
    responsible_user_id: uuid.UUID | None = None
    responsible_party: str = Field(default="", max_length=255)
    due_date: date | None = None
    target_text: str = Field(default="", max_length=255)
    in_tender_documents: bool = False


class ItemPatch(_In):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    audience: list[Audience] | None = None
    obligation: Obligation | None = None
    legal_basis: str | None = Field(default=None, max_length=255)
    responsible_user_id: uuid.UUID | None = None
    responsible_party: str | None = Field(default=None, max_length=255)
    due_date: date | None = None
    target_text: str | None = Field(default=None, max_length=255)
    evidence_note: str | None = Field(default=None, max_length=10000)
    in_tender_documents: bool | None = None
    status: Literal["open", "in_progress"] | None = None


class ItemMeet(_In):
    met_on: date | None = None
    evidence_note: str = Field(default="", max_length=10000)


class ItemWaive(_In):
    reason: str = Field(min_length=3, max_length=10000)
    not_applicable: bool = False


class ItemOut(_Out):
    id: uuid.UUID
    project_id: uuid.UUID
    frame_id: uuid.UUID
    topic: str
    template_code: str | None
    title: str
    description: str
    audience: list[str]
    obligation: str
    legal_basis: str
    status: str
    responsible_user_id: uuid.UUID | None
    responsible_party: str
    due_date: date | None
    met_on: date | None
    target_text: str
    evidence_note: str
    waive_reason: str
    waived_by: uuid.UUID | None
    in_tender_documents: bool
    source: str
    version: int
    overdue: bool = False
    links: list[LinkOut] = Field(default_factory=list)


# ── roles ──────────────────────────────────────────────────────────────────


class RoleCreate(_In):
    role_code: str = Field(pattern=_CODE, max_length=64)
    person_user_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    person_name: str = Field(default="", max_length=255)
    organisation: str = Field(default="", max_length=255)
    status: RoleStatus = "proposed"
    appointed_on: date | None = None
    ends_on: date | None = None
    qualification: str = Field(default="", max_length=255)
    qualification_valid_until: date | None = None
    appointment_document_id: uuid.UUID | None = None
    note: str = Field(default="", max_length=10000)


class RolePatch(_In):
    person_user_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    person_name: str | None = Field(default=None, max_length=255)
    organisation: str | None = Field(default=None, max_length=255)
    status: RoleStatus | None = None
    appointed_on: date | None = None
    ends_on: date | None = None
    qualification: str | None = Field(default=None, max_length=255)
    qualification_valid_until: date | None = None
    appointment_document_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=10000)


class RoleOut(_Out):
    id: uuid.UUID
    project_id: uuid.UUID
    frame_id: uuid.UUID
    role_code: str
    person_user_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    person_name: str
    organisation: str
    status: str
    appointed_on: date | None
    ends_on: date | None
    qualification: str
    qualification_valid_until: date | None
    appointment_document_id: uuid.UUID | None
    note: str
    in_force: bool = False


# ── links ──────────────────────────────────────────────────────────────────


class LinkCreate(_In):
    link_kind: str = Field(pattern=_CODE, max_length=30)
    link_id: str = Field(min_length=1, max_length=64)
    note: str = Field(default="", max_length=500)


class LinkOut(_Out):
    id: uuid.UUID
    item_id: uuid.UUID
    link_kind: str
    link_id: str
    note: str
    fact: dict[str, Any] | None = None


ItemOut.model_rebuild()


class ReviewDecision(_In):
    note: str = Field(default="", max_length=10000)
