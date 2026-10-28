# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Architecture Map API routes.

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

The ``?refresh=true`` query parameter - which forces re-reading a 1+ MB
JSON file from disk - is additionally gated to admins via the same
permission check (a non-admin path is impossible because the router-wide
dependency blocks them first). This prevents a non-admin DoS vector
where any logged-in user could hammer the endpoint and starve the event
loop with synchronous file I/O.

What the manifest can and cannot answer
---------------------------------------
Everything below is derived from the file
``frontend/src/features/architecture/architecture_manifest.json``, which
``scripts/generate_architecture_manifest.py`` produces by scanning the
tree. That file is the only source, so an endpoint can only answer a
question the file actually contains.

Until this was fixed, every endpoint except ``GET /`` was written
against a different schema: it read ``connections``, ``layers`` and
``categories`` at the top level and matched modules on ``id``. The file
has none of those. It carries ``_meta``, ``dependency_graph``,
``frontend_backend_mapping``, ``frontend_features``, ``modules`` and
``statistics``, and a module is keyed by ``module_id``. Because every
read went through ``dict.get`` with a default, nothing raised:
``/modules/{module_id}`` returned 404 for all 195 modules that exist and
the rest returned empty lists, silently and for as long as the code had
been shipped. The routes are now read against the real keys:

* Connections are derived from ``dependency_graph``, which maps each
  module id to the list of module ids it imports.
* Categories are derived from the distinct ``module_category`` values
  the modules already carry.
* A module is found by ``module_id``, and searched over ``module_id``,
  ``module_label``, ``module_category`` and its plugin manifest's
  description.

One concept was removed rather than repaired. There is no ``layer``
anywhere in the manifest: no module carries the key and there is no
top-level collection of layers, so the ``layer`` filter, the ``layers``
search group and the ``modules_by_layer`` / ``total_layers`` counters
had no source and never could have had one. Answering them with an
empty list would have been indistinguishable from a real answer of
"none", which is how this defect stayed invisible in the first place, so
they are gone. If layers are wanted, the generator has to emit them
first.

Endpoints:
    GET  /                     -- Full architecture manifest
    GET  /modules              -- List modules, filterable by category
    GET  /modules/{module_id}  -- Single module detail
    GET  /connections          -- List dependency edges, filterable
    GET  /search?q=            -- Fuzzy search across modules and edges
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

# The shape the generator emits, with every collection empty. Used when the
# file is missing or unreadable so callers get the real keys back rather than
# a KeyError. This previously declared "meta", "connections", "layers" and
# "categories", none of which the generator has ever produced, which meant the
# fallback advertised a schema that did not exist and agreed with the handlers
# that read it.
_EMPTY_MANIFEST: dict[str, Any] = {
    "_meta": {},
    "modules": [],
    "frontend_features": [],
    "dependency_graph": {},
    "frontend_backend_mapping": {},
    "statistics": {},
}

# The one kind of edge the manifest records. dependency_graph is built from
# module imports, so every edge is an import edge; the generator does not
# distinguish API calls from event subscriptions. Naming it is honest about
# what the data is. A caller filtering on any other type correctly gets
# nothing back, because nothing of another type has been measured.
_EDGE_TYPE = "import"


def _load_manifest(force: bool = False) -> dict[str, Any]:
    """Load the architecture manifest from disk, with in-memory caching.

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
    """Drop the in-memory manifest cache.

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
    """Structured log line for security-relevant architecture probes.

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


# ── Derivations from the real manifest shape ─────────────────────────────


def _edges(manifest: dict[str, Any]) -> list[dict[str, str]]:
    """Return every dependency edge the manifest records.

    ``dependency_graph`` maps a module id to the list of module ids it
    imports. Flattening it to ``{source, target, type}`` gives the
    connection shape the API has always claimed to serve, now built from
    data that exists.

    Args:
        manifest: A parsed architecture manifest.

    Returns:
        One dict per edge, sorted by source then target so the response is
        stable across processes. A malformed or absent graph yields an
        empty list rather than raising, because a caller asking for
        connections over a manifest that has none wants an empty answer,
        not a 500.
    """
    graph = manifest.get("dependency_graph")
    if not isinstance(graph, dict):
        return []

    edges: list[dict[str, str]] = []
    for source in sorted(graph):
        targets = graph[source]
        if not isinstance(targets, list):
            continue
        for target in sorted(str(t) for t in targets):
            edges.append({"source": str(source), "target": target, "type": _EDGE_TYPE})
    return edges


def _categories(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the module categories present in the manifest, with counts.

    The generator does not emit a category catalogue; it stamps each
    module with ``module_category``. The distinct values are therefore the
    only category list that can be stated truthfully, and the count is the
    only attribute they have. There is deliberately no description field,
    because nothing in the manifest supplies one.

    Args:
        manifest: A parsed architecture manifest.

    Returns:
        One dict per distinct category, sorted by id.
    """
    counts: dict[str, int] = {}
    modules = manifest.get("modules")
    if isinstance(modules, list):
        for mod in modules:
            if isinstance(mod, dict):
                category = str(mod.get("module_category", "")) or "uncategorised"
                counts[category] = counts.get(category, 0) + 1
    return [{"id": cat, "module_count": counts[cat]} for cat in sorted(counts)]


