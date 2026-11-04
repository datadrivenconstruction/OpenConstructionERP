# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Lessons learned ORM model.

Tables:
    oe_lessons_learned_lesson - one lesson from one project: what happened, what to do next time, and the
                                three tags (trade, cost code, risk category) other projects are matched by.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Lesson(Base):
    """One lesson learned, captured at closeout and confirmed by a manager."""

    __tablename__ = "oe_lessons_learned_lesson"
    __table_args__ = (
        Index("ix_lessons_learned_project_status", "project_id", "status"),
        Index("ix_lessons_learned_trade", "trade"),
        Index("ix_lessons_learned_risk_category", "risk_category"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    recommendation: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    trade: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    cost_code: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    risk_category: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")
    impact: Mapped[str] = mapped_column(String(10), nullable=False, default="medium", server_default="medium")
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft", server_default="draft")
    confirmed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<Lesson {self.title} ({self.status})>"
