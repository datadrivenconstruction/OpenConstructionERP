# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Permit roadmap and permit-condition register ORM models.

Tables (all prefixed ``oe_permits_``):
    roadmap                -- one per project: pinned ``permit_type`` catalogue, jurisdiction, settings
    requirement            -- a roadmap row: "we need permit type X", who applies, needed by when
    requirement_dependency -- typed edge between two requirements (``granted`` | ``submitted``)
    application            -- one filing with the authority (new, variation, discharge, ...), attempt n
    clock_event            -- stop / resume / extension of an application's statutory clock
    decision               -- immutable authority decision; a correction is a new row superseding it
    permit                 -- the right a non-refused decision granted (read model others link to)
    condition              -- THE register: every condition of every decision
    condition_evidence     -- a link to whatever proves a condition is met
    condition_discharge    -- immutable record of how a condition was discharged

Rows reference each other by id; there are no ``relationship()`` declarations,
so no lazy load can fire from async code. Soft links into other modules carry
no foreign key and are checked against the project at write time. Constraint
and index names are written out and match the migration.

Status columns are named ``status`` because ``core.fsm`` writes that attribute;
the API calls them ``state`` as the SPEC does.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_types import MoneyType
from app.database import GUID, Base

_PROJECT_FK = "oe_projects_project.id"
_REQ_FK = "oe_permits_requirement.id"
_APP_FK = "oe_permits_application.id"
_PERMIT_FK = "oe_permits_permit.id"
_COND_FK = "oe_permits_condition.id"


def _project(name: str) -> Mapped[uuid.UUID]:
    return mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name=name), nullable=False)


class PermitRoadmap(Base):
    """One per project: which catalogue the roadmap reads and the project's permit settings."""

    __tablename__ = "oe_permits_roadmap"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_permits_roadmap_project"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_permits_roadmap_project")
    catalogue_source: Mapped[str] = mapped_column(String(20), nullable=False, default="shipped")
    catalogue_id: Mapped[str] = mapped_column(String(64), nullable=False)
    catalogue_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # ISO 3166-1 / 3166-2 (e.g. DE-NW).
    jurisdiction: Mapped[str] = mapped_column(String(12), nullable=False, default="")
    route_assessment_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    delivery_model_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # The frame document of the roadmap's governance area; a deleted document unbinds, never dangles.
    governance_document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_governance_document.id", ondelete="SET NULL", name="fk_oe_permits_roadmap_governance_document"),
        nullable=True,
    )
    # draft | agreed (mirrors the binding state of the governance frame document hosting permits, rule 18)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # Governance area codes the roadmap and the condition register report to (resolved on create).
    roadmap_area_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    conditions_area_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    internal_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approval_route_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    escalation_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    buffer_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    # Approved frame change requests already spent on a structural change (rule 18): one request, one change.
    consumed_change_request_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class PermitRequirement(Base):
    """A roadmap row. Its state is derived from its applications, never stored."""

    __tablename__ = "oe_permits_requirement"
    __table_args__ = (
        Index("ix_oe_permits_requirement_project", "project_id", "permit_type_code"),
        Index("ix_oe_permits_requirement_activity", "project_id", "needed_by_activity_id"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_permits_requirement_project")
    permit_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    applicability_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    applicant_role: Mapped[str] = mapped_column(String(20), nullable=False, default="owner")
    # Where the default applicant came from: allocation | catalogue | override
    applicant_source: Mapped[str] = mapped_column(String(20), nullable=False, default="catalogue")
    applicant_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    applicant_party: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    applicant_contact_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    responsible_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    planned_submit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    needed_by_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    needed_by_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    clock_variant: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    expected_decision_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    schedule_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    governance_area_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    conflict_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Partial grant follow-up (rule 8): the requirement whose remaining scope this one covers.
    follow_up_of_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    proposed_from_route: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RequirementDependency(Base):
    __tablename__ = "oe_permits_requirement_dependency"
    __table_args__ = (
        UniqueConstraint("requirement_id", "depends_on_id", name="uq_oe_permits_dependency"),
        Index("ix_oe_permits_dependency_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_permits_dependency_project")
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_REQ_FK, ondelete="CASCADE", name="fk_oe_permits_dependency_req"), nullable=False
    )
    depends_on_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_REQ_FK, ondelete="CASCADE", name="fk_oe_permits_dependency_on"), nullable=False
    )
    # granted | submitted
    dep_type: Mapped[str] = mapped_column(String(12), nullable=False, default="granted")


