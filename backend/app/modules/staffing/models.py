# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Staffing ORM models.

Tables (all prefixed ``oe_staffing_``):
    plan        -- one per project: pinned staffing catalogue, state, the snapshot in force
    position    -- a role to staff in a phase, with FTE, headcount, dates, gate and owner
    fill        -- a person (``teams.RosterMember``) on a position for a period and FTE share
    handover    -- knowledge handover from a fill to a later position
    file        -- the personnel file: the privacy envelope of one person on the project
    document    -- one required document of a file, linked to a ``credentials.Credential``
    travel      -- a trip of the person (mobilisation, rotation, business, demobilisation)
    leave       -- an absence of the person

What is deliberately NOT here (SPEC section 10, lead decisions 1, 2, 5, 6, 8):
no person name (read through the roster member), no nationality, birth date,
address or medical field, no expiry date (the credential holds it), no full
document number (``number_last4`` only). ``tests/unit/test_staffing_catalogue_and_privacy.py``
asserts the column lists so a field that must stay empty cannot be added.

Constraint and index names are written out (``*_oe_staff_*``) and the
migration uses the same strings. No ``relationship()``: rows reference each
other by id and the repository loads explicitly. Soft references into other
modules (roster members, credentials, resource requests, contracts, RFQs,
users) carry no foreign key; the governance frame document does (SET NULL), as
the document reference gate requires of every ``*document_id`` column. Calendar days are ``Date``;
instants are timezone-aware ``DateTime``; FTE and money are exact decimals.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
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


def _fk(target: str, name: str) -> Any:
    return mapped_column(GUID(), ForeignKey(target, ondelete="CASCADE", name=name), nullable=False)


class StaffingPlan(Base):
    """The project's staffing plan: pinned catalogue, lifecycle, and the snapshot governance bound."""

    __tablename__ = "oe_staffing_plan"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_staff_plan_project"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_staff_plan_project")
    catalogue_source: Mapped[str] = mapped_column(String(20), nullable=False, default="shipped")
    catalogue_id: Mapped[str] = mapped_column(String(64), nullable=False)
    catalogue_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # draft | in_review | approved | binding | revising
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # Remote site: a confirmed fill without accommodation warns (rule 18).
    requires_accommodation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Planned commissioning date: operation key roles must start before it (rule 6).
    commissioning_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # The governance frame document that carries the plan; a deleted document unlinks, never cascades.
    governance_document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_governance_document.id", ondelete="SET NULL", name="fk_oe_staff_plan_gov_document"),
        nullable=True,
    )
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # gate | change_request: which governance act bound the plan.
    approval_source: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    bound_revision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Positions as bound (JSON-safe). Stays in force while the plan is ``revising`` (rule 7).
    bound_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class StaffingPosition(Base):
    """A role to staff: phase, organisation, FTE per head, headcount, entry and exit, gate, owner."""

    __tablename__ = "oe_staffing_position"
    __table_args__ = (
        Index("ix_oe_staff_position_project", "project_id"),
        Index("ix_oe_staff_position_plan", "plan_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_staff_position_project")
    plan_id: Mapped[uuid.UUID] = _fk("oe_staffing_plan.id", "fk_oe_staff_position_plan")
    # Catalogue role code, or ``custom`` with ``custom_label``.
    role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    custom_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    organisation: Mapped[str] = mapped_column(String(40), nullable=False)
    # development | execution | operation
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    fte: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("1"))
    headcount: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    entry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    exit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # What the phase this position is needed before must enable (a governance phase tag). Never a gate
    # code: the gate is found from the tag when it is read.
    required_before: Mapped[str | None] = mapped_column(String(64), nullable=True)
    key_role: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    handover_role: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # open | recruiting | on_hold | cancelled. ``filled`` is derived from confirmed fills, never stored.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    # internal | agency | direct | framework | consultant_contract
    recruiting_channel: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Line manager of the position: receives reminders (rule 10), may open the files of its fills (rule 13).
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    resource_request_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    rfq_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PositionFill(Base):
    """One person on one position for a period and FTE share. Several fills = job share or succession."""

    __tablename__ = "oe_staffing_fill"
    __table_args__ = (
        Index("ix_oe_staff_fill_project", "project_id"),
        Index("ix_oe_staff_fill_position", "position_id"),
        Index("ix_oe_staff_fill_roster", "roster_member_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_staff_fill_project")
    position_id: Mapped[uuid.UUID] = _fk("oe_staffing_position.id", "fk_oe_staff_fill_position")
    # Soft link to teams.RosterMember; cut (NULL) when the person's file is anonymised.
    roster_member_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    fte_share: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("1"))
    from_date: Mapped[date] = mapped_column(Date, nullable=False)
    to_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # proposed | confirmed | ended
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed")


