"""CDE (Common Data Environment) ORM models.

Tables:
    oe_cde_container — ISO 19650 document containers
    oe_cde_revision  — document revisions within containers
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class DocumentContainer(Base):
    """An ISO 19650 document container with CDE state management."""

    __tablename__ = "oe_cde_container"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    container_code: Mapped[str] = mapped_column(String(255), nullable=False)
    originator_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    functional_breakdown: Mapped[str | None] = mapped_column(String(50), nullable=True)
    spatial_breakdown: Mapped[str | None] = mapped_column(String(50), nullable=True)
    form_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    discipline_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sequence_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    classification_system: Mapped[str | None] = mapped_column(String(50), nullable=True)
    classification_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cde_state: Mapped[str] = mapped_column(String(50), nullable=False, default="wip", index=True)
    suitability_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    current_revision_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    security_classification: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<DocumentContainer {self.container_code} ({self.cde_state})>"


class DocumentRevision(Base):
    """A revision of a document within a CDE container."""

    __tablename__ = "oe_cde_revision"

    container_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_cde_container.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_code: Mapped[str] = mapped_column(String(20), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    is_preliminary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    approved_by: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<DocumentRevision {self.revision_code} ({self.status})>"
