# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Small counts for the navigation menu ("Invoices: 3 awaiting", "Issues: 5 open").

One ``COUNT(*)`` per badge over an already access-checked set of projects, so a
poll every minute stays cheap. A badge whose table is missing or whose query
fails is left out instead of failing the whole menu.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# A tender is "due" when its deadline is today or within this many days.
TENDER_DUE_WINDOW_DAYS = 2
# Upper bound of tender rows parsed per poll; deadlines are free text.
_TENDER_SCAN_LIMIT = 500

RFI_OPEN = ("open",)
PUNCH_OPEN = ("open", "in_progress")
NCR_CLOSED = ("closed", "void")
TASK_OPEN = ("open", "in_progress")
INVOICE_AWAITING = ("pending",)
TENDER_LIVE = ("draft", "issued", "open")


@dataclass(frozen=True)
class NavBadge:
    """One badge: a count, what it counts and how loud it is."""

    count: int
    kind: str
    tone: str = "neutral"
    due_in_days: int | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"count": self.count, "kind": self.kind, "tone": self.tone}
        if self.due_in_days is not None:
            out["due_in_days"] = self.due_in_days
        return out


def parse_deadline(raw: str | None) -> date | None:
    """The calendar day of a free-text tender deadline, or None when unreadable."""
    if not raw:
        return None
    text = raw.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def tender_due_days(deadlines: list[str | None], today: date) -> tuple[int, int | None]:
    """How many deadlines fall in [today, today + window], and the nearest one in days."""
    horizon = today + timedelta(days=TENDER_DUE_WINDOW_DAYS)
    days = [(d - today).days for d in map(parse_deadline, deadlines) if d is not None and today <= d <= horizon]
    return len(days), (min(days) if days else None)


async def _count(session: AsyncSession, stmt: Any) -> int | None:
    try:
        async with session.begin_nested():
            return int((await session.execute(stmt)).scalar_one() or 0)
    except Exception:
        logger.warning("nav badges: a count failed and is left out", exc_info=True)
        return None


async def compute_nav_badges(
    session: AsyncSession,
    project_ids: set[uuid.UUID],
    user_id: str,
    *,
    today: date | None = None,
) -> dict[str, dict[str, Any]]:
    """Badges keyed by the menu route they belong to; zero counts are omitted.

    Args:
        session: The request session.
        project_ids: Projects the caller may open, already checked.
        user_id: The caller, for the "my open tasks" count.
        today: Override for tests.

    Returns:
        ``{"/finance": {"count": 3, "kind": "awaiting", "tone": "warning"}, ...}``.
    """
    from app.modules.finance.models import Invoice
    from app.modules.ncr.models import NCR
    from app.modules.punchlist.models import PunchItem
    from app.modules.rfi.models import RFI
    from app.modules.tasks.models import Task
    from app.modules.tendering.models import TenderPackage

    if not project_ids:
        return {}
    ids = list(project_ids)
    badges: dict[str, NavBadge] = {}

    def put(route: str, badge: NavBadge) -> None:
        if badge.count > 0:
            badges[route] = badge

    def counted(model: Any, *where: Any) -> Any:
        return select(func.count()).select_from(model).where(model.project_id.in_(ids), *where)

    invoices = await _count(session, counted(Invoice, Invoice.status.in_(INVOICE_AWAITING)))
    if invoices is not None:
        put("/finance", NavBadge(invoices, "awaiting", "warning"))

    rfis = await _count(session, counted(RFI, RFI.status.in_(RFI_OPEN)))
    punch = await _count(session, counted(PunchItem, PunchItem.status.in_(PUNCH_OPEN)))
    ncrs = await _count(session, counted(NCR, NCR.status.not_in(NCR_CLOSED)))
    if rfis is not None:
        put("/rfi", NavBadge(rfis, "open"))
    if punch is not None:
        put("/punchlist", NavBadge(punch, "open"))
    if ncrs is not None:
        put("/ncr", NavBadge(ncrs, "open", "warning"))
    parts = [n for n in (rfis, punch, ncrs) if n is not None]
    if parts:
        put("/issues", NavBadge(sum(parts), "open"))

    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        uid = None
    if uid is not None:
        tasks = await _count(session, counted(Task, Task.status.in_(TASK_OPEN), Task.responsible_id == uid))
        if tasks is not None:
            put("/tasks", NavBadge(tasks, "assigned"))

    try:
        async with session.begin_nested():
            rows = (
                (
                    await session.execute(
                        select(TenderPackage.deadline)
                        .where(
                            TenderPackage.project_id.in_(ids),
                            TenderPackage.status.in_(TENDER_LIVE),
                            TenderPackage.deadline.is_not(None),
                        )
                        .limit(_TENDER_SCAN_LIMIT)
                    )
                )
                .scalars()
                .all()
            )
        due, nearest = tender_due_days(list(rows), today or datetime.now(UTC).date())
        put("/tendering", NavBadge(due, "due", "danger" if nearest == 0 else "warning", nearest))
    except Exception:
        logger.warning("nav badges: tender deadlines failed and are left out", exc_info=True)

    return {route: badge.as_dict() for route, badge in badges.items()}
