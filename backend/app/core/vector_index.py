"""Multi-collection embedding layer — the cross-module semantic memory.

This is the foundation that lets every business module (BOQ, documents,
tasks, risks, BIM elements, validation, chat, …) participate in the same
vector store with a uniform API.

Architecture
============

Each module ships a small ``vector_adapter.py`` that implements the
:class:`EmbeddingAdapter` protocol — defining its collection name, the
canonical text to embed for each row, and the lightweight payload that
should accompany the vector for hit rendering.  Hooking the adapter into
the event bus is then ~5 lines per module.

Read paths (search / similar items / unified search) all flow through
``search_collection`` and ``find_similar`` here, which:

  1. Encode the query text via :func:`~app.core.vector.encode_texts_async`
  2. Forward to :func:`~app.core.vector.vector_search_collection`
  3. Decode the JSON-encoded payload back into a dict
  4. Wrap each hit in a :class:`VectorHit` dataclass

Write paths (index_one / index_many / delete_one / reindex_collection)
likewise wrap :func:`~app.core.vector.vector_index_collection` and
:func:`~app.core.vector.vector_delete_collection`.

All operations are **non-fatal** — if the vector backend is unavailable
(LanceDB not installed, Qdrant unreachable, embedding model failed to
load) every helper logs a warning and returns an empty / no-op result.
The caller never has to wrap us in try/except.

Naming conventions
------------------

Collection names are short snake_case strings prefixed by the OE
namespace, e.g. ``oe_boq_positions``, ``oe_documents``, ``oe_tasks``,
``oe_risks``, ``oe_bim_elements``, ``oe_validation``, ``oe_chat``.  These
are exposed as constants in :mod:`app.core.vector_index` so each adapter
imports them rather than hard-coding strings.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.core.vector import (
    encode_texts_async,
    vector_count_collection,
    vector_delete_collection,
    vector_index_collection,
    vector_search_collection,
    vector_status as _vector_status_raw,
)

logger = logging.getLogger(__name__)


# ── Collection name constants ────────────────────────────────────────────
#
# Single source of truth so we never get a typo drift between adapter,
# router and unified search.  Add new collections here as you bring more
# modules online.

COLLECTION_BOQ = "oe_boq_positions"
COLLECTION_DOCUMENTS = "oe_documents"
COLLECTION_TASKS = "oe_tasks"
COLLECTION_RISKS = "oe_risks"
COLLECTION_BIM_ELEMENTS = "oe_bim_elements"
COLLECTION_VALIDATION = "oe_validation"
COLLECTION_CHAT = "oe_chat"

#: Ordered tuple used by :func:`unified_search` to fan out to every
#: registered collection when the caller doesn't specify ``types``.
ALL_COLLECTIONS: tuple[str, ...] = (
    COLLECTION_BOQ,
    COLLECTION_DOCUMENTS,
    COLLECTION_TASKS,
    COLLECTION_RISKS,
    COLLECTION_BIM_ELEMENTS,
    COLLECTION_VALIDATION,
    COLLECTION_CHAT,
)

#: Map collection name → human-readable module label.  Used by the
#: frontend Cmd+K modal to render facet badges and group hits.
COLLECTION_LABELS: dict[str, str] = {
    COLLECTION_BOQ: "BOQ",
    COLLECTION_DOCUMENTS: "Documents",
    COLLECTION_TASKS: "Tasks",
    COLLECTION_RISKS: "Risks",
    COLLECTION_BIM_ELEMENTS: "BIM Elements",
    COLLECTION_VALIDATION: "Validation",
    COLLECTION_CHAT: "Chat",
}


# ── Hit dataclass ────────────────────────────────────────────────────────


@dataclass(slots=True)
class VectorHit:
    """One semantic-search result from any collection.

    Attributes:
        id:            UUID string of the source row.
        score:         Cosine similarity in [0, 1] (higher = better).
        text:          The canonical text that was embedded.
        module:        Short module name ("boq", "documents", …).
        project_id:    Project UUID, or empty string if cross-project.
        tenant_id:     Tenant UUID for multi-tenant filtering.
        payload:       Decoded JSON payload — typically contains a
                       ``title`` field plus a few module-specific keys
                       like ``ordinal`` / ``status`` / ``unit``.
        collection:    Source collection name (set by the search wrapper).
    """

    id: str
    score: float
    text: str
    module: str
    project_id: str
    tenant_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    collection: str = ""

    @property
    def title(self) -> str:
        """Best-effort display title — falls back to a text snippet."""
        title = self.payload.get("title")
        if isinstance(title, str) and title:
            return title
        if self.text:
            return self.text[:120]
        return self.id

    @property
    def snippet(self) -> str:
        """Short text excerpt for hit cards (no markup)."""
        if not self.text:
            return ""
        if len(self.text) <= 220:
            return self.text
        return self.text[:217].rstrip() + "…"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "score": self.score,
            "text": self.text,
            "snippet": self.snippet,
            "title": self.title,
            "module": self.module,
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "payload": self.payload,
            "collection": self.collection,
        }


# ── EmbeddingAdapter protocol ────────────────────────────────────────────


@runtime_checkable
class EmbeddingAdapter(Protocol):
    """Protocol every per-module vector adapter must implement.

    Implementations live at ``app/modules/{module}/vector_adapter.py`` and
    are tiny — just `to_text` and `to_payload` over the SQLAlchemy row.

    Example
    -------
    ::

        class BOQPositionAdapter:
            collection_name = COLLECTION_BOQ
            module_name = "boq"

            def to_text(self, pos: Position) -> str:
                parts = [pos.description, pos.unit]
                if pos.classification:
                    parts.extend(str(v) for v in pos.classification.values())
                return " | ".join(p for p in parts if p)

            def to_payload(self, pos: Position) -> dict[str, Any]:
                return {
                    "title": pos.description[:120],
                    "ordinal": pos.ordinal,
                    "unit": pos.unit,
                    "boq_id": str(pos.boq_id),
                }

            def project_id_of(self, pos: Position) -> str | None:
                return None  # filled in by router via session lookup
    """

    collection_name: str
    module_name: str

    def to_text(self, row: Any) -> str: ...

    def to_payload(self, row: Any) -> dict[str, Any]: ...

    def project_id_of(self, row: Any) -> str | None:
        """Return the project UUID this row belongs to, or None."""
        ...


# ── Helpers ──────────────────────────────────────────────────────────────


def _coerce_id(row_id: Any) -> str:
    """Coerce a SQLAlchemy UUID / string id into the canonical string form."""
    if row_id is None:
        return ""
    return str(row_id)


def _safe_text(text: str | None) -> str:
    """Strip and clip text for embedding.  Empty input → empty string."""
    if not text:
        return ""
    cleaned = text.strip()
    # Sentence-transformers handles up to 512 tokens; clip well under to
    # avoid silent truncation surprises.
    if len(cleaned) > 4000:
        cleaned = cleaned[:4000]
    return cleaned


# ── Public write API ─────────────────────────────────────────────────────


async def index_one(
    adapter: EmbeddingAdapter,
    row: Any,
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
) -> bool:
    """Embed and upsert a single row into ``adapter.collection_name``.

    Returns ``True`` if the row was indexed, ``False`` otherwise.  Never
    raises — every failure is logged and swallowed so the caller (typically
    an event-bus subscriber) can stay one-line.
    """
    try:
        row_id = _coerce_id(getattr(row, "id", None))
        if not row_id:
            return False
        text = _safe_text(adapter.to_text(row))
        if not text:
            # Nothing to embed — make sure any stale entry is removed.
            await delete_one(adapter, row_id)
            return False
        try:
            vectors = await encode_texts_async([text])
        except Exception as exc:
            logger.debug(
                "vector_index.index_one: encode failed for %s: %s",
                adapter.collection_name,
                exc,
            )
            return False
        if not vectors:
            return False
        payload = adapter.to_payload(row) or {}
        item = {
            "id": row_id,
            "vector": vectors[0],
            "text": text,
            "tenant_id": tenant_id or "",
            "project_id": project_id or _coerce_id(adapter.project_id_of(row)) or "",
            "module": adapter.module_name,
            "payload": json.dumps(payload, ensure_ascii=False, default=str),
        }
        try:
            vector_index_collection(adapter.collection_name, [item])
        except Exception as exc:
            logger.debug(
                "vector_index.index_one: store failed for %s: %s",
                adapter.collection_name,
                exc,
            )
            return False
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("index_one(%s) failed: %s", adapter.collection_name, exc)
        return False


async def index_many(
    adapter: EmbeddingAdapter,
    rows: list[Any],
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    batch_size: int = 64,
) -> int:
    """Embed and upsert multiple rows in batches.

    Returns the number of rows successfully indexed.  Designed for backfill
    / reindex flows where you want to embed thousands of rows in one shot
    without exhausting GPU memory.
    """
    if not rows:
        return 0

    indexed = 0
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        texts: list[str] = []
        good_rows: list[Any] = []
        for row in chunk:
            row_id = _coerce_id(getattr(row, "id", None))
            if not row_id:
                continue
            text = _safe_text(adapter.to_text(row))
            if not text:
                continue
            texts.append(text)
            good_rows.append(row)
        if not texts:
            continue
        try:
            vectors = await encode_texts_async(texts)
        except Exception as exc:
            logger.debug("index_many: encode failed: %s", exc)
            continue
        if not vectors:
            continue
        items: list[dict[str, Any]] = []
        for row, text, vec in zip(good_rows, texts, vectors, strict=False):
            row_id = _coerce_id(getattr(row, "id", None))
            payload = adapter.to_payload(row) or {}
            items.append(
                {
                    "id": row_id,
                    "vector": vec,
                    "text": text,
                    "tenant_id": tenant_id or "",
                    "project_id": project_id
                    or _coerce_id(adapter.project_id_of(row))
                    or "",
                    "module": adapter.module_name,
                    "payload": json.dumps(payload, ensure_ascii=False, default=str),
                }
            )
        try:
            n = vector_index_collection(adapter.collection_name, items)
            indexed += n
        except Exception as exc:
            logger.debug("index_many: store failed: %s", exc)
            continue

    return indexed


async def delete_one(adapter: EmbeddingAdapter, row_id: str) -> bool:
    """Remove a single row from the adapter's collection.  Idempotent."""
    if not row_id:
        return False
    try:
        vector_delete_collection(adapter.collection_name, [_coerce_id(row_id)])
        return True
    except Exception as exc:
        logger.debug("delete_one(%s, %s) failed: %s", adapter.collection_name, row_id, exc)
        return False


