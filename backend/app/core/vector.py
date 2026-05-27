"""‌⁠‍Vector database integration — LanceDB (embedded) or Qdrant (server).

Default: LanceDB — embedded vector DB, runs in-process like SQLite.
No Docker, no server, no network. Data at ~/.openestimator/data/vectors/.

Alternative: Qdrant — for server/production deployments.
Switch via VECTOR_BACKEND=qdrant env var.

Usage:
    from app.core.vector import vector_db, encode_texts, vector_status

    vectors = encode_texts(["concrete wall 24cm C30/37"])
    vector_db().add(items)
    results = vector_db().search(query_vector, region="DE_BERLIN", limit=10)
"""

import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

COST_TABLE = "cost_items"
# Legacy default — kept as a fallback so existing CWICR LanceDB tables built
# with all-MiniLM-L6-v2 still load.  The active model is now resolved per call
# from `Settings.embedding_model_name` (multilingual by default).
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
QDRANT_SNAPSHOT_DIM = 3072  # Dimension for pre-built Qdrant snapshots from GitHub

# ── Multi-collection schemas ─────────────────────────────────────────────
#
# Generic collection schema used by every non-cost collection (BOQ, documents,
# tasks, risks, BIM elements, …).  All collections share this exact shape so
# the EmbeddingAdapter layer in `core/vector_index.py` can write to any one
# of them through the same code path.
#
#   id          UUID string — matches the source row PK
#   vector      list[float] — embedding (dimension = settings.embedding_model_dim)
#   text        canonical text that was embedded (for snippet rendering)
#   tenant_id   UUID string — multi-tenant scope filter
#   project_id  UUID string or "" — per-project scope filter
#   module      short module name ("boq", "documents", …)
#   payload     JSON string — light metadata for hit rendering without an
#               extra Postgres roundtrip (title, status, ordinal, etc.)
GENERIC_FIELDS: tuple[str, ...] = (
    "id",
    "vector",
    "text",
    "tenant_id",
    "project_id",
    "module",
    "payload",
)


# ── Embedding ──────────────────────────────────────────────────────────────


_embedder_instance: Any = None
_embedder_tried: bool = False


def _has_module(name: str) -> bool:
    """‌⁠‍Check if a module is importable WITHOUT actually importing it.

    Used during startup to report availability of optional dependencies
    (qdrant-client, sentence-transformers) without triggering heavy
    native imports like torch — which on Windows + Anaconda can cause
    MKL/OMP DLL conflicts that terminate the process silently.
    """
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _resolve_active_model() -> tuple[str, int]:
    """‌⁠‍Resolve the embedding model name + dim from settings.

    Returns ``(model_name, dim)``.  Settings are consulted lazily so that
    test fixtures can override them via the env var ``EMBEDDING_MODEL_NAME``
    without restarting the process.
    """
    try:
        from app.config import get_settings

        s = get_settings()
        return s.embedding_model_name, s.embedding_model_dim
    except Exception:
        return EMBEDDING_MODEL, EMBEDDING_DIM


_active_model_name: str | None = None


def get_embedder():
    """Get singleton embedding model.

    Resolution order:
        1. ``settings.embedding_model_name`` (multilingual-e5-small by default)
        2. ``settings.embedding_model_fallback`` (all-MiniLM-L6-v2)

    Uses sentence-transformers (PyTorch) directly.  FastEmbed is skipped
    because its ONNX model cache can become corrupted and hang on
    initialisation on Windows + Anaconda.

    Failure mode: once both primary and fallback models fail to load
    (offline install, broken HF cache, torch meta-tensor bug), the
    singleton stays ``None`` and ``_embedder_tried`` flips to ``True``
    so subsequent calls return ``None`` without re-running the multi-
    second download cascade. The cost-vector upsert path observed this
    in v2.9.30 — a stuck background task was hitting both models in a
    loop ~every second, burning ~10s of CPU per iteration and starving
    the match-elements request path of the GIL.
    """
    global _embedder_instance, _embedder_tried, _active_model_name
    if _embedder_instance is not None:
        return _embedder_instance
    # Short-circuit: a prior call exhausted both candidate models.
    # Without this guard every caller pays the multi-second retry cost.
    if _embedder_tried:
        return None

    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:
        logger.warning("sentence-transformers not installed: %s", exc)
        _embedder_tried = True
        return None

    primary, dim = _resolve_active_model()
    fallback_name = EMBEDDING_MODEL
    try:
        from app.config import get_settings

        fallback_name = get_settings().embedding_model_fallback or EMBEDDING_MODEL
    except Exception:
        pass

    for candidate in (primary, fallback_name):
        try:
            _embedder_instance = SentenceTransformer(candidate)
            _active_model_name = candidate
            logger.info(
                "Loaded sentence-transformers model: %s (~%dd)",
                candidate,
                dim,
            )
            return _embedder_instance
        except Exception as exc:
            logger.warning("Failed to load embedding model %s: %s", candidate, exc)
            continue

    logger.warning("No embedding model could be loaded (tried %s, %s)", primary, fallback_name)
    _embedder_tried = True
    return None


