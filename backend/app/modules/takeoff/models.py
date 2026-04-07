"""Takeoff ORM models.

Tables:
    oe_takeoff_document        — uploaded PDF documents for quantity takeoff
    oe_takeoff_measurement     — measurement annotations (distance, area, count, etc.)
    oe_takeoff_cad_session     — persistent CAD extraction sessions (replaces in-memory cache)
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class CadExtractionSession(Base):
    """Persistent storage for CAD file extraction sessions.

    Replaces the in-memory ``_cad_sessions`` dict to survive server restarts
    and support multi-process deployments.  Sessions expire after 24 hours.
    """

    __tablename__ = "oe_takeoff_cad_session"

    session_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), default="")
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_format: Mapped[str] = mapped_column(String(20), nullable=False)  # rvt, ifc, dwg, dgn
    element_count: Mapped[int] = mapped_column(Integer, default=0)
    extraction_time: Mapped[float] = mapped_column(Float, default=0)
    elements_data: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    columns_metadata: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    project_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_permanent: Mapped[bool] = mapped_column(default=False, server_default="0")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="")

    # Phase 17: session lifetime & BIM linkage
    session_ttl_days: Mapped[int | None] = mapped_column(Integer, nullable=True, default=7)
    is_persistent: Mapped[bool] = mapped_column(default=False, server_default="0")
    bim_model_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)

    def __repr__(self) -> str:
        return f"<CadExtractionSession {self.session_id} ({self.filename})>"


class TakeoffDocument(Base):
    """Uploaded PDF document for quantity takeoff."""

    __tablename__ = "oe_takeoff_document"

    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False, default="application/pdf")
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="uploaded"
    )  # uploaded | analyzing | analyzed | error
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Path to the stored PDF file on disk (for viewing/download)
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True, default=None)
    # Extracted text content from PDF (plain text for AI analysis)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Per-page data: [{ page: 1, text: "...", tables: [...] }, ...]
    page_data: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    # Analysis results from AI
    analysis: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<TakeoffDocument {self.filename} ({self.status})>"


class TakeoffMeasurement(Base):
    """Measurement annotation created during quantity takeoff.

    Stores geometric measurements (distance, area, count, polyline, volume)
    drawn on PDF pages, with optional links to BOQ positions and scale info.
    """

    __tablename__ = "oe_takeoff_measurement"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # distance, area, count, polyline, volume
    group_name: Mapped[str] = mapped_column(String(100), nullable=False, default="General")
    group_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#3B82F6")
    annotation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    points: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )  # [{x, y}, ...]
    measurement_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    measurement_unit: Mapped[str] = mapped_column(String(20), nullable=False, default="m")
    depth: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    perimeter: Mapped[float | None] = mapped_column(Float, nullable=True)
    count_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scale_pixels_per_unit: Mapped[float | None] = mapped_column(Float, nullable=True)
    linked_boq_position_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<TakeoffMeasurement {self.type} group={self.group_name} page={self.page}>"
