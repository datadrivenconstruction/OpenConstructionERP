"""Enterprise Workflows ORM models.

Tables:
    oe_workflows_approval  — configurable approval workflow definitions
    oe_workflows_request   — individual approval requests against workflows
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class ApprovalWorkflow(Base):
    """A configurable approval workflow definition."""

    __tablename__ = "oe_workflows_approval"

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    requests: Mapped[list["ApprovalRequest"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<ApprovalWorkflow {self.name} ({self.entity_type})>"


class ApprovalRequest(Base):
    """An individual approval request submitted against a workflow."""

    __tablename__ = "oe_workflows_request"

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_workflows_approval.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    requested_by: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    decided_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    workflow: Mapped["ApprovalWorkflow"] = relationship(back_populates="requests")

    def __repr__(self) -> str:
        return f"<ApprovalRequest {self.entity_type}/{self.entity_id} ({self.status})>"
