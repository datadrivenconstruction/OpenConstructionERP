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
    oe_survey_traverse - a closed traverse or a level run with its misclosure
        and the profile verdict it got when it was computed.
    oe_survey_profile - survey thresholds: one row per project, or the
        workspace default (project_id NULL). No core default value exists;
        demo and pack rows carry a label saying where the numbers come from.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text
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
    # How a computed point was made (inverse, polar, bearing_bearing, traverse, ...); "" = measured.
    method: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    # The inputs of that computation, kept for the audit trail.
    inputs: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class SurveyTraverse(Base):
    """A closed traverse (or, with ``kind='level'``, a level run) and its closure."""

    __tablename__ = "oe_survey_traverse"
    __table_args__ = (Index("ix_oe_survey_traverse_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # traverse | level
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="traverse", server_default="traverse")
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="bowditch", server_default="bowditch")
    # [{"leg", "from", "to", "length_m", "d_e", "d_n"}] as measured
    legs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # type: ignore[assignment]
    length_m: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=0)
    f_e: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    f_n: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    misclosure_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    ratio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profile_ratio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    misclosure_mm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    k_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    allowed_mm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # pass | fail | no_profile
    verdict: Mapped[str] = mapped_column(String(20), nullable=False, default="no_profile", server_default="no_profile")
    profile_label: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Field traverse: angular misclosure (seconds), the k of k*sqrt(n) and its allowance.
    angle_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ang_misclosure_sec: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    ang_k_sec: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    ang_allowed_sec: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # Field observations and the reduction (stations or level book rows, arithmetic check).
    observations: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class SurveyProfile(Base):
    """Survey thresholds for one project, or the workspace default when ``project_id`` is NULL."""

    __tablename__ = "oe_survey_profile"
    __table_args__ = (Index("ix_oe_survey_profile_project", "project_id"),)

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=True
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # user | demo | pack
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user", server_default="user")
    traverse_min_ratio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level_k_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    coverage_min_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    angular_k_sec: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
