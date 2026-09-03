# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Outlook Bridge ORM models.

Tables:
    oe_outlook_bridge_message - one row per swept Outlook message.

The row is the audit trail of what the sweep saw and what it decided:
``matched`` rows carry the correspondence they were filed onto; an
``unmatched`` row waits for a person to file or ignore it - mail is never
silently dropped, because a message nobody can see is a message nobody
can answer.
"""

from sqlalchemy import JSON, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

MESSAGE_STATUSES = ("unmatched", "matched", "filed", "ignored", "outbound_copy")


class OutlookMessage(Base):
    """One message the inbox sweep captured."""

    __tablename__ = "oe_outlook_bridge_message"
    __table_args__ = (
        # Outlook's EntryID is the idempotency key: a re-swept message must
        # never double-file (same contract as inbound_capture's external id).
        UniqueConstraint("entry_id", name="uq_oe_outlook_bridge_message_entry"),
        Index("ix_outlook_bridge_status_received", "status", "received_at"),
    )

    entry_id: Mapped[str] = mapped_column(String(200), nullable=False)
    internet_message_id: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    sender_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    sender_email: Mapped[str] = mapped_column(String(300), nullable=False, default="", index=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    received_at: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    #: Plain-text body, bounded at capture time (the full message stays in
    #: Outlook; this is what matching and analysis read).
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: [{"filename": ..., "path": ...}] - saved under uploads/outlook_bridge/.
    attachments: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unmatched", server_default="unmatched", index=True
    )
    #: Why the router decided what it did - "ref RFQ-004", "sender matched
    #: supplier X on project Y", or "two candidates - held for a person".
    match_note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    correspondence_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    filed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<OutlookMessage {self.subject[:40]!r} ({self.status})>"