def active_model_name() -> str:
    """Return the model name currently loaded into memory, or the configured
    name if nothing has been loaded yet.  Used by ``vector_status()`` and the
    multi-collection layer to detect drift between an indexed collection and
    the live model.
    """
    if _active_model_name:
        return _active_model_name
    name, _ = _resolve_active_model()
    return name


def encode_texts(texts: list[str]) -> list[list[float]]:
    """Encode texts to vectors. Works with both FastEmbed and sentence-transformers."""
    embedder = get_embedder()
    if embedder is None:
        raise RuntimeError("No embedding model available. Install fastembed or sentence-transformers.")

    # FastEmbed returns generator
    if hasattr(embedder, "embed"):
        return [v.tolist() for v in embedder.embed(texts)]

    # sentence-transformers returns numpy array
    return embedder.encode(texts, show_progress_bar=False, batch_size=64).tolist()


async def encode_texts_async(texts: list[str]) -> list[list[float]]:
    """Async wrapper — dispatch encode based on current concurrency.

    Smart routing (see ``app.core.embedding_pool``):
        * If the configured pool is up AND another encode is currently
          in flight, dispatch this call to the pool so the two calls
          run on different workers in parallel.
        * Otherwise (no in-flight calls, or pool disabled), run encode
          inline via ``asyncio.to_thread`` — this avoids the IPC
          overhead a process pool would add for what's already a fast
          single call.

    The smart route gives us best-of-both-worlds:
        single-call p50 stays at ~300 ms (no pool overhead);
        50× concurrent p95 drops because the pool absorbs the burst.
    """
    import asyncio

    # Empty input — skip both pool dispatch and the embedder altogether.
    if not texts:
        return []

    try:
        from app.core import embedding_pool as _pool_mod
    except Exception:
        _pool_mod = None  # type: ignore[assignment]

    # Increment in-flight count so the NEXT concurrent caller sees
    # ``inflight > 1`` and routes to the pool. Wrap the whole call so
    # even on exception we decrement — a leak would mean every future
    # call routes to the pool unnecessarily.
    if _pool_mod is not None:
        _pool_mod._inflight += 1
    try:
        # Route to pool ONLY if (a) the pool is up and (b) at least
        # one OTHER call is in flight (so this one would otherwise
        # serialise behind it). With ``inflight == 1`` we're alone —
        # encode inline.
        if _pool_mod is not None and _pool_mod._pool is not None and _pool_mod._inflight > 1:
            try:
                pooled = await _pool_mod.encode_texts_pooled(texts)
                if pooled is not None:
                    return pooled
            except Exception:
                pass

        return await asyncio.to_thread(encode_texts, texts)
    finally:
        if _pool_mod is not None:
            _pool_mod._inflight = max(0, _pool_mod._inflight - 1)


# ── LanceDB (default, embedded) ───────────────────────────────────────────


def _get_vector_dir() -> Path:
    """Resolve LanceDB storage directory."""
    from app.config import get_settings

    settings = get_settings()
    if settings.vector_data_dir:
        p = Path(settings.vector_data_dir)
    else:
        p = Path.home() / ".openestimator" / "data" / "vectors"
    p.mkdir(parents=True, exist_ok=True)
    return p


_lancedb_instance: Any = None
_lancedb_tried: bool = False


