# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Stakeholder register, communication plan, commitments, roles, bodies and mandates.

Tables (all prefixed ``oe_stakeholders_``):
    settings    -- one per project: pinned framework, analysis method, review interval, commitment route
    stakeholder -- the project relation to a contact (or a group without one); never a copy of the person
    assessment  -- append-only, dated, with the method version and the derived classification
    plan_item   -- a communication plan entry: audience, level, channel, recurrence or trigger, next due
    event       -- one engagement occurrence (held, planned or cancelled); soft deleted
    commitment  -- a promise TO a stakeholder, with source snapshot, owner, due date and loop closing
    role        -- a holder of a project role: a roster entry (person) or a contact (organisation)
    body        -- a governance body with quorum and decision level
    body_member -- a seat on a body: a role, a user or a contact, voting or not
    mandate     -- decision type x role or body x letter (P, D, A, C, I) per scope

People and companies live in contacts, users and the team roster (decision b);
meetings, correspondence, risks, tasks and requirements are soft links by id.
JSON columns hold only JSON values (ids and dates as strings), written through
``analysis.jsonable``. There are no ``relationship()`` declarations: rows
reference each other by id and the repository loads what a request needs, so
no lazy load can fire from async code. Constraint and index names are written
out and short, and the migration uses the same strings.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_types import MoneyType
from app.database import GUID, Base

_PROJECT_FK = "oe_projects_project.id"


def _project(name: str) -> Mapped[uuid.UUID]:
    return mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name=name), nullable=False)


