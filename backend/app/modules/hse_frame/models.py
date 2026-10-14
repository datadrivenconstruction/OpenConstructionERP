# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HSE frame ORM models.

Tables (all prefixed ``oe_hsef_``):
    frame -- one per project: pinned catalogue, state, the facts that decide which duties apply
             (duration, workers, employers, hazardous works) and the health and safety plan state
    item  -- the register: one row per requirement, review, clearance, target or measure
    role  -- who carries a responsibility (safety coordinator, ...), appointed on a day
    link  -- typed pointer from an item to a record another module owns; never a copy

Incidents, permits to work, audits, corrective actions, inspections and permit
conditions stay in their own modules (safety, hse_advanced, inspections,
construction_control, permits); the frame links and reads them.

There are no ``relationship()`` declarations; the repository loads by id.
Calendar days are ``Date``; instants are timezone-aware ``DateTime``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

_PROJECT_FK = "oe_projects_project.id"


def _project_fk() -> Any:
    return mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), nullable=False)


class HseFrame(Base):
    """The HSE frame of one project. ``version`` is the optimistic lock column."""

    __tablename__ = "oe_hsef_frame"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_hsef_frame_project"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    catalogue_source: Mapped[str] = mapped_column(String(20), nullable=False, default="shipped")
    catalogue_id: Mapped[str] = mapped_column(String(64), nullable=False, default="neutral")
    catalogue_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # draft | in_review | approved | binding | revising
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    governance_doc_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Facts that decide which duties apply; null = not known yet, which no rule reads as "no duty".
    planned_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    duration_working_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    peak_workers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    person_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    employers_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Catalogue codes of the particularly hazardous works the project will carry out.
    hazardous_work_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Whether someone looked at the hazardous works at all: an empty list means "none" only when this is true.
    hazardous_works_assessed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    advance_notice_sent_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    advance_notice_reference: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    # not_started | draft | issued | in_force
    plan_status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_started")
    plan_issued_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    plan_document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # not_started | draft | complete: the file for later works on the structure
    later_works_status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_started")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class HseItem(Base):
    """One entry of the register."""

    __tablename__ = "oe_hsef_item"
    __table_args__ = (
        Index("ix_oe_hsef_item_project_topic", "project_id", "topic"),
        UniqueConstraint("frame_id", "template_code", name="uq_oe_hsef_item_template"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk()
    frame_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_hsef_frame.id", ondelete="CASCADE", name="fk_oe_hsef_item_frame"), nullable=False
    )
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    # The catalogue template this row was created from; null for a manual row. Unique per frame, which
    # makes applying the templates twice a no-op.
    template_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Who the requirement binds: designer, contractor, owner, coordinator, operator.
    audience: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    obligation: Mapped[str] = mapped_column(String(20), nullable=False, default="mandatory")
    legal_basis: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # open | in_progress | met | waived | not_applicable
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    responsible_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    responsible_party: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    met_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_text: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    evidence_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    waive_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    waived_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Part of the tender documents handed to designers and contractors.
    in_tender_documents: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class HseRole(Base):
    """A responsibility carried by a person or a firm (safety coordinator, safety officer, ...)."""

    __tablename__ = "oe_hsef_role"
    __table_args__ = (Index("ix_oe_hsef_role_project_code", "project_id", "role_code"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    frame_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_hsef_frame.id", ondelete="CASCADE", name="fk_oe_hsef_role_frame"), nullable=False
    )
    role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    person_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    person_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    organisation: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # proposed | appointed | ended
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed")
    appointed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    qualification: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    qualification_valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    appointment_document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class HseLink(Base):
    """A typed pointer from an item to a record another module owns."""

    __tablename__ = "oe_hsef_link"
    __table_args__ = (
        UniqueConstraint("item_id", "link_kind", "link_id", name="uq_oe_hsef_link_target"),
        Index("ix_oe_hsef_link_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk()
    item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_hsef_item.id", ondelete="CASCADE", name="fk_oe_hsef_link_item"), nullable=False
    )
    link_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    link_id: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