def _get_lancedb():
    """Get singleton LanceDB connection. Retries if previously failed."""
    global _lancedb_instance, _lancedb_tried
    if _lancedb_instance is not None:
        return _lancedb_instance
    # Retry each time if not yet connected (e.g. package installed after startup)
    try:
        import lancedb

        db_path = str(_get_vector_dir())
        _lancedb_instance = lancedb.connect(db_path)
        logger.info("LanceDB connected at %s", db_path)
        return _lancedb_instance
    except Exception as exc:
        if not _lancedb_tried:
            logger.error("Failed to connect LanceDB: %s", exc)
            _lancedb_tried = True
        return None


def _lancedb_ensure_table(db: Any) -> bool:
    """Ensure cost_items table exists."""
    try:
        tables = db.table_names()
        if COST_TABLE not in tables:
            import pyarrow as pa

            schema = pa.schema(
                [
                    pa.field("id", pa.string()),
                    pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
                    pa.field("code", pa.string()),
                    pa.field("description", pa.string()),
                    pa.field("unit", pa.string()),
                    pa.field("rate", pa.float64()),
                    pa.field("region", pa.string()),
                ]
            )
            db.create_table(COST_TABLE, schema=schema)
            logger.info("Created LanceDB table: %s", COST_TABLE)
        return True
    except Exception as exc:
        logger.error("Failed to ensure LanceDB table: %s", exc)
        return False


def _lancedb_status() -> dict[str, Any]:
    """Get LanceDB status."""
    db = _get_lancedb()
    if db is None:
        return {"connected": False, "engine": "lancedb", "error": "LanceDB init failed"}

    try:
        tables = db.table_names()
        info: dict[str, Any] = {
            "connected": True,
            "engine": "lancedb",
            "path": str(_get_vector_dir()),
            "tables": len(tables),
        }
        if COST_TABLE in tables:
            tbl = db.open_table(COST_TABLE)
            info["cost_collection"] = {
                "vectors_count": tbl.count_rows(),
                "points_count": tbl.count_rows(),
                "status": "ready",
            }
        else:
            info["cost_collection"] = None
        # Multi-collection inventory — every non-cost collection registered by
        # the EmbeddingAdapter layer.  Lightweight: just a row count per table.
        generic_collections: dict[str, dict[str, Any]] = {}
        for table_name in tables:
            if table_name == COST_TABLE:
                continue
            try:
                tbl = db.open_table(table_name)
                generic_collections[table_name] = {
                    "vectors_count": tbl.count_rows(),
                    "status": "ready",
                }
            except Exception as exc:  # pragma: no cover - defensive
                generic_collections[table_name] = {"status": "error", "error": str(exc)}
        info["collections"] = generic_collections
        # LAZY checks — never instantiate heavy torch/qdrant during status.
        # Loading torch during startup on Windows + Anaconda can trigger
        # a silent MKL/OMP DLL conflict that terminates the process.
        #
        # ``can_restore_snapshots`` is False on LanceDB by design: the
        # Qdrant snapshot endpoint (3072-d embeddings, ~1.1 GB per region)
        # requires a running Qdrant server. Having ``qdrant_client``
        # pip-installed doesn't imply Qdrant is reachable — and the UI
        # used the flag to route clicks into the Qdrant path, which
        # raised "Qdrant not available" from /vector/restore-snapshot on
        # every region click. The LanceDB path (/vector/load-github)
        # already covers all regions with 384-d embeddings; snapshots
        # are a Qdrant-only feature.
        info["can_restore_snapshots"] = False
        info["can_generate_locally"] = _has_module("sentence_transformers")
        info["embedding_dim"] = EMBEDDING_DIM
        info["backend"] = "lancedb"
        info["model_name"] = active_model_name()
        return info
    except Exception as exc:
        return {"connected": False, "engine": "lancedb", "error": str(exc)}


# ── Multi-collection LanceDB helpers ─────────────────────────────────────


import re as _re

# Allowlist for string fields interpolated into LanceDB WHERE expressions.
# Only printable ASCII minus single-quote and backslash are allowed so a
# caller-supplied region / project_id / tenant_id can never break out of
# the surrounding ``field = '<value>'`` literal.  The cap (128 chars) is
# generous — real values are ≤ 64 chars.
_LANCEDB_SAFE_STRING_RE = _re.compile(r"^[^\x00-\x1f\x7f'\\]{1,128}$")