class StakeholderSettings(Base):
    """The project's pinned framework and register settings."""

    __tablename__ = "oe_stakeholders_settings"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_stk_settings_project"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_stk_settings_project")
    # shipped | tenant
    framework_source: Mapped[str] = mapped_column(String(20), nullable=False, default="shipped")
    framework_id: Mapped[str] = mapped_column(String(64), nullable=False)
    framework_version: Mapped[int] = mapped_column(Integer, nullable=False)
    analysis_method: Mapped[str] = mapped_column(String(64), nullable=False, default="power_interest")
    review_interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    owner_area_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # approval_routes.Route of kind ``stakeholder_commitment`` (soft), used when the framework routes commitments.
    commitment_route_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class Stakeholder(Base):
    """A party's relation to the project. Names and addresses stay in contacts (rule 17)."""

    __tablename__ = "oe_stakeholders_stakeholder"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_stk_stakeholder_code"),
        # The name is the platform's: ``app.core.pg_optimizations`` adds a ``(project_id, status)`` index
        # under exactly this name after ``create_all`` unless one is declared, and any other name would
        # leave the table with the same index twice.
        Index("ix_oe_stakeholders_stakeholder_project_id_status", "project_id", "status"),
        Index("ix_oe_stk_stakeholder_contact", "contact_id"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_stk_stakeholder_project")
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    # A label for a group or a party without a contact; empty when the contact carries the name.
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    is_group: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    group_size_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_stakeholder_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_stakeholders_stakeholder.id", ondelete="SET NULL", name="fk_oe_stk_stakeholder_parent"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    interests: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expectations: Mapped[str] = mapped_column(Text, nullable=False, default="")
    concerns: Mapped[str] = mapped_column(Text, nullable=False, default="")
    relationship_owner_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # {"lat": "...", "lon": "..."} or {"parcel_ref": "..."}; strings only.
    geo: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    is_confidential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # active | dormant | archived
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    risk_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    review_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class StakeholderAssessment(Base):
    """One dated assessment; never updated. The newest under the current method is the current one."""

    __tablename__ = "oe_stakeholders_assessment"
    __table_args__ = (Index("ix_oe_stk_assessment_stakeholder", "stakeholder_id", "assessed_at"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_stk_assessment_project")
    stakeholder_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_stakeholders_stakeholder.id", ondelete="CASCADE", name="fk_oe_stk_assessment_stakeholder"),
        nullable=False,
    )
    method_code: Mapped[str] = mapped_column(String(64), nullable=False)
    method_version: Mapped[int] = mapped_column(Integer, nullable=False)
    scores: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    engagement_current: Mapped[str | None] = mapped_column(String(32), nullable=True)
    engagement_desired: Mapped[str | None] = mapped_column(String(32), nullable=True)
    attitude: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    assessed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CommunicationPlanItem(Base):
    """A planned communication. Occurrences are computed, never stored ahead (decision f)."""

    __tablename__ = "oe_stakeholders_plan_item"
    # Named as ``app.core.pg_optimizations`` would name it, see ``Stakeholder``.
    __table_args__ = (Index("ix_oe_stakeholders_plan_item_project_id_status", "project_id", "status"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_stk_plan_project")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    key_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    audience_stakeholder_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    audience_categories: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    audience_body_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    participation_level: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    format_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # "once" or an RRULE subset string; empty for trigger items.
    frequency: Mapped[str] = mapped_column(String(255), nullable=False, default="once")
    # gate | event (None = scheduled)
    trigger_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # gate code or event type the trigger listens to; empty = any.
    trigger_ref: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    triggered_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    next_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    # The due date an overdue notice was last sent for (one notice per occurrence).
    overdue_notified_for: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class EngagementEvent(Base):
    """One engagement occurrence. Deleted softly so commitments keep their source (rule 9)."""

    __tablename__ = "oe_stakeholders_event"
    __table_args__ = (
        Index("ix_oe_stk_event_project", "project_id", "held_on"),
        Index("ix_oe_stk_event_plan", "plan_item_id", "occurrence_date"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_stk_event_project")
    plan_item_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_stakeholders_plan_item.id", ondelete="SET NULL", name="fk_oe_stk_event_plan"),
        nullable=True,
    )
    # The plan occurrence this event fulfils (None for ad hoc events).
    occurrence_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    format_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    participation_level: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    held_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    location: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    stakeholder_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    attendance_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(Text, nullable=False, default="")
    feedback_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    correspondence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # CDE document containers (minutes, presentation, photos).
    cde_container_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class StakeholderCommitment(Base):
    """Something promised to one or more stakeholders, followed until verified (rules 9, 10, 18, 19)."""

    __tablename__ = "oe_stakeholders_commitment"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_stk_commitment_code"),
        Index("ix_oe_stk_commitment_project", "project_id", "status", "due_date"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_stk_commitment_project")
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    stakeholder_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # event | meeting | correspondence | permit_condition | manual
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # {"title": str, "date": "YYYY-MM-DD" | None} frozen at creation.
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    verification: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cost_estimate: Mapped[Decimal | None] = mapped_column(MoneyType(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    # Module 2 release item (soft); required before ``agreed`` when cost and matrix exist (rule 10).
    release_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    risk_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed")
    # The mandate decision: who decided, how (direct | approval) and the approval instance.
    decision_ref: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    approval_instance_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # agreed | withdrawn while an approval runs.
    pending_target: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pending_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    withdraw_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    breach_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    communicated_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    loop_not_required_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    breach_notified_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class ProjectRole(Base):
    """One holder of a project role (decision j: the project's single role vocabulary)."""

    __tablename__ = "oe_stakeholders_role"
    __table_args__ = (Index("ix_oe_stk_role_project", "project_id", "role_code"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_stk_role_project")
    role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    # Label of a custom role not in the framework.
    custom_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # teams.RosterMember (person: user, contact or typed name) or a contact (organisation).
    roster_member_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    holder_contact_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    deputy_roster_member_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Acknowledged multiple-role conflict (rule 12).
    conflict_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class GovernanceBody(Base):
    __tablename__ = "oe_stakeholders_body"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_oe_stk_body_code"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_stk_body_project")
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    body_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    chair_role_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # min_members | majority | unanimous
    quorum_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="majority")
    quorum_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # meetings.Meeting.meeting_type of the body's meeting series (soft).
    meeting_series_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    terms_container_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class GovernanceBodyMember(Base):
    __tablename__ = "oe_stakeholders_body_member"
    __table_args__ = (Index("ix_oe_stk_member_body", "body_id"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_stk_member_project")
    body_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_stakeholders_body.id", ondelete="CASCADE", name="fk_oe_stk_member_body"), nullable=False
    )
    role_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    voting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)


class Mandate(Base):
    """Decision type x role or body x letter. Exactly one ``D`` per decision type and scope (rule 13)."""

    __tablename__ = "oe_stakeholders_mandate"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "decision_type", "scope", "holder_kind", "holder_code", name="uq_oe_stk_mandate_cell"
        ),
        # The database half of "two deciders -> refused": a concurrent second D cannot commit.
        Index(
            "uq_oe_stk_mandate_decider",
            "project_id",
            "decision_type",
            "scope",
            unique=True,
            postgresql_where=text("letter = 'D'"),
            sqlite_where=text("letter = 'D'"),
        ),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_stk_mandate_project")
    decision_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # "" = the whole project; NOT NULL so the unique index sees one scope, not many NULLs.
    scope: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
    holder_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    holder_code: Mapped[str] = mapped_column(String(64), nullable=False)
    letter: Mapped[str] = mapped_column(String(1), nullable=False)
    scope_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # {"authority_schedule": "pinned", "commitment_type": "works"}; never an amount (decision i).
    limit_ref: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
