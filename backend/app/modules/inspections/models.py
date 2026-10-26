# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Inspections ORM models.

Tables:
    oe_inspections_inspection - quality inspections with checklists and pass/fail results
"""

import uuid

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class QualityInspection(Base):
    """A quality inspection record with checklist and pass/fail result."""

    __tablename__ = "oe_inspections_inspection"
    __table_args__ = (
        Index(
            "ix_oe_inspections_inspection_project_type",
            "project_id",
            "inspection_type",
        ),
        # Per-project uniqueness of the human-facing INS-NNN number. COUNT+1
        # numbering races under concurrent creates; this constraint forces a
        # retry instead of a duplicate.
        UniqueConstraint(
            "project_id",
            "inspection_number",
            name="uq_oe_inspections_inspection_project_number",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    inspection_number: Mapped[str] = mapped_column(String(20), nullable=False)
    inspection_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    wbs_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    inspector_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    inspection_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="scheduled", index=True)
    result: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Checklist: [{id, category, question, response_type, response, notes, critical}]
    checklist_data: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # ── Geo binding (cross-module) ────────────────────────────────────────
    # Capture-time WGS84 pin so an inspection raised in the field renders on the
    # project's Geo Hub map. Mirrors punchlist ``geo_lat``/``geo_lon`` exactly.
    # Nullable + no server_default - absent means "no map pin", not "(0, 0)".
    geo_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    geo_lon: Mapped[float | None] = mapped_column(Float, nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Optimistic-lock counter for offline sync (see app.core.optimistic_lock).
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    def __repr__(self) -> str:
        return f"<QualityInspection {self.inspection_number} ({self.inspection_type}/{self.status})>"
