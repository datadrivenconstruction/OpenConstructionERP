# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Turning "this is late" into something that finds you.

The module already computes overdue items and suppliers who owe an
answer. Until now that was pull-only: true if you were looking at the
tab, invisible if you were not - which for a deadline is the same as
absent.

This is the sweep that pushes it onto the platform's bus.

THE DEDUPE IS THE LOAD-BEARING PART. The workspace polls every 45
seconds, so a naive publish would fire the same "RFI-004 is overdue"
event every 45 seconds, for days - which trains everyone to ignore the
bell, and an ignored bell is worse than no bell. Each reason fires at
most once per item per DAY, remembered in a server-owned key on the item
so the memory survives a restart and cannot be forged by an edit.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.register_workflow import events
from app.modules.register_workflow.models import RegisterItem

logger = logging.getLogger(__name__)

#: Server-owned key on ``item.fields`` holding the last date each reason
#: was announced: ``{"overdue": "2026-08-19", "chase:Alpha": "2026-08-19"}``.
#: Listed in service.RESERVED_FIELD_KEYS so an edit cannot rewrite it -
#: a client that could would be able to silence its own overdue notices.
NOTIFIED_KEY = "_notified"

#: A supplier who has not answered in this many days is worth chasing.
CHASE_AFTER_DAYS = 3


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _days_late(due: str | None) -> int:
    if not due:
        return 0
    try:
        return (datetime.now(UTC).date() - date.fromisoformat(str(due)[:10])).days
    except ValueError:
        return 0


def _already_today(item: RegisterItem, reason: str) -> bool:
    log = (item.fields or {}).get(NOTIFIED_KEY) or {}
    return isinstance(log, dict) and log.get(reason) == _today()


def _mark(item: RegisterItem, reason: str) -> None:
    fields = dict(item.fields or {})
    log = dict(fields.get(NOTIFIED_KEY) or {})
    log[reason] = _today()
    # Bounded: a long job would otherwise accumulate a key per supplier
    # per reason for ever inside a JSON column read on every render.
    if len(log) > 200:
        log = dict(sorted(log.items(), key=lambda kv: kv[1], reverse=True)[:200])
    fields[NOTIFIED_KEY] = log
    item.fields = fields


async def sweep_project(session: AsyncSession, *, project_id: uuid.UUID) -> dict[str, Any]:
    """Announce what has newly fallen due on one project.

    Returns a count of what it published, so the caller can say "3 new"
    rather than leaving the user to guess whether it did anything.
    """
    from app.modules.register_workflow import tracking

    published: list[str] = []
    items = (
        (
            await session.execute(
                select(RegisterItem).where(RegisterItem.project_id == project_id).where(RegisterItem.status == "open")
            )
        )
        .scalars()
        .all()
    )

    for item in items:
        late = _days_late(item.due_date)
        if late > 0 and not _already_today(item, "overdue"):
            events.item_overdue(item, late)
            _mark(item, "overdue")
            published.append(f"{item.reference} overdue")

        # Who owes an answer, and for how long. Read through the same
        # tracking code the screen uses, so the bell and the tab can never
        # disagree about who is silent.
        try:
            rows = (await tracking.tracking_for(session, item)).get("rows") or []
        except Exception:  # noqa: BLE001 - a bell is never a gate
            logger.debug("Tracking unavailable for %s", item.reference, exc_info=True)
            continue
        for row in rows:
            waiting = row.get("days_waiting")
            # The row's own STATE, not a guess: tracking already decides
            # who is silent, and re-deriving it here is how the bell and
            # the tab drift into disagreeing about the same supplier.
            if str(row.get("state") or "") not in ("waiting", "chase", "overdue"):
                continue
            if not isinstance(waiting, int) or waiting < CHASE_AFTER_DAYS:
                continue
            who = str(row.get("name") or "").strip()
            if not who:
                continue
            reason = f"chase:{who.lower()}"
            if _already_today(item, reason):
                continue
            events.chase_due(item, who, waiting)
            _mark(item, reason)
            published.append(f"{item.reference} chase {who}")

    await session.flush()
    return {"published": len(published), "detail": published[:50]}
