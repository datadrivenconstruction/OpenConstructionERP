# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Project handbook ORM models.

Tables (all prefixed ``oe_handbook_``):
    handbook         -- one per project: pinned chapter catalogue, title and edition
    chapter          -- a chapter: owner, text, status, working version and the approved one
    chapter_version  -- an approved text, immutable: what the handbook said when it was approved

What is deliberately NOT here: the records the chapters talk about. The organisation chapter reads
stakeholders and staffing, the schedule chapter the engineering brief, at the moment it is shown or
printed (``sources.py``); a copy would be wrong the day after.

Constraint and index names are written out (``*_oe_hb_*``) and the migration uses the same strings.
No ``relationship()``: rows reference each other by id and the repository loads explicitly. The data room
folders are rows of ``oe_documents_folder`` and live in the documents module.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

_PROJECT_FK = "oe_projects_project.id"


def _project_fk(name: str) -> Any:
    return mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name=name), nullable=False)


class Handbook(Base):
    """The project's handbook: which chapter catalogue it follows, its title and edition."""

    __tablename__ = "oe_handbook_handbook"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_hb_handbook_project"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_hb_handbook_project")
    catalogue_source: Mapped[str] = mapped_column(String(20), nullable=False, default="shipped")
    catalogue_id: Mapped[str] = mapped_column(String(64), nullable=False)
    catalogue_version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Free text printed under the title, e.g. "Edition 1, planning phase".
    edition: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class HandbookChapter(Base):
    """One chapter. ``status`` is draft | in_review | approved | revising."""

    __tablename__ = "oe_handbook_chapter"
    __table_args__ = (
        UniqueConstraint("handbook_id", "code", name="uq_oe_hb_chapter_code"),
        Index("ix_oe_hb_chapter_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_hb_chapter_project")
    handbook_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_handbook_handbook.id", ondelete="CASCADE", name="fk_oe_hb_chapter_handbook"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    area_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    folder_code: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # A project may retitle a chapter; empty means the catalogue's title.
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # The version being written; the approved one is ``approved_version`` and stays in force while revising.
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": row_version}


class HandbookChapterVersion(Base):
    """An approved text of a chapter. Never updated, never deleted but with its chapter."""

    __tablename__ = "oe_handbook_chapter_version"
    __table_args__ = (
        UniqueConstraint("chapter_id", "version", name="uq_oe_hb_version_number"),
        Index("ix_oe_hb_version_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_hb_version_project")
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_handbook_chapter.id", ondelete="CASCADE", name="fk_oe_hb_version_chapter"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
