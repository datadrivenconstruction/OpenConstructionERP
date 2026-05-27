"""Management of Change (MoC) ORM models.

Tables:
    oe_moc_entry   — MoC header: a proposed change to engineering scope,
                     safety procedure, design or contract baseline.
    oe_moc_impact  — Impact-assessment line items attached to a MoC entry.

State machine (per OSHA PSM / ISO 55000 / IEC 61511):
    proposed  -> reviewed   (risk review completed)
    reviewed  -> accepted   (sponsor approves) | declined (sponsor rejects)
    accepted  -> implemented (work completed)
    declined  -> [terminal]
    implemented -> [terminal]
"""

import uuid
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_types import MoneyType
from app.database import GUID, Base


class MoCEntry(Base):
    """Management-of-Change entry — the change proposal header."""

    __tablename__ = "oe_moc_entry"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_oe_moc_entry_project_code"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Category of change: engineering / safety / design / contract / other
    change_category: Mapped[str] = mapped_column(String(40), nullable=False, default="engineering")
    # Risk classification: low / medium / high / critical
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    proposed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    proposed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    review_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decided_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    implemented_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    implemented_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Total cost impact of implementing this MoC (String/MoneyType, per
    # platform rule: money as Decimal-string, never float).
    cost_impact: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    # Schedule delta in days (positive = delay, negative = acceleration).
    schedule_delta_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="proposed", index=True)
    # Soft cross-module links (no DB FK — avoids circular module dependency).
    variation_request_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    variation_order_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    change_order_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    impacts: Mapped[list["MoCImpact"]] = relationship(
        back_populates="moc_entry",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<MoCEntry {self.code} ({self.status})>"


class MoCImpact(Base):
    """Impact-assessment line item on a MoC entry.

    Captures individual affected areas (safety, cost, schedule, quality,
    environment) with estimated cost and schedule deltas.
    """

    __tablename__ = "oe_moc_impact"

    moc_entry_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_moc_entry.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Area: safety / cost / schedule / quality / environment / regulatory
    impact_area: Mapped[str] = mapped_column(String(40), nullable=False, default="cost")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Severity: low / medium / high / critical
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    cost_impact: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    schedule_delta_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    mitigation: Mapped[str] = mapped_column(Text, nullable=False, default="")

    moc_entry: Mapped[MoCEntry] = relationship(back_populates="impacts")

    def __repr__(self) -> str:
        return f"<MoCImpact {self.impact_area} {self.severity}>"