def _safe_quote_scalar(value: str, field: str = "field") -> str | None:
    """Validate and single-quote a scalar string for a LanceDB WHERE literal.

    Returns the quoted string (``'value'``) when the input passes the
    allowlist, or ``None`` when it must be rejected.  Callers MUST treat
    a ``None`` return as "drop this filter" — never fall through to
    interpolating the raw value.

    The allowlist is intentionally restrictive (printable ASCII excluding
    ``'`` and ``\\``) so the function stays correct even when LanceDB
    changes its SQL parser internals.  Legitimate CWICR region codes and
    UUID strings all pass; only crafted injection payloads fail.
    """
    if not isinstance(value, str) or not value:
        return None
    if not _LANCEDB_SAFE_STRING_RE.match(value):
        logger.warning(
            "LanceDB filter: unsafe %s value rejected (injection guard): %r",
            field,
            value[:80],
        )
        return None
    return f"'{value}'"


def _safe_quote_ids(raw_ids: list[Any]) -> list[str]:
    """Validate and quote a list of row ids for inclusion in a LanceDB SQL filter.

    LanceDB has no parameterised query API for the ``WHERE`` clause we
    need on ``DELETE``, so we have to interpolate strings.  This helper
    is the boundary check that prevents SQL injection: every id is
    re-parsed as a strict UUID, and anything that fails parsing is
    silently dropped (the adapter layer always passes UUIDs from
    SQLAlchemy ``GUID()`` columns, so a parse failure indicates either a
    bug or an attack).

    Returns a list of single-quoted UUID strings ready for ``IN (...)``.
    """
    import uuid as _uuid

    out: list[str] = []
    for raw in raw_ids:
        try:
            parsed = _uuid.UUID(str(raw))
        except (ValueError, AttributeError, TypeError):
            logger.debug("Dropping non-UUID id from LanceDB filter: %r", raw)
            continue
        out.append(f"'{parsed}'")
    return out


def _ensure_generic_table(db: Any, collection_name: str, dim: int) -> bool:
    """Ensure a generic LanceDB table for a non-cost collection exists.

    The schema is uniform across every collection so the EmbeddingAdapter
    layer (``core/vector_index.py``) can write to any collection through a
    single code path.  Idempotent: returns True if the table already exists
    or was just created.
    """
    try:
        if collection_name in db.table_names():
            return True
        import pyarrow as pa

        schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), dim)),
                pa.field("text", pa.string()),
                pa.field("tenant_id", pa.string()),
                pa.field("project_id", pa.string()),
                pa.field("module", pa.string()),
                pa.field("payload", pa.string()),
            ]
        )
        db.create_table(collection_name, schema=schema)
        logger.info("Created LanceDB collection: %s (%dd)", collection_name, dim)
        return True
    except Exception as exc:
        logger.error("Failed to ensure LanceDB collection %s: %s", collection_name, exc)
        return False


def _lancedb_index_generic(collection_name: str, items: list[dict], dim: int) -> int:
    """Upsert generic items into a non-cost LanceDB collection.

    Each item must have all of ``GENERIC_FIELDS``.  Existing rows with the
    same ``id`` are deleted before insert (LanceDB has no native upsert).
    """
    db = _get_lancedb()
    if db is None:
        raise RuntimeError("LanceDB not available")
    if not items:
        return 0
    if not _ensure_generic_table(db, collection_name, dim):
        raise RuntimeError(f"Cannot ensure collection {collection_name}")

    tbl = db.open_table(collection_name)
    quoted_ids = _safe_quote_ids([it["id"] for it in items])
    if quoted_ids:
        try:
            tbl.delete(f"id IN ({', '.join(quoted_ids)})")
        except Exception:
            pass
    tbl.add(items)
    return len(items)


