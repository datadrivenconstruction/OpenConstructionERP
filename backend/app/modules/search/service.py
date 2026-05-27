"""‌⁠‍Unified search service — fan-out + RRF over every vector collection.

Architecture
------------

The unified search is a two-track recall system:

1. Vector track — :func:`search_collection` from :mod:`app.core.vector_index`
   embeds the query once and runs ANN over every selected collection.
   Best at semantic recall ("reinforced concrete walls" matches "RC
   wall 240mm") but requires LanceDB / Qdrant to be installed AND for
   the collections to have been indexed.

2. SQL track — :func:`_sql_search_collection` runs ILIKE substring
   matches against the canonical text columns of each collection's
   backing table. Lower recall but ALWAYS available — it's the
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
import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vector_index import (
    ALL_COLLECTIONS,
    COLLECTION_BIM_ELEMENTS,
    COLLECTION_BOQ,
    COLLECTION_CHAT,
    COLLECTION_COSTS,
    COLLECTION_DOCUMENTS,
    COLLECTION_LABELS,
    COLLECTION_REQUIREMENTS,
    COLLECTION_RISKS,
    COLLECTION_TASKS,
    COLLECTION_VALIDATION,
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
    "validation": "oe_validation",
    "chat": "oe_chat",
}


def _normalize_types(raw: list[str] | None) -> list[str]:
    """‌⁠‍Resolve a list of user-supplied type names to canonical collections."""
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
    """Best-effort UUID parse — returns ``None`` for malformed input.

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

    The score is irrelevant for the fused output (RRF is rank-based),
    but we set a small positive value so any downstream consumer that
    sorts by raw score before fusion still gets a sensible order.
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


async def _sql_search_collection(
    session: AsyncSession,
    collection: str,
    query: str,
    *,
    project_id: str | None = None,
    tenant_id: str | None = None,
    limit: int = 10,
) -> list[VectorHit]:
    """ILIKE substring search against the table backing *collection*.

    Returns a ranked list of :class:`VectorHit` objects with the same
    shape as the vector path, so the fusion layer doesn't need to know
    which track produced each hit. Empty list if the collection has
    no SQL fallback wired (validation, chat, bim_elements — those are
    inherently vector-only or live outside core ORM tables).

    The match is a single OR'd ILIKE across the canonical text columns
    of each table. The ranking inside the SQL layer is "definition
    order" — first match wins — because SQL has no semantic similarity
    to lean on. Fusion via RRF mixes this rank with the vector rank.
    """
    pattern = f"%{query.strip()}%"
    if not pattern.strip("%"):
        return []

    project_uuid = _coerce_uuid(project_id)
    _ = _coerce_uuid(tenant_id)  # Reserved — most tables don't have tenant_id yet.

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
        if project_uuid is not None:
            stmt = stmt.where(BOQ.project_id == project_uuid)
        rows = (await session.execute(stmt)).all()
        return [
            _hit_from_row(
                row_id=pos.id,
                title=(pos.description or "")[:160],
                snippet=(pos.description or "")[:220],
                collection=collection,
                project_id=str(boq.project_id) if boq.project_id else "",
                payload={
                    "title": (pos.description or "")[:160],
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
        if project_uuid is not None:
            stmt = stmt.where(Task.project_id == project_uuid)
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
        if project_uuid is not None:
            stmt = stmt.where(RiskItem.project_id == project_uuid)
        risks = (await session.execute(stmt)).scalars().all()
        return [
            _hit_from_row(
                row_id=r.id,
                title=(r.title or "")[:160],
                snippet=(r.description or r.title or "")[:220],
                collection=collection,
                project_id=str(r.project_id) if r.project_id else "",
                payload={
                    "title": (r.title or "")[:160],
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
        if project_uuid is not None:
            stmt = stmt.where(Document.project_id == project_uuid)
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
        if project_uuid is not None:
            stmt = stmt.where(RequirementSet.project_id == project_uuid)
        rows = (await session.execute(stmt)).all()
        return [
            _hit_from_row(
                row_id=req.id,
                title=f"{req.entity}.{req.attribute}"[:160],
                snippet=f"{req.constraint_type} {req.constraint_value}"[:220],
                collection=collection,
                project_id=str(rset.project_id) if rset.project_id else "",
                payload={
                    "title": f"{req.entity}.{req.attribute}"[:160],
                    "constraint": (f"{req.constraint_type} {req.constraint_value}")[:160],
                    "status": req.status or "",
                    "priority": req.priority or "",
                },
            )
            for req, rset in rows
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
                title=(item.description or "")[:160],
                snippet=f"{item.code} — {item.description}"[:220],
                collection=collection,
                payload={
                    "title": (item.description or "")[:160],
                    "code": item.code or "",
                    "unit": item.unit or "",
                    "rate": str(item.rate) if item.rate else "",
                    "currency": item.currency or "",
                },
            )
            for item in items
        ]

    # Collections without a SQL fallback (chat, validation, bim_elements
    # via DDC canonical store, …) fall through to the empty list. The
    # vector track is still attempted, so the user-visible behaviour
    # only degrades for these specific surfaces — the rest still work.
    if collection in (COLLECTION_CHAT, COLLECTION_VALIDATION, COLLECTION_BIM_ELEMENTS):
        return []
    return []


async def unified_search_service(
    query: str,
    *,
    types: list[str] | None = None,
    project_id: str | None = None,
    tenant_id: str | None = None,
    limit_per_collection: int = 10,
    final_limit: int = 25,
) -> UnifiedSearchResponse:
    """‌⁠‍Search every selected collection in parallel and merge via RRF.

    Two-track recall: vector ANN + SQL ILIKE substring. Both are always
    attempted; the SQL track is the safety net when LanceDB is missing
    or the collection hasn't been embedded. Results are fused via RRF
    so the user gets a single coherent ranking.

    Project-scoped queries pass ``project_id`` to drop hits from other
    projects at both layers (vector filter on the embedding payload,
    SQL ``WHERE project_id = …`` clause).
    """
    import asyncio

    chosen = _normalize_types(types)

    # Vector track — best-effort, always tried first. Returns [] when
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

    # SQL track — always evaluated. Single shared session so all per-
    # collection queries share a single connection and roundtrip.
    sql_rankings: list[list[VectorHit]] = []
    async with async_session_factory() as session:
        for collection in chosen:
            try:
                hits = await _sql_search_collection(
                    session,
                    collection,
                    query,
                    project_id=project_id,
                    tenant_id=tenant_id,
                    limit=limit_per_collection,
                )
            except Exception as exc:
                logger.debug("_sql_search_collection(%s) failed: %s", collection, exc)
                hits = []
            sql_rankings.append(hits)

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
    """Aggregate status from every collection — used by the search status
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
