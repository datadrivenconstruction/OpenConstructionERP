"""Architecture Map API routes.

Read-only endpoints that serve the architecture manifest JSON and provide
search/filter capabilities over modules, connections, and statistics.

Endpoints:
    GET  /                     -- Full architecture manifest
    GET  /modules              -- List modules with optional stats
    GET  /modules/{module_id}  -- Single module detail
    GET  /connections          -- List connections, filterable by type/source/target
    GET  /search?q=            -- Fuzzy search across all entities
    GET  /stats                -- Aggregate statistics
"""

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Architecture Map"],
    dependencies=[Depends(get_current_user_id)],
)

# ── Manifest cache ───────────────────────────────────────────────────────

_MANIFEST_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "frontend"
    / "src"
    / "features"
    / "architecture"
    / "architecture_manifest.json"
)

_cached_manifest: dict[str, Any] | None = None

_EMPTY_MANIFEST: dict[str, Any] = {
    "meta": {},
    "modules": [],
    "connections": [],
    "layers": [],
    "categories": [],
}


def _load_manifest(force: bool = False) -> dict[str, Any]:
    """Load the architecture manifest from disk, with in-memory caching.

    Args:
        force: If True, bypass cache and re-read from disk.

    Returns:
        The parsed manifest dict, or an empty structure if file is missing.
    """
    global _cached_manifest

    if _cached_manifest is not None and not force:
        return _cached_manifest

    if not _MANIFEST_PATH.exists():
        logger.warning("Architecture manifest not found at %s", _MANIFEST_PATH)
        _cached_manifest = _EMPTY_MANIFEST.copy()
        return _cached_manifest

    try:
        raw = _MANIFEST_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        _cached_manifest = data
        logger.info("Loaded architecture manifest from %s", _MANIFEST_PATH)
        return _cached_manifest
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load architecture manifest: %s", exc)
        _cached_manifest = _EMPTY_MANIFEST.copy()
        return _cached_manifest


# ── GET / — Full manifest ────────────────────────────────────────────────


@router.get("/")
async def get_manifest(
    refresh: bool = Query(False, description="Force reload manifest from disk"),
) -> dict[str, Any]:
    """Return the full architecture manifest JSON.

    Pass ?refresh=true to force re-reading the file from disk.
    """
    return _load_manifest(force=refresh)


# ── GET /modules — List modules ──────────────────────────────────────────


@router.get("/modules/")
async def list_modules(
    layer: str | None = Query(None, description="Filter by layer (e.g. frontend, backend)"),
    category: str | None = Query(None, description="Filter by category"),
    refresh: bool = Query(False, description="Force reload manifest from disk"),
) -> list[dict[str, Any]]:
    """Return list of modules from the architecture manifest.

    Supports optional filtering by layer and category.
    Each module includes a connection count for quick stats.
    """
    manifest = _load_manifest(force=refresh)
    modules: list[dict[str, Any]] = manifest.get("modules", [])
    connections: list[dict[str, Any]] = manifest.get("connections", [])

    if layer:
        layer_lower = layer.lower()
        modules = [m for m in modules if m.get("layer", "").lower() == layer_lower]

    if category:
        category_lower = category.lower()
        modules = [m for m in modules if m.get("category", "").lower() == category_lower]

    # Enrich with connection counts
    result: list[dict[str, Any]] = []
    for mod in modules:
        mod_id = mod.get("id", "")
        conn_count = sum(
            1
            for c in connections
            if c.get("source") == mod_id or c.get("target") == mod_id
        )
        result.append({**mod, "connection_count": conn_count})

    return result


# ── GET /modules/{module_id} — Single module ─────────────────────────────


@router.get("/modules/{module_id}")
async def get_module(
    module_id: str,
    refresh: bool = Query(False, description="Force reload manifest from disk"),
) -> dict[str, Any]:
    """Return a single module by ID, with its inbound and outbound connections."""
    manifest = _load_manifest(force=refresh)
    modules: list[dict[str, Any]] = manifest.get("modules", [])
    connections: list[dict[str, Any]] = manifest.get("connections", [])

    module = next((m for m in modules if m.get("id") == module_id), None)
    if module is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Module '{module_id}' not found",
        )

    # Gather connections involving this module
    inbound = [c for c in connections if c.get("target") == module_id]
    outbound = [c for c in connections if c.get("source") == module_id]

    return {
        **module,
        "connections_inbound": inbound,
        "connections_outbound": outbound,
    }


# ── GET /connections — List connections ──────────────────────────────────


@router.get("/connections/")
async def list_connections(
    type: str | None = Query(None, description="Filter by connection type (e.g. api, event, data)"),
    source: str | None = Query(None, description="Filter by source module ID"),
    target: str | None = Query(None, description="Filter by target module ID"),
    refresh: bool = Query(False, description="Force reload manifest from disk"),
) -> list[dict[str, Any]]:
    """Return connections from the architecture manifest.

    Supports filtering by type, source module, and target module.
    All filters can be combined.
    """
    manifest = _load_manifest(force=refresh)
    connections: list[dict[str, Any]] = manifest.get("connections", [])

    if type:
        type_lower = type.lower()
        connections = [c for c in connections if c.get("type", "").lower() == type_lower]

    if source:
        connections = [c for c in connections if c.get("source") == source]

    if target:
        connections = [c for c in connections if c.get("target") == target]

    return connections