def _lancedb_search_generic(
    collection_name: str,
    query_vector: list[float],
    *,
    project_id: str | None = None,
    tenant_id: str | None = None,
    limit: int = 10,
    extra_where: str | None = None,
) -> list[dict]:
    """Search a generic LanceDB collection for similar vectors."""
    db = _get_lancedb()
    if db is None:
        return []
    try:
        if collection_name not in db.table_names():
            return []
        tbl = db.open_table(collection_name)
    except Exception:
        return []

    q = tbl.search(query_vector).limit(limit)
    where_parts: list[str] = []
    if project_id:
        safe_pid = _safe_quote_scalar(project_id, "project_id")
        if safe_pid:
            where_parts.append(f"project_id = {safe_pid}")
    if tenant_id:
        safe_tid = _safe_quote_scalar(tenant_id, "tenant_id")
        if safe_tid:
            where_parts.append(f"tenant_id = {safe_tid}")
    if extra_where:
        where_parts.append(extra_where)
    if where_parts:
        q = q.where(" AND ".join(where_parts))

    results = q.to_list()
    return [
        {
            "id": r["id"],
            "score": round(max(0.0, 1.0 - r.get("_distance", 0)), 4),
            "text": r.get("text", ""),
            "tenant_id": r.get("tenant_id", ""),
            "project_id": r.get("project_id", ""),
            "module": r.get("module", ""),
            "payload": r.get("payload", "{}"),
        }
        for r in results
    ]


def _lancedb_delete_generic(collection_name: str, ids: list[str]) -> int:
    """Delete items by id from a generic collection.

    Each id is validated as a strict UUID before being interpolated into
    the LanceDB filter via :func:`_safe_quote_ids`, blocking the
    string-interpolation injection vector that would otherwise exist on
    a backend that takes attacker-supplied row ids.
    """
    db = _get_lancedb()
    if db is None or not ids:
        return 0
    try:
        if collection_name not in db.table_names():
            return 0
        tbl = db.open_table(collection_name)
        quoted_ids = _safe_quote_ids(ids)
        if not quoted_ids:
            return 0
        tbl.delete(f"id IN ({', '.join(quoted_ids)})")
        return len(quoted_ids)
    except Exception as exc:
        logger.warning("delete_generic %s failed: %s", collection_name, exc)
        return 0


def _lancedb_count_generic(collection_name: str) -> int:
    """Return row count for a generic collection (0 if missing)."""
    db = _get_lancedb()
    if db is None:
        return 0
    try:
        if collection_name not in db.table_names():
            return 0
        return db.open_table(collection_name).count_rows()
    except Exception:
        return 0


def _lancedb_index(items: list[dict]) -> int:
    """Index items into LanceDB. Each item: {id, vector, code, description, unit, rate, region}.

    Cost item IDs originate from ``CostItem.id`` (a SQLAlchemy ``GUID()``
    column) so they're always UUID strings — :func:`_safe_quote_ids`
    enforces that as a defence-in-depth boundary check.
    """
    db = _get_lancedb()
    if db is None:
        raise RuntimeError("LanceDB not available")
    _lancedb_ensure_table(db)

    if not items:
        return 0

    tbl = db.open_table(COST_TABLE)

    # Delete existing items with same IDs (upsert)
    quoted_ids = _safe_quote_ids([it["id"] for it in items])
    if quoted_ids:
        try:
            tbl.delete(f"id IN ({', '.join(quoted_ids)})")
        except Exception:
            pass  # Table might be empty

    tbl.add(items)
    return len(items)


