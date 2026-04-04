"""Cost database API routes.

Endpoints:
    GET  /autocomplete    -- Fast text autocomplete for cost items (public)
    POST /                -- Create a cost item (auth required)
    GET  /                -- Search cost items (public, query params)
    GET  /{item_id}       -- Get cost item by ID
    PATCH /{item_id}      -- Update cost item (auth required)
    DELETE /{item_id}     -- Delete cost item (auth required)
    POST /bulk            -- Bulk import cost items (auth required)
    POST /import/file     -- Import cost items from Excel/CSV file (auth required)
    POST /load-cwicr/{db_id} -- Load CWICR regional database (auth required)
"""

import csv
import io
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.costs.schemas import (
    CostAutocompleteItem,
    CostItemCreate,
    CostItemResponse,
    CostItemUpdate,
    CostSearchQuery,
    CostSearchResponse,
)
from app.modules.costs.service import CostItemService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> CostItemService:
    return CostItemService(session)


# ── Autocomplete ──────────────────────────────────────────────────────────


@router.get("/autocomplete", response_model=list[CostAutocompleteItem])
async def autocomplete_cost_items(
    service: CostItemService = Depends(_get_service),
    q: str = Query(..., min_length=2, max_length=200, description="Search text (min 2 chars)"),
    region: str | None = Query(default=None, description="Filter by region (e.g. DE_BERLIN)"),
    limit: int = Query(default=8, ge=1, le=20, description="Max results to return"),
    semantic: bool = Query(default=False, description="Use vector semantic search if available"),
) -> list[CostAutocompleteItem]:
    """Fast autocomplete for cost items. Uses vector semantic search when available.

    When ``semantic=true`` and a vector index exists, uses AI embeddings
    to find semantically similar items (e.g. "concrete wall" finds
    "reinforced partition C30/37"). Falls back to text search otherwise.
    """
    # Try vector search first if requested
    if semantic:
        try:
            from app.core.vector import encode_texts, vector_search, vector_status
            status = vector_status()
            if status.get("connected") and status.get("cost_collection"):
                query_vec = encode_texts([q])[0]
                results = vector_search(query_vec, region=region, limit=limit)
                if results:
                    # Vector results may not have components — look them up from DB
                    codes = [r.get("code", "") for r in results]
                    components_map: dict[str, list[dict[str, Any]]] = {}
                    try:
                        items_from_db = await service.get_by_codes(codes)
                        for db_item in items_from_db:
                            components_map[db_item.code] = db_item.components or []
                    except Exception:
                        pass  # Graceful fallback — return without components

                    return [
                        CostAutocompleteItem(
                            code=r.get("code", ""),
                            description=r.get("description", ""),
                            unit=r.get("unit", ""),
                            rate=float(r.get("rate", 0)),
                            classification=r.get("classification", {}),
                            components=components_map.get(r.get("code", ""), []),
                        )
                        for r in results
                    ]
        except Exception:
            pass  # Fall back to text search

    # Standard text search — fetch extra to prioritize items with components
    query = CostSearchQuery(q=q, region=region, limit=limit * 3, offset=0)
    items, _ = await service.search_costs(query)

    # Sort: items WITH components first (richer data for estimators)
    import json as _json

    def _has_components(it: object) -> bool:
        comps = it.components  # type: ignore[attr-defined]
        if isinstance(comps, str):
            try:
                comps = _json.loads(comps)
            except Exception:
                return False
        return isinstance(comps, list) and len(comps) > 0

    sorted_items = sorted(
        items,
        key=lambda it: (0 if _has_components(it) else 1, it.code),
    )

    def _parse_components(raw: object) -> list[dict[str, Any]]:
        if isinstance(raw, str):
            try:
                parsed = _json.loads(raw)
                return parsed if isinstance(parsed, list) else []
            except Exception:
                return []
        return raw if isinstance(raw, list) else []

    return [
        CostAutocompleteItem(
            code=item.code,
            description=item.description,
            unit=item.unit,
            rate=float(item.rate),
            classification=item.classification or {},
            components=_parse_components(item.components),
        )
        for item in sorted_items[:limit]
    ]


# ── Create ────────────────────────────────────────────────────────────────


@router.post(
    "/",
    response_model=CostItemResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("costs.create"))],
)
async def create_cost_item(
    data: CostItemCreate,
    _user_id: CurrentUserId,
    service: CostItemService = Depends(_get_service),
) -> CostItemResponse:
    """Create a new cost item."""
    item = await service.create_cost_item(data)
    return CostItemResponse.model_validate(item)


# ── Search / List ─────────────────────────────────────────────────────────


