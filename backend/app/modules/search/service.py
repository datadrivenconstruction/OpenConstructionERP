# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unified search service - fan-out + RRF over every vector collection.

Architecture
------------

The unified search is a two-track recall system:

1. Vector track - :func:`search_collection` from :mod:`app.core.vector_index`
   embeds the query once and runs ANN over every selected collection.
   Best at semantic recall ("reinforced concrete walls" matches "RC
   wall 240mm") but requires LanceDB / Qdrant to be installed AND for
   the collections to have been indexed.

2. SQL track - :func:`_sql_search_collection` runs ILIKE substring
   matches against the canonical text columns of each collection's
   backing table. Lower recall but ALWAYS available - it's the
   fallback when LanceDB is missing (fresh ``pip install`` without
   ``[vector]`` extras) or when a collection has zero vectors.

The two tracks are merged via Reciprocal Rank Fusion. SQL hits ride
the same fusion path as vector hits, so the response shape is
identical regardless of which track produced the result. This is
IMP-016: SQL fallback is unconditional, vector adds re-rank quality
when available.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy import false as sql_false
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vector_index import (
    ALL_COLLECTIONS,
    COLLECTION_BIM_ELEMENTS,
    COLLECTION_BOQ,
    COLLECTION_CHANGE_ORDERS,
    COLLECTION_CHAT,
    COLLECTION_CORRESPONDENCE,
    COLLECTION_COSTS,
    COLLECTION_DOCUMENTS,
    COLLECTION_LABELS,
    COLLECTION_MOC,
    COLLECTION_REQUIREMENTS,
    COLLECTION_RFI,
    COLLECTION_RISKS,
    COLLECTION_SUBMITTALS,
    COLLECTION_TASKS,
    COLLECTION_VALIDATION,
    COLLECTION_VARIATIONS,
    VectorHit,
    all_collection_status,
    reciprocal_rank_fusion,
    search_collection,
)
from app.database import async_session_factory
from app.modules.search.schemas import (
    CollectionStatusItem,
    SearchStatusResponse,
    UnifiedSearchHit,
    UnifiedSearchResponse,
)

logger = logging.getLogger(__name__)


# Map short names ("boq", "documents", …) → full collection names so the
# frontend can pass either form.  Single source of truth: the labels dict
# from vector_index plus a few common aliases.
_SHORT_NAME_ALIASES: dict[str, str] = {
    "boq": "oe_boq_positions",
    "boq_positions": "oe_boq_positions",
    "documents": "oe_documents",
    "docs": "oe_documents",
    "tasks": "oe_tasks",
    "risks": "oe_risks",
    "risk": "oe_risks",
    "bim": "oe_bim_elements",
    "bim_elements": "oe_bim_elements",
    "requirements": "oe_requirements",
    "reqs": "oe_requirements",
    "rfi": "oe_rfi_rfis",
    "rfis": "oe_rfi_rfis",
    # The /search/types/ endpoint derives ``short`` via removeprefix("oe_"),
    # so the wire value for these collections is the doubled form below.
    # Accept both the friendly alias and the doubled short name.
    "rfi_rfis": "oe_rfi_rfis",
    "submittals": "oe_submittals_submittals",
    "submittal": "oe_submittals_submittals",
    "submittals_submittals": "oe_submittals_submittals",
    "correspondence": "oe_correspondence_correspondence",
    "correspondence_correspondence": "oe_correspondence_correspondence",
    # Change-management collections.
    "change_orders": "oe_change_orders",
    "change_order": "oe_change_orders",
    "changeorders": "oe_change_orders",
    "variations": "oe_variations",
    "variation": "oe_variations",
    "moc": "oe_moc",
    "management_of_change": "oe_moc",
    "validation": "oe_validation",
    "chat": "oe_chat",
}


def _normalize_types(raw: list[str] | None) -> list[str]:
    """Resolve a list of user-supplied type names to canonical collections."""
    if not raw:
        return list(ALL_COLLECTIONS)
    out: list[str] = []
    for name in raw:
        cleaned = (name or "").strip().lower()
        if not cleaned:
            continue
        canonical = _SHORT_NAME_ALIASES.get(cleaned, cleaned)
        if canonical in ALL_COLLECTIONS and canonical not in out:
            out.append(canonical)
    if not out:
        return list(ALL_COLLECTIONS)
    return out


def _coerce_uuid(value: str | None) -> uuid.UUID | None:
    """Best-effort UUID parse - returns ``None`` for malformed input.

    The unified search router already validates ``project_id`` via
    :func:`verify_project_access` upstream, but we still defensively
    parse here because ``tenant_id`` arrives raw and the SQL fallback
    must never raise.
    """
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def _accessible_project_ids(
    session: AsyncSession,
    user_id: str | None,
) -> set[uuid.UUID] | None:
    """Resolve the set of project UUIDs the caller may read.

    Returns ``None`` to mean *unrestricted* - admins (and an unknown /
    malformed user, which can only happen if the auth dependency is
    bypassed) see everything, mirroring the admin bypass in
    :func:`app.dependencies.verify_project_access`.

    Otherwise returns the set of project IDs the user owns OR is a team
    member of - exactly the scope used by
    :meth:`ProjectRepository.list_for_user`. This is what gates a
    cross-project (``project_id`` omitted) unified search so a user never
    receives hits from projects they cannot access (IDOR defence).
    """
    uid = _coerce_uuid(user_id)
    if uid is None:
        return None

    from app.modules.projects.models import Project
    from app.modules.teams.access import member_project_ids_subquery
    from app.modules.users.repository import UserRepository

    # Admin bypass - same policy as verify_project_access.
    try:
        user = await UserRepository(session).get_by_id(uid)
        if user is not None and getattr(user, "role", "") == "admin":
            return None
    except Exception:
        logger.exception("Admin-role lookup failed during search scope resolution")

    # Deleted projects are archived, not removed; their rows are not offered
    # as hits that open onto "Project not found".
    stmt = select(Project.id).where(
        or_(
            Project.owner_id == uid,
            Project.id.in_(member_project_ids_subquery(uid)),
        ),
        Project.status != "archived",
    )
    rows = (await session.execute(stmt)).scalars().all()
    return set(rows)


def _requirement_label(req: Any) -> str:
    """Name a requirement by the entity and attribute it constrains.

    That pair is how a requirement reads on its own page, but both halves may
    be empty while the row is still findable by its constraint value or its
    notes, and ``f"{entity}.{attribute}"`` then leaves a lone dot standing in
    for a title. The remaining searched columns take over in that case, so the
    hit is always named by something the reader could have typed to find it.

    Args:
        req: A requirement row.

    Returns:
        A display label, empty only when the row answers none of its columns.
    """
    pair = ".".join(part for part in ((req.entity or "").strip(), (req.attribute or "").strip()) if part)
    return (pair or (req.constraint_value or "").strip() or (req.notes or "").strip())[:160]


def _hit_from_row(
    *,
    row_id: object,
    title: str,
    snippet: str,
    collection: str,
    project_id: str = "",
    tenant_id: str = "",
    payload: dict[str, Any] | None = None,
    rank_score: float = 0.0,
) -> VectorHit:
    """Build a :class:`VectorHit` from an ORM row's display fields.

    ``rank_score`` is left at zero here because the per-collection
    branches below have no relevance signal to offer - Postgres reports
    only that the ILIKE matched, never how well. The score is filled in
    afterwards by :func:`_sql_search_collection`, which sees the query
    text alongside the assembled hit and can measure the match. Leaving
    it at zero and never filling it in is what shipped every hit to the
    frontend at 0%.
    """
    return VectorHit(
        id=str(row_id),
        score=rank_score,
        text=snippet,
        module=COLLECTION_LABELS.get(collection, collection),
        project_id=project_id,
        tenant_id=tenant_id,
        payload=payload or {"title": title},
        collection=collection,
    )


# Every hit handed back by the SQL track matched the ILIKE, so none of
# them is a non-match. This is the floor the lexical scale starts from,
# so the weakest surviving hit still reads as a match rather than as a
# zero the reader would take for "irrelevant".
_LEXICAL_FLOOR = 0.2


def _lexical_score(query: str, hit: VectorHit) -> float:
    """Score how well *hit* matches *query*, on a 0.0-1.0 scale.

    The SQL track has no relevance signal of its own: an ILIKE answers
    "matched" or "did not match", and the ``ORDER BY created_at DESC``
    in each branch below is recency. Fusing that order alone would give
    the caller a number that encodes only which row is newest, which is
    an arbitrary order wearing a relevance score.

    Three signals, in descending weight:

    * where the phrase landed - a hit on the title outranks one buried
      in the body text,
    * how many of the query's terms appear at all - a two-word query
      fully covered outranks one that matched on a single word,
    * how much of the matched field the phrase accounts for - a short
      title matched end to end outranks the same phrase inside a long
      paragraph.

    The result is floored at :data:`_LEXICAL_FLOOR` because the caller
    only ever passes hits the ILIKE already accepted.

    Args:
        query: The raw user query, as typed.
        hit: A hit assembled by :func:`_hit_from_row`.

    Returns:
        A relevance score in ``[_LEXICAL_FLOOR, 1.0]``.
    """
    needle = query.strip().lower()
    if not needle:
        return 0.0

    title = (hit.title or "").lower()
    body = (hit.text or "").lower()

    if title == needle:
        phrase = 1.0
    elif title.startswith(needle):
        phrase = 0.85
    elif needle in title:
        phrase = 0.7
    elif needle in body:
        phrase = 0.45
    else:
        # The ILIKE matched a column that is neither the display title
        # nor the snippet - a BOQ ordinal or a risk code, say. Still a
        # real match, just not one we can locate in the visible text.
        phrase = 0.0

    terms = [term for term in re.split(r"\W+", needle) if term]
    haystack = f"{title} {body}"
    term_ratio = sum(1 for term in terms if term in haystack) / len(terms) if terms else 0.0

    if needle in title:
        matched_field = title
    elif needle in body:
        matched_field = body
    else:
        # Nothing to measure coverage against - the phrase is in neither
        # visible field, so it contributes nothing rather than a ratio
        # taken over text it never appeared in.
        matched_field = ""
    coverage = min(len(needle) / len(matched_field), 1.0) if matched_field else 0.0

    quality = 0.6 * phrase + 0.25 * term_ratio + 0.15 * coverage
    return round(_LEXICAL_FLOOR + (1.0 - _LEXICAL_FLOOR) * quality, 6)


async def _sql_search_collection(
    session: AsyncSession,
    collection: str,
    query: str,
    *,
    project_id: str | None = None,
    tenant_id: str | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    limit: int = 10,
) -> list[VectorHit]:
    """ILIKE substring search against *collection*, ranked by match quality.

    Thin wrapper over :func:`_sql_search_collection_raw`: it takes the
    rows Postgres matched and puts them in relevance order, because the
    raw query can only order by recency. Each hit is scored by
    :func:`_lexical_score` and the list is sorted on that score, stably,
    so hits of equal match quality keep the newest-first order the SQL
    branch gave them.

    Args:
        session: Live async session; one is shared across all collections.
        collection: Canonical collection name (``oe_*``).
        query: The raw user query, as typed.
        project_id: Pin to a single, already-authorised project.
        tenant_id: Reserved; most tables carry no tenant column yet.
        allowed_project_ids: Cross-project access fence. ``None`` means
            unrestricted, an empty set means nothing is readable.
        limit: Maximum rows to take from the backing table.

    Returns:
        Hits in descending relevance order, each carrying a non-zero score.
    """
    hits = await _sql_search_collection_raw(
        session,
        collection,
        query,
        project_id=project_id,
        tenant_id=tenant_id,
        allowed_project_ids=allowed_project_ids,
        limit=limit,
    )
    for hit in hits:
        hit.score = _lexical_score(query, hit)
    return sorted(hits, key=lambda hit: hit.score, reverse=True)


async def _sql_search_collection_raw(
    session: AsyncSession,
    collection: str,
    query: str,
    *,
    project_id: str | None = None,
    tenant_id: str | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    limit: int = 10,
) -> list[VectorHit]:
    """ILIKE substring search against the table backing *collection*.

    Recall only - call :func:`_sql_search_collection` instead, which
    wraps this and puts the rows in relevance order. Returns a list of
    :class:`VectorHit` objects with the same shape as the vector path,
    so the fusion layer doesn't need to know which track produced each
    hit. Empty list if the collection has no SQL fallback wired
    (validation, chat, bim_elements - those are inherently vector-only
    or live outside core ORM tables).

    The match is a single OR'd ILIKE across the canonical text columns
    of each table, ordered newest-first because SQL has no semantic
    similarity to lean on. That order is recency, not relevance, which
    is why the wrapper re-ranks; it survives here as the tie-break
    between hits the wrapper scores equally.

    Access scoping: when ``project_id`` is given the query is pinned to
    that single project (the router already ran ``verify_project_access``).
    When it is omitted, ``allowed_project_ids`` restricts the search to the
    projects the caller may read - ``None`` means unrestricted (admin),
    an empty set means "no accessible projects" so nothing is returned.
    Shared catalogs without a project column (costs) are exempt.
    """
    pattern = f"%{query.strip()}%"
    if not pattern.strip("%"):
        return []

    project_uuid = _coerce_uuid(project_id)
    _ = _coerce_uuid(tenant_id)  # Reserved - most tables don't have tenant_id yet.

    def _scope(stmt: Any, project_col: Any) -> Any:
        """Apply per-project access scoping to a project-bearing query.

        When a single ``project_id`` is supplied it pins the query to it.
        Otherwise the cross-project search is fenced to the caller's
        accessible projects (IDOR defence); an empty allow-set yields an
        impossible predicate so the collection returns no rows.
        """
        if project_uuid is not None:
            return stmt.where(project_col == project_uuid)
        if allowed_project_ids is not None:
            if not allowed_project_ids:
                return stmt.where(sql_false())
            return stmt.where(project_col.in_(allowed_project_ids))
        return stmt

    if collection == COLLECTION_BOQ:
        from app.modules.boq.models import BOQ, Position

        stmt = (
            select(Position, BOQ)
            .join(BOQ, BOQ.id == Position.boq_id)
            .where(
                or_(
                    Position.description.ilike(pattern),
                    Position.ordinal.ilike(pattern),
                )
            )
            .order_by(Position.created_at.desc())
            .limit(limit)
        )
        stmt = _scope(stmt, BOQ.project_id)
        rows = (await session.execute(stmt)).all()
        return [
            _hit_from_row(
                row_id=pos.id,
                # The ordinal is searched, so it has to be able to name the
                # hit: an undescribed position found by its number carried no
                # title and no snippet, and reached the reader as a bare id.
                title=(pos.description or pos.ordinal or "")[:160],
                snippet=(pos.description or "")[:220],
                collection=collection,
                project_id=str(boq.project_id) if boq.project_id else "",
                payload={
                    "title": (pos.description or pos.ordinal or "")[:160],
                    "ordinal": pos.ordinal or "",
                    "unit": pos.unit or "",
                    "boq_id": str(pos.boq_id) if pos.boq_id else "",
                },
            )
            for pos, boq in rows
        ]

    if collection == COLLECTION_TASKS:
        from app.modules.tasks.models import Task

        stmt = (
            select(Task)
            .where(
                or_(
                    Task.title.ilike(pattern),
                    Task.description.ilike(pattern),
                )
            )
            .order_by(Task.created_at.desc())
            .limit(limit)
        )
        stmt = _scope(stmt, Task.project_id)
        tasks = (await session.execute(stmt)).scalars().all()
        return [
            _hit_from_row(
                row_id=t.id,
                title=(t.title or "")[:160],
                snippet=(t.description or t.title or "")[:220],
                collection=collection,
                project_id=str(t.project_id) if t.project_id else "",
                payload={
                    "title": (t.title or "")[:160],
                    "status": t.status or "",
                    "task_type": getattr(t, "task_type", "") or "",
                },
            )
            for t in tasks
        ]

    if collection == COLLECTION_RISKS:
        from app.modules.risk.models import RiskItem

        stmt = (
            select(RiskItem)
            .where(
                or_(
                    RiskItem.title.ilike(pattern),
                    RiskItem.description.ilike(pattern),
                    RiskItem.code.ilike(pattern),
                )
            )
            .order_by(RiskItem.created_at.desc())
            .limit(limit)
        )
        stmt = _scope(stmt, RiskItem.project_id)
        risks = (await session.execute(stmt)).scalars().all()
        return [
            _hit_from_row(
                row_id=r.id,
                # A risk is searched by its code as well, and a register entry
                # can hold a code before anyone has written its title.
                title=(r.title or r.code or "")[:160],
                snippet=(r.description or r.title or "")[:220],
                collection=collection,
                project_id=str(r.project_id) if r.project_id else "",
                payload={
                    "title": (r.title or r.code or "")[:160],
                    "code": r.code or "",
                    "status": r.status or "",
                    "category": r.category or "",
                },
            )
            for r in risks
        ]

    if collection == COLLECTION_DOCUMENTS:
        from app.modules.documents.models import Document

        stmt = (
            select(Document)
            .where(
                or_(
                    Document.name.ilike(pattern),
                    Document.description.ilike(pattern),
                )
            )
            .order_by(Document.created_at.desc())
            .limit(limit)
        )
        stmt = _scope(stmt, Document.project_id)
        docs = (await session.execute(stmt)).scalars().all()
        return [
            _hit_from_row(
                row_id=d.id,
                title=(d.name or "")[:160],
                snippet=(d.description or d.name or "")[:220],
                collection=collection,
                project_id=str(d.project_id) if d.project_id else "",
                payload={
                    "title": (d.name or "")[:160],
                    "category": d.category or "",
                },
            )
            for d in docs
        ]

    if collection == COLLECTION_REQUIREMENTS:
        from app.modules.requirements.models import Requirement, RequirementSet

        stmt = (
            select(Requirement, RequirementSet)
            .join(RequirementSet, RequirementSet.id == Requirement.requirement_set_id)
            .where(
                or_(
                    Requirement.entity.ilike(pattern),
                    Requirement.attribute.ilike(pattern),
                    Requirement.constraint_value.ilike(pattern),
                    Requirement.notes.ilike(pattern),
                )
            )
            .order_by(Requirement.created_at.desc())
            .limit(limit)
        )
        stmt = _scope(stmt, RequirementSet.project_id)
        rows = (await session.execute(stmt)).all()
        return [
            _hit_from_row(
                row_id=req.id,
                title=_requirement_label(req),
                snippet=f"{req.constraint_type} {req.constraint_value}"[:220],
                collection=collection,
                project_id=str(rset.project_id) if rset.project_id else "",
                payload={
                    "title": _requirement_label(req),
                    "constraint": (f"{req.constraint_type} {req.constraint_value}")[:160],
                    "status": req.status or "",
                    "priority": req.priority or "",
                },
            )
            for req, rset in rows
        ]

    if collection == COLLECTION_RFI:
        from app.modules.rfi.models import RFI

        stmt = (
            select(RFI)
            .where(
                or_(
                    RFI.subject.ilike(pattern),
                    RFI.question.ilike(pattern),
                    RFI.official_response.ilike(pattern),
                    RFI.rfi_number.ilike(pattern),
                )
            )
            .order_by(RFI.created_at.desc())
            .limit(limit)
        )
        stmt = _scope(stmt, RFI.project_id)
        rfis = (await session.execute(stmt)).scalars().all()
        return [
            _hit_from_row(
                row_id=r.id,
                title=(r.subject or r.rfi_number or "")[:160],
                snippet=(r.question or r.official_response or r.subject or "")[:220],
                collection=collection,
                project_id=str(r.project_id) if r.project_id else "",
                payload={
                    "title": (r.subject or r.rfi_number or "")[:160],
                    "rfi_number": r.rfi_number or "",
                    "status": r.status or "",
                    "discipline": getattr(r, "discipline", "") or "",
                },
            )
            for r in rfis
        ]

    if collection == COLLECTION_SUBMITTALS:
        from app.modules.submittals.models import Submittal

        stmt = (
            select(Submittal)
            .where(
                or_(
                    Submittal.title.ilike(pattern),
                    Submittal.spec_section.ilike(pattern),
                    Submittal.submittal_number.ilike(pattern),
                )
            )
            .order_by(Submittal.created_at.desc())
            .limit(limit)
        )
        stmt = _scope(stmt, Submittal.project_id)
        submittals = (await session.execute(stmt)).scalars().all()
        return [
            _hit_from_row(
                row_id=s.id,
                # The spec section is searched and is often the only thing a
                # submittal carries while it is still being raised.
                title=(s.title or s.submittal_number or s.spec_section or "")[:160],
                snippet=(f"{s.submittal_number} - {s.title}" if s.submittal_number else (s.title or ""))[:220],
                collection=collection,
                project_id=str(s.project_id) if s.project_id else "",
                payload={
                    "title": (s.title or s.submittal_number or s.spec_section or "")[:160],
                    "submittal_number": s.submittal_number or "",
                    "status": s.status or "",
                    "submittal_type": getattr(s, "submittal_type", "") or "",
                    "spec_section": getattr(s, "spec_section", "") or "",
                },
            )
            for s in submittals
        ]

    if collection == COLLECTION_CORRESPONDENCE:
        from app.modules.correspondence.models import Correspondence

        stmt = (
            select(Correspondence)
            .where(
                or_(
                    Correspondence.subject.ilike(pattern),
                    Correspondence.notes.ilike(pattern),
                    Correspondence.reference_number.ilike(pattern),
                )
            )
            .order_by(Correspondence.created_at.desc())
            .limit(limit)
        )
        stmt = _scope(stmt, Correspondence.project_id)
        rows = (await session.execute(stmt)).scalars().all()
        return [
            _hit_from_row(
                row_id=c.id,
                title=(c.subject or c.reference_number or "")[:160],
                snippet=(c.notes or c.subject or "")[:220],
                collection=collection,
                project_id=str(c.project_id) if c.project_id else "",
                payload={
                    "title": (c.subject or c.reference_number or "")[:160],
                    "reference_number": c.reference_number or "",
                    "direction": getattr(c, "direction", "") or "",
                    "correspondence_type": getattr(c, "correspondence_type", "") or "",
                },
            )
            for c in rows
        ]

    if collection == COLLECTION_COSTS:
        from app.modules.costs.models import CostItem

        stmt = (
            select(CostItem)
            .where(
                CostItem.is_active.is_(True),
                or_(
                    CostItem.code.ilike(pattern),
                    CostItem.description.ilike(pattern),
                ),
            )
            .order_by(CostItem.code)
            .limit(limit)
        )
        items = (await session.execute(stmt)).scalars().all()
        return [
            _hit_from_row(
                row_id=item.id,
                # The code is searched, and a rate can be filed under a code
                # before anyone writes the description that names it.
                title=(item.description or item.code or "")[:160],
                snippet=f"{item.code} - {item.description}"[:220],
                collection=collection,
                payload={
                    "title": (item.description or item.code or "")[:160],
                    "code": item.code or "",
                    "unit": item.unit or "",
                    "rate": str(item.rate) if item.rate else "",
                    "currency": item.currency or "",
                },
            )
            for item in items
        ]

    if collection == COLLECTION_CHANGE_ORDERS:
        from app.modules.changeorders.models import ChangeOrder

        stmt = (
            select(ChangeOrder)
            .where(
                or_(
                    ChangeOrder.title.ilike(pattern),
                    ChangeOrder.description.ilike(pattern),
                    ChangeOrder.code.ilike(pattern),
                )
            )
            .order_by(ChangeOrder.created_at.desc())
            .limit(limit)
        )
        stmt = _scope(stmt, ChangeOrder.project_id)
        orders = (await session.execute(stmt)).scalars().all()
        return [
            _hit_from_row(
                row_id=co.id,
                title=(co.title or co.code or "")[:160],
                snippet=(co.description or co.title or "")[:220],
                collection=collection,
                project_id=str(co.project_id) if co.project_id else "",
                payload={
                    "title": (co.title or co.code or "")[:160],
                    "code": co.code or "",
                    "status": co.status or "",
                    "ball_in_court": co.ball_in_court or "",
                },
            )
            for co in orders
        ]

    if collection == COLLECTION_MOC:
        from app.modules.moc.models import MoCEntry

        stmt = (
            select(MoCEntry)
            .where(
                or_(
                    MoCEntry.title.ilike(pattern),
                    MoCEntry.description.ilike(pattern),
                    MoCEntry.code.ilike(pattern),
                )
            )
            .order_by(MoCEntry.created_at.desc())
            .limit(limit)
        )
        stmt = _scope(stmt, MoCEntry.project_id)
        entries = (await session.execute(stmt)).scalars().all()
        return [
            _hit_from_row(
                row_id=m.id,
                title=(m.title or m.code or "")[:160],
                snippet=(m.description or m.title or "")[:220],
                collection=collection,
                project_id=str(m.project_id) if m.project_id else "",
                payload={
                    "title": (m.title or m.code or "")[:160],
                    "code": m.code or "",
                    "status": m.status or "",
                    "risk_level": m.risk_level or "",
                    "ball_in_court": m.ball_in_court or "",
                },
            )
            for m in entries
        ]

    if collection == COLLECTION_VARIATIONS:
        # One "Variations" surface spanning the three variation entities -
        # early-warning notice, variation request and variation order - each
        # tagged in the payload by ``kind`` so the UI can distinguish them.
        from app.modules.variations.models import Notice, VariationOrder, VariationRequest

        collected: list[tuple[Any, VectorHit]] = []

        notices = (
            (
                await session.execute(
                    _scope(
                        select(Notice)
                        .where(
                            or_(
                                Notice.title.ilike(pattern),
                                Notice.description.ilike(pattern),
                                Notice.code.ilike(pattern),
                            )
                        )
                        .order_by(Notice.created_at.desc())
                        .limit(limit),
                        Notice.project_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        collected += [
            (
                n.created_at,
                _hit_from_row(
                    row_id=n.id,
                    title=(n.title or n.code or "")[:160],
                    snippet=(n.description or n.title or "")[:220],
                    collection=collection,
                    project_id=str(n.project_id) if n.project_id else "",
                    payload={
                        "title": (n.title or n.code or "")[:160],
                        "code": n.code or "",
                        "kind": "notice",
                        "status": n.status or "",
                        "ball_in_court": n.ball_in_court or "",
                    },
                ),
            )
            for n in notices
        ]

        requests = (
            (
                await session.execute(
                    _scope(
                        select(VariationRequest)
                        .where(
                            or_(
                                VariationRequest.title.ilike(pattern),
                                VariationRequest.description.ilike(pattern),
                                VariationRequest.code.ilike(pattern),
                            )
                        )
                        .order_by(VariationRequest.created_at.desc())
                        .limit(limit),
                        VariationRequest.project_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        collected += [
            (
                vr.created_at,
                _hit_from_row(
                    row_id=vr.id,
                    title=(vr.title or vr.code or "")[:160],
                    snippet=(vr.description or vr.title or "")[:220],
                    collection=collection,
                    project_id=str(vr.project_id) if vr.project_id else "",
                    payload={
                        "title": (vr.title or vr.code or "")[:160],
                        "code": vr.code or "",
                        "kind": "request",
                        "status": vr.status or "",
                        "ball_in_court": vr.ball_in_court or "",
                    },
                ),
            )
            for vr in requests
        ]

        orders = (
            (
                await session.execute(
                    _scope(
                        select(VariationOrder)
                        .where(
                            or_(
                                VariationOrder.title.ilike(pattern),
                                VariationOrder.code.ilike(pattern),
                            )
                        )
                        .order_by(VariationOrder.created_at.desc())
                        .limit(limit),
                        VariationOrder.project_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        collected += [
            (
                vo.created_at,
                _hit_from_row(
                    row_id=vo.id,
                    title=(vo.title or vo.code or "")[:160],
                    snippet=(vo.title or vo.code or "")[:220],
                    collection=collection,
                    project_id=str(vo.project_id) if vo.project_id else "",
                    payload={
                        "title": (vo.title or vo.code or "")[:160],
                        "code": vo.code or "",
                        "kind": "order",
                        "status": vo.status or "",
                        "ball_in_court": vo.ball_in_court or "",
                    },
                ),
            )
            for vo in orders
        ]

        # Newest first across all three variation entities, capped at limit.
        collected.sort(key=lambda pair: pair[0], reverse=True)
        return [hit for _, hit in collected[:limit]]

    # Collections without a SQL fallback (chat, validation, bim_elements
    # via DDC canonical store, …) fall through to the empty list. The
    # vector track is still attempted, so the user-visible behaviour
    # only degrades for these specific surfaces - the rest still work.
    if collection in (COLLECTION_CHAT, COLLECTION_VALIDATION, COLLECTION_BIM_ELEMENTS):
        return []
    return []


def _filter_vector_hits_by_access(
    rankings: list[list[VectorHit]],
    allowed_project_ids: set[uuid.UUID] | None,
) -> list[list[VectorHit]]:
    """Drop vector hits whose project the caller may not read.

    Mirrors the SQL-track scoping for the cross-project case: a hit is
    kept only when its ``project_id`` is in ``allowed_project_ids``.
    Hits with no project (empty ``project_id`` - shared catalogs such as
    costs, and inherently cross-project collections) are kept because
    they carry no per-project access decision. ``None`` means unrestricted
    (admin), so nothing is filtered.
    """
    if allowed_project_ids is None:
        return list(rankings)
    out: list[list[VectorHit]] = []
    for ranking in rankings:
        kept: list[VectorHit] = []
        for hit in ranking:
            pid = _coerce_uuid(getattr(hit, "project_id", "") or None)
            if pid is None or pid in allowed_project_ids:
                kept.append(hit)
        out.append(kept)
    return out


async def unified_search_service(
    query: str,
    *,
    user_id: str | None = None,
    types: list[str] | None = None,
    project_id: str | None = None,
    tenant_id: str | None = None,
    limit_per_collection: int = 10,
    final_limit: int = 25,
) -> UnifiedSearchResponse:
    """Search every selected collection in parallel and merge via RRF.

    Two-track recall: vector ANN + SQL ILIKE substring. Both are always
    attempted; the SQL track is the safety net when LanceDB is missing
    or the collection hasn't been embedded. Results are fused via RRF
    so the user gets a single coherent ranking.

    Project-scoped queries pass ``project_id`` to drop hits from other
    projects at both layers (vector filter on the embedding payload,
    SQL ``WHERE project_id = …`` clause). The router already verified the
    caller's access to that single project.

    Cross-project queries (``project_id`` omitted) are fenced to the
    projects ``user_id`` may read - owned or team-member, with an admin
    bypass - so the unified search never leaks data from projects the
    caller has no access to (IDOR defence).
    """
    import asyncio

    chosen = _normalize_types(types)

    # Vector track - best-effort, always tried first. Returns [] when
    # LanceDB is unavailable or the collection is empty (the helper
    # logs and swallows internally).
    vector_coros = [
        search_collection(
            collection,
            query,
            project_id=project_id,
            tenant_id=tenant_id,
            limit=limit_per_collection,
        )
        for collection in chosen
    ]
    vector_rankings = await asyncio.gather(*vector_coros, return_exceptions=False)

    # SQL track - always evaluated. Single shared session so all per-
    # collection queries share a single connection and roundtrip. The
    # same session resolves the caller's accessible projects for the
    # cross-project access fence.
    sql_rankings: list[list[VectorHit]] = []
    async with async_session_factory() as session:
        # Only resolve the accessible-project fence for cross-project
        # searches; when project_id is set the router already authorised it.
        allowed_project_ids = None if project_id else await _accessible_project_ids(session, user_id)
        for collection in chosen:
            try:
                hits = await _sql_search_collection(
                    session,
                    collection,
                    query,
                    project_id=project_id,
                    tenant_id=tenant_id,
                    allowed_project_ids=allowed_project_ids,
                    limit=limit_per_collection,
                )
            except Exception as exc:
                logger.debug("_sql_search_collection(%s) failed: %s", collection, exc)
                hits = []
            sql_rankings.append(hits)

    # Apply the same access fence to the vector track. For a single
    # authorised project_id the vector layer already filtered on the
    # embedding payload, so allowed_project_ids stays None and this is a
    # no-op; for cross-project searches it drops out-of-scope hits.
    vector_rankings = _filter_vector_hits_by_access(vector_rankings, allowed_project_ids)

    # Per-collection facet counts include hits from both tracks,
    # deduplicated by id so the badge reflects unique items.
    facets: dict[str, int] = {}
    for collection, vec, sql in zip(chosen, vector_rankings, sql_rankings, strict=False):
        seen: set[str] = set()
        for h in (*vec, *sql):
            seen.add(h.id)
        facets[collection] = len(seen)

    # Fuse vector and SQL rankings together. RRF treats each ranking
    # list independently, so passing both flat lists gives the vector
    # hit a boost when it ALSO appears in the SQL list (and vice versa).
    fused = reciprocal_rank_fusion([*vector_rankings, *sql_rankings])
    fused = fused[:final_limit]

    hits = [
        UnifiedSearchHit(
            id=h.id,
            score=h.score,
            title=h.title,
            snippet=h.snippet,
            text=h.text,
            module=h.module or COLLECTION_LABELS.get(h.collection, h.collection),
            project_id=h.project_id,
            tenant_id=h.tenant_id,
            payload=h.payload,
            collection=h.collection,
        )
        for h in fused
    ]
    return UnifiedSearchResponse(
        query=query,
        types=chosen,
        project_id=project_id,
        total=len(hits),
        hits=hits,
        facets=facets,
    )


def search_status_snapshot() -> SearchStatusResponse:
    """Aggregate status from every collection - used by the search status
    endpoint and the global health page."""
    raw: dict[str, Any] = all_collection_status()
    multi = raw.get("multi_collection") or {}
    collections = [
        CollectionStatusItem(
            collection=meta.get("collection", name),
            label=meta.get("label", name),
            vectors_count=int(meta.get("vectors_count", 0) or 0),
            ready=bool(meta.get("ready", False)),
        )
        for name, meta in multi.items()
    ]
    return SearchStatusResponse(
        backend=str(raw.get("backend", "")),
        engine=str(raw.get("engine", "")),
        model_name=str(raw.get("model_name", "")),
        embedding_dim=int(raw.get("embedding_dim", 0) or 0),
        connected=bool(raw.get("connected", False)),
        collections=collections,
        cost_collection=raw.get("cost_collection"),
    )