class HandoverLink(Base):
    """Knowledge handover from a fill to a later position, with an overlap in days."""

    __tablename__ = "oe_staffing_handover"
    __table_args__ = (Index("ix_oe_staff_handover_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_staff_handover_project")
    from_fill_id: Mapped[uuid.UUID] = _fk("oe_staffing_fill.id", "fk_oe_staff_handover_fill")
    to_position_id: Mapped[uuid.UUID] = _fk("oe_staffing_position.id", "fk_oe_staff_handover_position")
    overlap_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scope: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # planned | done
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")


class PersonnelFile(Base):
    """The privacy envelope of one person on one project. Holds no name and no nationality."""

    __tablename__ = "oe_staffing_file"
    __table_args__ = (
        UniqueConstraint("project_id", "roster_member_id", name="uq_oe_staff_file_member"),
        Index("ix_oe_staff_file_project", "project_id"),
        Index("ix_oe_staff_file_due", "status", "retention_due_at"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_staff_file_project")
    # Soft link to teams.RosterMember; NULL after anonymisation.
    roster_member_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    employer_organisation: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # employee | posted_worker | contractor_staff | consultant | agency
    employment_basis: Mapped[str] = mapped_column(String(30), nullable=False, default="employee")
    # True only when a work permit check applies; nationality itself is never stored (lead decision 6).
    nationality_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # contract | legal_obligation | legitimate_interest
    lawful_basis: Mapped[str] = mapped_column(String(30), nullable=False, default="contract")
    # active | ended | retention_hold | anonymised
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    ended_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    retention_due_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    hold_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    held_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    anonymised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # After anonymisation: {"YYYY-MM": {"travel": n, "leave": n}}; nothing that identifies a person.
    activity_counts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class PersonnelDocument(Base):
    """One required document of a file. Validity lives on the linked credential, never here."""

    __tablename__ = "oe_staffing_document"
    __table_args__ = (
        UniqueConstraint("personnel_file_id", "document_kind", name="uq_oe_staff_document_kind"),
        # One validity record belongs to one document, so removing a file never removes another person's.
        UniqueConstraint("project_id", "credential_id", name="uq_oe_staff_document_credential"),
        Index("ix_oe_staff_document_project", "project_id"),
        Index("ix_oe_staff_document_credential", "credential_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_staff_document_project")
    personnel_file_id: Mapped[uuid.UUID] = _fk("oe_staffing_file.id", "fk_oe_staff_document_file")
    document_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    # Soft link to credentials.Credential (valid_until, status, notify_days_before live there).
    credential_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Last four characters of the document number, only for kinds with ``store_number`` (rule 12).
    number_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    # Who last stated the document's validity; that person does not verify it (four eyes).
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    waived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    waiver_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Occupational health certificate only: yes | with_restrictions | no (rule 11). No other health field exists.
    fit_for_role: Mapped[str | None] = mapped_column(String(20), nullable=True)


class TravelRecord(Base):
    """A trip of the person: city-level places, dates, booking reference and cost."""

    __tablename__ = "oe_staffing_travel"
    __table_args__ = (
        Index("ix_oe_staff_travel_project", "project_id"),
        Index("ix_oe_staff_travel_file", "personnel_file_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_staff_travel_project")
    personnel_file_id: Mapped[uuid.UUID] = _fk("oe_staffing_file.id", "fk_oe_staff_travel_file")
    # mobilisation | rotation | business | demobilisation
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    from_place: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    to_place: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    depart_date: Mapped[date] = mapped_column(Date, nullable=False)
    return_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    booking_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    # planned | booked | done | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")


class LeaveRecord(Base):
    """An absence: type and dates only. No reason field exists (lead decision 11)."""

    __tablename__ = "oe_staffing_leave"
    __table_args__ = (
        Index("ix_oe_staff_leave_project", "project_id"),
        Index("ix_oe_staff_leave_file", "personnel_file_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_staff_leave_project")
    personnel_file_id: Mapped[uuid.UUID] = _fk("oe_staffing_file.id", "fk_oe_staff_leave_file")
    leave_type: Mapped[str] = mapped_column(String(30), nullable=False)
    from_date: Mapped[date] = mapped_column(Date, nullable=False)
    to_date: Mapped[date] = mapped_column(Date, nullable=False)
    # requested | approved | taken | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


ALL_MODELS = (
    StaffingPlan,
    StaffingPosition,
    PositionFill,
    HandoverLink,
    PersonnelFile,
    PersonnelDocument,
    TravelRecord,
    LeaveRecord,
)