def _lancedb_search(
    query_vector: list[float],
    region: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search LanceDB for similar vectors."""
    db = _get_lancedb()
    if db is None:
        return []

    try:
        tbl = db.open_table(COST_TABLE)
    except Exception:
        return []

    q = tbl.search(query_vector).limit(limit)
    if region:
        safe_region = _safe_quote_scalar(region, "region")
        if safe_region:
            q = q.where(f"region = {safe_region}")

    results = q.to_list()
    return [
        {
            "id": r["id"],
            "score": round(max(0.0, 1.0 - r.get("_distance", 0)), 4),
            "code": r.get("code", ""),
            "description": r.get("description", ""),
            "unit": r.get("unit", ""),
            "rate": r.get("rate", 0.0),
            "region": r.get("region", ""),
        }
        for r in results
    ]


# ── Qdrant (server mode) ──────────────────────────────────────────────────


_qdrant_instance: Any = None
_qdrant_tried: bool = False
_qdrant_last_attempt_ts: float = 0.0
_QDRANT_RETRY_COOLDOWN_S: float = 5.0


def reset_qdrant_client() -> None:
    """Drop the cached client so the next ``_get_qdrant`` call reconnects.

    Called by ``/api/v1/match_elements/qdrant/install`` after a successful
    spawn — without this the rest of the backend keeps returning
    ``"Qdrant not reachable"`` because the first boot-time probe latched
    a ``None`` client. Cheap to call: no-op when nothing is cached.
    """
    global _qdrant_instance, _qdrant_tried, _qdrant_last_attempt_ts
    _qdrant_instance = None
    _qdrant_tried = False
    _qdrant_last_attempt_ts = 0.0


def _get_qdrant():
    """Get Qdrant client (only used when VECTOR_BACKEND=qdrant).

    First call attempts a connection and caches the result. On failure
    we record the timestamp and rate-limit reconnect attempts to once
    every ``_QDRANT_RETRY_COOLDOWN_S`` so a brief network blip doesn't
    turn into a permanently-disabled vector backend for the lifetime
    of the process. Explicit reconnect available via
    ``reset_qdrant_client()`` (called by the install endpoint).
    """
    global _qdrant_instance, _qdrant_tried, _qdrant_last_attempt_ts
    if _qdrant_instance is not None:
        return _qdrant_instance
    if _qdrant_tried:
        # Self-healing: retry after the cooldown so a delayed Qdrant
        # spawn (manual start, supervisor restart, brief container
        # restart) recovers without a process restart.
        if (time.monotonic() - _qdrant_last_attempt_ts) < _QDRANT_RETRY_COOLDOWN_S:
            return None
    _qdrant_tried = True
    _qdrant_last_attempt_ts = time.monotonic()
    try:
        from qdrant_client import QdrantClient

        from app.config import get_settings

        url = get_settings().qdrant_url or "http://localhost:6333"
        client = QdrantClient(url=url, timeout=2, check_compatibility=False)
        client.get_collections()
        _qdrant_instance = client
        logger.info("Connected to Qdrant at %s", url)
        return client
    except Exception as exc:
        logger.info("Qdrant not available: %s", exc)
        return None


# ── Public API (auto-selects backend) ──────────────────────────────────────


def _backend() -> str:
    from app.config import get_settings

    return get_settings().vector_backend


def vector_status() -> dict[str, Any]:
    """Get vector DB status."""
    if _backend() == "qdrant":
        client = _get_qdrant()
        if client is None:
            return {"connected": False, "engine": "qdrant", "error": "Qdrant not reachable"}
        try:
            from app.core.vector import COST_TABLE as CT

            collections = [c.name for c in client.get_collections().collections]
            info: dict[str, Any] = {"connected": True, "engine": "qdrant", "collections": len(collections)}
            if CT in collections:
                col = client.get_collection(CT)
                # qdrant-client >=1.9 dropped ``CollectionInfo.vectors_count``;
                # prefer ``points_count`` and fall back resiliently so a
                # client version bump can never crash collection-info reads.
                count = getattr(col, "points_count", None)
                if count is None:
                    count = getattr(col, "vectors_count", None)
                if count is None:
                    try:
                        count = client.count(CT).count
                    except Exception:
                        count = 0
                count = int(count or 0)
                info["cost_collection"] = {
                    "vectors_count": count,
                    "points_count": count,
                    "status": col.status.value if col.status else "unknown",
                }
            else:
                info["cost_collection"] = None
            info["can_restore_snapshots"] = True
            # Lazy — see note on _lancedb_status above.
            info["can_generate_locally"] = _has_module("sentence_transformers")
            info["embedding_dim"] = QDRANT_SNAPSHOT_DIM
            info["backend"] = "qdrant"
            return info
        except Exception as exc:
            return {"connected": False, "engine": "qdrant", "error": str(exc)}

    return _lancedb_status()


def vector_index(items: list[dict]) -> int:
    """Index items into vector DB. Items: [{id, vector, code, description, unit, rate, region}]."""
    if _backend() == "qdrant":
        client = _get_qdrant()
        if client is None:
            raise RuntimeError("Qdrant not available")
        from qdrant_client.models import Distance, PointStruct, VectorParams

        # Ensure collection
        collections = [c.name for c in client.get_collections().collections]
        if COST_TABLE not in collections:
            client.create_collection(
                COST_TABLE, vectors_config=VectorParams(size=QDRANT_SNAPSHOT_DIM, distance=Distance.COSINE)
            )

        points = [
            PointStruct(
                id=it["id"], vector=it["vector"], payload={k: v for k, v in it.items() if k not in ("id", "vector")}
            )
            for it in items
        ]
        client.upsert(COST_TABLE, points=points)
        return len(points)

    return _lancedb_index(items)


def vector_search(
    query_vector: list[float],
    region: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search for similar vectors."""
    if _backend() == "qdrant":
        client = _get_qdrant()
        if client is None:
            return []
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        search_filter = None
        if region:
            search_filter = Filter(must=[FieldCondition(key="region", match=MatchValue(value=region))])
        results = client.search(COST_TABLE, query_vector=query_vector, query_filter=search_filter, limit=limit)
        return [{"id": h.id, "score": round(h.score, 4), **h.payload} for h in results]

    return _lancedb_search(query_vector, region, limit)


# ── Multi-collection public API ──────────────────────────────────────────
#
# These functions are the entry points used by ``core/vector_index.py`` and
# every per-module ``vector_adapter.py``.  They mirror the cost-collection
# helpers above but accept a ``collection_name`` so the same code path can
# write to oe_boq_positions, oe_documents, oe_tasks, oe_risks, etc.
#
# The Qdrant branch lazy-creates collections with cosine distance and the
# embedding dimension from settings.  The LanceDB branch delegates to
# ``_ensure_generic_table`` / ``_lancedb_index_generic`` above.


def vector_index_collection(collection_name: str, items: list[dict]) -> int:
    """Upsert generic items into ``collection_name``.

    Each item must contain ``id, vector, text, tenant_id, project_id,
    module, payload`` (see ``GENERIC_FIELDS``).  ``payload`` must already
    be JSON-encoded as a string so the LanceDB schema stays uniform.
    """
    if not items:
        return 0
    _, dim = _resolve_active_model()

    if _backend() == "qdrant":
        client = _get_qdrant()
        if client is None:
            raise RuntimeError("Qdrant not available")
        from qdrant_client.models import Distance, PointStruct, VectorParams

        collections = [c.name for c in client.get_collections().collections]
        if collection_name not in collections:
            client.create_collection(
                collection_name,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )

        points: list[Any] = []
        for it in items:
            payload_dict = it.get("payload")
            if isinstance(payload_dict, str):
                import json as _json

                try:
                    payload_dict = _json.loads(payload_dict)
                except Exception:
                    payload_dict = {}
            elif not isinstance(payload_dict, dict):
                payload_dict = {}
            qdrant_payload = {
                "text": it.get("text", ""),
                "tenant_id": it.get("tenant_id", ""),
                "project_id": it.get("project_id", ""),
                "module": it.get("module", ""),
                **payload_dict,
            }
            points.append(PointStruct(id=it["id"], vector=it["vector"], payload=qdrant_payload))
        client.upsert(collection_name, points=points)
        return len(points)

    return _lancedb_index_generic(collection_name, items, dim)


def vector_search_collection(
    collection_name: str,
    query_vector: list[float],
    *,
    project_id: str | None = None,
    tenant_id: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search ``collection_name`` for nearest neighbours.

    Returns a list of hits with ``id, score, text, tenant_id, project_id,
    module, payload``.  ``payload`` is returned as a JSON string for
    LanceDB and as the original dict (re-serialised) for Qdrant — callers
    should treat it as opaque and let ``core/vector_index.py`` decode it.
    """
    if _backend() == "qdrant":
        client = _get_qdrant()
        if client is None:
            return []
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        must_clauses: list[Any] = []
        if project_id:
            must_clauses.append(FieldCondition(key="project_id", match=MatchValue(value=project_id)))
        if tenant_id:
            must_clauses.append(FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)))
        search_filter = Filter(must=must_clauses) if must_clauses else None
        try:
            results = client.search(
                collection_name,
                query_vector=query_vector,
                query_filter=search_filter,
                limit=limit,
            )
        except Exception as exc:
            logger.debug("Qdrant search %s failed: %s", collection_name, exc)
            return []
        import json as _json

        # Reserved keys are extracted from the Qdrant payload via ``get``
        # (NOT ``pop``) so we never mutate the source dict — the qdrant
        # client may cache result objects and other consumers downstream
        # would otherwise see a stripped payload.
        _RESERVED = {"text", "tenant_id", "project_id", "module"}
        out: list[dict] = []
        for h in results:
            raw_payload = h.payload or {}
            if not isinstance(raw_payload, dict):
                raw_payload = {}
            text = str(raw_payload.get("text") or "")
            tid = str(raw_payload.get("tenant_id") or "")
            pid = str(raw_payload.get("project_id") or "")
            mod = str(raw_payload.get("module") or "")
            # Build the user-facing payload without the reserved keys, but
            # without touching the qdrant-owned dict.
            user_payload = {k: v for k, v in raw_payload.items() if k not in _RESERVED}
            out.append(
                {
                    "id": str(h.id),
                    "score": round(h.score, 4),
                    "text": text,
                    "tenant_id": tid,
                    "project_id": pid,
                    "module": mod,
                    "payload": _json.dumps(user_payload, ensure_ascii=False),
                }
            )
        return out

    return _lancedb_search_generic(
        collection_name,
        query_vector,
        project_id=project_id,
        tenant_id=tenant_id,
        limit=limit,
    )


def vector_delete_collection(collection_name: str, ids: list[str]) -> int:
    """Delete points by id from ``collection_name``.  Idempotent."""
    if not ids:
        return 0
    if _backend() == "qdrant":
        client = _get_qdrant()
        if client is None:
            return 0
        try:
            from qdrant_client.models import PointIdsList

            client.delete(
                collection_name,
                points_selector=PointIdsList(points=ids),  # type: ignore[arg-type]
            )
            return len(ids)
        except Exception as exc:
            logger.debug("Qdrant delete %s failed: %s", collection_name, exc)
            return 0
    return _lancedb_delete_generic(collection_name, ids)


def vector_count_collection(collection_name: str) -> int:
    """Return point count for ``collection_name`` (0 if missing)."""
    if _backend() == "qdrant":
        client = _get_qdrant()
        if client is None:
            return 0
        try:
            col = client.get_collection(collection_name)
            # ``points_count`` first, ``vectors_count`` (older clients) next,
            # then a live count() — version-tolerant across qdrant-client.
            count = getattr(col, "points_count", None)
            if count is None:
                count = getattr(col, "vectors_count", None)
            if count is None:
                count = client.count(collection_name).count
            return int(count or 0)
        except Exception:
            return 0
    return _lancedb_count_generic(collection_name)


def vector_count_with_payload_substring(
    collection_name: str,
    substring: str,
) -> int:
    """Count vectors whose stringified payload contains ``substring``.

    Used to surface per-catalogue vectorisation progress to the UI: we
    embed payload as a JSON string with the catalogue's region code in
    it, so a LIKE substring is enough to count "how many vectors come
    from this catalogue" without parsing JSON server-side.

    Returns 0 on any failure path so the caller can keep the call site
    one-line.
    """
    if not substring:
        return 0
    # Sanitise: only allow CWICR-style ids (LETTERS/digits/underscore)
    # so a malicious caller can't inject SQL into the LanceDB filter
    # expression. The whitelist is intentionally tight — every legitimate
    # CWICR id matches it (e.g. ``RU_STPETERSBURG``, ``USA_USD``).
    import re  # noqa: PLC0415

    if not re.fullmatch(r"[A-Z0-9_]{1,32}", substring):
        return 0
    if _backend() == "qdrant":
        # Qdrant filter API requires a typed PayloadSelector; for the
        # purposes of this UI counter we fall back to the unfiltered
        # collection count, which over-reports but doesn't break.
        return vector_count_collection(collection_name)
    db = _get_lancedb()
    if db is None:
        return 0
    try:
        if collection_name not in db.table_names():
            return 0
        tbl = db.open_table(collection_name)
        return int(tbl.count_rows(filter=f"payload LIKE '%{substring}%'"))
    except Exception as exc:
        logger.debug("vector_count_with_payload_substring failed: %s", exc)
        return 0
