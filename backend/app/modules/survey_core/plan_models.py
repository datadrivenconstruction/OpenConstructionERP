# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan editor tables of the survey group.

Tables:
    oe_survey_edit - one revision of one record edited on the plan (point, parcel, work zone,
        surface, breakline, traverse, alignment, sketch): before/after JSON, author, time, note.
        It is the history behind the inspector and the 409 check on a stale ``base_rev``.
        For ``sketch`` features it is also the store: the latest revision is the feature.
    oe_survey_code_library - a project's own feature code library (the pack default applies
        while there is no row).
    oe_survey_plan_settings - a project's display and input conventions (angle unit, direction
        format, axis order, units, chainage); the country default applies while there is none.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class SurveyEdit(Base):
    """One saved revision of a record edited on the plan."""

    __tablename__ = "oe_survey_edit"
    __table_args__ = (
        Index("ix_oe_survey_edit_entity", "project_id", "entity_type", "entity_id", "rev"),
        Index("ix_oe_survey_edit_project_time", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rev: Mapped[int] = mapped_column(Integer, nullable=False)
    # create | update | delete | revert
    op: Mapped[str] = mapped_column(String(16), nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    author: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    author_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")


class SurveyCodeLibrary(Base):
    """A project's feature code library, replacing the pack default as a whole."""

    __tablename__ = "oe_survey_code_library"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_survey_code_library_project"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    codes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class SurveyPlanSettings(Base):
    """A project's plan conventions; keys it does not set fall back to the country default."""

    __tablename__ = "oe_survey_plan_settings"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_survey_plan_settings_project"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    conventions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
