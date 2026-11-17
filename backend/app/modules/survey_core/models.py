# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Survey register ORM models.

Tables:
    oe_survey_project_crs - the coordinate system ONE project's survey data is in.
        Horizontal EPSG or a local grid, heights same-as-source or a vertical
        EPSG, and who confirmed it. A detected CRS stays unconfirmed until a
        person confirms it (SRV-002).
    oe_survey_point_set - one imported point file: source file, format,
        instrument, survey date, and the EPSG its coordinates were read in.
    oe_survey_point - one point of a set, stored in the project CRS.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class SurveyProjectCrs(Base):
    """The coordinate system a project's survey data is stored in."""

    __tablename__ = "oe_survey_project_crs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    horizontal_epsg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    horizontal_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # same_as_source | epsg
    vertical_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="same_as_source", server_default="same_as_source"
    )
    vertical_epsg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_local_grid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    local_origin_e: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    local_origin_n: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    local_rotation_deg: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    local_scale_factor: Mapped[Decimal | None] = mapped_column(Numeric(12, 10), nullable=True)
    # user | detected
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user", server_default="user")
    detected_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SurveyPointSet(Base):
    """One imported point file."""

    __tablename__ = "oe_survey_point_set"
    __table_args__ = (Index("ix_oe_survey_point_set_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # csv | txt | geojson
    file_format: Mapped[str] = mapped_column(String(20), nullable=False, default="csv", server_default="csv")
    column_preset: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    instrument: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    surveyed_by: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    survey_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # EPSG the file's coordinates were written in; NULL = the project CRS at import time.
    source_epsg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # EPSG the points are stored in; NULL = no CRS was set when the file came in (SRV-001).
    stored_epsg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transformed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    duplicate_policy: Mapped[str] = mapped_column(
        String(20), nullable=False, default="keep_first", server_default="keep_first"
    )
    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    point_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class SurveyPoint(Base):
    """One surveyed point, in the coordinate system of its set."""

    __tablename__ = "oe_survey_point"
    __table_args__ = (
        Index("ix_oe_survey_point_project_pid", "project_id", "point_id"),
        Index("ix_oe_survey_point_set", "point_set_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    point_set_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_survey_point_set.id", ondelete="CASCADE"), nullable=False
    )
    point_id: Mapped[str] = mapped_column(String(64), nullable=False)
    e: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    n: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    z: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    # control | benchmark | topo | stake | asbuilt
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="topo", server_default="topo")
    sigma: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    source_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
