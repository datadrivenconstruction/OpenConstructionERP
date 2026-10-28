# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Global search - searches across all modules simultaneously.

Usage:
    GET /api/v1/search?q=reinforced+concrete&project_id=xxx&limit=20

Returns results from: BOQ positions, contacts, documents, RFIs,
tasks, cost items, meetings, inspections, NCRs - ranked by relevance.

One rule holds across all nine: every column a type is matched on is also a
candidate for that type's title, so a row is always named by something the
searcher could have typed to find it. Break that and the type gains a blank
result the moment a record leaves its display column empty, which is legal in
every one of them - see :func:`_title`.
"""

import logging
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def global_search(
    session: AsyncSession,
    query: str,
    project_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search across all modules using ILIKE text matching.

    Each result is a dict with keys:
        module, type, id, title, subtitle, url, score

    Results are sorted by relevance score descending, then limited.
    Gracefully degrades: if a table does not exist yet, the search
    for that entity is skipped silently.
    """
    if not query or not query.strip():
        return []

    pattern = f"%{query.strip()}%"
    results: list[dict[str, Any]] = []

    # --- BOQ Positions ---
    try:
        from app.modules.boq.models import Position

        stmt = select(Position).where(
            or_(
                Position.description.ilike(pattern),
                Position.ordinal.ilike(pattern),
            )
        )
        if project_id:
            stmt = stmt.where(Position.boq_id.in_(select(_boq_id_for_project(project_id))))
        stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            # Compute a simple relevance score: exact match in ordinal > description
            score = _score(query, row.ordinal, row.description)
            results.append(
                {
                    "module": "boq",
                    "type": "position",
                    "id": str(row.id),
                    "title": _title(_join(row.ordinal, row.description[:120]), kind="position", row_id=row.id),
                    "subtitle": f"{row.quantity} {row.unit}",
                    "url": f"/boq/{row.boq_id}",
                    "score": score,
                }
            )
    except Exception:
        logger.debug("global_search: BOQ positions search skipped", exc_info=True)

    # --- Contacts ---
    try:
        # ``contact_display_name`` is the one place that knows how to name a
        # contact, and it lives in a module while this is core. Imported here
        # rather than at module scope because that is the same lazy, fail-soft
        # shape every other core-to-module reference uses, and this handler
        # already relies on it for ``Contact`` itself. Worth naming the cost:
        # if the finance module is ever absent this import raises and the whole
        # contacts branch is skipped, so contacts would drop out of search
        # rather than merely lose a label.
        from app.modules.contacts.models import Contact
        from app.modules.finance.einvoice_parties import contact_display_name

        stmt = (
            select(Contact)
            .where(
                or_(
                    Contact.company_name.ilike(pattern),
                    Contact.first_name.ilike(pattern),
                    Contact.last_name.ilike(pattern),
                    Contact.primary_email.ilike(pattern),
                )
            )
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            label = contact_display_name(row)
            score = _score(query, label, row.primary_email or "")
            results.append(
                {
                    "module": "contacts",
                    "type": "contact",
                    "id": str(row.id),
                    "title": _title(label, kind="contact", row_id=row.id),
                    "subtitle": row.contact_type,
                    "url": "/contacts",
                    "score": score,
                }
            )
    except Exception:
        logger.debug("global_search: contacts search skipped", exc_info=True)

    # --- Documents ---
    try:
        from app.modules.documents.models import Document

        stmt = select(Document).where(
            or_(
                Document.name.ilike(pattern),
                Document.description.ilike(pattern),
            )
        )
        if project_id:
            stmt = stmt.where(Document.project_id == project_id)
        stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            score = _score(query, row.name, row.description)
            results.append(
                {
                    "module": "documents",
                    "type": "document",
                    "id": str(row.id),
                    "title": _title(row.name, row.description, kind="document", row_id=row.id),
                    "subtitle": row.category,
                    "url": f"/projects/{row.project_id}/documents",
                    "score": score,
                }
            )
    except Exception:
        logger.debug("global_search: documents search skipped", exc_info=True)

    # --- RFIs ---
    try:
        from app.modules.rfi.models import RFI

        stmt = select(RFI).where(
            or_(
                RFI.subject.ilike(pattern),
                RFI.question.ilike(pattern),
                RFI.rfi_number.ilike(pattern),
            )
        )
        if project_id:
            stmt = stmt.where(RFI.project_id == project_id)
        stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            score = _score(query, row.rfi_number, row.subject)
            results.append(
                {
                    "module": "rfi",
                    "type": "rfi",
                    "id": str(row.id),
                    "title": _title(
                        _join(row.rfi_number, row.subject[:120]),
                        row.question,
                        kind="rfi",
                        row_id=row.id,
                    ),
                    "subtitle": row.status,
                    "url": f"/projects/{row.project_id}/rfi",
                    "score": score,
                }
            )
    except Exception:
        logger.debug("global_search: RFI search skipped", exc_info=True)

    # --- Tasks ---
    try:
        from app.modules.tasks.models import Task

        stmt = select(Task).where(
            or_(
                Task.title.ilike(pattern),
                Task.description.ilike(pattern),
            )
        )
        if project_id:
            stmt = stmt.where(Task.project_id == project_id)
        stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            score = _score(query, row.title, row.description or "")
            results.append(
                {
                    "module": "tasks",
                    "type": "task",
                    "id": str(row.id),
                    "title": _title(row.title, row.description, kind="task", row_id=row.id),
                    "subtitle": f"{row.status} / {row.priority}",
                    "url": f"/projects/{row.project_id}/tasks",
                    "score": score,
                }
            )
    except Exception:
        logger.debug("global_search: tasks search skipped", exc_info=True)

    # --- Cost Items ---
    try:
        from app.modules.costs.models import CostItem

        stmt = (
            select(CostItem)
            .where(
                or_(
                    CostItem.code.ilike(pattern),
                    CostItem.description.ilike(pattern),
                )
            )
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            score = _score(query, row.code, row.description)
            results.append(
                {
                    "module": "costs",
                    "type": "cost_item",
                    "id": str(row.id),
                    "title": _title(_join(row.code, row.description[:120]), kind="cost_item", row_id=row.id),
                    "subtitle": f"{row.rate} {row.currency}/{row.unit}",
                    "url": "/costs",
                    "score": score,
                }
            )
    except Exception:
        logger.debug("global_search: cost items search skipped", exc_info=True)

    # --- Meetings ---
    try:
        from app.modules.meetings.models import Meeting

        stmt = select(Meeting).where(
            or_(
                Meeting.title.ilike(pattern),
                Meeting.minutes.ilike(pattern),
                Meeting.meeting_number.ilike(pattern),
            )
        )
        if project_id:
            stmt = stmt.where(Meeting.project_id == project_id)
        stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            score = _score(query, row.title, row.meeting_number)
            results.append(
                {
                    "module": "meetings",
                    "type": "meeting",
                    "id": str(row.id),
                    "title": _title(
                        _join(row.meeting_number, row.title[:120]),
                        row.minutes,
                        kind="meeting",
                        row_id=row.id,
                    ),
                    "subtitle": row.meeting_date,
                    "url": f"/projects/{row.project_id}/meetings",
                    "score": score,
                }
            )
    except Exception:
        logger.debug("global_search: meetings search skipped", exc_info=True)

    # --- Inspections ---
    try:
        from app.modules.inspections.models import QualityInspection

        stmt = select(QualityInspection).where(
            or_(
                QualityInspection.title.ilike(pattern),
                QualityInspection.inspection_number.ilike(pattern),
            )
        )
        if project_id:
            stmt = stmt.where(QualityInspection.project_id == project_id)
        stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            score = _score(query, row.title, row.inspection_number)
            results.append(
                {
                    "module": "inspections",
                    "type": "inspection",
                    "id": str(row.id),
                    "title": _title(
                        _join(row.inspection_number, row.title[:120]),
                        kind="inspection",
                        row_id=row.id,
                    ),
                    "subtitle": row.status,
                    "url": f"/projects/{row.project_id}/inspections",
                    "score": score,
                }
            )
    except Exception:
        logger.debug("global_search: inspections search skipped", exc_info=True)

    # --- NCRs ---
    try:
        from app.modules.ncr.models import NCR

        stmt = select(NCR).where(
            or_(
                NCR.title.ilike(pattern),
                NCR.description.ilike(pattern),
                NCR.ncr_number.ilike(pattern),
            )
        )
        if project_id:
            stmt = stmt.where(NCR.project_id == project_id)
        stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            score = _score(query, row.ncr_number, row.title)
            results.append(
                {
                    "module": "ncr",
                    "type": "ncr",
                    "id": str(row.id),
                    "title": _title(
                        _join(row.ncr_number, row.title[:120]),
                        row.description,
                        kind="ncr",
                        row_id=row.id,
                    ),
                    "subtitle": f"{row.severity} / {row.status}",
                    "url": f"/projects/{row.project_id}/ncr",
                    "score": score,
                }
            )
    except Exception:
        logger.debug("global_search: NCR search skipped", exc_info=True)

    # Sort by relevance score descending and limit
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


def _boq_id_for_project(project_id: str):
    """Return a subquery selecting BOQ IDs for a specific project."""
    from app.modules.boq.models import BOQ

    return select(BOQ.id).where(BOQ.project_id == project_id).scalar_subquery()


def _join(*parts: str | None) -> str:
    """Join the parts that carry a value with " - ".

    Composite titles here read "number - subject". Both halves are NOT NULL
    columns but either may legitimately hold an empty string, and the plain
    f-string then shipped the separator on its own: a record without a number
    read as " - Slab pour check", and one without either read as " - ".

    Args:
        *parts: title fragments, in the order they should be read.

    Returns:
        The non-empty fragments joined, or an empty string when none carry a
        value.
    """
    return " - ".join(part.strip() for part in parts if part and part.strip())


def _title(*candidates: str | None, kind: str, row_id: object) -> str:
    """Return the label a person can recognise this row by.

    A row is matched on one set of columns and titled from another, usually
    smaller, set. Match on a column the title is not built from, with the
    title's own columns empty, and the row comes back as a blank line: found,
    and then not named. The fix is a rule rather than a patch per module -
    every column the WHERE clause can match on is also a title candidate here,
    so whatever the searcher typed is in the title they get back, which is the
    string their eye is looking for.

    The last resort is the record's own type plus a short id. That type is the
    machine token this function's caller already ships as ``type``, not English
    prose, so it needs no translation and none is invented on the backend. It
    is deliberately not the bare identifier: a full UUID names nothing to the
    person reading it.

    Args:
        *candidates: display strings in preference order, empty ones skipped.
        kind: the record type, used only when no candidate carries a value.
        row_id: the record's id, truncated for the last-resort label.

    Returns:
        A non-empty, non-whitespace title.
    """
    for candidate in candidates:
        if candidate and candidate.strip():
            return candidate.strip()[:200]
    return f"{kind} {str(row_id)[:8]}"


def _score(query: str, primary: str, secondary: str) -> float:
    """Compute a simple relevance score (0.0 - 1.0).

    Exact match in primary field scores highest; partial matches lower.
    """
    q = query.lower().strip()
    p = (primary or "").lower()
    s = (secondary or "").lower()

    if p == q:
        return 1.0
    if p.startswith(q):
        return 0.9
    if q in p:
        return 0.7
    if s == q:
        return 0.6
    if q in s:
        return 0.5
    return 0.3
