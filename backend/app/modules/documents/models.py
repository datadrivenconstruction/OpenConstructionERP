"""Document Management ORM models.

Tables:
    oe_documents_document — uploaded project documents with metadata
    oe_documents_photo   — project photo gallery with EXIF/GPS metadata
    oe_documents_sheet   — individual drawing sheets extracted from multi-page PDFs
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Document(Base):
    """Uploaded project document with metadata and categorization."""

    __tablename__ = "oe_documents_document"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="other", index=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    uploaded_by: Mapped[str] = mapped_column(String(36), nullable=False, default="")
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

    # ── Phase 17: CDE / revision-chain fields (all nullable for backward compat) ──
    cde_state: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default=None,
    )  # wip / shared / published / archived
    suitability_code: Mapped[str | None] = mapped_column(
        String(10), nullable=True, default=None,
    )  # S0-S5
    revision_code: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default=None,
    )  # P.01.01 / C.01
    drawing_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True, default=None,
    )
    is_current_revision: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=True,
    )
    parent_document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_documents_document.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    security_classification: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default=None,
    )
    discipline: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default=None,
    )  # architectural / structural / mechanical / electrical / plumbing / civil

    def __repr__(self) -> str:
        return f"<Document {self.name} ({self.category})>"


class ProjectPhoto(Base):
    """Project photo with EXIF/GPS metadata for site documentation gallery."""

    __tablename__ = "oe_documents_photo"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    gps_lon: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    tags: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="site")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_by: Mapped[str] = mapped_column(String(36), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<ProjectPhoto {self.filename} ({self.category})>"


class Sheet(Base):
    """Individual drawing sheet extracted from a multi-page PDF."""

    __tablename__ = "oe_documents_sheet"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sheet_number: Mapped[str | None] = mapped_column(String(100), nullable=True, default=None)
    sheet_title: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    discipline: Mapped[str | None] = mapped_column(String(100), nullable=True, default=None)
    revision: Mapped[str | None] = mapped_column(String(50), nullable=True, default=None)
    revision_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    scale: Mapped[str | None] = mapped_column(String(50), nullable=True, default=None)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, default=None)
    thumbnail_path: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<Sheet page={self.page_number} number={self.sheet_number}>"
