# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Change flags on BOQ positions.

A change flag tells the estimator that something a position was measured from
has moved since: a drawing got a new revision, or a BIM model got a new version
whose elements the position is linked to. The flag never changes a number. It
is a review item, and the person who reads it marks it reviewed.

Table:
    oe_boq_change_flag - one row per (position, source, source revision)

Idempotency lives in the unique constraint on
``(position_id, source_type, source_key)``. ``source_key`` names the source
revision (``document:<id>:<revision>`` or ``bim:<new model id>``), so the same
revision reported twice, by an event and by a scan or by two scans, collapses
into one row, while the next revision of the same drawing is a new key and so a
new flag. A reviewed flag is never reopened by a repeat of its own key.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

#: A drawing or document the position was measured from has a newer revision.
SOURCE_DOCUMENT_REVISION = "document_revision"
#: A BIM model the position is linked to has a newer version.
SOURCE_BIM_VERSION = "bim_version"
CHANGE_FLAG_SOURCES: tuple[str, ...] = (SOURCE_DOCUMENT_REVISION, SOURCE_BIM_VERSION)

FLAG_STATUS_OPEN = "open"
FLAG_STATUS_REVIEWED = "reviewed"
CHANGE_FLAG_STATUSES: tuple[str, ...] = (FLAG_STATUS_OPEN, FLAG_STATUS_REVIEWED)


class BOQChangeFlag(Base):
    """A position whose source drawing or model changed after it was measured.

    Columns:
        project_id - the project of the owning BOQ, denormalised so a project
            wide count does not need the join
        boq_id / position_id - the flagged line (both CASCADE on delete)
        source_type - ``document_revision`` or ``bim_version``
        source_key - idempotency key naming the source revision
        source_id - the document, drawing or new model id
        source_label - human name of the source (document name, model name)
        source_version - the revision code or model version that triggered it
        reason - ``document_revised``, ``elements_modified``,
            ``elements_deleted``, ``elements_changed`` or ``model_changed``
        details - what was found (element counts, stable ids, old model id)
        detected_via - ``event`` (published by another module) or ``scan``
        status - ``open`` until a person marks it ``reviewed``
        reviewed_by / reviewed_at / review_note - who closed it and why
    """

    __tablename__ = "oe_boq_change_flag"
    __table_args__ = (
        UniqueConstraint("position_id", "source_type", "source_key"),
        Index("ix_boq_change_flag_boq_status", "boq_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    boq_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_boq.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_position.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_key: Mapped[str] = mapped_column(String(255), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_label: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    detected_via: Mapped[str] = mapped_column(String(16), nullable=False, default="scan", server_default="scan")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=FLAG_STATUS_OPEN, server_default="open")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<BOQChangeFlag pos={self.position_id} {self.source_type}:{self.source_key} ({self.status})>"