@router.get("/", response_model=CostSearchResponse)
async def search_cost_items(
    service: CostItemService = Depends(_get_service),
    q: str | None = Query(default=None, description="Text search on code and description"),
    unit: str | None = Query(default=None, description="Filter by unit"),
    source: str | None = Query(default=None, description="Filter by source"),
    region: str | None = Query(default=None, description="Filter by region (e.g. DE_BERLIN)"),
    category: str | None = Query(
        default=None, description="Filter by classification.collection (construction category)"
    ),
    min_rate: float | None = Query(default=None, ge=0, description="Minimum rate"),
    max_rate: float | None = Query(default=None, ge=0, description="Maximum rate"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CostSearchResponse:
    """Search cost items with optional filters. Public endpoint.

    Returns a paginated response with items, total count, limit and offset.
    """
    query = CostSearchQuery(
        q=q,
        unit=unit,
        source=source,
        region=region,
        category=category,
        min_rate=min_rate,
        max_rate=max_rate,
        limit=limit,
        offset=offset,
    )
    items, total = await service.search_costs(query)
    return CostSearchResponse(
        items=[CostItemResponse.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── Regions ───────────────────────────────────────────────────────────────


# ── In-memory cache for slow aggregate queries ──────────────────────────────

import time as _time

_region_cache: dict[str, Any] = {"regions": None, "stats": None, "categories": None, "ts": 0}
_CACHE_TTL = 30  # seconds


def _invalidate_cost_cache() -> None:
    """Call after import/delete to force refresh on next request."""
    _region_cache["ts"] = 0


@router.get("/regions", response_model=list[str])
async def list_loaded_regions(
    session: SessionDep,
) -> list[str]:
    """List distinct regions that have cost items loaded."""
    now = _time.monotonic()
    if _region_cache["regions"] is not None and now - _region_cache["ts"] < _CACHE_TTL:
        return _region_cache["regions"]

    from sqlalchemy import select, distinct
    from app.modules.costs.models import CostItem

    result = await session.execute(
        select(distinct(CostItem.region))
        .where(CostItem.is_active.is_(True))
        .where(CostItem.region.isnot(None))
        .where(CostItem.region != "")
    )
    regions = sorted(row[0] for row in result.all())
    _region_cache["regions"] = regions
    _region_cache["ts"] = now
    return regions


@router.get("/regions/stats")
async def region_stats(
    session: SessionDep,
) -> list[dict]:
    """Return item count per loaded region. Cached for 30s."""
    now = _time.monotonic()
    if _region_cache["stats"] is not None and now - _region_cache["ts"] < _CACHE_TTL:
        return _region_cache["stats"]

    from sqlalchemy import select, func
    from app.modules.costs.models import CostItem

    result = await session.execute(
        select(CostItem.region, func.count(CostItem.id).label("cnt"))
        .where(CostItem.is_active.is_(True))
        .where(CostItem.region.isnot(None))
        .where(CostItem.region != "")
        .group_by(CostItem.region)
        .order_by(func.count(CostItem.id).desc())
    )
    stats = [{"region": row[0], "count": row[1]} for row in result.all()]
    _region_cache["stats"] = stats
    _region_cache["ts"] = now
    return stats


@router.delete(
    "/actions/clear-region/{region}",
    dependencies=[Depends(RequirePermission("costs.update"))],
)
async def clear_region_database(
    region: str,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> dict:
    """Delete all cost items for a specific region.

    E.g. ``DELETE /actions/clear-region/DE_BERLIN`` removes all DE_BERLIN items.
    """
    from sqlalchemy import delete as sql_delete
    from app.modules.costs.models import CostItem

    stmt = sql_delete(CostItem).where(CostItem.region == region)
    result = await session.execute(stmt)
    await session.commit()
    count = result.rowcount  # type: ignore[union-attr]

    logger.info("Cleared region %s: %d items deleted", region, count)
    _invalidate_cost_cache()
    return {"deleted": count, "region": region}


# ── Vector database (LanceDB embedded / Qdrant server) ──────────────────────


@router.get("/vector/status")
async def get_vector_status() -> dict:
    """Check vector DB status (LanceDB embedded or Qdrant server)."""
    from app.core.vector import vector_status as vs

    return vs()


@router.get("/vector/regions")
async def vector_region_stats() -> list[dict]:
    """Return per-region vector counts from the vector DB.

    Response: ``[{"region": "DE_BERLIN", "count": 55719}, ...]``
    """
    from app.core.vector import vector_status as vs

    status = vs()
    if not status.get("connected"):
        return []

    # LanceDB: query the table directly for per-region counts
    try:
        from app.core.vector import _get_lancedb, COST_TABLE, _backend
        if _backend() != "qdrant":
            db = _get_lancedb()
            if db is None:
                return []
            try:
                tbl = db.open_table(COST_TABLE)
            except Exception:
                return []
            import pandas as pd
            df = tbl.to_pandas()
            if "region" not in df.columns:
                return []
            counts = df.groupby("region").size().reset_index(name="count")
            return [{"region": r, "count": int(c)} for r, c in zip(counts["region"], counts["count"]) if r]
        else:
            # For Qdrant, return total count only (per-region requires scroll)
            col = status.get("cost_collection")
            if col and col.get("vectors_count", 0) > 0:
                return [{"region": "all", "count": col["vectors_count"]}]
            return []
    except Exception:
        return []


@router.post(
    "/vector/index",
    dependencies=[Depends(RequirePermission("costs.create"))],
)
async def vectorize_cost_items(
    session: SessionDep,
    _user_id: CurrentUserId,
    region: str | None = Query(default=None, description="Only index items from this region"),
    batch_size: int = Query(default=256, ge=32, le=1024),
) -> dict:
    """Generate embeddings and index cost items into vector DB.

    Uses FastEmbed/ONNX (all-MiniLM-L6-v2, 384d) locally — no API key needed.
    Default backend: LanceDB (embedded, no Docker required).
    """
    import time
    from sqlalchemy import select
    from app.modules.costs.models import CostItem
    from app.core.vector import encode_texts, vector_index

    start = time.monotonic()

    # Fetch cost items
    stmt = select(CostItem).where(CostItem.is_active.is_(True))
    if region:
        stmt = stmt.where(CostItem.region == region)

    result = await session.execute(stmt)
    items = result.scalars().all()

    if not items:
        return {"indexed": 0, "message": "No cost items found to index"}

    logger.info("Vectorizing %d cost items (region=%s)...", len(items), region or "all")

    # Pre-extract all data from ORM objects before they expire
    items_data = []
    for item in items:
        cls = item.classification or {}
        items_data.append({
            "id": str(item.id),
            "code": item.code,
            "description": (item.description or "")[:200],
            "unit": item.unit or "",
            "rate": float(item.rate) if item.rate else 0.0,
            "region": item.region or "",
            "text": " ".join(p for p in [
                item.description or "",
                item.unit or "",
                cls.get("collection", ""),
                cls.get("department", ""),
                cls.get("section", ""),
            ] if p),
        })

    # Run CPU-heavy embedding in a separate process to not block event loop
    import asyncio
    import concurrent.futures

    def _vectorize_batch(data: list[dict], bs: int) -> int:
        from app.core.vector import encode_texts, vector_index
        total = 0
        for i in range(0, len(data), bs):
            batch = data[i:i + bs]
            texts = [d["text"] for d in batch]
            vectors = encode_texts(texts)
            records = [{**{k: d[k] for k in ("id", "code", "description", "unit", "rate", "region")}, "vector": vectors[j]} for j, d in enumerate(batch)]
            total += vector_index(records)
        return total

    loop = asyncio.get_event_loop()
    with concurrent.futures.ProcessPoolExecutor(max_workers=1) as pool:
        indexed = await loop.run_in_executor(pool, _vectorize_batch, items_data, batch_size)

    duration = round(time.monotonic() - start, 1)
    logger.info("Indexed %d cost items in %.1fs", indexed, duration)

    return {
        "indexed": indexed,
        "region": region or "all",
        "duration_seconds": duration,
    }


@router.post(
    "/vector/load-github/{db_id}",
    dependencies=[Depends(RequirePermission("costs.create"))],
)
async def load_vector_from_github(
    db_id: str,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> dict:
    """Download pre-built vector embeddings from GitHub and index into LanceDB.

    Downloads a parquet file with pre-computed 384d embeddings (all-MiniLM-L6-v2)
    for the given region, so users don't need to run the embedding model locally.
    """
    import time
    import traceback
    import urllib.request

    from app.core.vector import vector_index

    start = time.monotonic()

    github_path = _GITHUB_CWICR_FILES.get(db_id)
    if not github_path:
        raise HTTPException(404, f"Unknown database ID: {db_id}")

    # Vector parquet is stored alongside the regular parquet in the same repo
    vector_filename = f"{db_id}_vectors.parquet"
    vector_github_path = f"{db_id}/{vector_filename}"
    url = f"{_GITHUB_CWICR_BASE_URL}/{vector_github_path}"

    # Cache locally
    cache_dir = _CWICR_CACHE_DIR / "vectors"
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_path = cache_dir / vector_filename

    # Download if not cached
    github_available = False
    if not local_path.exists() or local_path.stat().st_size < 1000:
        logger.info("Downloading vector data for %s from GitHub: %s", db_id, url)
        try:
            urllib.request.urlretrieve(url, str(local_path))
            if local_path.exists() and local_path.stat().st_size > 1000:
                github_available = True
        except Exception as exc:
            local_path.unlink(missing_ok=True)
            logger.info("GitHub vectors not available for %s, will generate locally: %s", db_id, exc)
    else:
        github_available = True

    # Fallback: generate vectors locally from cost items in DB
    if not github_available:
        logger.info("Generating vectors locally for %s from cost database", db_id)
        try:
            import asyncio
            from concurrent.futures import ThreadPoolExecutor
            from app.core.vector import encode_texts, vector_index as vi
            from app.modules.costs.repository import CostItemRepository

            repo = CostItemRepository(session)
            items_list, total = await repo.search(region=db_id, limit=5000)
            if not items_list:
                items_list, total = await repo.search(limit=5000)

            if not items_list:
                raise HTTPException(400, f"No cost items found for '{db_id}'.")

            # Run embedding generation in a thread to not block event loop
            def _generate_vectors(items_data):
                batch_size = 128
                indexed = 0
                for i in range(0, len(items_data), batch_size):
                    batch = items_data[i:i + batch_size]
                    texts = [f"{it['code']} {it['desc']}" for it in batch]
                    vectors = encode_texts(texts)
                    records = [
                        {
                            "id": it["id"],
                            "vector": vec,
                            "code": it["code"],
                            "description": it["desc"],
                            "unit": it["unit"],
                            "rate": it["rate"],
                            "region": it["region"],
                        }
                        for it, vec in zip(batch, vectors)
                    ]
                    if records:
                        indexed += vi(records)
                return indexed

            # Prepare data outside the thread (ORM objects can't cross threads)
            items_data = [
                {
                    "id": str(ci.id),
                    "code": ci.code or "",
                    "desc": (ci.description or "")[:200],
                    "unit": ci.unit or "",
                    "rate": float(ci.rate) if ci.rate else 0.0,
                    "region": ci.region or db_id,
                }
                for ci in items_list
            ]

            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor(max_workers=1) as pool:
                indexed = await loop.run_in_executor(pool, _generate_vectors, items_data)

            duration = round(time.monotonic() - start, 1)
            logger.info("Generated %d vectors locally for %s in %.1fs", indexed, db_id, duration)
            return {
                "indexed": indexed,
                "database": db_id,
                "source": "local",
                "duration_seconds": duration,
            }
        except HTTPException:
            raise
        except Exception as gen_err:
            logger.exception("Failed to generate vectors for %s", db_id)
            raise HTTPException(
                500,
                f"Vector generation failed for '{db_id}': {gen_err}. "
                f"Ensure sentence-transformers and lancedb are installed.",
            ) from gen_err

    logger.info("Loading vector data from %s", local_path)

    # Read parquet: columns = id, vector, code, description, unit, rate, region
    import pandas as pd

    df = pd.read_parquet(local_path)
    total = len(df)

    if total == 0:
        return {"indexed": 0, "database": db_id, "message": "Empty vector file"}

    # Index in batches
    batch_size = 256
    indexed = 0
    for i in range(0, total, batch_size):
        batch = df.iloc[i : i + batch_size]
        records = []
        for _, row in batch.iterrows():
            vec = row.get("vector")
            if vec is None:
                continue
            # Convert numpy array to list if needed
            if hasattr(vec, "tolist"):
                vec = vec.tolist()
            elif isinstance(vec, str):
                import json
                vec = json.loads(vec)

            records.append({
                "id": str(row.get("id", "")),
                "vector": vec,
                "code": str(row.get("code", "")),
                "description": str(row.get("description", ""))[:200],
                "unit": str(row.get("unit", "")),
                "rate": float(row.get("rate", 0)),
                "region": str(row.get("region", db_id)),
            })

        if records:
            indexed += vector_index(records)

    duration = round(time.monotonic() - start, 1)
    logger.info("Loaded %d vectors for %s from GitHub in %.1fs", indexed, db_id, duration)

    return {
        "indexed": indexed,
        "database": db_id,
        "source": "github",
        "duration_seconds": duration,
    }


# Mapping db_id to GitHub folder and snapshot filename (3072d embeddings)
_GITHUB_SNAPSHOT_FILES: dict[str, str] = {
    "USA_USD": "US___DDC_CWICR/USA_USD_workitems_costs_resources_EMBEDDINGS_3072_DDC_CWICR.snapshot",
    "UK_GBP": "UK___DDC_CWICR/UK_GBP_workitems_costs_resources_EMBEDDINGS_3072_DDC_CWICR.snapshot",
    "DE_BERLIN": "DE___DDC_CWICR/DE_BERLIN_workitems_costs_resources_EMBEDDINGS_3072_DDC_CWICR.snapshot",
    "ENG_TORONTO": "EN___DDC_CWICR/EN_TORONTO_workitems_costs_resources_EMBEDDINGS_3072_DDC_CWICR.snapshot",
    "FR_PARIS": "FR___DDC_CWICR/FR_PARIS_workitems_costs_resources_EMBEDDINGS_3072_DDC_CWICR.snapshot",
    "SP_BARCELONA": "ES___DDC_CWICR/SP_BARCELONA_workitems_costs_resources_EMBEDDINGS_3072_DDC_CWICR.snapshot",
    "PT_SAOPAULO": "PT___DDC_CWICR/PT_SAOPAULO_workitems_costs_resources_EMBEDDINGS_3072_DDC_CWICR.snapshot",
    "RU_STPETERSBURG": "RU___DDC_CWICR/RU_STPETERSBURG_workitems_costs_resources_EMBEDDINGS_3072_DDC_CWICR.snapshot",
    "AR_DUBAI": "AR___DDC_CWICR/AR_DUBAI_workitems_costs_resources_EMBEDDINGS_3072_DDC_CWICR.snapshot",
    "ZH_SHANGHAI": "ZH___DDC_CWICR/ZH_SHANGHAI_workitems_costs_resources_EMBEDDINGS_3072_DDC_CWICR.snapshot",
    "HI_MUMBAI": "HI___DDC_CWICR/HI_MUMBAI_workitems_costs_resources_EMBEDDINGS_3072_DDC_CWICR.snapshot",
}


@router.post(
    "/vector/restore-snapshot/{db_id}",
    dependencies=[Depends(RequirePermission("costs.create"))],
)
async def restore_qdrant_snapshot(
    db_id: str,
    _user_id: CurrentUserId,
) -> dict:
    """Download a pre-built Qdrant snapshot from GitHub and restore it.

    Downloads 3072d embeddings snapshot (~1.1 GB) and restores into Qdrant.
    Requires Qdrant server running (Docker or binary).
    """
    import asyncio
    import time
    import urllib.request

    from app.core.vector import _get_qdrant

    start = time.monotonic()

    client = _get_qdrant()
    if client is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Qdrant not available. Start Qdrant: docker run -p 6333:6333 qdrant/qdrant",
        )

    snapshot_path = _GITHUB_SNAPSHOT_FILES.get(db_id)
    if not snapshot_path:
        available = ", ".join(sorted(_GITHUB_SNAPSHOT_FILES.keys()))
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Unknown database ID: {db_id}. Available: {available}",
        )

    url = f"{_GITHUB_CWICR_BASE_URL}/{snapshot_path}"

    # Cache locally to avoid re-downloading ~1.1 GB
    cache_dir = Path.home() / ".openestimator" / "cache" / "snapshots"
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_path = cache_dir / f"{db_id}.snapshot"

    # Download if not already cached
    if not local_path.exists() or local_path.stat().st_size < 10_000:
        logger.info(
            "Downloading Qdrant snapshot for %s from GitHub (~1.1 GB): %s",
            db_id,
            url,
        )
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                urllib.request.urlretrieve,
                url,
                str(local_path),
            )
        except Exception as exc:
            local_path.unlink(missing_ok=True)
            logger.error("Failed to download snapshot for %s: %s", db_id, exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"Failed to download snapshot from GitHub: {exc}",
            )

        if not local_path.exists() or local_path.stat().st_size < 10_000:
            local_path.unlink(missing_ok=True)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "Downloaded snapshot file is too small or missing. "
                "The file may not exist on GitHub yet.",
            )
        logger.info(
            "Snapshot downloaded for %s: %.1f MB",
            db_id,
            local_path.stat().st_size / (1024 * 1024),
        )
    else:
        logger.info(
            "Using cached snapshot for %s: %s (%.1f MB)",
            db_id,
            local_path,
            local_path.stat().st_size / (1024 * 1024),
        )

    # Restore snapshot into Qdrant
    collection_name = f"cwicr_{db_id.lower()}"

    try:
        from qdrant_client.models import Distance, VectorParams

        # Create collection if it does not already exist
        existing = [c.name for c in client.get_collections().collections]
        if collection_name not in existing:
            client.create_collection(
                collection_name,
                vectors_config=VectorParams(size=3072, distance=Distance.COSINE),
            )
            logger.info("Created Qdrant collection: %s", collection_name)

        # Recover snapshot — uses the Qdrant HTTP API under the hood
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: client.recover_snapshot(collection_name, location=str(local_path)),
        )
        logger.info("Snapshot restored for collection %s", collection_name)
    except Exception as exc:
        logger.error("Failed to restore snapshot for %s: %s", db_id, exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Failed to restore Qdrant snapshot: {exc}",
        )

    duration = round(time.monotonic() - start, 1)

    # Get collection info after restore
    try:
        col_info = client.get_collection(collection_name)
        vectors_count = col_info.vectors_count
    except Exception:
        vectors_count = None

    logger.info(
        "Qdrant snapshot restore complete for %s: collection=%s, vectors=%s, duration=%.1fs",
        db_id,
        collection_name,
        vectors_count,
        duration,
    )

    return {
        "restored": True,
        "collection": collection_name,
        "database": db_id,
        "vectors_count": vectors_count,
        "source": "github_snapshot",
        "duration_seconds": duration,
    }


@router.get("/vector/search")
async def semantic_search(
    q: str = Query(..., min_length=2, max_length=500, description="Natural language query"),
    region: str | None = Query(default=None, description="Filter by region"),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[dict]:
    """Semantic search using vector similarity.

    Finds cost items whose descriptions are semantically similar
    to the query, even if the exact words don't match.
    E.g. "concrete wall" finds "reinforced partition C30/37".
    """
    from app.core.vector import encode_texts, vector_search

    query_vector = encode_texts([q])[0]
    return vector_search(query_vector, region=region, limit=limit)


# ── Categories (distinct classification.collection values) ───────────────


@router.get("/categories", response_model=list[str])
async def list_categories(
    session: SessionDep,
    region: str | None = Query(default=None, description="Filter by region"),
) -> list[str]:
    """Return distinct classification.collection values. Cached for 30s."""
    cache_key = f"categories_{region or 'all'}"
    now = _time.monotonic()
    if _region_cache.get(cache_key) is not None and now - _region_cache["ts"] < _CACHE_TTL:
        return _region_cache[cache_key]

    from sqlalchemy import select, distinct, func
    from app.modules.costs.models import CostItem

    collection_expr = func.json_extract(CostItem.classification, "$.collection")

    stmt = (
        select(distinct(collection_expr))
        .where(CostItem.is_active.is_(True))
        .where(collection_expr.isnot(None))
        .where(collection_expr != "")
    )

    if region:
        stmt = stmt.where(CostItem.region == region)

    stmt = stmt.order_by(collection_expr)

    result = await session.execute(stmt)
    cats = [row[0] for row in result.all() if row[0]]
    _region_cache[cache_key] = cats
    _region_cache["ts"] = now
    return cats


# ── Get by ID ─────────────────────────────────────────────────────────────


@router.get("/{item_id}", response_model=CostItemResponse)
async def get_cost_item(
    item_id: uuid.UUID,
    service: CostItemService = Depends(_get_service),
) -> CostItemResponse:
    """Get a cost item by ID."""
    item = await service.get_cost_item(item_id)
    return CostItemResponse.model_validate(item)


# ── Update ────────────────────────────────────────────────────────────────


@router.patch(
    "/{item_id}",
    response_model=CostItemResponse,
    dependencies=[Depends(RequirePermission("costs.update"))],
)
async def update_cost_item(
    item_id: uuid.UUID,
    data: CostItemUpdate,
    _user_id: CurrentUserId,
    service: CostItemService = Depends(_get_service),
) -> CostItemResponse:
    """Update a cost item."""
    item = await service.update_cost_item(item_id, data)
    return CostItemResponse.model_validate(item)


# ── Delete ────────────────────────────────────────────────────────────────


@router.delete(
    "/{item_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("costs.delete"))],
)
async def delete_cost_item(
    item_id: uuid.UUID,
    _user_id: CurrentUserId,
    service: CostItemService = Depends(_get_service),
) -> None:
    """Soft-delete a cost item."""
    await service.delete_cost_item(item_id)


# ── Bulk import ───────────────────────────────────────────────────────────


@router.post(
    "/bulk",
    response_model=list[CostItemResponse],
    status_code=201,
    dependencies=[Depends(RequirePermission("costs.create"))],
)
async def bulk_import_cost_items(
    data: list[CostItemCreate],
    _user_id: CurrentUserId,
    service: CostItemService = Depends(_get_service),
) -> list[CostItemResponse]:
    """Bulk import cost items. Skips duplicates by code."""
    items = await service.bulk_import(data)
    return [CostItemResponse.model_validate(i) for i in items]


# ── File import (CSV / Excel) ────────────────────────────────────────────

# Column name aliases for flexible matching (all lowercased)
_COST_COLUMN_ALIASES: dict[str, list[str]] = {
    "code": [
        "code", "item code", "cost code", "artikelnummer", "art.nr.",
        "item", "nr", "nr.", "no", "no.", "#", "id", "position",
    ],
    "description": [
        "description", "beschreibung", "desc", "text", "bezeichnung",
        "item description", "name", "title",
    ],
    "unit": [
        "unit", "einheit", "me", "uom", "unit of measure", "measure",
    ],
    "rate": [
        "rate", "price", "cost", "unit rate", "unit price", "unit cost",
        "ep", "einheitspreis", "preis", "amount", "value",
    ],
    "currency": [
        "currency", "währung", "curr", "cur",
    ],
    "classification": [
        "classification", "din 276", "din276", "kg", "cost group",
        "nrm", "masterformat", "class", "category", "group",
    ],
}


def _match_cost_column(header: str) -> str | None:
    """Match a header string to a canonical column name using the alias map.

    Args:
        header: Raw column header text from the uploaded file.

    Returns:
        Canonical column key or None if unrecognised.
    """
    normalised = header.strip().lower()
    for canonical, aliases in _COST_COLUMN_ALIASES.items():
        if normalised in aliases:
            return canonical
    return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Parse a value to float, returning *default* on failure.

    Handles strings with comma decimal separators (e.g. "1.234,56" -> 1234.56).
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    # Handle European-style numbers: "1.234,56" -> "1234.56"
    if "," in text and "." in text:
        last_comma = text.rfind(",")
        last_dot = text.rfind(".")
        if last_comma > last_dot:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except (ValueError, TypeError):
        return default


def _parse_cost_rows_from_csv(content_bytes: bytes) -> list[dict[str, Any]]:
    """Parse rows from a CSV file for cost import.

    Tries UTF-8 first, then Latin-1 as fallback (common for DACH region files).
    """
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = content_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Unable to decode CSV file -- unsupported encoding")

    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel  # type: ignore[assignment]

    reader = csv.reader(io.StringIO(text), dialect)
    raw_headers = next(reader, None)
    if not raw_headers:
        raise ValueError("CSV file is empty or has no header row")

    column_map: dict[int, str] = {}
    for idx, hdr in enumerate(raw_headers):
        canonical = _match_cost_column(hdr)
        if canonical:
            column_map[idx] = canonical

    rows: list[dict[str, Any]] = []
    for raw_row in reader:
        row: dict[str, Any] = {}
        for idx, val in enumerate(raw_row):
            canonical = column_map.get(idx)
            if canonical:
                row[canonical] = val.strip() if isinstance(val, str) else val
        if row:
            rows.append(row)

    return rows


def _parse_cost_rows_from_excel(content_bytes: bytes) -> list[dict[str, Any]]:
    """Parse rows from an Excel (.xlsx) file for cost import."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(content_bytes), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        raise ValueError("Excel file has no worksheets")

    rows_iter = ws.iter_rows(values_only=True)
    raw_headers = next(rows_iter, None)
    if not raw_headers:
        raise ValueError("Excel file is empty or has no header row")

    column_map: dict[int, str] = {}
    for idx, hdr in enumerate(raw_headers):
        if hdr is not None:
            canonical = _match_cost_column(str(hdr))
            if canonical:
                column_map[idx] = canonical

    rows: list[dict[str, Any]] = []
    for raw_row in rows_iter:
        row: dict[str, Any] = {}
        for idx, val in enumerate(raw_row):
            canonical = column_map.get(idx)
            if canonical and val is not None:
                row[canonical] = val
        if row:
            rows.append(row)

    wb.close()
    return rows


@router.post(
    "/import/file",
    dependencies=[Depends(RequirePermission("costs.create"))],
)
async def import_cost_file(
    _user_id: CurrentUserId,
    file: UploadFile = File(..., description="Excel (.xlsx) or CSV (.csv) file"),
    service: CostItemService = Depends(_get_service),
) -> dict[str, Any]:
    """Import cost items from an Excel or CSV file upload.

    Accepts a multipart file upload. The file must be .xlsx or .csv.

    Expected columns (flexible auto-detection):
    - **Code / Item Code / Nr.** -- unique cost item code (required)
    - **Description / Beschreibung / Text** -- description (required)
    - **Unit / Einheit / ME** -- unit of measurement
    - **Rate / Price / Cost / EP** -- unit rate or price
    - **Currency / Wahrung** -- currency code (defaults to EUR)
    - **Classification / DIN 276 / KG** -- classification code

    Returns:
        Summary with counts of imported, skipped, and error details per row.
    """
    # Validate file type
    filename = (file.filename or "").lower()
    if not filename.endswith((".xlsx", ".csv", ".xls")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Please upload an Excel (.xlsx) or CSV (.csv) file.",
        )

    # Read file content
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    # Limit file size (10 MB)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large. Maximum size is 10 MB.",
        )

    # Parse rows based on file type
    try:
        if filename.endswith(".xlsx") or filename.endswith(".xls"):
            rows = _parse_cost_rows_from_excel(content)
        else:
            rows = _parse_cost_rows_from_csv(content)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse file: {exc}",
        )
    except Exception as exc:
        logger.exception("Unexpected error parsing cost import file: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to parse file. Please check the format and try again.",
        )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No data rows found in file. Check that the first row contains column headers.",
        )

    # Convert rows to CostItemCreate objects and import via service
    items_to_import: list[CostItemCreate] = []
    skipped = 0
    errors: list[dict[str, Any]] = []
    auto_code = 1

    for row_idx, row in enumerate(rows, start=2):
        try:
            code = str(row.get("code", "")).strip()
            description = str(row.get("description", "")).strip()

            # Skip rows without both code and description
            if not code and not description:
                skipped += 1
                continue

            # Auto-generate code if missing
            if not code:
                code = f"IMPORT-{auto_code:06d}"
            auto_code += 1

            # Skip obvious summary rows
            desc_lower = description.lower()
            if desc_lower in (
                "total", "grand total", "summe", "gesamt", "gesamtsumme",
                "subtotal", "zwischensumme",
            ):
                skipped += 1
                continue

            # Parse unit (default: pcs)
            unit = str(row.get("unit", "pcs")).strip()
            if not unit:
                unit = "pcs"

            # Parse rate
            rate = _safe_float(row.get("rate"), default=0.0)

            # Parse currency (default: EUR)
            currency = str(row.get("currency", "EUR")).strip().upper()
            if not currency:
                currency = "EUR"

            # Build classification
            classification: dict[str, str] = {}
            class_value = str(row.get("classification", "")).strip()
            if class_value:
                classification["code"] = class_value

            items_to_import.append(
                CostItemCreate(
                    code=code,
                    description=description,
                    unit=unit,
                    rate=rate,
                    currency=currency,
                    source="file_import",
                    classification=classification,
                )
            )

        except Exception as exc:
            errors.append({
                "row": row_idx,
                "error": str(exc),
                "data": {k: str(v)[:100] for k, v in row.items()},
            })
            logger.warning("Cost import error at row %d: %s", row_idx, exc)

    # Bulk import via service (handles duplicate detection)
    imported_items = await service.bulk_import(items_to_import) if items_to_import else []
    imported_count = len(imported_items)
    skipped_by_duplicate = len(items_to_import) - imported_count

    logger.info(
        "Cost file import complete: imported=%d, skipped=%d (empty) + %d (duplicate), errors=%d",
        imported_count,
        skipped,
        skipped_by_duplicate,
        len(errors),
    )

    return {
        "imported": imported_count,
        "skipped": skipped + skipped_by_duplicate,
        "errors": errors,
        "total_rows": len(rows),
    }


# ── Load CWICR database from local DDC Toolkit ──────────────────────────────

# GitHub repository info for downloading CWICR parquet files
_GITHUB_CWICR_BASE_URL = (
    "https://github.com/datadrivenconstruction/"
    "OpenConstructionEstimate-DDC-CWICR/raw/main"
)

# Mapping from db_id to the GitHub folder/filename structure
_GITHUB_CWICR_FILES: dict[str, str] = {
    "USA_USD": "US___DDC_CWICR/USA_USD_workitems_costs_resources_DDC_CWICR.parquet",
    "UK_GBP": "UK___DDC_CWICR/UK_GBP_workitems_costs_resources_DDC_CWICR.parquet",
    "DE_BERLIN": "DE___DDC_CWICR/DE_BERLIN_workitems_costs_resources_DDC_CWICR.parquet",
    "ENG_TORONTO": "EN___DDC_CWICR/ENG_TORONTO_workitems_costs_resources_DDC_CWICR.parquet",
    "FR_PARIS": "FR___DDC_CWICR/FR_PARIS_workitems_costs_resources_DDC_CWICR.parquet",
    "SP_BARCELONA": "ES___DDC_CWICR/SP_BARCELONA_workitems_costs_resources_DDC_CWICR.parquet",
    "PT_SAOPAULO": "PT___DDC_CWICR/PT_SAOPAULO_workitems_costs_resources_DDC_CWICR.parquet",
    "RU_STPETERSBURG": "RU___DDC_CWICR/RU_STPETERSBURG_workitems_costs_resources_DDC_CWICR.parquet",
    "AR_DUBAI": "AR___DDC_CWICR/AR_DUBAI_workitems_costs_resources_DDC_CWICR.parquet",
    "ZH_SHANGHAI": "ZH___DDC_CWICR/ZH_SHANGHAI_workitems_costs_resources_DDC_CWICR.parquet",
    "HI_MUMBAI": "HI___DDC_CWICR/HI_MUMBAI_workitems_costs_resources_DDC_CWICR.parquet",
}

CWICR_SEARCH_PATHS = [
    "../../DDC_Toolkit/pricing/data/excel",
    "../DDC_Toolkit/pricing/data/excel",
    str(Path.home() / "DDC_Toolkit" / "pricing" / "data" / "excel"),
    str(Path.home() / "Desktop" / "CodeProjects" / "DDC_Toolkit" / "pricing" / "data" / "excel"),
]

# Local cache directory for downloaded parquet files
_CWICR_CACHE_DIR = Path.home() / ".openestimator" / "cache"


def _download_cwicr_from_github_sync(db_id: str) -> Path | None:
    """Download a CWICR parquet file from GitHub if available (sync version).

    Downloads to ~/.openestimator/cache/{db_id}.parquet.
    Returns the local path on success, None on failure.
    """
    import urllib.request

    github_path = _GITHUB_CWICR_FILES.get(db_id)
    if not github_path:
        return None

    url = f"{_GITHUB_CWICR_BASE_URL}/{github_path}"
    cache_dir = _CWICR_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_path = cache_dir / f"{db_id}.parquet"

    # If already cached, return it
    if local_path.exists() and local_path.stat().st_size > 1000:
        logger.info("Using cached CWICR file: %s", local_path)
        return local_path

    logger.info("Downloading CWICR %s from GitHub: %s", db_id, url)
    try:
        urllib.request.urlretrieve(url, str(local_path))
        if local_path.exists() and local_path.stat().st_size > 1000:
            logger.info("Downloaded CWICR %s: %d bytes", db_id, local_path.stat().st_size)
            return local_path
        else:
            logger.warning("Downloaded file too small or missing: %s", local_path)
            local_path.unlink(missing_ok=True)
            return None
    except Exception as exc:
        logger.warning("Failed to download CWICR %s from GitHub: %s", db_id, exc)
        local_path.unlink(missing_ok=True)
        return None


async def _download_cwicr_from_github(db_id: str) -> Path | None:
    """Async wrapper: runs the sync download in a thread pool to avoid blocking."""
    import asyncio
    return await asyncio.to_thread(_download_cwicr_from_github_sync, db_id)


async def _find_cwicr_file(db_id: str) -> Path | None:
    """Find a CWICR database file by database ID (e.g., DE_BERLIN).

    Priority: Local Parquet > Local Excel SIMPLE > Local Excel any > GitHub download.
    """
    # Priority 1: Parquet files in local DDC_Toolkit (fastest and most reliable)
    for search_path in CWICR_SEARCH_PATHS:
        parquet_path = Path(search_path).parent / "parquet"
        if parquet_path.exists():
            for f in parquet_path.iterdir():
                if f.name.startswith(db_id) and f.suffix == ".parquet":
                    return f

    # Priority 2: Cached parquet from previous GitHub download
    cached = _CWICR_CACHE_DIR / f"{db_id}.parquet"
    if cached.exists() and cached.stat().st_size > 1000:
        return cached

    # Priority 3: Excel SIMPLE
    for search_path in CWICR_SEARCH_PATHS:
        p = Path(search_path)
        if not p.exists():
            continue
        for f in p.iterdir():
            if f.name.startswith(db_id) and "_SIMPLE" in f.name and f.suffix == ".xlsx":
                return f

    # Priority 4: Any Excel
    for search_path in CWICR_SEARCH_PATHS:
        p = Path(search_path)
        if not p.exists():
            continue
        for f in p.iterdir():
            if f.name.startswith(db_id) and f.suffix == ".xlsx":
                return f

    # Priority 5: Download from GitHub (fallback — runs in thread to not block event loop)
    downloaded = await _download_cwicr_from_github(db_id)
    if downloaded:
        return downloaded

    return None


@router.post(
    "/load-cwicr/{db_id}",
    dependencies=[Depends(RequirePermission("costs.create"))],
)
async def load_cwicr_database(
    db_id: str,
    session: SessionDep,
    _user_id: CurrentUserId,
) -> dict:
    """Load a CWICR regional database from local DDC Toolkit files.

    Optimized: reads Parquet, deduplicates by rate_code (55K unique items
    from 900K total rows), then bulk-inserts into SQLite.
    Typical time: 10-30 seconds.

    For databases not available locally (e.g. UK_GBP, USA_USD), automatically
    downloads from GitHub and caches at ~/.openestimator/cache/.
    """
    import time

    import pandas as pd
    from sqlalchemy import func, select

    start = time.monotonic()

    # Quick check: if this region is already loaded, return immediately
    from app.modules.costs.models import CostItem

    existing_count_stmt = (
        select(func.count())
        .select_from(CostItem)
        .where(CostItem.region == db_id, CostItem.is_active.is_(True))
    )
    existing_count = (await session.execute(existing_count_stmt)).scalar_one()
    if existing_count > 10:
        duration = round(time.monotonic() - start, 1)
        logger.info("CWICR %s already loaded (%d items), skipping", db_id, existing_count)
        return {
            "imported": 0,
            "skipped": existing_count,
            "region": db_id,
            "total_items": existing_count,
            "status": "already_loaded",
            "message": f"Database '{db_id}' is already loaded with {existing_count:,} items. "
                       f"To reload, delete the region first.",
            "duration_seconds": duration,
        }

    # Find the file (async — GitHub download runs in thread pool)
    cwicr_path = await _find_cwicr_file(db_id)
    if not cwicr_path:
        raise HTTPException(
            status_code=404,
            detail=f"CWICR database '{db_id}' not found. "
            f"Install DDC_Toolkit at ~/Desktop/CodeProjects/DDC_Toolkit "
            f"or check your internet connection for GitHub download.",
        )

    logger.info("Loading CWICR from %s", cwicr_path)

    # Read file in thread pool to avoid blocking event loop
    import asyncio

    _path = cwicr_path

    def _read_file() -> "pd.DataFrame":
        if _path.suffix == ".parquet":
            return pd.read_parquet(_path)
        return pd.read_excel(_path, engine="openpyxl")

    df = await asyncio.to_thread(_read_file)

    total_rows = len(df)
    logger.info("Raw data: %d rows", total_rows)

    from app.config import get_settings
    settings = get_settings()
    sqlite_url = settings.database_url
    db_file = sqlite_url.split("///")[-1] if "///" in sqlite_url else "openestimate.db"

    # Run in thread to avoid blocking the event loop during heavy pandas + sqlite work.
    try:
        result_data = await asyncio.to_thread(
            _process_and_insert_cwicr, str(cwicr_path), db_id, db_file
        )
    except Exception:
        logger.exception("CWICR import failed for %s", db_id)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to import CWICR database '{db_id}'. Check server logs.",
        )

    duration = round(time.monotonic() - start, 1)
    result_data["duration_seconds"] = duration
    result_data["source_file"] = cwicr_path.name
    logger.info("CWICR %s: %d imported, %d skipped in %.1fs",
                db_id, result_data.get("imported", 0), result_data.get("skipped", 0), duration)
    _invalidate_cost_cache()
    return result_data


def _process_and_insert_cwicr(parquet_path: str, db_id: str, db_file: str) -> dict[str, Any]:
    """Process CWICR parquet + insert into SQLite. Runs in a SEPARATE PROCESS.

    Uses vectorized pandas (no iterrows!) + micro-batch SQLite inserts.
    Completely bypasses GIL — the main process event loop stays responsive.
    """
    import json as _json
    import logging
    import math
    import sqlite3
    import time

    import pandas as pd

    _log = logging.getLogger("cwicr_import")
    start = time.monotonic()

    # 1. Read parquet
    df = pd.read_parquet(parquet_path)
    total_rows = len(df)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "rate_code" not in df.columns:
        return {"imported": 0, "skipped": 0, "total_rows": total_rows, "error": "no rate_code column"}

    # 2. Vectorized processing — use groupby.first() instead of iterrows
    if "rate_original_name" in df.columns and "rate_final_name" in df.columns:
        df["_desc"] = (df["rate_original_name"].fillna("").astype(str) + " " +
                       df["rate_final_name"].fillna("").astype(str)).str.strip()
    elif "rate_original_name" in df.columns:
        df["_desc"] = df["rate_original_name"].fillna("").astype(str)
    else:
        df["_desc"] = ""

    # Aggregate: take first row's values per rate_code (vectorized, no iteration)
    agg_cols = {}
    for col in ["_desc", "rate_unit", "total_cost_per_position",
                 "collection_name", "department_name", "section_name", "subsection_name",
                 "category_type", "cost_of_working_hours",
                 "total_value_machinery_equipment", "total_material_cost_per_position",
                 "total_labor_hours_all_personnel", "count_total_people_per_unit"]:
        if col in df.columns:
            agg_cols[col] = "first"

    grouped = df.groupby("rate_code", sort=False).agg(agg_cols)
    _log.info("Grouped %d unique items from %d rows in %.1fs",
              len(grouped), total_rows, time.monotonic() - start)

    # 3. Build insert tuples (vectorized — no Python loop over rows)
    def _safe_float(v: object) -> float:
        if v is None:
            return 0.0
        try:
            f = float(v)  # type: ignore[arg-type]
            return 0.0 if math.isnan(f) else f
        except (ValueError, TypeError):
            return 0.0

    def _safe_str(v: object) -> str:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        return str(v).strip()

    # 4. Pre-build resource components per rate_code using vectorized pandas
    # Filter out empty rows, then group resources by rate_code
    _LABOR_UNITS = {"hrs", "h", "person-hour", "person-hours", "man-hours"}

    # Handle column name variants across different CWICR regional databases:
    # Most databases use: resource_cost, resource_price_per_unit_current
    # ENG_TORONTO uses:   resource_cost_eur, resource_price_per_unit_eur_current
    _cost_col = "resource_cost" if "resource_cost" in df.columns else "resource_cost_eur"
    _price_col = "resource_price_per_unit_current" if "resource_price_per_unit_current" in df.columns else "resource_price_per_unit_eur_current"

    res_cols = ["rate_code", "resource_name", "resource_code", "resource_unit",
                "resource_quantity", _price_col,
                _cost_col, "row_type", "is_machine", "is_material"]
    available_res_cols = [c for c in res_cols if c in df.columns]

    resources_by_code: dict[str, list[dict]] = {}
    if "resource_name" in df.columns and _cost_col in df.columns:
        # Filter rows that have resource data (non-empty name, non-zero cost)
        res_df = df[available_res_cols].copy()
        res_df = res_df[res_df["resource_name"].fillna("").str.len() > 0]
        if _cost_col in res_df.columns:
            res_df = res_df[res_df[_cost_col].fillna(0).astype(float).abs() > 0.001]
        if "row_type" in res_df.columns:
            res_df = res_df[res_df["row_type"].fillna("") != "Scope of work"]

        for rc, grp in res_df.groupby("rate_code", sort=False):
            comps = []
            for _, r in grp.iterrows():
                res_unit = _safe_str(r.get("resource_unit", ""))
                is_mach = bool(r.get("is_machine", False))
                is_mat = bool(r.get("is_material", False))
                rtype = _safe_str(r.get("row_type", ""))

                if is_mach:
                    ctype = "operator" if rtype == "Machinist" else "electricity" if rtype == "Electricity" else "equipment"
                elif is_mat:
                    ctype = "labor" if res_unit.lower() in _LABOR_UNITS else "material"
                elif rtype == "Abstract resource":
                    ctype = "material"
                else:
                    ctype = "other"

                comps.append({
                    "name": _safe_str(r.get("resource_name", ""))[:200],
                    "code": _safe_str(r.get("resource_code", ""))[:50],
                    "unit": res_unit[:20],
                    "quantity": round(_safe_float(r.get("resource_quantity", 0)), 4),
                    "unit_rate": round(_safe_float(r.get(_price_col, 0)), 2),
                    "cost": round(_safe_float(r.get(_cost_col, 0)), 2),
                    "type": ctype,
                })
            resources_by_code[str(rc)] = comps

        _log.info("Built resources for %d rate_codes in %.1fs", len(resources_by_code), time.monotonic() - start)

    # 5. Open SQLite and insert in micro-batches
    conn = sqlite3.connect(db_file, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")

    sql = """INSERT OR IGNORE INTO oe_costs_item
        (id, code, description, unit, rate, currency, source,
         classification, tags, components, descriptions,
         is_active, region, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""

    imported = 0
    skipped_count = 0
    micro_batch_size = 200
    batch: list[tuple] = []

    for rate_code, row in grouped.iterrows():
        desc = _safe_str(row.get("_desc", ""))
        if len(desc) < 3:
            desc = _safe_str(row.get("subsection_name", ""))
        if len(desc) < 3:
            skipped_count += 1
            continue

        code = _safe_str(rate_code)[:100]
        if not code:
            skipped_count += 1
            continue

        unit = _safe_str(row.get("rate_unit", "m2"))[:20] or "m2"
        rate = round(_safe_float(row.get("total_cost_per_position", 0)), 2)

        classification: dict[str, str] = {}
        for key in ("collection_name", "department_name", "section_name", "subsection_name"):
            val = _safe_str(row.get(key, ""))
            if val:
                classification[key.replace("_name", "")] = val
        cat = _safe_str(row.get("category_type", ""))
        if cat:
            classification["category"] = cat

        metadata: dict[str, float] = {}
        for mkey, col in [("labor_cost", "cost_of_working_hours"),
                          ("equipment_cost", "total_value_machinery_equipment"),
                          ("material_cost", "total_material_cost_per_position"),
                          ("labor_hours", "total_labor_hours_all_personnel"),
                          ("workers_per_unit", "count_total_people_per_unit")]:
            v = _safe_float(row.get(col, 0))
            if v > 0:
                metadata[mkey] = round(v, 2)

        # Get full resource components for this rate_code
        components = resources_by_code.get(code, [])

        batch.append((
            str(uuid.uuid4()), code, desc[:500], unit, str(rate), "", "cwicr",
            _json.dumps(classification), "[]", _json.dumps(components), "{}",
            1, db_id, _json.dumps(metadata),
        ))

        if len(batch) >= micro_batch_size:
            try:
                conn.executemany(sql, batch)
                conn.commit()
                imported += len(batch)
            except Exception:
                conn.rollback()
                for r in batch:
                    try:
                        conn.execute(sql, r)
                        conn.commit()
                        imported += 1
                    except Exception:
                        conn.rollback()
            batch.clear()

    # Final batch
    if batch:
        try:
            conn.executemany(sql, batch)
            conn.commit()
            imported += len(batch)
        except Exception:
            conn.rollback()
            for r in batch:
                try:
                    conn.execute(sql, r)
                    conn.commit()
                    imported += 1
                except Exception:
                    conn.rollback()

    conn.close()
    elapsed = round(time.monotonic() - start, 1)
    _log.info("CWICR %s: %d imported, %d skipped in %.1fs", db_id, imported, skipped_count, elapsed)

    return {
        "imported": imported,
        "skipped": skipped_count,
        "total_rows": total_rows,
        "unique_items": len(grouped),
        "database": db_id,
    }


def _build_cwicr_items(df: "pd.DataFrame", db_id: str) -> list[dict[str, Any]]:
    """Legacy — kept for reference but no longer called."""
    import math

    import pandas as pd_local

    # Normalize column names
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]

    def _safe(val: object) -> float:
        if val is None:
            return 0.0
        try:
            f = float(val)  # type: ignore[arg-type]
            return 0.0 if math.isnan(f) else f
        except (ValueError, TypeError):
            return 0.0

    def _str(val: object) -> str:
        if val is None or (isinstance(val, float) and pd_local.isna(val)):
            return ""
        return str(val).strip()

    # Build description column
    if "rate_original_name" in df.columns and "rate_final_name" in df.columns:
        df.loc[:, "_full_desc"] = (
            df["rate_original_name"].fillna("").astype(str) + " " +
            df["rate_final_name"].fillna("").astype(str)
        ).str.strip()

    if "rate_code" not in df.columns:
        return []

    grouped = df.groupby("rate_code", sort=False)
    total_rows = len(df)
    logger.info("Grouped into %d unique rate_codes from %d rows", len(grouped), total_rows)

    result_items: list[dict[str, Any]] = []
    item_count = 0

    for rate_code, group in grouped:
        first = group.iloc[0]

        desc = _str(first.get("_full_desc", "")) if "_full_desc" in first.index else ""
        if len(desc) < 3:
            desc = _str(first.get("rate_original_name", ""))
        if len(desc) < 3:
            desc = _str(first.get("subsection_name", ""))
        if len(desc) < 3:
            continue

        code = _str(rate_code)[:100] or f"CWICR-{db_id}-{item_count:06d}"
        unit = _str(first.get("rate_unit", "m2"))[:20] or "m2"
        rate = _safe(first.get("total_cost_per_position", 0))

        classification: dict[str, str] = {}
        for key in ("collection_name", "department_name", "section_name", "subsection_name"):
            val = _str(first.get(key, ""))
            if val:
                classification[key.replace("_name", "")] = val
        cat_type = _str(first.get("category_type", ""))
        if cat_type:
            classification["category"] = cat_type

        # Extract summary metadata from first row only (skip per-row component iteration for speed)
        labor_total = _safe(first.get("cost_of_working_hours", 0))
        equipment_total = _safe(first.get("total_value_machinery_equipment", 0))
        material_total = _safe(first.get("total_material_cost_per_position", 0))
        labor_hours = _safe(first.get("total_labor_hours_all_personnel", 0))

        metadata: dict[str, Any] = {}
        if labor_total > 0:
            metadata["labor_cost"] = round(labor_total, 2)
        if equipment_total > 0:
            metadata["equipment_cost"] = round(equipment_total, 2)
        if material_total > 0:
            metadata["material_cost"] = round(material_total, 2)
        if labor_hours > 0:
            metadata["labor_hours"] = round(labor_hours, 2)
        workers = _safe(first.get("count_total_people_per_unit", 0))
        if workers > 0:
            metadata["workers_per_unit"] = round(workers, 1)

        result_items.append({
            "code": code,
            "description": desc[:500],
            "unit": unit,
            "rate": str(round(rate, 2)),
            "currency": "",
            "source": "cwicr",
            "classification": classification,
            "tags": [],
            "components": [],
            "descriptions": {},
            "is_active": True,
            "region": db_id,
            "metadata": metadata,
        })
        item_count += 1

    return result_items

    # Old processing code removed — now handled by _build_cwicr_items() + batch insert above
    pass  # unreachable — function returns above


def _bulk_insert_costs_sync(db_path: str, items: list[dict]) -> int:
    """Bulk insert cost items using a SEPARATE sync SQLite connection.

    This runs in a thread pool and uses its own connection, so it does NOT
    block the async session pool (login, search, etc. remain responsive).

    Uses INSERT OR IGNORE to skip duplicate codes per region.
    """
    import json as _json
    import sqlite3

    if not items:
        return 0

    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")  # WAL allows concurrent reads during write
    conn.execute("PRAGMA busy_timeout=30000")  # Wait up to 30s if locked

    sql = """
        INSERT OR IGNORE INTO oe_costs_item
            (id, code, description, unit, rate, currency, source,
             classification, tags, components, descriptions,
             is_active, region, metadata)
        VALUES
            (?, ?, ?, ?, ?, ?, ?,
             ?, ?, ?, ?,
             ?, ?, ?)
    """

    rows = []
    for item in items:
        region = item.get("region", "")

        rows.append((
            str(uuid.uuid4()),
            item["code"],
            item["description"][:500],
            item["unit"][:20],
            item["rate"],
            item.get("currency", ""),
            item.get("source", "cwicr"),
            _json.dumps(item.get("classification", {})),
            "[]",
            "[]",
            "{}",
            1,
            region,
            _json.dumps(item.get("metadata", {})),
        ))

    # Insert in micro-batches of 200 with commit after each.
    # This releases the SQLite write lock between batches so other
    # connections (login, search) are never blocked for more than ~1 second.
    import time
    micro_batch = 200
    inserted = 0
    for i in range(0, len(rows), micro_batch):
        chunk = rows[i:i + micro_batch]
        try:
            conn.executemany(sql, chunk)
            conn.commit()
            inserted += len(chunk)
        except Exception:
            conn.rollback()
            # Fallback: one-by-one for this chunk
            for row in chunk:
                try:
                    conn.execute(sql, row)
                    conn.commit()
                    inserted += 1
                except Exception:
                    conn.rollback()
        # Brief sleep to yield SQLite lock for other connections
        if i % 2000 == 0 and i > 0:
            time.sleep(0.1)

    conn.close()
    return inserted


async def _bulk_insert_costs(session: AsyncSession, items: list[dict]) -> int:
    """Async wrapper: runs bulk insert in a thread with its own SQLite connection."""
    import asyncio
    from app.config import get_settings

    settings = get_settings()
    db_url = settings.database_url
    # Extract SQLite file path from URL like "sqlite+aiosqlite:///path/to/db"
    if "sqlite" in db_url:
        db_path = db_url.split("///")[-1] if "///" in db_url else "openestimate.db"
    else:
        db_path = "openestimate.db"

    return await asyncio.to_thread(_bulk_insert_costs_sync, db_path, items)


# ── Delete CWICR database ───────────────────────────────────────────────────


@router.delete(
    "/actions/clear-database",
    dependencies=[Depends(RequirePermission("costs.update"))],
)
async def clear_cost_database(
    session: SessionDep,
    _user_id: CurrentUserId,
    source: str = Query(
        default="", description="Filter by source (e.g. 'cwicr'). Empty = delete ALL.",
    ),
) -> dict:
    """Delete cost items. Optionally filter by source."""
    from sqlalchemy import delete as sql_delete
    from app.modules.costs.models import CostItem

    if source:
        stmt = sql_delete(CostItem).where(CostItem.source == source)
    else:
        stmt = sql_delete(CostItem)

    result = await session.execute(stmt)
    await session.commit()
    count = result.rowcount  # type: ignore[union-attr]

    return {"deleted": count, "source_filter": source or "all"}


# ── Export cost database as Excel ────────────────────────────────────────────


@router.get(
    "/actions/export-excel",
    dependencies=[Depends(RequirePermission("costs.list"))],
)
async def export_cost_database(
    session: SessionDep,
    _user_id: CurrentUserId,
) -> StreamingResponse:
    """Export all cost items as Excel file."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    from app.modules.costs.models import CostItem
    from sqlalchemy import select

    result = await session.execute(
        select(CostItem).where(CostItem.is_active.is_(True)).limit(50000)
    )
    items = result.scalars().all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Cost Database"

    headers = ["Code", "Description", "Unit", "Rate", "Currency", "Source", "Region"]
    for i, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=i, value=h)
        cell.font = Font(bold=True)

    for row_idx, item in enumerate(items, 2):
        ws.cell(row=row_idx, column=1, value=item.code)
        ws.cell(row=row_idx, column=2, value=item.description)
        ws.cell(row=row_idx, column=3, value=item.unit)
        try:
            ws.cell(row=row_idx, column=4, value=float(item.rate))
        except (ValueError, TypeError):
            ws.cell(row=row_idx, column=4, value=0)
        ws.cell(row=row_idx, column=5, value=item.currency)
        ws.cell(row=row_idx, column=6, value=item.source)
        ws.cell(row=row_idx, column=7, value=getattr(item, "region", ""))

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="cost_database.xlsx"'},
    )




