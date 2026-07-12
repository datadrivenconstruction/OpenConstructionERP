"""Plan-image record — one row per uploaded floor-plan image (the source for
the Gemini-vision extract step).

The image bytes themselves live in object storage (``storage_key``); this row
is the metadata the extract endpoint joins on. Mirrors
:class:`RenderRecord`'s shape (project-scoped, status, storage_key).
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class PlanImageRecord(Base):
    """A single uploaded floor-plan image tied to a project."""

    __tablename__ = "oe_acap_plan_image"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")

    def __repr__(self) -> str:
        return f"<PlanImageRecord project={self.project_id} [{self.status}] {self.filename}>"