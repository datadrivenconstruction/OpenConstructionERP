"""‌⁠‍Daily Site Diary ORM models.

Tables (all prefixed ``oe_daily_diary_``):
    oe_daily_diary_diary               — daily diary header with status/sign-off
    oe_daily_diary_weather             — granular weather records (Open-Meteo/manual/sensor)
    oe_daily_diary_entry               — visitor/event/delivery/completion/etc. entries
    oe_daily_diary_photo               — geo-tagged site photos and 360° captures
    oe_daily_diary_video               — site videos
    oe_daily_diary_drone_survey        — drone flights with ortho/DSM/point-cloud refs
    oe_daily_diary_reality_capture     — laser scans / photogrammetry / mobile scans
    oe_daily_diary_archive_signature   — immutable hash + signer payload

The ``source_ref``, ``linked_bim_model_ref`` and ``pdf_export_ref`` columns
are plain GUIDs **without** an SQLAlchemy ForeignKey: they reference rows
that live in modules we don't directly depend on (HSE, procurement, BIM
hub, generated PDF artefacts). The Alembic migration enforces the
referential cleanup boundaries instead.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class DailyDiary(Base):
    """‌⁠‍Daily site diary header — one per project per calendar day."""

    __tablename__ = "oe_daily_diary_diary"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "diary_date",
            name="uq_oe_daily_diary_diary_project_date",
        ),
        Index(
            "ix_oe_daily_diary_diary_project_status",
            "project_id",
            "status",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    diary_date: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    site_supervisor_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    weather_summary: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    labour_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    equipment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    owner_signature_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supervisor_signature_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # pdf_export_ref is a plain GUID — points at a generated PDF artefact in
    # the documents module, but we don't enforce a hard FK here.
    pdf_export_ref: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<DailyDiary {self.diary_date} ({self.status})>"


class WeatherRecord(Base):
    """‌⁠‍Granular weather record. Multiple per day per project."""

    __tablename__ = "oe_daily_diary_weather"
    __table_args__ = (
        Index(
            "ix_oe_daily_diary_weather_project_time",
            "project_id",
            "captured_at",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    captured_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")  # open_meteo / manual / sensor
    temperature_c: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    humidity_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    wind_speed_kmh: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    precipitation_mm: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    conditions_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    conditions_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sunrise: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sunset: Mapped[str | None] = mapped_column(String(40), nullable=True)
    location_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<WeatherRecord {self.captured_at} {self.source}>"


class DiaryEntry(Base):
    """A single diary entry — visitor, event, delivery, completion, etc."""

    __tablename__ = "oe_daily_diary_entry"
    __table_args__ = (
        Index(
            "ix_oe_daily_diary_entry_diary_type",
            "diary_id",
            "entry_type",
        ),
        Index(
            "ix_oe_daily_diary_entry_source",
            "source_module",
            "source_ref",
        ),
    )

    diary_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_daily_diary_diary.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entry_time: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_module: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # source_ref points at an upstream record (incident/inspection/PO/...);
    # plain GUID — no FK because we don't depend on those modules.
    source_ref: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    photo_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<DiaryEntry {self.entry_type} {self.title[:40]!r}>"


class DiaryPhoto(Base):
    """A geo-tagged site photo. May predate the diary it belongs to."""

    __tablename__ = "oe_daily_diary_photo"
    __table_args__ = (
        Index(
            "ix_oe_daily_diary_photo_project_taken_at",
            "project_id",
            "taken_at",
        ),
    )

    diary_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_daily_diary_diary.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    taken_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    photographer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(80), nullable=False, default="image/jpeg")
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    is_360: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_drone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<DiaryPhoto {self.taken_at} {self.file_url[:40]!r}>"


class DiaryVideo(Base):
    """A site video."""

    __tablename__ = "oe_daily_diary_video"
    __table_args__ = (
        Index(
            "ix_oe_daily_diary_video_project_recorded_at",
            "project_id",
            "recorded_at",
        ),
    )

    diary_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_daily_diary_diary.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recorded_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)
    file_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<DiaryVideo {self.recorded_at}>"


class DroneSurvey(Base):
    """A single drone survey flight."""

    __tablename__ = "oe_daily_diary_drone_survey"
    __table_args__ = (
        Index(
            "ix_oe_daily_diary_drone_survey_project_flown_at",
            "project_id",
            "flown_at",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flown_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)
    pilot_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    drone_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    area_m2: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    ortho_file_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    dsm_file_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    point_cloud_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    elevation_min_m: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    elevation_max_m: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<DroneSurvey {self.flown_at} {self.drone_model or ''}>"


class RealityCaptureDataset(Base):
    """Reality-capture dataset — laser scan, photogrammetry, or mobile scan."""

    __tablename__ = "oe_daily_diary_reality_capture"
    __table_args__ = (
        Index(
            "ix_oe_daily_diary_reality_capture_project_captured_at",
            "project_id",
            "captured_at",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    captured_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)
    capture_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="laser_scan"
    )  # laser_scan / photogrammetry / mobile_scan
    file_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    point_count_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_min: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )
    bbox_max: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )
    accuracy_mm: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # linked_bim_model_ref points at oe_bim_*; plain GUID, no FK.
    linked_bim_model_ref: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<RealityCaptureDataset {self.capture_type} {self.captured_at}>"


class DiaryArchiveSignature(Base):
    """Immutable archive signature for a closed/signed diary.

    The SHA-256 hash freezes the on-the-record contents at sign time;
    any subsequent edit can be detected via
    :func:`app.modules.daily_diary.service.validate_diary_immutability`.
    """

    __tablename__ = "oe_daily_diary_archive_signature"
    __table_args__ = (UniqueConstraint("diary_id", name="uq_oe_daily_diary_archive_signature_diary"),)

    diary_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_daily_diary_diary.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signed_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)
    signed_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    signature_payload: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    def __repr__(self) -> str:
        return f"<DiaryArchiveSignature diary={self.diary_id} rev={self.revision} sha={self.content_sha256[:8]}>"
