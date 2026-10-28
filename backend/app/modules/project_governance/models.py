# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Project governance ORM models.

Tables (all prefixed ``oe_governance_``):
    catalogue          -- a tenant's own catalogue: code, name, editable draft
    catalogue_version  -- an immutable published version of a tenant catalogue
    model              -- the catalogue (source, id, version) one project pins
    area               -- a management area of a project, with owner and deputy
    gate               -- a gate between two phases of the pinned model
    document           -- a frame document: area x document type, CDE soft link
    check              -- readiness of one area for one attempt of one gate
    decision           -- an immutable gate decision with its snapshot
    condition          -- a condition attached to a decision
    change_request     -- the only way a binding frame document changes

Constraint and index names are written out and short, and the migration uses
the same strings: a generated name for these tables would exceed PostgreSQL's
63 characters and be shortened by a hash, which a hand-written migration then
fails to reproduce.

There are no ``relationship()`` declarations. Rows reference each other by id
and the repository loads what a request needs explicitly, so no lazy load can
fire from async code. Soft references into other modules (CDE containers and
revisions, schedule activities, approval route instances) carry no foreign
key: the other module owns those rows.

Calendar days (due dates, resume dates, planned gate dates) are ISO strings
in ``String(40)``, as elsewhere on the platform; instants are timezone-aware
``DateTime`` columns.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

_PROJECT_FK = "oe_projects_project.id"


