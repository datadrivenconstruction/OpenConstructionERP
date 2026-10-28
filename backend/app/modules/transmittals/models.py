# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Transmittals ORM models.

Tables:
    oe_transmittals_transmittal - formal document transmittal
    oe_transmittals_recipient   - recipient with acknowledgement/response tracking
    oe_transmittals_item        - line items (documents) within a transmittal
"""

import uuid

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class Transmittal(Base):
    """A formal document transmittal package."""

    __tablename__ = "oe_transmittals_transmittal"
    # ``(project_id, transmittal_number)`` must be unique so concurrent
    # ``create_transmittal`` calls racing on ``max(transmittal_number)+1``
    # get a clean :class:`IntegrityError` the service can retry, rather than
    # quietly writing two TR-007 rows in the same project. Mirrors the
    # rfi ``uq_rfi_project_number`` / file_transmittals
    # ``uq_oe_file_transmittal_project_id_number`` pattern.
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "transmittal_number",
            name="uq_oe_transmittals_project_id_number",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    transmittal_number: Mapped[str] = mapped_column(String(50), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    sender_org_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    purpose_code: Mapped[str] = mapped_column(String(50), nullable=False)
    issued_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    response_due_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="draft",
        server_default="draft",
        index=True,
    )
    cover_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    recipients: Mapped[list["TransmittalRecipient"]] = relationship(
        back_populates="transmittal",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    items: Mapped[list["TransmittalItem"]] = relationship(
        back_populates="transmittal",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Transmittal {self.transmittal_number} ({self.status})>"


class TransmittalRecipient(Base):
    """A recipient of a transmittal with acknowledgement and response tracking."""

    __tablename__ = "oe_transmittals_recipient"

    transmittal_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_transmittals_transmittal.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_org_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Free-text identity for a recipient who is not a system user or a stored
    # contact - the common case for a transmittal, which is often sent to an
    # external party by name and email. Either or both may be set; a recipient
    # can also carry only recipient_org_id / recipient_user_id when picked from
    # contacts. At least one of these four is expected, but none is enforced so
    # a bare "to be filled in" row can still be created on a draft.
    recipient_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    action_required: Mapped[str | None] = mapped_column(String(100), nullable=True)
    acknowledged_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    transmittal: Mapped[Transmittal] = relationship(back_populates="recipients")

    def __repr__(self) -> str:
        return f"<TransmittalRecipient {self.id} for transmittal={self.transmittal_id}>"


class TransmittalItem(Base):
    """A line item (document reference) within a transmittal."""

    __tablename__ = "oe_transmittals_item"

    transmittal_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_transmittals_transmittal.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Cross-link to a specific CDE document revision when the item was picked
    # from the CDE container browser. ``document_id`` and ``revision_id`` are
    # not mutually exclusive - when both are set, ``revision_id`` is the
    # authoritative reference; ``document_id`` remains for free-form attachments.
    revision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    item_number: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    transmittal: Mapped[Transmittal] = relationship(back_populates="items")

    def __repr__(self) -> str:
        return f"<TransmittalItem #{self.item_number} in transmittal={self.transmittal_id}>"
