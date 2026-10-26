# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Condition assessment ORM models.

Tables:
    oe_condition_scale      - a condition scale defined for one project
    oe_condition_assessment - one condition rating of an asset or element
    oe_condition_action     - one maintenance action of the multi-year plan

Assets are referenced softly (no foreign key): ``asset_ref`` is a BIM element id
from the asset register, a plant item id or a free tag, named by ``asset_kind``.
That keeps the module installable without the BIM hub or the plant register and
lets an element nobody modelled ("north facade render") be rated all the same.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_types import SafeDate
from app.database import GUID, Base

__all__ = ["ConditionAction", "ConditionAssessment", "ConditionScale"]


class ConditionScale(Base):
    """A condition scale a project defined for itself (levels as JSON, best first)."""

    __tablename__ = "oe_condition_scale"
    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_condition_scale_project_key"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=4, server_default="4")
    levels: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")  # type: ignore[assignment]
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<ConditionScale {self.key} ({len(self.levels or [])} levels)>"


class ConditionAssessment(Base):
    """One condition rating of an asset or element, usually recorded during an inspection.

    ``rating`` is a level of the scale named by ``scale_key`` (1 = best).
    ``severity`` and ``intensity`` run 1 (minor / slow) to 4 (critical /
    urgent); ``extent_pct`` is the share of the element affected. The rating
    the record suggested and its confidence are kept next to the rating the
    inspector chose, so a reviewer can see where a person overrode a proposal.
    """

    __tablename__ = "oe_condition_assessment"
    __table_args__ = (
        Index("ix_condition_assessment_project_asset", "project_id", "asset_ref"),
        Index("ix_condition_assessment_project_date", "project_id", "assessed_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    inspection_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    asset_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="element", server_default="element")
    asset_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    element_name: Mapped[str] = mapped_column(String(255), nullable=False)
    element_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    area: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scale_key: Mapped[str] = mapped_column(String(60), nullable=False, default="default_6", server_default="default_6")
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    suggested_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suggestion_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extent_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    intensity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    defect_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    assessed_at: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    assessed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    photos: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")  # type: ignore[assignment]
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ConditionAssessment {self.element_name[:40]} rating={self.rating}/{self.scale_key}>"


class ConditionAction(Base):
    """One maintenance action of the plan: what, when, how often, at what unit cost.

    ``source`` is ``derived`` for an action proposed from a rating (with its
    ``confidence``) and ``manual`` for one a person entered. A derived action
    starts ``proposed`` and counts in the plan only once a person approves it,
    unless the plan is asked to include proposals.
    """

    __tablename__ = "oe_condition_action"
    __table_args__ = (
        Index("ix_condition_action_project_status", "project_id", "status"),
        Index("ix_condition_action_assessment", "assessment_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_condition_assessment.id", ondelete="SET NULL"),
        nullable=True,
    )
    asset_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="element", server_default="element")
    asset_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    element_name: Mapped[str] = mapped_column(String(255), nullable=False)
    area: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    first_year: Mapped[int] = mapped_column(Integer, nullable=False)
    interval_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed", server_default="proposed")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", server_default="manual")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ConditionAction {self.action_type} {self.element_name[:30]} {self.first_year}>"
