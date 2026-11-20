"""Brief tables: the current ``ddc-brief/1`` per project and every saved version of it."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class DesignBrief(Base):
    """Head row; ``id`` is the document's ``brief_id``, ``version`` its latest version."""

    __tablename__ = "oe_design_brief"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[dict] = mapped_column(JSON, nullable=False)  # type: ignore[assignment]
    updated_by: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)


class DesignBriefVersion(Base):
    """Immutable copy of each version, so a revision can name the brief it was generated from."""

    __tablename__ = "oe_design_brief_version"
    __table_args__ = (UniqueConstraint("brief_id", "version", name="uq_design_brief_version"),)

    brief_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_design_brief.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)  # save | confirm
    document: Mapped[dict] = mapped_column(JSON, nullable=False)  # type: ignore[assignment]
    saved_by: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
