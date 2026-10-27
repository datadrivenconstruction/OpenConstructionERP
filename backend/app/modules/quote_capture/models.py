# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quote​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ capture ORM model.

Tables:
    oe_quote_capture_quote - one uploaded supplier or subcontractor quote: the
                             stored document, the extracted header, lines and
                             flagged conditions (each value with its confidence,
                             source anchor and the machine's own reading), the
                             review state and, once confirmed, where it went.

``package_id`` and ``boq_id`` are soft links (no foreign key), like the other
registers, so deleting a tender package never cascades into captured quotes.
"""

import uuid

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class CapturedQuote(Base):
    """One supplier quote captured for review, levelling and confirmation."""

    __tablename__ = "oe_quote_capture_quote"
    __table_args__ = (
        Index("ix_quote_capture_project_status", "project_id", "status"),
        Index("ix_quote_capture_package", "package_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    package_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    boq_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    supplier_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="text", server_default="text")
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    extraction_engine: Mapped[str] = mapped_column(String(20), nullable=False, default="rules", server_default="rules")
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    quote_total: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    header: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    lines: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    notes: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    document: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    confirmation: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    document_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<CapturedQuote {self.supplier_name} ({self.status})>"
