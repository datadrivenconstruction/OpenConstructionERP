"""Vector database integration — LanceDB (embedded) or Qdrant (server).

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
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

COST_TABLE = "cost_items"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
QDRANT_SNAPSHOT_DIM = 3072  # Dimension for pre-built Qdrant snapshots from GitHub


# ── Embedding ──────────────────────────────────────────────────────────────


_embedder_instance: Any = None
_embedder_tried: bool = False


def get_embedder():
    """Get singleton embedding model.

    Uses sentence-transformers (PyTorch) directly. FastEmbed is skipped because
    its ONNX model cache can become corrupted and hang on initialisation.
    """
    global _embedder_instance, _embedder_tried
    if _embedder_instance is not None:
        return _embedder_instance

    # sentence-transformers (reliable, uses PyTorch)
    try:
        from sentence_transformers import SentenceTransformer

        _embedder_instance = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Loaded sentence-transformers model: all-MiniLM-L6-v2 (%dd)", EMBEDDING_DIM)
        return _embedder_instance
    except Exception as exc:
        if not _embedder_tried:
            logger.warning("No embedding model available: %s", exc)
            _embedder_tried = True
        return None


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
    """Async wrapper — runs encode_texts in a thread to avoid blocking the event loop."""
    import asyncio

    return await asyncio.to_thread(encode_texts, texts)


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

            schema = pa.schema([
                pa.field("id", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
                pa.field("code", pa.string()),
                pa.field("description", pa.string()),
                pa.field("unit", pa.string()),
                pa.field("rate", pa.float64()),
                pa.field("region", pa.string()),
            ])
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
        info["can_restore_snapshots"] = _get_qdrant() is not None
        info["can_generate_locally"] = get_embedder() is not None
        info["embedding_dim"] = EMBEDDING_DIM
        info["backend"] = "lancedb"
        return info
    except Exception as exc:
        return {"connected": False, "engine": "lancedb", "error": str(exc)}


def _lancedb_index(items: list[dict]) -> int:
    """Index items into LanceDB. Each item: {id, vector, code, description, unit, rate, region}."""
    db = _get_lancedb()
    if db is None:
        raise RuntimeError("LanceDB not available")
    _lancedb_ensure_table(db)

    if not items:
        return 0

    tbl = db.open_table(COST_TABLE)

    # Delete existing items with same IDs (upsert)
    ids = [it["id"] for it in items]
    try:
        id_list = ", ".join(f"'{i}'" for i in ids)
        tbl.delete(f"id IN ({id_list})")
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
        q = q.where(f"region = '{region}'")

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


def _get_qdrant():
    """Get Qdrant client (only used when VECTOR_BACKEND=qdrant)."""
    global _qdrant_instance, _qdrant_tried
    if _qdrant_instance is not None:
        return _qdrant_instance
    if _qdrant_tried:
        return None
    _qdrant_tried = True
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
                info["cost_collection"] = {
                    "vectors_count": col.vectors_count,
                    "points_count": col.points_count,
                    "status": col.status.value if col.status else "unknown",
                }
            else:
                info["cost_collection"] = None
            info["can_restore_snapshots"] = True
            info["can_generate_locally"] = get_embedder() is not None
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
        from qdrant_client.models import PointStruct, Distance, VectorParams

        # Ensure collection
        collections = [c.name for c in client.get_collections().collections]
        if COST_TABLE not in collections:
            client.create_collection(COST_TABLE, vectors_config=VectorParams(size=QDRANT_SNAPSHOT_DIM, distance=Distance.COSINE))

        points = [
            PointStruct(id=it["id"], vector=it["vector"], payload={k: v for k, v in it.items() if k not in ("id", "vector")})
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
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        search_filter = None
        if region:
            search_filter = Filter(must=[FieldCondition(key="region", match=MatchValue(value=region))])
        results = client.search(COST_TABLE, query_vector=query_vector, query_filter=search_filter, limit=limit)
        return [{"id": h.id, "score": round(h.score, 4), **h.payload} for h in results]

    return _lancedb_search(query_vector, region, limit)
