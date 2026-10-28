# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Engineering brief ORM models.

Tables (all prefixed ``oe_engbrief_``):
    brief      -- one per project: pinned catalogue, state, the requirement set and schedule it uses
    concept    -- a topic of the technical concept with its decision and the requirements it answers
    programme  -- a line of the area and quantity programme
    milestone  -- a milestone of the framework schedule, bound to a governance gate or to a lead time
    study      -- a site analysis or suitability study with its report in the documents module
    issue      -- an issued version of the requirements specification (the Lastenheft document)

What is deliberately NOT here: the requirements. They are rows of ``oe_requirements_item`` in the
requirement set the brief points at, so there is one requirements register and no copy of it. The
framework schedule is published into ``oe_schedule_activity`` rows, not kept twice.

Constraint and index names are written out (``*_oe_eb_*``) and the migration uses the same strings.
No ``relationship()``: rows reference each other by id and the repository loads explicitly, so no lazy
load fires from async code. Soft references into other modules (requirements, schedule activities,
permit roadmap requirements, governance gates by code) carry no foreign key, except the requirement
set, the schedule and the governance frame document, which are SET NULL so a deleted target unlinks.
Calendar days are ``Date``; instants are timezone-aware ``DateTime``; quantities are exact decimals.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

_PROJECT_FK = "oe_projects_project.id"


def _project_fk(name: str) -> Any:
    return mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name=name), nullable=False)


def _brief_fk(name: str) -> Any:
    return mapped_column(GUID(), ForeignKey("oe_engbrief_brief.id", ondelete="CASCADE", name=name), nullable=False)


class EngineeringBrief(Base):
    """The project's brief: pinned catalogue, lifecycle, requirement set, schedule and the bound snapshot."""

    __tablename__ = "oe_engbrief_brief"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_eb_brief_project"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_eb_brief_project")
    catalogue_source: Mapped[str] = mapped_column(String(20), nullable=False, default="shipped")
    catalogue_id: Mapped[str] = mapped_column(String(64), nullable=False)
    catalogue_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # draft | in_review | approved | binding | revising
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The requirement set that holds the structured requirements of this brief.
    requirement_set_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_requirements_set.id", ondelete="SET NULL", name="fk_oe_eb_brief_req_set"),
        nullable=True,
    )
    # The schedule the framework schedule is published into; created on the first publication.
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_schedule_schedule.id", ondelete="SET NULL", name="fk_oe_eb_brief_schedule"),
        nullable=True,
    )
    # Date the operating proof is due: the anchor the framework schedule is planned backwards from.
    operation_proof_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # The governance frame document that carries the brief; a deleted document unlinks, never cascades.
    governance_document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_governance_document.id", ondelete="SET NULL", name="fk_oe_eb_brief_gov_document"),
        nullable=True,
    )
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # gate | change_request | hand: which act bound the brief.
    approval_source: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    bound_revision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Requirements, concept, programme and milestones as bound (JSON-safe). Stays in force while revising.
    bound_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # SHA-256 of the requirements as bound: a requirement edited behind the brief's back shows as drift.
    bound_requirements_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class ConceptItem(Base):
    """One topic of the technical concept: supply, building structure, modularity, construction method."""

    __tablename__ = "oe_engbrief_concept"
    __table_args__ = (
        UniqueConstraint("brief_id", "code", name="uq_oe_eb_concept_code"),
        Index("ix_oe_eb_concept_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_eb_concept_project")
    brief_id: Mapped[uuid.UUID] = _brief_fk("fk_oe_eb_concept_brief")
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    topic_code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decision: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # open | agreed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    # Requirement ids (strings) of the brief's set that this item answers.
    requirement_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ProgrammeLine(Base):
    """One line of the area and quantity programme: the basis for the cost frame and the packages."""

    __tablename__ = "oe_engbrief_programme"
    __table_args__ = (
        UniqueConstraint("brief_id", "code", name="uq_oe_eb_programme_code"),
        Index("ix_oe_eb_programme_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_eb_programme_project")
    brief_id: Mapped[uuid.UUID] = _brief_fk("fk_oe_eb_programme_brief")
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    kind_code: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    basis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class FrameMilestone(Base):
    """A milestone of the framework schedule.

    Planned backwards from the operating proof: ``successor_id`` names the milestone this one must
    precede and ``lead_days`` how many calendar days before it. A milestone with a ``gate_code`` is the
    schedule's side of that governance gate.
    """

    __tablename__ = "oe_engbrief_milestone"
    __table_args__ = (
        UniqueConstraint("brief_id", "code", name="uq_oe_eb_milestone_code"),
        Index("ix_oe_eb_milestone_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_eb_milestone_project")
    brief_id: Mapped[uuid.UUID] = _brief_fk("fk_oe_eb_milestone_brief")
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    kind_code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    lead_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    successor_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_engbrief_milestone.id", ondelete="SET NULL", name="fk_oe_eb_milestone_successor"),
        nullable=True,
    )
    # The governance gate this milestone is the schedule side of, by code. Checked against the project's gates.
    gate_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # A permit roadmap requirement whose decision this milestone waits for (read through the permits port).
    permit_requirement_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # The schedule activity this milestone was published as.
    activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Study(Base):
    """A tracked study that backs a gate criterion: a site analysis or a suitability study."""

    __tablename__ = "oe_engbrief_study"
    __table_args__ = (
        UniqueConstraint("brief_id", "code", name="uq_oe_eb_study_code"),
        Index("ix_oe_eb_study_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_eb_study_project")
    brief_id: Mapped[uuid.UUID] = _brief_fk("fk_oe_eb_study_brief")
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    # site_analysis | suitability
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    study_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # open | suitable | conditional | unsuitable
    conclusion: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    # The report in the documents module. No foreign key: a deleted document leaves the study unlinked.
    document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SpecificationIssue(Base):
    """One issue of the requirements specification: a numbered version of the brief as a document."""

    __tablename__ = "oe_engbrief_issue"
    __table_args__ = (
        UniqueConstraint("brief_id", "version_no", name="uq_oe_eb_issue_version"),
        Index("ix_oe_eb_issue_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_eb_issue_project")
    brief_id: Mapped[uuid.UUID] = _brief_fk("fk_oe_eb_issue_brief")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    issued_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # SHA-256 of the requirements as issued; a later edit makes the issue stale.
    requirements_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requirement_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
