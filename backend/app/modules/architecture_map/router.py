"""‌⁠‍Architecture Map API routes.

Read-only endpoints that serve the architecture manifest JSON and provide
search/filter capabilities over modules, connections, and statistics.

Security model
--------------
The manifest leaks substantial structural detail about the deployed
system: every module's file list, every ORM model + table name + column
SQL type, inter-module dependency edges, registered routes. That is
high-signal intelligence for an attacker mapping an unknown ERP instance
and offers no value to estimators / project managers.

Therefore every endpoint requires the ``architecture.read`` permission,
which is registered at ``Role.ADMIN`` in
:mod:`app.modules.architecture_map.permissions`. ``RequirePermission``
returns 403 to anyone below the bar.

The ``?refresh=true`` query parameter — which forces re-reading a 1+ MB
JSON file from disk — is additionally gated to admins via the same
permission check (a non-admin path is impossible because the router-wide
dependency blocks them first). This prevents a non-admin DoS vector
where any logged-in user could hammer the endpoint and starve the event
loop with synchronous file I/O.

Endpoints:
    GET  /                     -- Full architecture manifest
    GET  /modules              -- List modules with optional stats
    GET  /modules/{module_id}  -- Single module detail
    GET  /connections          -- List connections, filterable
    GET  /search?q=            -- Fuzzy search across all entities
    GET  /stats                -- Aggregate statistics
"""

import json
import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import RequirePermission, get_current_user_payload

logger = logging.getLogger(__name__)

