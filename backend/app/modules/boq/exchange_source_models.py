# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The original exchange file a bill was imported from, kept with a fingerprint.

A bill that arrives from another party (a GAEB X83 call for bids, a BC3 budget)
must go back to that party with the same item numbers, units, quantities and
texts. The file itself is filed in Documents; this row keeps its SHA-256 and a
snapshot of every priceable line as it was read, so "has the bill changed since
it was imported" has an answer that does not depend on the file being re-read.

Table:
    oe_boq_exchange_source - one row per import; the newest row of a bill is its source
"""

import uuid

from sqlalchemy import JSON, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class BOQExchangeSource(Base):
    """One imported exchange file and the bill lines it carried."""

    __tablename__ = "oe_boq_exchange_source"
    __table_args__ = (Index("ix_boq_exchange_source_boq_created", "boq_id", "created_at"),)

    boq_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_boq.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    #: Registry token of the reader: ``gaeb_xml``, ``bc3``, ``excel`` ...
    format_id: Mapped[str] = mapped_column(String(30), nullable=False)
    #: Phase or flavour, e.g. ``x83``; empty when the format has none.
    variant: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    #: Where the original bytes are kept; empty when they could not be written.
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    #: The Documents row the file is filed as, when filing worked.
    document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    #: SHA-256 of the canonical line snapshot (ordinal, unit, quantity, text).
    bill_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    lines: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<BOQExchangeSource {self.format_id}/{self.variant} boq={self.boq_id}>"
