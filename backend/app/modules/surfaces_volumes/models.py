# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Surfaces and volumes ORM models.

Tables:
    oe_survey_surface - a ground model (TIN) built from a point set, read from
        LandXML, or taken from a scan DTM; vertices and triangles kept inline.
    oe_survey_volume - one cut/fill calculation between two surfaces, with the
        method, cell size, coverage, confidence and who confirmed it. A
        confirmed calculation is locked; changing it means Duplicate.
    oe_survey_volume_event - the History tab: computed, confirmed, sent to BOQ,
        progress recorded, report printed, each with who and when.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class SurveySurface(Base):
    """A triangulated ground surface in the project CRS."""

    __tablename__ = "oe_survey_surface"
    __table_args__ = (Index("ix_oe_survey_surface_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # points | landxml | dtm
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="points", server_default="points")
    point_set_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("oe_survey_point_set.id", ondelete="SET NULL"), nullable=True
    )
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    epsg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # pointcloud LOA tier for scan surfaces: survey | standard | coarse
    accuracy_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    point_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    triangle_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    area_m2: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=0, server_default="0")
    z_min: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    z_max: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    # [[e, n, z], ...] and [[i, j, k], ...]
    vertices: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # type: ignore[assignment]
    faces: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # type: ignore[assignment]
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class SurveyVolume(Base):
    """A cut/fill calculation between a base and a compare surface."""

    __tablename__ = "oe_survey_volume"
    __table_args__ = (Index("ix_oe_survey_volume_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_surface_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("oe_survey_surface.id", ondelete="SET NULL"), nullable=True
    )
    compare_surface_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("oe_survey_surface.id", ondelete="SET NULL"), nullable=True
    )
    # Names as they were when computed, so a report reads the same after a rename or delete.
    base_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    compare_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # grid | tin | end_area
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="grid", server_default="grid")
    cell_size_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    cell_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    boundary: Mapped[list | None] = mapped_column(JSON, nullable=True)  # type: ignore[assignment]
    material: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    swell_factor: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=1, server_default="1")
    shrink_factor: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=1, server_default="1")
    cut_m3: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=0, server_default="0")
    fill_m3: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=0, server_default="0")
    net_m3: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=0, server_default="0")
    calc_area_m2: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=0, server_default="0")
    covered_area_m2: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=0, server_default="0")
    coverage_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0, server_default="0")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    crs_epsg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accuracy_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    heat: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[assignment]
    sections: Mapped[list | None] = mapped_column(JSON, nullable=True)  # type: ignore[assignment]
    # draft | confirmed | sent
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    confirmed_by_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged: Mapped[list | None] = mapped_column(JSON, nullable=True)  # type: ignore[assignment]
    override_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    duplicated_from_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class SurveyVolumeEvent(Base):
    """One line of a calculation's history."""

    __tablename__ = "oe_survey_volume_event"
    __table_args__ = (Index("ix_oe_survey_volume_event_volume", "volume_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    volume_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_survey_volume.id", ondelete="CASCADE"), nullable=False
    )
    # computed | confirmed | override | sent_boq | progress | duplicated | report
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    target_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(16, 3), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # type: ignore[assignment]
    user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    user_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