class GovernanceCatalogue(Base):
    """A catalogue a company owns: cloned from a shipped one or started empty.

    ``draft_body`` is the editable working copy, in exactly the JSON shape of a
    shipped catalogue file. Publishing validates it with the same models and
    rules as a shipped file and freezes it as a new
    :class:`GovernanceCatalogueVersion`.
    """

    __tablename__ = "oe_governance_catalogue"
    __table_args__ = (
        UniqueConstraint("tenant_id", "kind", "code", name="uq_oe_gov_catalogue_tenant_code"),
        Index("ix_oe_gov_catalogue_tenant", "tenant_id", "kind"),
    )

    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # The registered catalogue kind (``catalogue_kinds``): phase_model, and
    # later kinds owned by other modules (delivery_forms, authority_schedule).
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="phase_model")
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # "shipped:hoai_lph@1", "tenant:<uuid>@3" or "" when started empty.
    based_on: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    # draft | published | retired
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    draft_body: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class GovernanceCatalogueVersion(Base):
    """An immutable published version of a tenant catalogue."""

    __tablename__ = "oe_governance_catalogue_version"
    __table_args__ = (
        UniqueConstraint("catalogue_id", "version", name="uq_oe_gov_catver_version"),
        Index("ix_oe_gov_catver_catalogue", "catalogue_id"),
    )

    catalogue_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_governance_catalogue.id", ondelete="RESTRICT", name="fk_oe_gov_catver_catalogue"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GovernanceModel(Base):
    """The catalogue version one project pins, and its project-level switches."""

    __tablename__ = "oe_governance_model"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_gov_model_project"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name="fk_oe_gov_model_project"), nullable=False
    )
    # shipped | tenant | pack
    catalogue_source: Mapped[str] = mapped_column(String(20), nullable=False, default="shipped")
    catalogue_id: Mapped[str] = mapped_column(String(64), nullable=False)
    catalogue_version: Mapped[int] = mapped_column(Integer, nullable=False)
    current_phase: Mapped[str | None] = mapped_column(String(64), nullable=True)
    four_eyes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Soft links to approval_routes.Route; None = resolve by target kind.
    decision_route_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    change_route_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    stopped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class GovernanceArea(Base):
    """A management area of one project. The owner lives here and only here."""

    __tablename__ = "oe_governance_area"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_gov_area_code"),
        Index("ix_oe_gov_area_owner", "owner_user_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name="fk_oe_gov_area_project"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name_override: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    deputy_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    na_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # An area the current model no longer has; kept for its history.
    retired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class GovernanceGate(Base):
    """A gate between two phases. ``version`` is the optimistic lock column."""

    __tablename__ = "oe_governance_gate"
    __table_args__ = (
        UniqueConstraint("project_id", "catalogue_id", "code", name="uq_oe_gov_gate_code"),
        Index("ix_oe_gov_gate_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name="fk_oe_gov_gate_project"), nullable=False
    )
    catalogue_id: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    from_phase: Mapped[str] = mapped_column(String(64), nullable=False)
    to_phase: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_started")
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    schedule_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    target_date: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    approval_instance_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    hold_resume_date: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    last_outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    # A gate of a model the project left; kept because it carries decisions.
    historic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class GovernanceDocument(Base):
    """A frame document of one area. Its versions ARE the CDE container's revisions."""

    __tablename__ = "oe_governance_document"
    __table_args__ = (
        UniqueConstraint("project_id", "area_id", "doc_type", name="uq_oe_gov_document_type"),
        Index("ix_oe_gov_document_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name="fk_oe_gov_document_project"), nullable=False
    )
    area_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_governance_area.id", ondelete="CASCADE", name="fk_oe_gov_document_area"), nullable=False
    )
    doc_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Gate codes at which the catalogue requires this document.
    required_at_gates: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    container_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    bound_revision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    bound_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_gate_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    read_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class GovernanceCheck(Base):
    """Readiness of one area for one attempt of one gate."""

    __tablename__ = "oe_governance_check"
    __table_args__ = (
        UniqueConstraint("gate_id", "attempt_no", "area_id", name="uq_oe_gov_check_attempt_area"),
        Index("ix_oe_gov_check_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name="fk_oe_gov_check_project"), nullable=False
    )
    gate_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_governance_gate.id", ondelete="CASCADE", name="fk_oe_gov_check_gate"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    area_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_governance_area.id", ondelete="CASCADE", name="fk_oe_gov_check_area"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_assessed")
    rag: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_revisions: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    na_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Ticks on the catalogue's readiness criteria: {criterion code: {met, note, by, at}}.
    criteria: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class GovernanceDecision(Base):
    """An immutable gate decision. One per gate attempt; never updated or deleted by the ORM."""

    __tablename__ = "oe_governance_decision"
    __table_args__ = (
        UniqueConstraint("gate_id", "attempt_no", name="uq_oe_gov_decision_attempt"),
        Index("ix_oe_gov_decision_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name="fk_oe_gov_decision_project"), nullable=False
    )
    gate_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_governance_gate.id", ondelete="CASCADE", name="fk_oe_gov_decision_gate"), nullable=False
    )
    gate_code: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decided_by: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    proceed_at_risk_areas: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    accepted_not_applicable: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    hold_resume_date: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    approval_instance_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class GovernanceCondition(Base):
    """A condition attached to a decision, cleared by evidence or waived with a reason."""

    __tablename__ = "oe_governance_condition"
    __table_args__ = (
        # The name ``app.core.pg_optimizations`` gives these columns. Under a name of our own
        # the hook would add the same index a second time after any ``create_all``.
        Index("ix_oe_governance_condition_project_id_status", "project_id", "status"),
        Index("ix_oe_gov_condition_decision", "decision_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name="fk_oe_gov_condition_project"), nullable=False
    )
    decision_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_governance_decision.id", ondelete="CASCADE", name="fk_oe_gov_condition_decision"),
        nullable=False,
    )
    gate_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    gate_code: Mapped[str] = mapped_column(String(64), nullable=False)
    area_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    due_date: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    # critical | essential | recommended
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="essential")
    # open | cleared | waived | overdue
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cleared_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    waiver_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    waived_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    waived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GovernanceChangeRequest(Base):
    """A request to make a newer CDE revision of a binding frame document binding."""

    __tablename__ = "oe_governance_change_request"
    __table_args__ = (Index("ix_oe_gov_change_document", "document_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name="fk_oe_gov_change_project"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_governance_document.id", ondelete="CASCADE", name="fk_oe_gov_change_document"),
        nullable=False,
    )
    previous_revision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    proposed_revision_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    proposed_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    impact: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # submitted | approved | rejected | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="submitted")
    approval_instance_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImmutableRecordError(RuntimeError):
    """Raised when code tries to change or delete a record that is frozen by design."""


def _refuse_change(_mapper: Any, _connection: Any, target: Any) -> None:
    raise ImmutableRecordError(f"{type(target).__name__} {getattr(target, 'id', '?')} is immutable")


for _cls in (GovernanceDecision, GovernanceCatalogueVersion):
    event.listen(_cls, "before_update", _refuse_change)
    event.listen(_cls, "before_delete", _refuse_change)