async def delete_many(adapter: EmbeddingAdapter, row_ids: list[str]) -> int:
    """Remove multiple rows from the adapter's collection."""
    cleaned = [_coerce_id(r) for r in row_ids if r]
    if not cleaned:
        return 0
    try:
        return vector_delete_collection(adapter.collection_name, cleaned)
    except Exception as exc:
        logger.debug("delete_many(%s) failed: %s", adapter.collection_name, exc)
        return 0


# ── Public read API ──────────────────────────────────────────────────────


def _decode_payload(raw: Any) -> dict[str, Any]:
    """Best-effort payload decoding.  Always returns a dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            decoded = json.loads(raw)
            return decoded if isinstance(decoded, dict) else {}
        except Exception:
            return {}
    return {}


def _hit_from_raw(raw: dict[str, Any], collection: str) -> VectorHit:
    """Build a VectorHit from the raw dict returned by the LanceDB / Qdrant
    backend layer.  Tolerates partial / missing fields."""
    return VectorHit(
        id=str(raw.get("id", "")),
        score=float(raw.get("score", 0.0)),
        text=str(raw.get("text", "")),
        module=str(raw.get("module", "")),
        project_id=str(raw.get("project_id", "")),
        tenant_id=str(raw.get("tenant_id", "")),
        payload=_decode_payload(raw.get("payload")),
        collection=collection,
    )


async def search_collection(
    adapter_or_name: EmbeddingAdapter | str,
    query: str,
    *,
    project_id: str | None = None,
    tenant_id: str | None = None,
    limit: int = 10,
) -> list[VectorHit]:
    """Semantic search inside a single collection.

    ``adapter_or_name`` accepts either an EmbeddingAdapter instance or a
    bare collection name string — useful when the unified search router
    fans out to collections without instantiating per-module adapters.

    Returns an empty list if the embedding model is unavailable, the
    collection doesn't exist, or the query is empty.
    """
    text = _safe_text(query)
    if not text:
        return []
    try:
        vectors = await encode_texts_async([text])
    except Exception as exc:
        logger.debug("search_collection: encode failed: %s", exc)
        return []
    if not vectors:
        return []

    collection = (
        adapter_or_name
        if isinstance(adapter_or_name, str)
        else adapter_or_name.collection_name
    )
    try:
        raw_hits = vector_search_collection(
            collection,
            vectors[0],
            project_id=project_id,
            tenant_id=tenant_id,
            limit=limit,
        )
    except Exception as exc:
        logger.debug("search_collection(%s) failed: %s", collection, exc)
        return []

    return [_hit_from_raw(r, collection) for r in raw_hits]


async def find_similar(
    adapter: EmbeddingAdapter,
    row: Any,
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    cross_project: bool = False,
    limit: int = 5,
) -> list[VectorHit]:
    """Return rows most semantically similar to ``row``.

    Excludes the source row from the results.  When ``cross_project`` is
    True, the project filter is dropped so callers can find similar items
    across the whole tenant — invaluable for risk lessons-learned reuse
    and BOQ template suggestion.
    """
    row_id = _coerce_id(getattr(row, "id", None))
    text = _safe_text(adapter.to_text(row))
    if not text or not row_id:
        return []

    project_filter = (
        None
        if cross_project
        else (project_id or _coerce_id(adapter.project_id_of(row)) or None)
    )
    hits = await search_collection(
        adapter,
        text,
        project_id=project_filter,
        tenant_id=tenant_id,
        limit=limit + 1,  # +1 because the source row will probably show up
    )
    return [h for h in hits if h.id != row_id][:limit]


# ── Reciprocal Rank Fusion (used by unified search) ──────────────────────


def reciprocal_rank_fusion(
    rankings: list[list[VectorHit]],
    *,
    k: int = 60,
) -> list[VectorHit]:
    """Merge multiple ranked hit lists into a single global ranking.

    RRF is a parameter-free, score-agnostic fusion that works extremely
    well for combining ranked lists from heterogeneous retrievers — here
    each ranking comes from a different collection (BOQ, documents,
    tasks, …) and we want a single global "best of all worlds" list.

    Reference: Cormack, Clarke, Buettcher (2009).
    """
    score_by_id: dict[str, float] = {}
    hit_by_id: dict[str, VectorHit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            key = f"{hit.collection}:{hit.id}"
            score_by_id[key] = score_by_id.get(key, 0.0) + 1.0 / (k + rank)
            if key not in hit_by_id:
                hit_by_id[key] = hit
    fused = [
        (hit_by_id[key], score)
        for key, score in score_by_id.items()
    ]
    fused.sort(key=lambda pair: pair[1], reverse=True)
    return [hit for hit, _ in fused]


async def unified_search(
    query: str,
    *,
    types: list[str] | None = None,
    project_id: str | None = None,
    tenant_id: str | None = None,
    limit_per_collection: int = 10,
    final_limit: int = 20,
) -> list[VectorHit]:
    """Cross-collection semantic search.

    Fans out to every collection in ``types`` (or :data:`ALL_COLLECTIONS`
    if ``types`` is None), runs ``search_collection`` in parallel, and
    merges the results via :func:`reciprocal_rank_fusion`.
    """
    import asyncio

    chosen = types or list(ALL_COLLECTIONS)
    coros = [
        search_collection(
            collection,
            query,
            project_id=project_id,
            tenant_id=tenant_id,
            limit=limit_per_collection,
        )
        for collection in chosen
    ]
    rankings = await asyncio.gather(*coros, return_exceptions=False)
    fused = reciprocal_rank_fusion(rankings)
    return fused[:final_limit]


# ── Status / health ──────────────────────────────────────────────────────


def collection_status(collection_name: str) -> dict[str, Any]:
    """Return a small status snapshot for one collection."""
    count = 0
    try:
        count = vector_count_collection(collection_name)
    except Exception:
        pass
    return {
        "collection": collection_name,
        "label": COLLECTION_LABELS.get(collection_name, collection_name),
        "vectors_count": count,
        "ready": count > 0,
    }


def all_collection_status() -> dict[str, Any]:
    """Return per-collection status for the unified-search status endpoint."""
    overall = _vector_status_raw()
    overall["multi_collection"] = {
        c: collection_status(c) for c in ALL_COLLECTIONS
    }
    return overall


# ── Reindex helper used by per-module routers ────────────────────────────


async def reindex_collection(
    adapter: EmbeddingAdapter,
    rows: list[Any],
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    purge_first: bool = False,
) -> dict[str, Any]:
    """Backfill a collection from the ground up.

    If ``purge_first`` is True the entire collection is wiped before the
    new rows are indexed — useful when the embedding model changes and a
    full reindex is needed.

    Returns ``{"indexed": int, "skipped": int, "purged": bool}``.
    """
    purged = False
    if purge_first and rows:
        ids = [_coerce_id(getattr(r, "id", None)) for r in rows]
        try:
            vector_delete_collection(adapter.collection_name, [i for i in ids if i])
            purged = True
        except Exception as exc:
            logger.debug("reindex_collection: purge failed: %s", exc)

    indexed = await index_many(
        adapter,
        rows,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    return {
        "indexed": indexed,
        "skipped": max(0, len(rows) - indexed),
        "purged": purged,
        "collection": adapter.collection_name,
    }