# ── GET /search — Fuzzy search ───────────────────────────────────────────


@router.get("/search/")
async def search_entities(
    q: str = Query(..., min_length=1, description="Search query"),
    refresh: bool = Query(False, description="Force reload manifest from disk"),
) -> dict[str, Any]:
    """Fuzzy search across modules, connections, layers, and categories.

    Searches module id, name, description, and tags. Also searches
    connection labels and types. Returns grouped results.
    """
    manifest = _load_manifest(force=refresh)
    query = q.lower()

    # Search modules
    matched_modules: list[dict[str, Any]] = []
    for mod in manifest.get("modules", []):
        searchable = " ".join(
            str(v).lower()
            for v in [
                mod.get("id", ""),
                mod.get("name", ""),
                mod.get("description", ""),
                mod.get("layer", ""),
                mod.get("category", ""),
                " ".join(mod.get("tags", [])),
            ]
        )
        if query in searchable:
            matched_modules.append(mod)

    # Search connections
    matched_connections: list[dict[str, Any]] = []
    for conn in manifest.get("connections", []):
        searchable = " ".join(
            str(v).lower()
            for v in [
                conn.get("source", ""),
                conn.get("target", ""),
                conn.get("type", ""),
                conn.get("label", ""),
                conn.get("description", ""),
            ]
        )
        if query in searchable:
            matched_connections.append(conn)

    # Search layers
    matched_layers: list[dict[str, Any]] = []
    for layer in manifest.get("layers", []):
        searchable = " ".join(
            str(v).lower()
            for v in [
                layer.get("id", ""),
                layer.get("name", ""),
                layer.get("description", ""),
            ]
        )
        if query in searchable:
            matched_layers.append(layer)

    # Search categories
    matched_categories: list[dict[str, Any]] = []
    for cat in manifest.get("categories", []):
        searchable = " ".join(
            str(v).lower()
            for v in [
                cat.get("id", ""),
                cat.get("name", ""),
                cat.get("description", ""),
            ]
        )
        if query in searchable:
            matched_categories.append(cat)

    return {
        "query": q,
        "modules": matched_modules,
        "connections": matched_connections,
        "layers": matched_layers,
        "categories": matched_categories,
        "total": (
            len(matched_modules)
            + len(matched_connections)
            + len(matched_layers)
            + len(matched_categories)
        ),
    }


# ── GET /stats — Aggregate statistics ────────────────────────────────────


@router.get("/stats/")
async def get_stats(
    refresh: bool = Query(False, description="Force reload manifest from disk"),
) -> dict[str, Any]:
    """Return aggregate statistics about the architecture.

    Includes counts of modules, connections, layers, categories,
    as well as breakdowns by layer, category, and connection type.
    """
    manifest = _load_manifest(force=refresh)
    modules: list[dict[str, Any]] = manifest.get("modules", [])
    connections: list[dict[str, Any]] = manifest.get("connections", [])
    layers: list[dict[str, Any]] = manifest.get("layers", [])
    categories: list[dict[str, Any]] = manifest.get("categories", [])

    # Modules per layer
    modules_by_layer: dict[str, int] = {}
    for mod in modules:
        layer = mod.get("layer", "unknown")
        modules_by_layer[layer] = modules_by_layer.get(layer, 0) + 1

    # Modules per category
    modules_by_category: dict[str, int] = {}
    for mod in modules:
        cat = mod.get("category", "unknown")
        modules_by_category[cat] = modules_by_category.get(cat, 0) + 1

    # Connections per type
    connections_by_type: dict[str, int] = {}
    for conn in connections:
        conn_type = conn.get("type", "unknown")
        connections_by_type[conn_type] = connections_by_type.get(conn_type, 0) + 1

    # Most connected modules (top 10)
    connection_counts: dict[str, int] = {}
    for conn in connections:
        src = conn.get("source", "")
        tgt = conn.get("target", "")
        if src:
            connection_counts[src] = connection_counts.get(src, 0) + 1
        if tgt:
            connection_counts[tgt] = connection_counts.get(tgt, 0) + 1

    most_connected = sorted(
        connection_counts.items(), key=lambda x: x[1], reverse=True
    )[:10]

    return {
        "total_modules": len(modules),
        "total_connections": len(connections),
        "total_layers": len(layers),
        "total_categories": len(categories),
        "modules_by_layer": modules_by_layer,
        "modules_by_category": modules_by_category,
        "connections_by_type": connections_by_type,
        "most_connected": [
            {"module_id": mid, "connection_count": cnt} for mid, cnt in most_connected
        ],
        "manifest_file_exists": _MANIFEST_PATH.exists(),
    }
