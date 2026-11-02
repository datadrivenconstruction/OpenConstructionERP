# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Photos module ORM models.

The photo itself stays :class:`app.modules.documents.models.ProjectPhoto`
(``oe_documents_photo``); this module owns only what hangs off it:

    oe_photos_album          - named photo sets per project
    oe_photos_album_item     - album membership with a position
    oe_photos_link           - photo -> BOQ position / activity / punch item / ...
    oe_photos_ai_suggestion  - AI caption, tags, progress and hazard proposals
    oe_photos_compare        - saved before/after pairs

Drawing pins reuse ``oe_plan_pin`` (``photo_ref = "photo:<id>"``) and the map
reads the photo's own GPS, so neither needs a table here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Index, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

_PHOTO_FK = "oe_documents_photo.id"


class PhotoAlbum(Base):
    """A named set of photos inside one project."""

    __tablename__ = "oe_photos_album"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_oe_photos_album_project_name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    cover_photo_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey(_PHOTO_FK, ondelete="SET NULL"), nullable=True, default=None
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)


#: Album membership. A plain table with a composite key: the row has no identity of its own.
photo_album_item = Table(
    "oe_photos_album_item",
    Base.metadata,
    Column("album_id", GUID(), ForeignKey("oe_photos_album.id", ondelete="CASCADE"), primary_key=True),
    Column("photo_id", GUID(), ForeignKey(_PHOTO_FK, ondelete="CASCADE"), primary_key=True, index=True),
    Column("position", Integer, nullable=False, default=0, server_default="0"),
)


class PhotoLink(Base):
    """A photo shown as evidence on another record of the same project."""

    __tablename__ = "oe_photos_link"
    __table_args__ = (
        UniqueConstraint("photo_id", "target_kind", "target_id", name="uq_oe_photos_link_target"),
        Index("ix_oe_photos_link_target", "target_kind", "target_id"),
    )

    photo_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey(_PHOTO_FK, ondelete="CASCADE"), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)


class PhotoAISuggestion(Base):
    """One AI proposal for a photo. Nothing is applied until a person accepts it."""

    __tablename__ = "oe_photos_ai_suggestion"
    __table_args__ = (Index("ix_oe_photos_ai_suggestion_photo_kind_status", "photo_id", "kind", "status"),)

    photo_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey(_PHOTO_FK, ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # type: ignore[assignment]
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True, default=None)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)


class PhotoCompare(Base):
    """A saved before/after pair of photos."""

    __tablename__ = "oe_photos_compare"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    before_photo_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PHOTO_FK, ondelete="CASCADE"), nullable=False
    )
    after_photo_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey(_PHOTO_FK, ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