def _module_id(module: dict[str, Any]) -> str:
    """Return a module entry's id under the key the generator actually writes."""
    return str(module.get("module_id", ""))


# ── GET / - Full manifest ────────────────────────────────────────────────


@router.get("/")
async def get_manifest(
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
    refresh: bool = Query(False, description="Force reload manifest from disk"),
) -> dict[str, Any]:
    """Return the full architecture manifest JSON.

    Pass ?refresh=true to force re-reading the file from disk.
    Admin-only (router-level gate).
    """
    _audit(payload, "get_manifest", refresh=refresh)
    return _load_manifest(force=refresh)


# ── GET /modules - List modules ──────────────────────────────────────────


@router.get("/modules/")
async def list_modules(
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
    category: str | None = Query(None, description="Filter by module_category, for example core or business"),
    refresh: bool = Query(False, description="Force reload manifest from disk"),
) -> list[dict[str, Any]]:
    """Return the modules from the architecture manifest.

    Supports optional filtering by category. Each module is enriched with
    the number of dependency edges that touch it in either direction.

    The ``layer`` filter this endpoint used to accept was removed: no
    module in the manifest carries a layer, so it could only ever have
    filtered everything away.
    """
    _audit(payload, "list_modules", category=category)
    manifest = _load_manifest(force=refresh)
    modules: list[dict[str, Any]] = manifest.get("modules", [])
    edges = _edges(manifest)

    if category:
        category_lower = category.lower()
        modules = [m for m in modules if str(m.get("module_category", "")).lower() == category_lower]

    # Enrich with connection counts, counting both directions.
    degree: dict[str, int] = {}
    for edge in edges:
        degree[edge["source"]] = degree.get(edge["source"], 0) + 1
        degree[edge["target"]] = degree.get(edge["target"], 0) + 1

    return [{**mod, "connection_count": degree.get(_module_id(mod), 0)} for mod in modules]


# ── GET /modules/{module_id} - Single module ─────────────────────────────


@router.get("/modules/{module_id}")
async def get_module(
    module_id: str,
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
    refresh: bool = Query(False, description="Force reload manifest from disk"),
) -> dict[str, Any]:
    """Return a single module by id, with its inbound and outbound edges.

    Matched on ``module_id``. This previously matched on ``id``, a key no
    module has ever carried, so the lookup returned 404 for every module
    in the manifest.
    """
    _audit(payload, "get_module", module_id=module_id)
    manifest = _load_manifest(force=refresh)
    modules: list[dict[str, Any]] = manifest.get("modules", [])
    connections = _edges(manifest)

    module = next((m for m in modules if _module_id(m) == module_id), None)
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


# ── GET /connections - List connections ──────────────────────────────────


@router.get("/connections/")
async def list_connections(
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
    type: str | None = Query(None, description=f"Filter by edge type. The manifest records only {_EDGE_TYPE!r}"),
    source: str | None = Query(None, description="Filter by source module id"),
    target: str | None = Query(None, description="Filter by target module id"),
    refresh: bool = Query(False, description="Force reload manifest from disk"),
) -> list[dict[str, Any]]:
    """Return the dependency edges from the architecture manifest.

    Derived from ``dependency_graph``. This previously read a top-level
    ``connections`` key that the generator has never emitted, so it
    returned an empty list on every call.
    """
    _audit(payload, "list_connections", type=type, source=source, target=target)
    manifest = _load_manifest(force=refresh)
    connections: list[dict[str, Any]] = list(_edges(manifest))

    if type:
        type_lower = type.lower()
        connections = [c for c in connections if c.get("type", "").lower() == type_lower]

    if source:
        connections = [c for c in connections if c.get("source") == source]

    if target:
        connections = [c for c in connections if c.get("target") == target]

    return connections


