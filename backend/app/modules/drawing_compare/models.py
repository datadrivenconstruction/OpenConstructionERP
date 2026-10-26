# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Drawing revision compare ORM models.

Tables:
    oe_drawing_compare_comparison - one compare of two revisions of a drawing
    oe_drawing_compare_change     - one changed region found by that compare

Both revisions are referenced by id strings, not foreign keys: a PDF side is a
takeoff document (or a documents-hub row), a DWG side a parsed drawing
version, and those live in modules that may be absent. A compare outlives a
deleted revision as a record of what changed.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base

SOURCE_KINDS: tuple[str, ...] = ("pdf", "dwg")
CHANGE_KINDS: tuple[str, ...] = ("added", "removed", "modified", "text")
CHANGE_STATUSES: tuple[str, ...] = ("open", "relevant", "not_relevant")
ALIGNMENT_METHODS: tuple[str, ...] = ("none", "auto", "manual")


class DrawingComparison(Base):
    """A stored compare of an older and a newer revision of one drawing.

    ``alignment`` holds ``{method, matrix: [a, b, c, d, e, f], confidence,
    points_old, points_new}``; the matrix maps the old sheet onto the new one
    in PDF units (identity for DWG, whose revisions share drawing units).
    ``summary`` is the count per change kind written when the compare is saved.
    """

    __tablename__ = "oe_drawing_compare_comparison"
    __table_args__ = (Index("ix_drawing_compare_refs", "project_id", "old_ref_id", "new_ref_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_kind: Mapped[str] = mapped_column(String(8), nullable=False, default="pdf")
    old_ref_id: Mapped[str] = mapped_column(String(64), nullable=False)
    new_ref_id: Mapped[str] = mapped_column(String(64), nullable=False)
    old_page: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    new_page: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    old_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    new_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    old_revision: Mapped[str | None] = mapped_column(String(50), nullable=True, default=None)
    new_revision: Mapped[str | None] = mapped_column(String(50), nullable=True, default=None)
    page_width: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    page_height: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    alignment: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    settings: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    summary: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    created_by: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    changes: Mapped[list[DrawingChange]] = relationship(
        back_populates="comparison",
        cascade="all, delete-orphan",
        order_by="DrawingChange.seq",
        lazy="raise_on_sql",
    )

    def __repr__(self) -> str:
        return f"<DrawingComparison {self.source_kind} {self.old_ref_id} -> {self.new_ref_id}>"


class DrawingChange(Base):
    """One changed region: where it is, what kind of change, what was done about it.

    ``x``/``y``/``w``/``h`` are in the newer revision's frame (PDF units with a
    top-left origin on page ``page``; drawing units for DWG). ``status`` is the
    reviewer's call; ``rfi_id`` / ``markup_id`` point at what was raised from
    the change; the ``flagged_*`` lists record which takeoff measurements, DWG
    annotations and BOQ positions were marked for re-measure.
    """

    __tablename__ = "oe_drawing_compare_change"

    comparison_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_drawing_compare_comparison.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    x: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    y: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    w: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    h: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    score: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    old_text: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    new_text: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    layer: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    details: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    thumbnail: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", server_default="open")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    rfi_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    markup_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    flagged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    flagged_measurement_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    flagged_annotation_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    flagged_position_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)

    comparison: Mapped[DrawingComparison] = relationship(back_populates="changes", lazy="raise_on_sql")

    def __repr__(self) -> str:
        return f"<DrawingChange #{self.seq} {self.kind} ({self.status})>"