# Router-wide guard: every route below inherits the permission check.
# The architecture manifest is admin-only intelligence; gating at the
# router level is defence-in-depth so a future contributor cannot add a
# new GET that forgets the dependency.
router = APIRouter(
    tags=["Architecture Map"],
    dependencies=[Depends(RequirePermission("architecture.read"))],
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
    """‌⁠‍Load the architecture manifest from disk, with in-memory caching.

    Args:
        force: If True, bypass cache and re-read from disk. Caller must
            be admin (enforced at router level).

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


def invalidate_cache() -> None:
    """‌⁠‍Drop the in-memory manifest cache.

    Public so the module loader / hot-reload code can call us after a
    module install / enable / disable event; otherwise the cached graph
    keeps reporting the pre-change state until the process restarts.
    """
    global _cached_manifest
    _cached_manifest = None
    logger.debug("Architecture manifest cache invalidated")


def _audit(
    payload: dict[str, Any],
    action: str,
    **extra: Any,
) -> None:
    """‌⁠‍Structured log line for security-relevant architecture probes.

    Even though the surface is admin-only, admin actions on a system-map
    endpoint are exactly the kind of thing a forensic timeline wants.
    Emitted at INFO so default log shipping picks them up.
    """
    user_id = payload.get("sub", "unknown")
    role = payload.get("role", "unknown")
    logger.info(
        "architecture_map.%s user=%s role=%s %s",
        action,
        user_id,
        role,
        " ".join(f"{k}={v!r}" for k, v in extra.items()),
    )


# ── GET / — Full manifest ────────────────────────────────────────────────


@router.get("/")
async def get_manifest(
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
    refresh: bool = Query(False, description="Force reload manifest from disk"),
) -> dict[str, Any]:
    """‌⁠‍Return the full architecture manifest JSON.

    Pass ?refresh=true to force re-reading the file from disk.
    Admin-only (router-level gate).
    """
    _audit(payload, "get_manifest", refresh=refresh)
    return _load_manifest(force=refresh)


# ── GET /modules — List modules ──────────────────────────────────────────


@router.get("/modules/")
async def list_modules(
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
    layer: str | None = Query(None, description="Filter by layer (e.g. frontend, backend)"),
    category: str | None = Query(None, description="Filter by category"),
    refresh: bool = Query(False, description="Force reload manifest from disk"),
) -> list[dict[str, Any]]:
    """Return list of modules from the architecture manifest.

    Supports optional filtering by layer and category.
    Each module includes a connection count for quick stats.
    """
    _audit(payload, "list_modules", layer=layer, category=category)
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
        conn_count = sum(1 for c in connections if c.get("source") == mod_id or c.get("target") == mod_id)
        result.append({**mod, "connection_count": conn_count})

    return result


# ── GET /modules/{module_id} — Single module ─────────────────────────────


@router.get("/modules/{module_id}")
async def get_module(
    module_id: str,
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
    refresh: bool = Query(False, description="Force reload manifest from disk"),
) -> dict[str, Any]:
    """Return a single module by ID, with its inbound and outbound connections."""
    _audit(payload, "get_module", module_id=module_id)
    manifest = _load_manifest(force=refresh)
    modules: list[dict[str, Any]] = manifest.get("modules", [])
    connections: list[dict[str, Any]] = manifest.get("connections", [])

    module = next((m for m in modules if m.get("id") == module_id), None)
    if module is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Module '{module_id}' not found",
        )

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
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
    type: str | None = Query(None, description="Filter by connection type (e.g. api, event, data)"),
    source: str | None = Query(None, description="Filter by source module ID"),
    target: str | None = Query(None, description="Filter by target module ID"),
    refresh: bool = Query(False, description="Force reload manifest from disk"),
) -> list[dict[str, Any]]:
    """Return connections from the architecture manifest."""
    _audit(payload, "list_connections", type=type, source=source, target=target)
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
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
    q: str = Query(..., min_length=1, max_length=200, description="Search query"),
    refresh: bool = Query(False, description="Force reload manifest from disk"),
) -> dict[str, Any]:
    """Fuzzy search across modules, connections, layers, and categories."""
    _audit(payload, "search", q=q)
    manifest = _load_manifest(force=refresh)
    query = q.lower()

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
        "total": (len(matched_modules) + len(matched_connections) + len(matched_layers) + len(matched_categories)),
    }


# ── GET /stats — Aggregate statistics ────────────────────────────────────


@router.get("/stats/")
async def get_stats(
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
    refresh: bool = Query(False, description="Force reload manifest from disk"),
) -> dict[str, Any]:
    """Return aggregate statistics about the architecture."""
    _audit(payload, "get_stats")
    manifest = _load_manifest(force=refresh)
    modules: list[dict[str, Any]] = manifest.get("modules", [])
    connections: list[dict[str, Any]] = manifest.get("connections", [])
    layers: list[dict[str, Any]] = manifest.get("layers", [])
    categories: list[dict[str, Any]] = manifest.get("categories", [])

    modules_by_layer: dict[str, int] = {}
    for mod in modules:
        layer = mod.get("layer", "unknown")
        modules_by_layer[layer] = modules_by_layer.get(layer, 0) + 1

    modules_by_category: dict[str, int] = {}
    for mod in modules:
        cat = mod.get("category", "unknown")
        modules_by_category[cat] = modules_by_category.get(cat, 0) + 1

    connections_by_type: dict[str, int] = {}
    for conn in connections:
        conn_type = conn.get("type", "unknown")
        connections_by_type[conn_type] = connections_by_type.get(conn_type, 0) + 1

    connection_counts: dict[str, int] = {}
    for conn in connections:
        src = conn.get("source", "")
        tgt = conn.get("target", "")
        if src:
            connection_counts[src] = connection_counts.get(src, 0) + 1
        if tgt:
            connection_counts[tgt] = connection_counts.get(tgt, 0) + 1

    most_connected = sorted(connection_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "total_modules": len(modules),
        "total_connections": len(connections),
        "total_layers": len(layers),
        "total_categories": len(categories),
        "modules_by_layer": modules_by_layer,
        "modules_by_category": modules_by_category,
        "connections_by_type": connections_by_type,
        "most_connected": [{"module_id": mid, "connection_count": cnt} for mid, cnt in most_connected],
        "manifest_file_exists": _MANIFEST_PATH.exists(),
    }
