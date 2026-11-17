# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Plan Room ORM models.

Tables:
    oe_plan_pin - a positioned photo / note pin dropped on a document page

The Plan Room composites read-only overlays (defect pins, markups, measurements
and photos) for a document page. Only the positioned photo / note pins are
owned here; every other overlay source is read from its owning module at
request time. ``project_id`` carries a real foreign key to the project so a pin
is torn down with its project; ``document_id`` is a plain string (the same
document-id string the markups / takeoff / punchlist rows store) so a pin can
point at any viewable document without a hard cross-module FK. ``x`` / ``y`` are
normalized 0..1 page coordinates (origin top-left), matching the punch-pin
convention so the two pin kinds composite onto the same overlay.
"""

import uuid

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class PlanPin(Base):
    """A positioned photo / note pin on a document page.

    ``photo_ref`` optionally points at a :class:`ProjectPhoto` id or a punch
    photo path; ``file_version_id`` records which document revision the pin was
    dropped on. ``metadata_`` is a free-form JSON bag for module-extensible
    extras.
    """

    __tablename__ = "oe_plan_pin"
    __table_args__ = (
        UniqueConstraint("project_id", "client_op_id", name="uq_plan_pin_project_client_op"),
        Index("ix_plan_pin_project_sheet", "project_id", "sheet_id"),
        Index("ix_plan_pin_target", "target_kind", "target_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # A pin has exactly one location: drawing (document_id + page + x/y) or BIM element.
    # BIM pins leave the drawing columns at their defaults.
    document_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True, default="")
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    x: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    y: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # The record this pin points at stays in its own module; the pin only references it.
    target_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="note", server_default="note")
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sheet_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    bim_model_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    bim_element_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    bim_xyz: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    revision_state: Mapped[str] = mapped_column(String(20), nullable=False, default="current", server_default="current")
    carried_from_pin_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    client_op_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<PlanPin {self.target_kind} doc={self.document_id} page={self.page} ({self.x:.3f},{self.y:.3f})>"
