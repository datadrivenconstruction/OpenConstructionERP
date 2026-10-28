# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Risk Register ORM models.

Tables:
    oe_risk_register - risk items with probability, impact, mitigation, and status
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class RiskItem(Base):
    """Risk register entry tracking project risks and mitigation."""

    __tablename__ = "oe_risk_register"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="technical")
    probability: Mapped[str] = mapped_column(String(10), nullable=False, default="0.5")
    impact_cost: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    impact_schedule_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    impact_severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    risk_score: Mapped[str] = mapped_column(String(10), nullable=False, default="0")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="identified", index=True)
    mitigation_strategy: Mapped[str] = mapped_column(Text, nullable=False, default="")
    contingency_plan: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    response_cost: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")

    # Expanded risk scoring (Phase 16 enhancement)
    probability_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    impact_score_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    impact_score_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Mitigation actions: [{description, responsible_id, due_date, status}]
    mitigation_actions: Mapped[list | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )

    # ── Auto-escalation (TOP-30 #24) ──────────────────────────────────────
    # A risk auto-escalates exactly once per *trigger* when either its
    # severity product (probability_score x impact_score) crosses the
    # escalation threshold, or its next-review date has lapsed. The flag
    # and timestamp guarantee idempotency: the engine never escalates a
    # risk that is already flagged for the same trigger. ``escalation_trigger``
    # records which condition fired ("severity" | "review_lapsed"), and
    # ``escalation_threshold`` is an optional per-risk override of the
    # project/global default (1-25 PMBOK product scale).
    escalated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,
    )
    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    escalation_trigger: Mapped[str | None] = mapped_column(String(20), nullable=True)
    escalation_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Monte Carlo / PERT three-point estimate (v3.11 - T1) ───────────
    # Optional triples (optimistic / most-likely / pessimistic) used by
    # the quantitative Monte Carlo simulation. When unset the risk
    # contributes zero to the simulated distribution; the qualitative
    # 5x5 scoring path keeps working unchanged.
    cost_p10: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    cost_p50: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    cost_p90: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    schedule_p10: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_p50: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_p90: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Snapshot of the last Monte Carlo run that touched this risk.
    # Shape:
    #   {iterations, p50_cost, p80_cost, p95_cost,
    #    p50_schedule_days, p80_schedule_days, p95_schedule_days,
    #    histogram_bins: [...], tornado: [{risk_id, code, contribution}, ...]}
    last_simulation: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<RiskItem {self.code} - {self.title[:40]} ({self.status})>"
