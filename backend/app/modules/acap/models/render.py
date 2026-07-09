"""Visual-render record — one row per generated render of a floor-plan version.

The render is DECORATIVE: it is produced from the floor-plan JSON for human
presentation and is NEVER a source of RAB quantities (that remains the
floor-plan JSON alone). ``storage_key`` points at the image saved in the fork's
object storage (local / MinIO); ``source_url`` keeps the provider's original
media URL for provenance.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class RenderRecord(Base):
    """A single image render tied to a project + floor-plan version."""

    __tablename__ = "oe_acap_render"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    floor_plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Provider job id (GeminiGen uuid) — provenance / re-poll handle.
    provider_uuid: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Provider's original media URL (kept for provenance; may expire).
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Object-storage key of the image WE persisted (durable; served via storage).
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<RenderRecord project={self.project_id} v{self.floor_plan_version} [{self.status}]>"
