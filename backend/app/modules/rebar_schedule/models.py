# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rebar schedule ORM models.

Tables:
    oe_rebar_schedule_import - one imported ABS file
    oe_rebar_shape           - one bending shape from that file

A shape keeps the exact source line it was parsed from in ``raw``. Two reasons:
the checksum covers those exact characters, so re-deriving the line from the
parsed columns would produce a different record; and the bending shop works
from the file, so when a discrepancy is argued later the row can be compared
against what was actually sent rather than against our reading of it.
"""

import uuid
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class RebarScheduleImport(Base):
    """One ABS file taken into a project."""

    __tablename__ = "oe_rebar_schedule_import"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # SHA-256 of the uploaded bytes. Re-importing the same file into the same
    # project is a no-op the service can recognise instead of duplicating
    # several hundred shapes.
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # The encoding the bytes were decoded with. The standard names ASCII;
    # anything else is recorded because it is a finding, not a detail.
    encoding: Mapped[str] = mapped_column(String(16), nullable=False, default="ascii", server_default="ascii")
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Sum over the file of weight per shape times number of shapes, in kg.
    total_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(16, 3), nullable=True)
    # Worst severity the validation report reached: "passed", "info",
    # "warnings" or "errors". A file that did not pass is still stored, so the
    # findings can be shown against the rows they came from.
    validation_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="passed",
        server_default="passed",
        index=True,
    )
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    shapes: Mapped[list["RebarShape"]] = relationship(
        back_populates="schedule_import",
        lazy="raise_on_sql",
        cascade="all, delete-orphan",
    )

    __table_args__ = (UniqueConstraint("project_id", "content_sha256", name="uq_rebar_import_project_content"),)

    def __repr__(self) -> str:
        return f"<RebarScheduleImport {self.filename} ({self.record_count} shapes)>"


class RebarShape(Base):
    """One bending shape: a row of the bending schedule."""

    __tablename__ = "oe_rebar_shape"

    import_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_rebar_schedule_import.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schedule_import: Mapped["RebarScheduleImport"] = relationship(
        back_populates="shapes",
        lazy="raise_on_sql",
    )
    # Denormalised from the import so a project-wide query over shapes does not
    # have to join, and so an IDOR check can be made on the row itself.
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # Super-group: BF2D, BF3D, BFWE, BFMA, BFGT or BFAU.
    super_group: Mapped[str] = mapped_column(String(4), nullable=False, index=True)

    # Header fields, named for what they mean rather than for their letter.
    project_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    drawing_ref: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    drawing_index: Mapped[str | None] = mapped_column(String(16), nullable=True)
    position: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    length_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    diameter_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    steel_grade: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bending_roller_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    mesh_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    width_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    height_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Layer, counting upwards. Drives the placing order on automated lines.
    layer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Stagger group: the marker that ties the single positions of one
    # staggered set together.
    stagger_group: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    # Geometry, read out of the geometry block into a shape a viewer can draw
    # without re-parsing: {"kind": "segments"|"coordinates"|"turns", ...}.
    geometry: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Which block identifiers the record carried, in order, e.g. "HGC".
    block_layout: Mapped[str | None] = mapped_column(String(32), nullable=True)
    checksum_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    raw: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return f"<RebarShape {self.super_group} pos={self.position} d={self.diameter_mm}>"