class PermitApplication(Base):
    """One filing. ``status`` follows ``APPLICATION_FSM``; ``decided`` only through a decision."""

    __tablename__ = "oe_permits_application"
    __table_args__ = (
        UniqueConstraint("requirement_id", "kind", "attempt", name="uq_oe_permits_application_attempt"),
        Index("ix_oe_permits_application_project_id_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_permits_application_project")
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_REQ_FK, ondelete="CASCADE", name="fk_oe_permits_application_req"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="new")
    parent_permit_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    discharges_condition_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Who files a change to an issued permit (rule 2): allocation | requirement; empty for new applications.
    applicant_role: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    applicant_source: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    authority_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    authority_reference: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    submitted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    received_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    validated_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    review_cycle_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    submission_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    cde_container_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approval_instance_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="planned")
    appeal_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class ClockEvent(Base):
    __tablename__ = "oe_permits_clock_event"
    __table_args__ = (Index("ix_oe_permits_clock_event_app", "application_id"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_permits_clock_event_project")
    application_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_APP_FK, ondelete="CASCADE", name="fk_oe_permits_clock_event_app"), nullable=False
    )
    # stop | resume | extension_agreed | extension_by_authority
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    period: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class PermitDecision(Base):
    """Immutable. ``revision`` 1 is the first record; a correction is revision n+1 with ``supersedes_id``."""

    __tablename__ = "oe_permits_decision"
    __table_args__ = (UniqueConstraint("application_id", "revision", name="uq_oe_permits_decision_revision"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_permits_decision_project")
    application_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_APP_FK, ondelete="CASCADE", name="fk_oe_permits_decision_app"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    decision_date: Mapped[date] = mapped_column(Date, nullable=False)
    served_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reference: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    scope_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scope_activity_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    conditions_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    appeal_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    document_revision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    deemed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class Permit(Base):
    """The granted right; one per non-refused decision."""

    __tablename__ = "oe_permits_permit"
    __table_args__ = (
        UniqueConstraint("decision_id", name="uq_oe_permits_permit_decision"),
        Index("ix_oe_permits_permit_project_id_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_permits_permit_project")
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_REQ_FK, ondelete="CASCADE", name="fk_oe_permits_permit_req"), nullable=False
    )
    application_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    decision_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    permit_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="full")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_force")
    reference: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    revocable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    security_amount: Mapped[Decimal | None] = mapped_column(MoneyType(18, 4), nullable=True)
    security_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    start_notified_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Work interrupted since this day: the permit is back on a lapse clock (rule 9, ``lapse_if_paused``).
    paused_since: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class PermitCondition(Base):
    """One condition of one permit, verbatim, with its legal kind, trigger and owner."""

    __tablename__ = "oe_permits_condition"
    __table_args__ = (
        UniqueConstraint("permit_id", "number", name="uq_oe_permits_condition_number"),
        Index("ix_oe_permits_condition_project_id_status", "project_id", "status"),
        Index("ix_oe_permits_condition_trigger", "project_id", "trigger", "status"),
        Index("ix_oe_permits_condition_due", "project_id", "due_date"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_permits_condition_project")
    permit_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PERMIT_FK, ondelete="CASCADE", name="fk_oe_permits_condition_permit"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="obligation")
    national_kind: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    trigger: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    stage_ref: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    event_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    topic: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    # restoration | security | "" (rule 10)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Who submitted the evidence for discharge; never the verifier (rule 13).
    evidence_submitted_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    responsible_party: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    requires_authority_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence_required: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    hse_override: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    # manual | ai_extracted; an AI proposal counts only once confirmed (rule 15)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    confidence: Mapped[Decimal | None] = mapped_column(MoneyType(5, 4), nullable=True)
    text_span: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    # The quoted sentence of the notice an extracted proposal is taken from (rule 15).
    source_passage: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    gate_condition_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    original_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    breach_ref_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    breach_ref_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    breach_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class ConditionEvidence(Base):
    __tablename__ = "oe_permits_condition_evidence"
    __table_args__ = (Index("ix_oe_permits_evidence_condition", "condition_id"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_permits_evidence_project")
    condition_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_COND_FK, ondelete="CASCADE", name="fk_oe_permits_evidence_condition"), nullable=False
    )
    # cde_revision | inspection | commissioning_item | report | photo | external_url | discharge_decision
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    ref_id: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    added_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class ConditionDischarge(Base):
    """Immutable record of one discharge (with the evidence snapshot it relied on)."""

    __tablename__ = "oe_permits_condition_discharge"
    __table_args__ = (Index("ix_oe_permits_discharge_condition", "condition_id"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_permits_discharge_project")
    condition_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_COND_FK, ondelete="CASCADE", name="fk_oe_permits_discharge_condition"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    discharge_application_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    verifier_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    discharged_on: Mapped[date] = mapped_column(Date, nullable=False)
    document_revision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    # A variation copied this record forward from the discharge of the original condition (rule 14).
    carried_from_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


ALL_MODELS = (
    PermitRoadmap,
    PermitRequirement,
    RequirementDependency,
    PermitApplication,
    ClockEvent,
    PermitDecision,
    Permit,
    PermitCondition,
    ConditionEvidence,
    ConditionDischarge,
)