# ── GET /search - Fuzzy search ───────────────────────────────────────────


@router.get("/search/")
async def search_entities(
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
    q: str = Query(..., min_length=1, max_length=200, description="Search query"),
    refresh: bool = Query(False, description="Force reload manifest from disk"),
) -> dict[str, Any]:
    """Fuzzy search across modules, dependency edges and categories.

    Modules are matched on their id, label, category and the description
    from their plugin manifest, which are the fields the generator
    actually writes. The previous implementation searched ``id``,
    ``name``, ``description``, ``layer`` and ``tags`` on the module,
    none of which exist, so it matched nothing for any query.

    There is no ``layers`` group in the result. The manifest has no
    layers to search.
    """
    _audit(payload, "search", q=q)
    manifest = _load_manifest(force=refresh)
    query = q.lower()

    matched_modules: list[dict[str, Any]] = []
    for mod in manifest.get("modules", []):
        if not isinstance(mod, dict):
            continue
        plugin_manifest = mod.get("manifest")
        description = plugin_manifest.get("description", "") if isinstance(plugin_manifest, dict) else ""
        searchable = " ".join(
            str(v).lower()
            for v in [
                mod.get("module_id", ""),
                mod.get("module_label", ""),
                mod.get("module_category", ""),
                description,
            ]
        )
        if query in searchable:
            matched_modules.append(mod)

    matched_connections: list[dict[str, Any]] = []
    for conn in _edges(manifest):
        searchable = " ".join(str(v).lower() for v in [conn["source"], conn["target"], conn["type"]])
        if query in searchable:
            matched_connections.append(conn)

    matched_categories = [cat for cat in _categories(manifest) if query in cat["id"].lower()]

    return {
        "query": q,
        "modules": matched_modules,
        "connections": matched_connections,
        "categories": matched_categories,
        "total": len(matched_modules) + len(matched_connections) + len(matched_categories),
    }


# ── GET /stats - Aggregate statistics ────────────────────────────────────


@router.get("/stats/")
async def get_stats(
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
    refresh: bool = Query(False, description="Force reload manifest from disk"),
) -> dict[str, Any]:
    """Return aggregate statistics about the architecture.

    The counters are computed from the manifest's own sections. The
    generator also ships a ``statistics`` block of its own, covering
    totals this endpoint cannot derive such as column and route counts,
    and it is passed through under ``manifest_statistics`` rather than
    recomputed, so the two can never disagree.

    ``modules_by_layer`` and ``total_layers`` were removed along with the
    rest of the layer concept: the manifest has no layers, so both were
    permanently empty.
    """
    _audit(payload, "get_stats")
    manifest = _load_manifest(force=refresh)
    modules: list[dict[str, Any]] = manifest.get("modules", [])
    connections = _edges(manifest)
    categories = _categories(manifest)

    modules_by_category = {cat["id"]: cat["module_count"] for cat in categories}

    connections_by_type: dict[str, int] = {}
    for conn in connections:
        connections_by_type[conn["type"]] = connections_by_type.get(conn["type"], 0) + 1

    connection_counts: dict[str, int] = {}
    for conn in connections:
        connection_counts[conn["source"]] = connection_counts.get(conn["source"], 0) + 1
        connection_counts[conn["target"]] = connection_counts.get(conn["target"], 0) + 1

    # Sort by descending degree, then by id, so equal degrees do not
    # reorder between calls.
    most_connected = sorted(connection_counts.items(), key=lambda item: (-item[1], item[0]))[:10]

    statistics = manifest.get("statistics")

    return {
        "total_modules": len(modules),
        "total_connections": len(connections),
        "total_categories": len(categories),
        "modules_by_category": modules_by_category,
        "connections_by_type": connections_by_type,
        "most_connected": [{"module_id": mid, "connection_count": cnt} for mid, cnt in most_connected],
        "manifest_statistics": statistics if isinstance(statistics, dict) else {},
        "manifest_file_exists": _MANIFEST_PATH.exists(),
    }
