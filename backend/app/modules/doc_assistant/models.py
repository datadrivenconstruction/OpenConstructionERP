# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document assistant ORM models.

Table ``oe_doc_assistant_answer``: an answer a user chose to keep, either as
a project note or attached to an RFI draft. The citations travel with the
answer so the record stays checkable after the documents change.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class SavedAnswer(Base):
    """An assistant answer saved to a record (note or RFI draft)."""

    __tablename__ = "oe_doc_assistant_answer"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    claims: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # type: ignore[type-arg]
    citations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # type: ignore[type-arg]
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    locale: Mapped[str] = mapped_column(String(12), nullable=False, default="en")
    target_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="note")  # note | rfi
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    validation: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # type: ignore[type-arg]
