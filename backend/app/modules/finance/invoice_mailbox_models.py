# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mailbox settings for scan-to-email invoice intake.

Table:
    oe_finance_invoice_mailbox - one IMAP mailbox per project that the platform
    polls for supplier invoices sent by scanners and offices.

The password is stored encrypted with :mod:`app.core.crypto` and never leaves the
backend: the read schema only reports whether one is set.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class InvoiceMailbox(Base):
    """The mailbox a project's invoice scans arrive in."""

    __tablename__ = "oe_finance_invoice_mailbox"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="false")
    host: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=993, server_default="993")
    use_ssl: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True, server_default="true")
    username: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    folder: Mapped[str] = mapped_column(String(255), nullable=False, default="INBOX", server_default="INBOX")
    # Empty: processed messages are only marked as seen.
    processed_folder: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # The address shown in the capture help, i.e. where scanners send to.
    intake_address: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    last_polled_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<InvoiceMailbox {self.host}/{self.folder} enabled={self.enabled}>"
