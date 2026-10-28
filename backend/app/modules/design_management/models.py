# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Design management ORM models.

Tables (all prefixed ``oe_design_``):
    setup          -- one per project: pinned numbering scheme and reports catalogue, switches
    role           -- who designs what (party, discipline, originator code, responsible WBS nodes)
    approval_point -- where design needs a decision, decided through an approval route
    deliverable    -- a design schedule line; its state is computed from its drawings
    drawing        -- 1:1 register extension of a CDE container (number and revisions stay in CDE)
    number_counter -- per project and scope key, the next sequence value (row locked)
    dist_rule      -- one row of the distribution matrix
    release        -- revisions released together, issued as transmittals
    review         -- an internal phase review, with comments on CDE revisions
    review_comment
    report         -- an expert report or proof, itself a CDE container
    permit         -- the permit design package and its pinned contents
    permit_item

The WBS is ``projects.ProjectWBS`` (SPEC decision 1): no tree table here.
Nothing stores a drawing number, a revision, a transmittal, a schedule date or
an approval: those are read from CDE, transmittals, schedule and approval_routes.

Constraint and index names are written out and short (``*_oe_dsg_*``) so
``app.core.pg_optimizations`` (which generates ``ix_oe_design_*``) never
collides, and the migration uses the same strings. There are no
``relationship()`` declarations: rows reference each other by id and the
service loads what a request needs, so no lazy load can fire from async code.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

_PROJECT_FK = "oe_projects_project.id"


def _project(name: str) -> Mapped[uuid.UUID]:
    return mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name=name), nullable=False)


class DesignSetup(Base):
    """The project's pinned scheme and catalogue, and its design switches."""

    __tablename__ = "oe_design_setup"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_dsg_setup_project"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_dsg_setup_project")
    # shipped | tenant
    scheme_source: Mapped[str] = mapped_column(String(20), nullable=False, default="shipped")
    scheme_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scheme_version: Mapped[int] = mapped_column(Integer, nullable=False)
    reports_source: Mapped[str] = mapped_column(String(20), nullable=False, default="shipped")
    reports_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reports_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Earlier pins, newest last: [{"source", "id", "version", "until"}] (rule 9).
    previous_schemes: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    four_eyes_release: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_distribution_purpose: Mapped[str] = mapped_column(String(30), nullable=False, default="for_information")
    lead_designer_role_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    hierarchical_codes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    wbs_separator: Mapped[str] = mapped_column(String(1), nullable=False, default=".")
    # {phase_code: suitability code} a deliverable must reach to be accepted.
    target_suitability: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Soft links to approval_routes.Route; None = the project's route of that target kind.
    approval_route_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    release_route_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


#: Which roles hold an originator code exclusively (stored upper-cased by the service).
ROLE_ORIGINATOR_UNIQUE_WHERE = (
    "party_kind = 'discipline_designer' AND status <> 'released' AND originator_code IS NOT NULL"
)


class DesignRole(Base):
    """Who designs what: a party in a role, with a discipline and an originator code."""

    __tablename__ = "oe_design_role"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_dsg_role_code"),
        Index("ix_oe_dsg_role_originator", "project_id", "originator_code"),
        # Rule 21 backstop: the service serialises role writes per project, this holds if it ever does not.
        Index(
            "uq_oe_dsg_role_originator",
            "project_id",
            "originator_code",
            unique=True,
            postgresql_where=text(ROLE_ORIGINATOR_UNIQUE_WHERE),
            sqlite_where=text(ROLE_ORIGINATOR_UNIQUE_WHERE),
        ),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_dsg_role_project")
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # owner | lead_designer | discipline_designer | specialist | checker | authority | contractor_designer
    party_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    discipline_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    originator_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Soft link to delivery_model ContractPackage (the design award).
    contract_package_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    responsible_wbs_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")


