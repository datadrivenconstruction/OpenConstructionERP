# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Requisition history and the replayable change feed (issue #516).

Every change to a requisition goes through :func:`note_change`, which does
three things in the caller's transaction: it appends the entry to the
requisition's own history, bumps ``row_version`` and writes one row to
``oe_procurement_req_change``. Because the feed row commits or rolls back with
the change itself, a submission, edit or cancellation that committed always
has its entry. The detached events published next to it stay best effort; the
feed is what an integration replays when it missed one.

Reading the feed
----------------
Entries are ordered by ``(created_at, id)`` and a cursor is that pair, encoded.
``created_at`` is stamped when the row is written, not when its transaction
commits, so a transaction that commits late could otherwise land behind a
cursor a reader already moved past. The reader therefore only serves entries
older than a settle window (:data:`DEFAULT_SETTLE_SECONDS`), long enough for any
request to commit, and the cursor never moves past what it served. Polling
with the returned cursor never skips an entry; a duplicate can only come from a
caller replaying an older cursor, and every entry carries its own id and the
requisition's ``row_version`` to drop it by.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.procurement.models import MaterialRequisition, RequisitionChange
from app.modules.procurement.schemas import RequisitionFeedEntry, RequisitionFeedPage

#: Entries younger than this are not served yet (see the module docstring).
DEFAULT_SETTLE_SECONDS = 5
MAX_SETTLE_SECONDS = 600

#: History entries keep at most this many lines of a before/after line summary.
_LINE_SUMMARY_LIMIT = 50


def append_history(req: MaterialRequisition, action: str, actor: str | None, **extra: Any) -> dict[str, Any]:
    """Append one entry to the requisition's own history and return it.

    The metadata dict is replaced rather than mutated so the ORM sees the change.
    """
    meta = dict(req.metadata_ or {})
    history = list(meta.get("history") or [])
    entry: dict[str, Any] = {"at": datetime.now(UTC).isoformat(), "action": action, "actor": actor}
    entry.update({k: v for k, v in extra.items() if v is not None})
    history.append(entry)
    meta["history"] = history
    req.metadata_ = meta
    return entry


def note_change(
    session: AsyncSession,
    req: MaterialRequisition,
    event: str,
    actor: str | None,
    *,
    status_override: str | None = None,
    **extra: Any,
) -> RequisitionChange:
    """Record a change in the history and the feed, and bump ``row_version``.

    ``extra`` lands in both the history entry and the feed payload; ``None``
    values are dropped. ``status_override`` names the status the feed should
    report when the row's own status is written by a bulk UPDATE the instance
    has not seen yet.
    """
    append_history(req, event, actor, **extra)
    req.row_version = int(req.row_version or 0) + 1
    change = RequisitionChange(
        project_id=req.project_id,
        requisition_id=req.id,
        req_number=req.req_number,
        event=event,
        status=status_override or req.status,
        row_version=req.row_version,
        actor_id=actor,
        payload={k: v for k, v in extra.items() if v is not None},
    )
    session.add(change)
    return change


def line_summary(items: list[Any]) -> list[dict[str, Any]]:
    """A compact, ordered picture of a requisition's lines for a before/after record."""
    out: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda i: getattr(i, "sort_order", 0))[:_LINE_SUMMARY_LIMIT]:
        out.append(
            {
                "description": item.description,
                "unit": item.unit,
                "quantity": str(item.quantity_requested),
                "suggested_vendor_id": str(item.suggested_vendor_id) if item.suggested_vendor_id else None,
                "required_date": item.required_date,
                "sources": len(item.sources),
            }
        )
    return out


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    """An opaque cursor for the position just after one feed entry."""
    stamp = _as_utc(created_at).isoformat()
    return base64.urlsafe_b64encode(f"{stamp}|{row_id}".encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Read a cursor back, refusing anything this module did not write with a 422."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        stamp, row_id = raw.split("|", 1)
        return _as_utc(datetime.fromisoformat(stamp)), uuid.UUID(row_id)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The feed cursor is not one this server issued. Start again without 'after'.",
        ) from exc


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def page_feed(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    after: str | None,
    limit: int,
    settle_seconds: int = DEFAULT_SETTLE_SECONDS,
    requisition_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> RequisitionFeedPage:
    """One page of a project's feed after ``after``, oldest first, settled entries only."""
    horizon = _as_utc(now or datetime.now(UTC)) - timedelta(seconds=max(0, min(settle_seconds, MAX_SETTLE_SECONDS)))
    conditions = [RequisitionChange.project_id == project_id, RequisitionChange.created_at < horizon]
    if requisition_id is not None:
        conditions.append(RequisitionChange.requisition_id == requisition_id)
    if after:
        stamp, row_id = decode_cursor(after)
        conditions.append(
            or_(
                RequisitionChange.created_at > stamp,
                and_(RequisitionChange.created_at == stamp, RequisitionChange.id > row_id),
            )
        )
    rows = list(
        (
            await session.execute(
                select(RequisitionChange)
                .where(*conditions)
                .order_by(RequisitionChange.created_at, RequisitionChange.id)
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        RequisitionFeedEntry(
            id=row.id,
            cursor=encode_cursor(row.created_at, row.id),
            occurred_at=_as_utc(row.created_at),
            requisition_id=row.requisition_id,
            req_number=row.req_number,
            event=row.event,
            status=row.status,
            row_version=row.row_version,
            actor_id=row.actor_id,
            payload=dict(row.payload or {}),
        )
        for row in rows
    ]
    return RequisitionFeedPage(
        items=items,
        next_cursor=items[-1].cursor if items else after,
        settled_before=horizon,
        has_more=has_more,
    )
