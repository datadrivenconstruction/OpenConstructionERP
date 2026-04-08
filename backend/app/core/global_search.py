"""Global search — searches across all modules simultaneously.

Usage:
    GET /api/v1/search?q=reinforced+concrete&project_id=xxx&limit=20

Returns results from: BOQ positions, contacts, documents, RFIs,
tasks, cost items, meetings, inspections, NCRs — ranked by relevance.
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
            stmt = stmt.where(Position.boq_id.in_(
                select(_boq_id_for_project(project_id))
            ))
        stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            # Compute a simple relevance score: exact match in ordinal > description
            score = _score(query, row.ordinal, row.description)
            results.append({
                "module": "boq",
                "type": "position",
                "id": str(row.id),
                "title": f"{row.ordinal} — {row.description[:120]}",
                "subtitle": f"{row.quantity} {row.unit}",
                "url": f"/boq/{row.boq_id}",
                "score": score,
            })
    except Exception:
        logger.debug("global_search: BOQ positions search skipped", exc_info=True)

    # --- Contacts ---
    try:
        from app.modules.contacts.models import Contact

        stmt = select(Contact).where(
            or_(
                Contact.company_name.ilike(pattern),
                Contact.first_name.ilike(pattern),
                Contact.last_name.ilike(pattern),
                Contact.primary_email.ilike(pattern),
            )
        ).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            label = row.company_name or f"{row.first_name or ''} {row.last_name or ''}".strip()
            score = _score(query, label, row.primary_email or "")
            results.append({
                "module": "contacts",
                "type": "contact",
                "id": str(row.id),
                "title": label,
                "subtitle": row.contact_type,
                "url": "/contacts",
                "score": score,
            })
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
            results.append({
                "module": "documents",
                "type": "document",
                "id": str(row.id),
                "title": row.name,
                "subtitle": row.category,
                "url": f"/projects/{row.project_id}/documents",
                "score": score,
            })
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
            results.append({
                "module": "rfi",
                "type": "rfi",
                "id": str(row.id),
                "title": f"{row.rfi_number} — {row.subject[:120]}",
                "subtitle": row.status,
                "url": f"/projects/{row.project_id}/rfi",
                "score": score,
            })
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
            results.append({
                "module": "tasks",
                "type": "task",
                "id": str(row.id),
                "title": row.title[:200],
                "subtitle": f"{row.status} / {row.priority}",
                "url": f"/projects/{row.project_id}/tasks",
                "score": score,
            })
    except Exception:
        logger.debug("global_search: tasks search skipped", exc_info=True)

    # --- Cost Items ---
    try:
        from app.modules.costs.models import CostItem

        stmt = select(CostItem).where(
            or_(
                CostItem.code.ilike(pattern),
                CostItem.description.ilike(pattern),
            )
        ).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            score = _score(query, row.code, row.description)
            results.append({
                "module": "costs",
                "type": "cost_item",
                "id": str(row.id),
                "title": f"{row.code} — {row.description[:120]}",
                "subtitle": f"{row.rate} {row.currency}/{row.unit}",
                "url": "/costs",
                "score": score,
            })
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
            results.append({
                "module": "meetings",
                "type": "meeting",
                "id": str(row.id),
                "title": f"{row.meeting_number} — {row.title[:120]}",
                "subtitle": row.meeting_date,
                "url": f"/projects/{row.project_id}/meetings",
                "score": score,
            })
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
            results.append({
                "module": "inspections",
                "type": "inspection",
                "id": str(row.id),
                "title": f"{row.inspection_number} — {row.title[:120]}",
                "subtitle": row.status,
                "url": f"/projects/{row.project_id}/inspections",
                "score": score,
            })
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
            results.append({
                "module": "ncr",
                "type": "ncr",
                "id": str(row.id),
                "title": f"{row.ncr_number} — {row.title[:120]}",
                "subtitle": f"{row.severity} / {row.status}",
                "url": f"/projects/{row.project_id}/ncr",
                "score": score,
            })
    except Exception:
        logger.debug("global_search: NCR search skipped", exc_info=True)

    # Sort by relevance score descending and limit
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


def _boq_id_for_project(project_id: str):
    """Return a subquery selecting BOQ IDs for a specific project."""
    from app.modules.boq.models import BOQ

    return select(BOQ.id).where(BOQ.project_id == project_id).scalar_subquery()


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
