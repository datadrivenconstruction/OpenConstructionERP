# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Transmittals ORM models (Wave W7).

Tables
------
* ``oe_file_transmittal`` — header row (one per outgoing transmittal).
* ``oe_file_transmittal_item`` — files included in the transmittal
  (polymorphic ``file_kind`` + ``file_id`` reference, matching the
  existing ``file_versions`` convention).
* ``oe_file_transmittal_recipient`` — recipient email + ack token.

Numbering
~~~~~~~~~
``number`` is allocated by the service on create. The service holds a
row-lock on the project + queries ``MAX(number)`` to pick the next
``T-NNNN`` slug; the ``Unique(project_id, number)`` constraint is the
final safety net against double-allocation.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base

# Canonical set of "reason" codes the wizard surfaces. Open ``String(32)``
# in the DB so a future code (e.g. ``for_tender``) does not require a
# migration; this tuple is the API-surface whitelist used by the schema.
TRANSMITTAL_REASONS: tuple[str, ...] = (
    "for_review",
    "for_construction",
    "for_approval",
    "for_information",
    "for_record",
)

# Lifecycle states. ``draft`` → ``sent`` is the only forward edge from
# user action; ``acknowledged`` / ``rejected`` flip on recipient response.
TRANSMITTAL_STATUSES: tuple[str, ...] = (
    "draft",
    "sent",
    "acknowledged",
    "rejected",
)


class FileTransmittal(Base):
    """One outgoing transmittal — header + relations to items + recipients."""

    __tablename__ = "oe_file_transmittal"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "number",
            name="uq_oe_file_transmittal_project_id_number",
        ),
        Index("ix_oe_file_transmittal_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    sender_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="sent", server_default="sent")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    cover_sheet_path: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)

    items: Mapped[list[FileTransmittalItem]] = relationship(
        "FileTransmittalItem",
        back_populates="transmittal",
        cascade="all, delete-orphan",
        order_by="FileTransmittalItem.sort_order",
    )
    recipients: Mapped[list[FileTransmittalRecipient]] = relationship(
        "FileTransmittalRecipient",
        back_populates="transmittal",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<FileTransmittal {self.number} '{self.subject}' ({self.status}, project={self.project_id})>"


class FileTransmittalItem(Base):
    """One file inside a transmittal — snapshots canonical_name + version."""

    __tablename__ = "oe_file_transmittal_item"
    __table_args__ = (
        Index(
            "ix_oe_file_transmittal_item_transmittal_id",
            "transmittal_id",
        ),
    )

    transmittal_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_file_transmittal.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    file_id: Mapped[str] = mapped_column(String(64), nullable=False)
    file_version_snapshot: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    canonical_name_snapshot: Mapped[str] = mapped_column(String(512), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    transmittal: Mapped[FileTransmittal] = relationship("FileTransmittal", back_populates="items")


class FileTransmittalRecipient(Base):
    """One recipient of a transmittal — email + ack state."""

    __tablename__ = "oe_file_transmittal_recipient"
    __table_args__ = (
        UniqueConstraint(
            "transmittal_id",
            "email",
            name="uq_oe_file_transmittal_recipient_transmittal_id_email",
        ),
        Index(
            "ix_oe_file_transmittal_recipient_token",
            "acknowledge_token",
        ),
    )

    transmittal_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_file_transmittal.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    role: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    acknowledge_token: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)

    transmittal: Mapped[FileTransmittal] = relationship("FileTransmittal", back_populates="recipients")
