# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Capital plan models.

A plan ranks projects against yearly funding envelopes. Scenarios are
copy-on-write variants of the item list, so a what-if never touches the
baseline. ``node_id`` points at a portfolio node (the programme tree is the
portfolio); ``project_id`` is a plain GUID, matching the portfolio precedent.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

ITEM_STATUSES: tuple[str, ...] = ("proposed", "funded", "deferred")


class CapitalPlan(Base):
    """One multi-year capital plan, scoped to a portfolio node (or the whole tenant)."""

    __tablename__ = "oe_capital_plan"

    node_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("oe_portfolio_node.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    start_year: Mapped[int] = mapped_column(Integer, nullable=False)
    horizon_years: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )


class CapitalPlanEnvelope(Base):
    """Money available in one year from one funding source."""

    __tablename__ = "oe_capital_plan_envelope"
    __table_args__ = (UniqueConstraint("plan_id", "year", "label", name="uq_capital_plan_envelope_year_label"),)

    plan_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_capital_plan.id", ondelete="CASCADE"), nullable=False, index=True
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    label: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")


class CapitalPlanScenario(Base):
    """A named variant of the item list; at most one per plan is the baseline."""

    __tablename__ = "oe_capital_plan_scenario"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_capital_plan.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")


class CapitalPlanItem(Base):
    """One project (or placeholder) competing for the envelope in a scenario."""

    __tablename__ = "oe_capital_plan_item"

    scenario_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_capital_plan_scenario.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Plain GUID (no cross-module FK), per the portfolio membership precedent.
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    start_year: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_years: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    phasing_json: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed", server_default="proposed")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
