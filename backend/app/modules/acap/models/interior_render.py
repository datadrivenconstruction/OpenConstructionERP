"""Interior render record — one row per generated interior render of a room.

Mirrors ``RenderRecord`` (render/models.py) with extra room_name and style columns.
The render image is saved to object storage; ``source_url`` keeps the provider's
original media URL for provenance (may expire — storage_key is the durable copy).
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class InteriorRenderRecord(Base):
    """A single interior room render tied to a project + floor-plan version."""

    __tablename__ = "oe_acap_interior_render"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    floor_plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    room_name: Mapped[str] = mapped_column(String(120), nullable=False)
    style: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_uuid: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<InteriorRenderRecord project={self.project_id} room={self.room_name} [{self.status}]>"
