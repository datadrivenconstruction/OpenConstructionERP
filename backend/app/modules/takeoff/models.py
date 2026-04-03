"""Takeoff ORM models.

Tables:
    oe_takeoff_document — uploaded PDF documents for quantity takeoff
"""

import uuid

from sqlalchemy import Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


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
