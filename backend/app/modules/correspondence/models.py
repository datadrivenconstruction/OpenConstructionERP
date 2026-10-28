# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Correspondence ORM models.

Tables:
    oe_correspondence_correspondence - project correspondence with direction and contact tracking
"""

import uuid

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Correspondence(Base):
    """One entry in a project's correspondence register, typed by ``CORRESPONDENCE_TYPES``."""

    __tablename__ = "oe_correspondence_correspondence"
    # ``reference_number`` must be unique per project - the auto-generator
    # uses ``MAX(suffix)+1`` which has a TOCTOU race under concurrent
    # creates; without this constraint two parallel POSTs would silently
    # persist ``COR-005`` twice. With the constraint the second commit
    # raises ``IntegrityError`` and the service layer retries.
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "reference_number",
            name="uq_oe_correspondence_correspondence_project_reference",
        ),
    )

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

    # Lifecycle + legal-deadline tracking. A correspondence record, and above
    # all a formal notice, often carries a contractual response deadline; with
    # only CRUD fields the register could not tell an open notice from a closed
    # one, nor flag one whose reply window has lapsed. ``status`` is one of
    # open|awaiting_response|responded|closed; ``response_required_by`` is an ISO
    # date (yyyy-mm-dd); ``contract_clause_ref`` is a free-text clause pointer
    # (for example "NEC cl. 61.3" or "FIDIC 20.1"). is_overdue / days_until_due
    # are computed at serialisation time, never stored.
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="open",
        server_default="open",
        index=True,
    )
    response_required_by: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contract_clause_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Stored attachment paths (validated magic-byte uploads). Server-derived
    # filenames only - the client never controls the path on disk, so we
    # never serve attacker-named extensions back. See router upload handler.
    attachments: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<Correspondence {self.reference_number} ({self.direction}/{self.correspondence_type})>"
