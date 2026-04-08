"""Change Order ORM models.

Tables:
    oe_changeorders_order — change order header with status, cost/schedule impact
    oe_changeorders_item  — individual line items within a change order
"""

import uuid

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class ChangeOrder(Base):
    """Change order tracking scope changes during project execution."""

    __tablename__ = "oe_changeorders_order"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reason_category: Mapped[str] = mapped_column(String(50), nullable=False, default="client_request")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    submitted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    submitted_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    approved_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cost_impact: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    schedule_impact_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")

    # Variation fields (Phase 16 enhancement)
    variation_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cost_basis: Mapped[str | None] = mapped_column(String(50), nullable=True)
    contractor_submission_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contractor_amount: Mapped[str | None] = mapped_column(String(50), nullable=True)
    engineer_amount: Mapped[str | None] = mapped_column(String(50), nullable=True)
    approved_amount: Mapped[str | None] = mapped_column(String(50), nullable=True)
    time_impact_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    items: Mapped[list["ChangeOrderItem"]] = relationship(
        back_populates="change_order",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ChangeOrderItem.sort_order",
    )

    def __repr__(self) -> str:
        return f"<ChangeOrder {self.code} — {self.title[:40]} ({self.status})>"


class ChangeOrderItem(Base):
    """Individual line item within a change order."""

    __tablename__ = "oe_changeorders_item"

    change_order_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_changeorders_order.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    change_type: Mapped[str] = mapped_column(String(50), nullable=False, default="modified")
    original_quantity: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    new_quantity: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    original_rate: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    new_rate: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    cost_delta: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    change_order: Mapped[ChangeOrder] = relationship(back_populates="items")

    def __repr__(self) -> str:
        return f"<ChangeOrderItem {self.description[:40]} ({self.change_type})>"
