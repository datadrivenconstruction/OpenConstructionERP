"""Correspondence ORM models.

Tables:
    oe_correspondence_correspondence — project correspondence with direction and contact tracking
"""

import uuid

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Correspondence(Base):
    """A project correspondence record (letter, email, notice)."""

    __tablename__ = "oe_correspondence_correspondence"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reference_number: Mapped[str] = mapped_column(String(50), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    from_contact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # To contact IDs: array of contact UUID strings
    to_contact_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    date_sent: Mapped[str | None] = mapped_column(String(20), nullable=True)
    date_received: Mapped[str | None] = mapped_column(String(20), nullable=True)
    correspondence_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Linked document IDs: array of document UUID strings
    linked_document_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    linked_transmittal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    linked_rfi_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return (
            f"<Correspondence {self.reference_number} "
            f"({self.direction}/{self.correspondence_type})>"
        )
