# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Event-reconciliation ORM models.

Tables:
    oe_record_link - a scored, reviewable correlation between two heterogeneous
        records (a change order, a piece of correspondence, a variation, a MoC,
        ...) that the pure :mod:`correlate` engine judged to describe the same
        underlying event. The engine recomputes candidate links on every read;
        a row exists here only once a reviewer has *confirmed* or *rejected* a
        suggested link, so the table is the durable record of human decisions
        layered over the engine's suggestions, not a cache of the suggestions
        themselves.

The link is generic (not one table per source pair): each endpoint is named by
an opaque ``(type, id)`` pair so a new source type never needs a schema change.
The pair is stored in the engine's canonical order (the smaller ``(type, id)``
as the *left*) so the same undirected link is never persisted twice with the
endpoints swapped.
"""

import uuid
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

#: Link review states. A link starts life as an engine *suggestion* (never
#: persisted) and a row is written only when a reviewer confirms or rejects it.
STATUS_SUGGESTED = "suggested"
STATUS_CONFIRMED = "confirmed"
STATUS_REJECTED = "rejected"

#: The persisted review states, in display order. ``suggested`` is included so a
#: caller may explicitly persist "seen but undecided", though the common path
#: writes only ``confirmed`` / ``rejected``.
LINK_STATUSES: tuple[str, ...] = (STATUS_SUGGESTED, STATUS_CONFIRMED, STATUS_REJECTED)


class RecordLink(Base):
    """A reviewed correlation between two records describing one event.

    Endpoints are opaque ``(type, id)`` pairs - ``left_type='change_order'`` /
    ``left_id='<uuid>'`` and so on - so the table is decoupled from any one
    source schema. ``confidence`` is the engine's blended score in ``[0, 1]``,
    a ratio (not money) held as ``NUMERIC(6, 4)`` so it round-trips exactly as
    Decimal. ``relation`` carries the engine's relation token (only
    ``same_event`` today) so the vocabulary can grow without a migration.
    """

    __tablename__ = "oe_record_link"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The canonical-left endpoint: an opaque source-type token and the record's
    # id within that type (rendered as a string so any id shape fits).
    left_type: Mapped[str] = mapped_column(String(60), nullable=False, server_default="", default="")
    left_id: Mapped[str] = mapped_column(String(36), nullable=False, server_default="", default="")
    # The canonical-right endpoint.
    right_type: Mapped[str] = mapped_column(String(60), nullable=False, server_default="", default="")
    right_id: Mapped[str] = mapped_column(String(36), nullable=False, server_default="", default="")
    # The relation the engine asserted between the two records. Defaults to the
    # engine's same-event token; a plain string so the vocabulary can grow.
    relation: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default="same_event",
        default="same_event",
    )
    # The engine's blended confidence in [0, 1]. A ratio, NOT money: NUMERIC(6,4)
    # keeps four decimal places (for example 0.6000) and reads back as Decimal.
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(6, 4),
        nullable=False,
        server_default="0",
        default=Decimal("0"),
    )
    # Review state: suggested / confirmed / rejected. Indexed so a project's
    # confirmed (or rejected) decisions are cheap to scan when assembling a
    # thread.
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=STATUS_SUGGESTED,
        default=STATUS_SUGGESTED,
        index=True,
    )
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
            f"<RecordLink {self.id} "
            f"{self.left_type}:{self.left_id} <-> {self.right_type}:{self.right_id} "
            f"{self.status}>"
        )