class DesignApprovalPoint(Base):
    """A point where design needs a decision; decided by whoever the approval route entitles."""

    __tablename__ = "oe_design_approval_point"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_dsg_ap_code"),
        Index("ix_oe_dsg_ap_instance", "approval_instance_id"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_dsg_ap_project")
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    phase_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # owner_approval | user_signoff | cost_check | authority | internal_review
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    governance_gate_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approver_role_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    approval_instance_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class DesignDeliverable(Base):
    """A design schedule line. ``status`` is a cache of the computed state (rule 15)."""

    __tablename__ = "oe_design_deliverable"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_dsg_deliverable_code"),
        Index("ix_oe_dsg_deliverable_phase", "project_id", "phase_code"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_dsg_deliverable_project")
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Empty only on a project without a phase model; with one the service requires it.
    phase_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    discipline_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    form_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    wbs_node_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    planned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    planned_count_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Soft link to schedule.Activity: the schedule owns the dates.
    schedule_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Approval point ids and permit package ids this line is needed for.
    required_for: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    target_suitability: Mapped[str | None] = mapped_column(String(10), nullable=True)
    waived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    waived_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="not_started")


class DesignDrawing(Base):
    """Register-only attributes of a CDE container that is a drawing (SPEC decision 4)."""

    __tablename__ = "oe_design_drawing"
    __table_args__ = (
        UniqueConstraint("container_id", name="uq_oe_dsg_drawing_container"),
        Index("ix_oe_dsg_drawing_project", "project_id"),
        Index("ix_oe_dsg_drawing_deliverable", "deliverable_id"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_dsg_drawing_project")
    container_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_cde_container.id", ondelete="CASCADE", name="fk_oe_dsg_drawing_container"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    scale: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    sheet_size: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    phase_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deliverable_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    wbs_node_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    role_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    planned_first_issue: Mapped[str | None] = mapped_column(String(10), nullable=True)
    forecast_issue: Mapped[str | None] = mapped_column(String(10), nullable=True)
    schedule_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    superseded_by_container_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # The scheme the number was checked against; differs from the pin after a scheme change (rule 9).
    scheme_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    scheme_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    legacy_scheme: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Earlier numbers after a renumber, searchable.
    aliases: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    # Last title-block sheet number read for this drawing (rule 11).
    title_block_number: Mapped[str | None] = mapped_column(String(255), nullable=True)


class DesignNumberCounter(Base):
    """The next sequence value of one numbering scope. Only ever increases (rule 8)."""

    __tablename__ = "oe_design_number_counter"
    __table_args__ = (UniqueConstraint("project_id", "scope_key", name="uq_oe_dsg_counter_scope"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_dsg_counter_project")
    scope_key: Mapped[str] = mapped_column(String(255), nullable=False)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class DesignNumberReservation(Base):
    """A drawing number once used in the project; outlives its container so it is never reused (rule 8).

    No foreign keys on purpose: the row must survive the deletion of the
    container and drawing it was written for.
    """

    __tablename__ = "oe_design_number_reservation"
    __table_args__ = (UniqueConstraint("project_id", "number", name="uq_oe_dsg_reservation_number"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_dsg_reservation_project")
    number: Mapped[str] = mapped_column(String(255), nullable=False)
    container_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    reason: Mapped[str] = mapped_column(String(20), nullable=False, default="issued")


class DesignDistributionRule(Base):
    """One row of the distribution matrix: who receives which drawings, for what, in which format."""

    __tablename__ = "oe_design_dist_rule"
    __table_args__ = (Index("ix_oe_dsg_dist_rule_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_dsg_dist_rule_project")
    # file_distribution list id OR design role id
    recipient_list_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    recipient_role_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    discipline_codes: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    form_codes: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    phase_codes: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    wbs_node_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    min_suitability: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Empty = the rule applies to releases of any purpose; set = only to releases of that purpose.
    # It never changes what is sent: a transmittal carries the release's purpose.
    purpose: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    # pdf | native | both
    format: Mapped[str] = mapped_column(String(10), nullable=False, default="pdf")
    copies_paper: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ack_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class DesignRelease(Base):
    """Container revisions released together; issuing creates one transmittal per recipient."""

    __tablename__ = "oe_design_release"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_dsg_release_code"),
        Index("ix_oe_dsg_release_instance", "approval_instance_id"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_dsg_release_project")
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    purpose: Mapped[str] = mapped_column(String(30), nullable=False, default="for_information")
    revision_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    transmittal_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    # [{"recipient_key", "transmittal_id", "revision_ids", "excluded", "duplicates"}]
    issue_plan: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    duplicate_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    approval_instance_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    prepared_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Who last changed what goes out or marked it ready: that person cannot approve it (decision 14).
    content_changed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # none | pending | approved | rejected
    approval_status: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DesignReview(Base):
    """An internal review of a phase's deliverables."""

    __tablename__ = "oe_design_review"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_oe_dsg_review_code"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_dsg_review_project")
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    phase_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deliverable_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    reviewer_role_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    # accepted | accepted_with_comments | rework
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    concluded_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    concluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DesignReviewComment(Base):
    """A review comment on one CDE revision."""

    __tablename__ = "oe_design_review_comment"
    __table_args__ = (Index("ix_oe_dsg_comment_review", "review_id"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_dsg_comment_project")
    review_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_design_review.id", ondelete="CASCADE", name="fk_oe_dsg_comment_review"), nullable=False
    )
    container_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    revision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # minor | major | critical
    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="minor")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answered_by_role_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class DesignReport(Base):
    """An expert report or proof; the document itself is a CDE container."""

    __tablename__ = "oe_design_report"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_dsg_report_code"),
        Index("ix_oe_dsg_report_cycle", "review_cycle_id"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_dsg_report_project")
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    kind_code: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    phase_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    author_role_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    container_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    checker_role_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    external_check: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Soft link to review_authority.ReviewCycle for an external check.
    review_cycle_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # catalogue | manual
    required_reason: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    # The independent-check level in force: the catalogue's, or the overridden one.
    independent_check: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    hint_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="required")
    conditions_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    governance_condition_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)


class DesignPermit(Base):
    """The permit design package; from ``submitted`` on its state is read from the review cycle."""

    __tablename__ = "oe_design_permit"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_dsg_permit_code"),
        Index("ix_oe_dsg_permit_cycle", "review_cycle_id"),
    )

    project_id: Mapped[uuid.UUID] = _project("fk_oe_dsg_permit_project")
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    profile_code: Mapped[str] = mapped_column(String(40), nullable=False)
    authority_submission_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    review_cycle_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Soft link to the permits module's application.
    permit_application_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    target_submission_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    schedule_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="assembling")
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_content: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Conditions recorded on approval, each confirmed by a person before it becomes a task (rule 20):
    # [{"id", "text", "owner_user_id", "due_date", "state": proposed|confirmed|dismissed, "task_id"}]
    conditions: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)


class DesignPermitItem(Base):
    """One item of a permit package: a drawing, a report or a form."""

    __tablename__ = "oe_design_permit_item"
    __table_args__ = (Index("ix_oe_dsg_permit_item_permit", "permit_id"),)

    project_id: Mapped[uuid.UUID] = _project("fk_oe_dsg_permit_item_project")
    permit_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_design_permit.id", ondelete="CASCADE", name="fk_oe_dsg_permit_item_permit"),
        nullable=False,
    )
    # drawing | report | form
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    container_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    report_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    included_revision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


ALL_MODELS: tuple[type[Base], ...] = (
    DesignSetup,
    DesignRole,
    DesignApprovalPoint,
    DesignDeliverable,
    DesignDrawing,
    DesignNumberCounter,
    DesignNumberReservation,
    DesignDistributionRule,
    DesignRelease,
    DesignReview,
    DesignReviewComment,
    DesignReport,
    DesignPermit,
    DesignPermitItem,
)
