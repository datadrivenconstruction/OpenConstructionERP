"""‌⁠‍Change Order ORM models.

Tables:
    oe_changeorders_order   - change order header with status, cost/schedule impact
    oe_changeorders_item    - individual line items within a change order
    oe_changeorder_approval - ordered per-approver decisions (construction management platform style chain)
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_types import MoneyType
from app.database import GUID, Base


class ChangeOrder(Base):
    """‌⁠‍Change order tracking scope changes during project execution."""

    __tablename__ = "oe_changeorders_order"
    # BUG-354: ``(project_id, code)`` must be unique so that concurrent
    # creators racing on ``count + 1`` get a clean IntegrityError the
    # service can retry, rather than quietly writing duplicate codes.
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_changeorders_project_code"),)

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
    # BUG-351: rejection populates its own fields - previously ``approved_by``
    # was reused on reject, which made UIs show the rejector as the approver.
    rejected_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # ISO-8601 timestamp strings ("2026-05-30T16:33:01.947702+00:00" = 32 chars).
    # Width must hold microseconds + offset: String(20) silently overflowed on
    # PostgreSQL ("value too long for character varying(20)") while SQLite ignored
    # the limit. String(40) leaves margin for any offset form.
    submitted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    approved_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rejected_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Phase 2e: signed money column (scope changes can be negative on credits).
    cost_impact: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    schedule_impact_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Platform rule (task #217, the architecture guide): NO model-/DB-level hardcoded
    # currency. The column defaults to empty string; the service layer is
    # responsible for resolving and stamping the project's currency on
    # create so a non-Eurozone project never silently inherits "EUR".
    currency: Mapped[str] = mapped_column(String(10), nullable=False, server_default="", default="")

    # Variation fields (Phase 16 enhancement)
    variation_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cost_basis: Mapped[str | None] = mapped_column(String(50), nullable=True)
    contractor_submission_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    contractor_amount: Mapped[Decimal | None] = mapped_column(MoneyType(), nullable=True)
    engineer_amount: Mapped[Decimal | None] = mapped_column(MoneyType(), nullable=True)
    approved_amount: Mapped[Decimal | None] = mapped_column(MoneyType(), nullable=True)
    time_impact_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # T3: construction management platform style commitment / RFI links. Stored as JSON arrays of
    # UUID strings rather than association tables - the cardinality is
    # tiny (typically <10 entries per CO) and the data is read-heavy /
    # display-only, so the indirection isn't worth a join. The column is
    # nullable for backward compat with COs created before v3082; the
    # service / API layer normalises ``None`` to ``[]`` on read.
    linked_po_ids: Mapped[list | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
        default=list,
        server_default="[]",
    )
    linked_rfi_ids: Mapped[list | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
        default=list,
        server_default="[]",
    )
    # Cursor into ``approvals`` - points at the active ``step_order`` of
    # the in-flight chain. ``None`` means no chain has been started (a
    # legacy CO using the single-step ``approve`` endpoint). Indexed so
    # "pending my approval" boards can scan it cheaply without joining
    # the approval table.
    current_approval_step: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )

    # Relationships
    items: Mapped[list["ChangeOrderItem"]] = relationship(
        back_populates="change_order",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ChangeOrderItem.sort_order",
    )
    approvals: Mapped[list["ChangeOrderApproval"]] = relationship(
        back_populates="change_order",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ChangeOrderApproval.step_order",
    )

    def __repr__(self) -> str:
        return f"<ChangeOrder {self.code} - {self.title[:40]} ({self.status})>"


class ChangeOrderItem(Base):
    """‌⁠‍Individual line item within a change order."""

    __tablename__ = "oe_changeorders_item"

    change_order_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_changeorders_order.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    change_type: Mapped[str] = mapped_column(String(50), nullable=False, default="modified")
    # Wider scale for quantities / rates so "1.234567 units @ €12.50/unit"
    # doesn't lose precision on round-trip. PG type: NUMERIC(18, 6).
    original_quantity: Mapped[Decimal] = mapped_column(MoneyType(scale=6), nullable=False, default=Decimal("0"))
    new_quantity: Mapped[Decimal] = mapped_column(MoneyType(scale=6), nullable=False, default=Decimal("0"))
    original_rate: Mapped[Decimal] = mapped_column(MoneyType(scale=6), nullable=False, default=Decimal("0"))
    new_rate: Mapped[Decimal] = mapped_column(MoneyType(scale=6), nullable=False, default=Decimal("0"))
    cost_delta: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
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


# Per-step decision vocabulary for a construction management platform style approval chain.
APPROVAL_DECISIONS: tuple[str, ...] = ("pending", "approved", "rejected")


class ChangeOrderApproval(Base):
    """‌⁠‍One ordered step in a change order's multi-approver chain.

    A change order's chain is a list of these rows keyed by ``step_order``
    (1, 2, 3, …). The :class:`ChangeOrder` carries a ``current_approval_step``
    cursor pointing at the row that is currently in ``pending`` and is
    expected to act next; the service advances the cursor on each
    ``approve`` decision and short-circuits the chain on a ``reject``.

    The FK to ``oe_users_user`` is ``SET NULL`` rather than ``CASCADE``
    because we want the audit trail of who decided what to survive a
    user being removed - the row becomes "decision recorded, decider
    deleted" instead of vanishing.
    """

    __tablename__ = "oe_changeorder_approval"
    __table_args__ = (
        UniqueConstraint(
            "change_order_id",
            "step_order",
            name="uq_oe_changeorder_approval_change_order_id_step_order",
        ),
    )

    change_order_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_changeorders_order.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decision: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    # Relationships
    change_order: Mapped[ChangeOrder] = relationship(back_populates="approvals")

    def __repr__(self) -> str:
        return f"<ChangeOrderApproval step={self.step_order} approver={self.approver_user_id} decision={self.decision}>"
