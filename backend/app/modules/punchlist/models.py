# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Punch List ORM models.

Tables:
    oe_punchlist_item - punch list items tracking construction deficiencies
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, column, event, select, table
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_types import CalendarDayDateTime
from app.database import GUID, Base


class PunchItem(Base):
    """Punch list entry tracking a construction deficiency or quality issue."""

    __tablename__ = "oe_punchlist_item"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # A calendar day, kept as midnight UTC in a timestamp column (see app.core.calendar_day).
    due_date: Mapped[datetime | None] = mapped_column(CalendarDayDateTime(), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trade: Mapped[str | None] = mapped_column(String(100), nullable=True)
    photos: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    reopen_history: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    # ── Rework cost (Decimal as string - never Float) ─────────────────────
    # Stored as VARCHAR so there is no floating-point rounding on money values.
    # Service layer validates it as a Decimal string before persisting.
    rework_cost: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # No ORM default: an unset currency is filled from the project at insert
    # time (see ``_stamp_rework_currency`` below), whichever module builds the
    # row. The server default only covers raw SQL inserts.
    rework_cost_currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")

    # ── Clash linkage (cross-module) ──────────────────────────────────────
    # When a punch item is auto-created from a high/critical clash, this
    # column carries the originating ``ClashResult.id`` so the two rows stay
    # traceable and the auto-creation stays idempotent (a duplicate event
    # for the same clash must never spawn a second punch item). Nullable +
    # no server_default: absent means "not clash-sourced", not "0".
    clash_result_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # ── Geo binding (cross-module) ────────────────────────────────────────
    # In addition to the sheet-pinned (page, location_x, location_y) drawing
    # coordinate, punch items can carry a world-space WGS84 pin so they
    # render on the project's Geo Hub map. Nullable + no server_default;
    # absent values mean "no map pin", not "(0, 0)". See SafetyIncident
    # for the same rationale and the #154 incident notes.
    geo_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    geo_lon: Mapped[float | None] = mapped_column(Float, nullable=True)

    def __repr__(self) -> str:
        return f"<PunchItem {self.title[:40]} ({self.status}/{self.priority})>"


# Fallback when the project has no usable currency. Same value, and the same
# reasoning, as ``PunchListService._rework_currency``: an undecided project
# currency is a legitimate state and the column is NOT NULL.
_FALLBACK_REWORK_CURRENCY = "USD"

# A lightweight handle on the projects table: punchlist must stay loadable
# without the projects module, so the ORM model is not imported here.
_projects = table("oe_projects_project", column("id", GUID()), column("currency", String()))


@event.listens_for(PunchItem, "before_insert")
def _stamp_rework_currency(_mapper: object, connection: object, target: PunchItem) -> None:
    """Price an item with no currency in its project's currency.

    ``PunchListService.create_item`` resolves this itself, but the punchlist
    event bridges, the inspections router and the field diary build
    ``PunchItem`` directly, and the old model default stamped every one of
    those USD, on a euro project too.
    """
    if (target.rework_cost_currency or "").strip():
        return
    code = ""
    if target.project_id is not None:
        found = connection.execute(  # type: ignore[attr-defined]
            select(_projects.c.currency).where(_projects.c.id == target.project_id)
        ).scalar_one_or_none()
        code = str(found or "").strip().upper()
    target.rework_cost_currency = code if len(code) == 3 and code.isalpha() else _FALLBACK_REWORK_CURRENCY
