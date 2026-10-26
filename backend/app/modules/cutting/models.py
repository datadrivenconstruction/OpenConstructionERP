# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cutting optimisation ORM models.

Tables:
    oe_cutting_job   - one cut-list problem: material, constraints, source, links
    oe_cutting_piece - a demanded piece (length, or length x width for sheets)
    oe_cutting_stock - a stock length or sheet on offer, or an inventory offcut
    oe_cutting_plan  - one optimiser run: figures, layout, offcuts, validation

Dimensions are millimetres. For sheets ``length_mm`` runs along the sheet's x
axis (the grain direction) and ``width_mm`` along y. Links to BOQ positions,
requisition items and inventory items are plain indexed GUIDs without a
ForeignKey, the cross-module convention that keeps this module droppable.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_types import AwareDateTime, MoneyType
from app.database import GUID, Base

JOB_KINDS = ("linear", "sheet")
JOB_STATUSES = ("draft", "optimised", "applied")
SOURCE_TYPES = ("manual", "rebar_schedule", "takeoff", "boq", "import")


class CuttingJob(Base):
    """A cut list to optimise against the stock on offer."""

    __tablename__ = "oe_cutting_job"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="linear", server_default="linear")
    material: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    kerf_mm: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=Decimal("0"), server_default="0")
    trim_mm: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=Decimal("0"), server_default="0")
    min_offcut_mm: Mapped[Decimal] = mapped_column(
        Numeric(12, 1), nullable=False, default=Decimal("0"), server_default="0"
    )
    yield_threshold_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("85"), server_default="85"
    )
    # kg per metre (linear) or per square metre (sheet), to propose a BOQ line kept in kg or t.
    unit_mass_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="manual", server_default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    procurement_req_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    pieces: Mapped[list[CuttingPiece]] = relationship(
        "app.modules.cutting.models.CuttingPiece",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="CuttingPiece.sort_order",
    )
    stocks: Mapped[list[CuttingStock]] = relationship(
        "app.modules.cutting.models.CuttingStock",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="CuttingStock.sort_order",
    )
    plans: Mapped[list[CuttingPlan]] = relationship(
        "app.modules.cutting.models.CuttingPlan",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
    )

    def __repr__(self) -> str:
        return f"<CuttingJob {self.name} ({self.kind})>"


class CuttingPiece(Base):
    """A demanded piece: ``quantity`` cuts of one size."""

    __tablename__ = "oe_cutting_piece"

    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_cutting_job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ref: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    length_mm: Mapped[Decimal] = mapped_column(Numeric(12, 1), nullable=False)
    width_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 1), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    rotatable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    job: Mapped[CuttingJob] = relationship(back_populates="pieces", lazy="raise_on_sql")


class CuttingStock(Base):
    """A stock length or sheet on offer; ``available`` of ``None`` means unlimited."""

    __tablename__ = "oe_cutting_stock"

    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_cutting_job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ref: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    length_mm: Mapped[Decimal] = mapped_column(Numeric(12, 1), nullable=False)
    width_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 1), nullable=True)
    unit_cost: Mapped[Decimal] = mapped_column(MoneyType(18, 4), nullable=False, default=Decimal("0"))
    available: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_offcut: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    inventory_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    job: Mapped[CuttingJob] = relationship(back_populates="stocks", lazy="raise_on_sql")


class CuttingPlan(Base):
    """One optimiser run over a job, frozen with the inputs it used.

    Totals are in metres (linear) or square metres (sheet). ``layout`` holds the
    per-stock cut list the diagrams, the PDF and the workbook are drawn from.
    """

    __tablename__ = "oe_cutting_plan"

    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_cutting_job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    stock_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pieces_placed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pieces_unplaced: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stock_total: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    pieces_total: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    offcut_total: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    scrap_total: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    yield_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=Decimal("0"))
    waste_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=Decimal("0"))
    cost: Mapped[Decimal] = mapped_column(MoneyType(18, 4), nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    exact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    proven_optimal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    layout: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    stock_usage: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    offcuts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    unplaced: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    validation: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    inventory_synced_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(AwareDateTime(), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    job: Mapped[CuttingJob] = relationship(back_populates="plans", lazy="raise_on_sql")

    def __repr__(self) -> str:
        return f"<CuttingPlan job={self.job_id} yield={self.yield_pct}%>"
