# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid day ORM models.

Tables:
    oe_bid_day_board    - one board per tender package: currency, markups, status, version.
    oe_bid_day_row      - one trade package or scope on the board, with the estimate's plug figure.
    oe_bid_day_quote    - a quote on a row: read from a bid submission or tender bid, or entered late.
    oe_bid_day_event    - the change log shown on the board.
    oe_bid_day_snapshot - what was submitted; written once, never updated or deleted.

``tender_id``, ``bid_package_id`` and ``source_ref`` are soft links (no foreign
key) like the other registers, so reorganising tendering never cascades here.
Money is stored as decimal strings and computed as ``Decimal``.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, event, inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class BidDayBoard(Base):
    """The live bid-day board of one tender."""

    __tablename__ = "oe_bid_day_board"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tender_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, unique=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    overhead_pct: Mapped[str] = mapped_column(String(20), nullable=False, default="0", server_default="0")
    risk_pct: Mapped[str] = mapped_column(String(20), nullable=False, default="0", server_default="0")
    profit_pct: Mapped[str] = mapped_column(String(20), nullable=False, default="0", server_default="0")
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", server_default="open")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    markup_rev: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    rows: Mapped[list["BidDayRow"]] = relationship(
        back_populates="board", cascade="all, delete-orphan", lazy="selectin", order_by="BidDayRow.sort_order"
    )


class BidDayRow(Base):
    """One trade package or scope on the board."""

    __tablename__ = "oe_bid_day_row"

    board_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_bid_day_board.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bid_package_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="subcontract", server_default="subcontract")
    plug_amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    chosen_quote_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rev: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    board: Mapped[BidDayBoard] = relationship(back_populates="rows", lazy="raise_on_sql")
    quotes: Mapped[list["BidDayQuote"]] = relationship(
        back_populates="row", cascade="all, delete-orphan", lazy="selectin", order_by="BidDayQuote.created_at"
    )


class BidDayQuote(Base):
    """A quote for one row, as received and as adjusted on the board."""

    __tablename__ = "oe_bid_day_quote"
    __table_args__ = (Index("ix_bid_day_quote_source", "source", "source_ref"),)

    row_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_bid_day_row.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="late", server_default="late")
    source_ref: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="portal", server_default="portal")
    vendor: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    source_amount: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    fx_rate: Mapped[str] = mapped_column(String(30), nullable=False, default="1", server_default="1")
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    exclusions: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    rev: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    row: Mapped[BidDayRow] = relationship(back_populates="quotes", lazy="raise_on_sql")


class BidDayEvent(Base):
    """One entry of the board's change log."""

    __tablename__ = "oe_bid_day_event"
    __table_args__ = (Index("ix_bid_day_event_board_created", "board_id", "created_at"),)

    board_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_bid_day_board.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    user_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    delta: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    total_after: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")


class BidDaySnapshot(Base):
    """An immutable record of a submitted bid."""

    __tablename__ = "oe_bid_day_snapshot"

    board_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_bid_day_board.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    tender_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    submitted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    submitted_by_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    bid_total: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SnapshotImmutableError(RuntimeError):
    """A submitted bid snapshot was about to change."""


# Recording that the snapshot was pushed into the estimate is the one permitted write.
SNAPSHOT_MUTABLE_FIELDS = frozenset({"pushed_at", "updated_at"})


def changed_snapshot_fields(target: BidDaySnapshot) -> set[str]:
    """Names of the persisted fields a pending flush would change."""
    return {a.key for a in inspect(target).attrs if a.history.has_changes()} - SNAPSHOT_MUTABLE_FIELDS


@event.listens_for(BidDaySnapshot, "before_update")
def _refuse_snapshot_update(_mapper, _connection, target: BidDaySnapshot) -> None:  # noqa: ANN001
    changed = changed_snapshot_fields(target)
    if changed:
        raise SnapshotImmutableError(f"A submitted bid snapshot cannot change ({', '.join(sorted(changed))}).")


@event.listens_for(BidDaySnapshot, "before_delete")
def _refuse_snapshot_delete(_mapper, _connection, _target: BidDaySnapshot) -> None:  # noqa: ANN001
    raise SnapshotImmutableError("A submitted bid snapshot cannot be deleted.")
