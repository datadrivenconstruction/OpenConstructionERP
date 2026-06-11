# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Geo Hub API routes.

Mounted by the module loader at ``/api/v1/geo-hub/``. All routes are
RBAC-gated; the service layer additionally closes cross-tenant IDOR
holes by 404-ing project-mismatched accesses.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import uuid
from collections import OrderedDict
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile

from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.dependencies import CurrentUserPayload, RequirePermission, SessionDep
from app.modules.geo_hub.schemas import (
    AnchoredProjectResponse,
    AnchorFromAddressRequest,
    AnchorFromAddressResponse,
    BulkAnchorFromAddressResponse,
    CanonicalToTilesetRequest,
    DiaryPhotoPinResponse,
    GeoAnchorCreate,
    GeoAnchorResponse,
    GeoAnchorUpdate,
    GeocodeCachePurgeResponse,
    GeocodeCacheStatsResponse,
    GeocodeSuggestionResponse,
    GeocodeSuggestResponse,
    GeoJSONImportRequest,
    GeoOverlayCreate,
    GeoOverlayResponse,
    GeoOverlayUpdate,
    GeoRasterOverlayResponse,
    GeoRasterOverlayUpdate,
    HSEPinResponse,
    ImageryLayerCreate,
    ImageryLayerResponse,
    ImageryLayerUpdate,
    KMLImportRequest,
    MapConfigResponse,
    MapSummaryResponse,
    PunchlistPinResponse,
    RasterOverlayUploadResponse,
    TerrainSourceCreate,
    TerrainSourceResponse,
    TerrainSourceUpdate,
    TileGenerateRequest,
    TileJobResponse,
    TilesetCreate,
    TilesetResponse,
    TilesetUpdate,
    ViewpointCreate,
    ViewpointResponse,
    ViewpointUpdate,
)
from app.modules.geo_hub.service import GeoHubService

router = APIRouter(tags=["geo_hub"])


def _svc(session: SessionDep) -> GeoHubService:
    return GeoHubService(session)


# ── Basemap tile proxy (public) ─────────────────────────────────────────────
# Browsers cannot reliably reach public tile CDNs directly: ad and privacy
# blockers routinely block ``basemaps.cartocdn.com`` and the OpenStreetMap
# tile servers, and OSM's usage policy forbids app or bulk use of its raw
# tiles (it returns an "Access blocked" tile). Either way the 3D globe and the
# project-card thumbnails go blank. We proxy the basemap through our own
# origin: the browser only ever talks to same-origin ``/api`` (which blockers
# do not touch), and the server fetches each tile once, with a proper
# User-Agent, and caches it. This removes the external runtime dependency and
# keeps the maps working in any browser. It is intentionally the one public
# route in this module: ``<img>`` and the Cesium/MapLibre tile loaders cannot
# attach an auth header, and basemap tiles are public imagery.
_TILE_UPSTREAM = "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png"
# Bounded LRU of ``(bytes, etag)`` keyed by ``z/x/y``. 4096 256px PNGs is a
# few MB resident - small enough to keep in-process, big enough to cover a
# project view plus several pan/zoom steps so repeat loads never re-fetch.
_TILE_CACHE: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
_TILE_CACHE_MAX = 4096
_TILE_HEADERS = {
    "User-Agent": "OpenConstructionERP/1.0 (+https://openconstructionerp.com)",
    "Accept": "image/png,image/*;q=0.8,*/*;q=0.5",
    "Referer": "https://openconstructionerp.com/",
}
# A basemap tile for a fixed z/x/y is effectively immutable for a week, so we
# let the browser AND any shared cache hold onto it. ``immutable`` stops the
# revalidation round-trip entirely on supporting browsers; the ETag covers the
# rest via conditional GETs (304, empty body).
_TILE_CACHE_CONTROL = "public, max-age=604800, stale-while-revalidate=86400, immutable"
# 1x1 transparent PNG returned on any upstream failure so the map shows a
# clean gap rather than a broken-image icon. NOT cached client-side (a later
# request must be able to retry the upstream), so it carries no-store.
_BLANK_TILE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
)
_BLANK_TILE_HEADERS = {"Cache-Control": "no-store"}

# Shared, pooled httpx client. The previous implementation opened a brand-new
# ``AsyncClient`` (and therefore a fresh TLS handshake + connection) for EVERY
# tile, which under Cesium's burst of ~20-60 simultaneous tile requests starved
# the event loop and left many tiles to time out - the "loads slowly / only a
# fragment of the map" report. A single process-wide client with a sized
# connection pool keeps the upstream connections warm and lets many tiles fly
# in parallel over kept-alive sockets.
_tile_client: httpx.AsyncClient | None = None
_tile_client_lock = asyncio.Lock()


async def _get_tile_client() -> httpx.AsyncClient:
    """Return the process-wide pooled httpx client, creating it once.

    Guarded by an async lock so a burst of concurrent first-requests can't
    race two clients into existence. Connection limits are sized for the
    fan-out of a single Cesium scene; timeouts are split so a slow upstream
    connect fails fast while an in-flight read gets a little more room.
    """
    global _tile_client
    client = _tile_client
    if client is not None and not client.is_closed:
        return client
    async with _tile_client_lock:
        if _tile_client is not None and not _tile_client.is_closed:
            return _tile_client
        _tile_client = httpx.AsyncClient(
            headers=_TILE_HEADERS,
            http2=False,
            limits=httpx.Limits(
                max_connections=64,
                max_keepalive_connections=32,
                keepalive_expiry=30.0,
            ),
            timeout=httpx.Timeout(connect=4.0, read=8.0, write=4.0, pool=8.0),
            follow_redirects=True,
        )
        return _tile_client


async def close_tile_client() -> None:
    """Close the shared tile client. Safe to call when none was created."""
    global _tile_client
    client = _tile_client
    _tile_client = None
    if client is not None and not client.is_closed:
        await client.aclose()


def _tile_response(data: bytes, etag: str) -> Response:
    """Build a cacheable 200 image response with validators."""
    return Response(
        content=data,
        media_type="image/png",
        headers={
            "Cache-Control": _TILE_CACHE_CONTROL,
            "ETag": etag,
            "Content-Length": str(len(data)),
        },
    )


@router.get("/tiles/{z}/{x}/{y}.png", include_in_schema=False)
async def proxy_basemap_tile(z: int, x: int, y: int, request: Request) -> Response:
    """Proxy one XYZ basemap raster tile through our own origin.

    Public by design (see the section comment). Coordinates are clamped to
    the valid web-mercator range so this can only ever fetch real basemap
    tiles and never act as an open proxy for arbitrary URLs. Results come
    from a bounded in-process LRU cache backed by a shared, pooled httpx
    client; a miss fetches the upstream tile once. Every hit carries a
    strong ``ETag`` + long ``Cache-Control`` so the browser short-circuits
    repeat loads (and conditional ``If-None-Match`` GETs get a 304 with no
    body). Any failure returns a transparent, non-cacheable tile so the map
    degrades to a clean gap instead of a broken image and can retry later.
    """
    if not (0 <= z <= 22):
        return Response(content=_BLANK_TILE, media_type="image/png", headers=_BLANK_TILE_HEADERS)
    bound = (1 << z) - 1
    if not (0 <= x <= bound and 0 <= y <= bound):
        return Response(content=_BLANK_TILE, media_type="image/png", headers=_BLANK_TILE_HEADERS)

    key = f"{z}/{x}/{y}"
    hit = _TILE_CACHE.get(key)
    if hit is not None:
        data, etag = hit
        _TILE_CACHE.move_to_end(key)
        if request.headers.get("if-none-match") == etag:
            return Response(
                status_code=304,
                headers={"Cache-Control": _TILE_CACHE_CONTROL, "ETag": etag},
            )
        return _tile_response(data, etag)

    try:
        client = await _get_tile_client()
        res = await client.get(_TILE_UPSTREAM.format(z=z, x=x, y=y))
    except (httpx.HTTPError, OSError):
        return Response(content=_BLANK_TILE, media_type="image/png", headers=_BLANK_TILE_HEADERS)

    if res.status_code != 200 or not res.content:
        return Response(content=_BLANK_TILE, media_type="image/png", headers=_BLANK_TILE_HEADERS)

    data = res.content
    # Strong validator derived from the bytes so a re-fetch of identical
    # content keeps the same ETag (and the browser's conditional GET 304s).
    etag = f'"{hashlib.sha1(data).hexdigest()}"'  # noqa: S324 - cache validator, not security
    _TILE_CACHE[key] = (data, etag)
    _TILE_CACHE.move_to_end(key)
    while len(_TILE_CACHE) > _TILE_CACHE_MAX:
        _TILE_CACHE.popitem(last=False)
    return _tile_response(data, etag)


# ── Anchors ──────────────────────────────────────────────────────────────


@router.get("/anchors/", response_model=list[GeoAnchorResponse])
async def list_anchors(
    project_id: uuid.UUID = Query(...),
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> list[GeoAnchorResponse]:
    await service._verify_project_owner(
        project_id,
        payload,
        not_found_detail=translate("errors.project_not_found", locale=get_locale()),
    )
    anchor = await service.get_anchor_for_project(project_id)
    if anchor is None:
        return []
    return [GeoAnchorResponse.model_validate(anchor)]


@router.post(
    "/anchors/",
    response_model=GeoAnchorResponse,
    status_code=201,
)
async def create_anchor(
    data: GeoAnchorCreate,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.write")),
) -> GeoAnchorResponse:
    obj = await service.create_anchor(data, payload=payload)
    return GeoAnchorResponse.model_validate(obj)


@router.get("/anchors/{anchor_id}", response_model=GeoAnchorResponse)
async def get_anchor(
    anchor_id: uuid.UUID,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> GeoAnchorResponse:
    obj = await service.get_anchor(anchor_id)
    await service._verify_project_owner(
        obj.project_id,
        payload,
        not_found_detail="Anchor not found",
    )
    return GeoAnchorResponse.model_validate(obj)


@router.patch("/anchors/{anchor_id}", response_model=GeoAnchorResponse)
async def update_anchor(
    anchor_id: uuid.UUID,
    data: GeoAnchorUpdate,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.write")),
) -> GeoAnchorResponse:
    obj = await service.update_anchor(anchor_id, data, payload=payload)
    return GeoAnchorResponse.model_validate(obj)


@router.post(
    "/anchors/from-address/",
    response_model=AnchorFromAddressResponse,
    status_code=201,
)
async def anchor_from_address(
    data: AnchorFromAddressRequest,
    force: bool = Query(default=False),
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.write")),
) -> AnchorFromAddressResponse:
    """Auto-anchor a project from its stored address.

    Behaviour:

    * 404 if project missing / cross-tenant.
    * 409 if an anchor already exists and ``force=false`` (the existing
      anchor id is returned in the detail so the UI can prompt the user
      to re-geocode).
    * 422 if the project address has no country.
    * 502 if the geocoder couldn't resolve the address and no cached
      fallback exists.
    * 201 with the new anchor + precision + source on success.
    """
    anchor, precision, source, display_name = await service.anchor_from_address(
        data.project_id,
        payload=payload,
        force=force,
    )
    return AnchorFromAddressResponse(
        anchor=GeoAnchorResponse.model_validate(anchor),
        precision=precision,
        source=source,
        display_name=display_name or None,
    )


@router.post(
    "/anchors/from-address/bulk/",
    response_model=BulkAnchorFromAddressResponse,
    status_code=200,
)
async def bulk_anchor_from_address(
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.write")),
) -> BulkAnchorFromAddressResponse:
    """Run auto-anchor across every caller-accessible un-anchored project.

    Returns aggregate counts (succeeded / skipped / failed) plus a
    per-project breakdown so the UI can highlight which projects need
    an address filled in.
    """
    summary = await service.bulk_anchor_from_address(payload=payload)
    return BulkAnchorFromAddressResponse.model_validate(summary)


# ── Geocode (Nominatim) - suggest + admin cache ────────────────────────


@router.get("/geocode/suggest", response_model=GeocodeSuggestResponse)
async def geocode_suggest(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=5, ge=1, le=10),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> GeocodeSuggestResponse:
    """Free-text Nominatim search for the address autocomplete dropdown.

    Returns up to ``limit`` results (capped at 10). The endpoint never
    raises on geocoder failure - it returns an empty ``suggestions``
    array so the frontend can render "no matches" without exception
    handling. Authentication is required (``geo_hub.read``) so an
    unauthenticated caller can't pin Nominatim through our IP.

    Rate-limit: every call serialises through the same process-global
    1 req/s semaphore as the structured ``geocode_address`` so the
    autocomplete dropdown can't accidentally violate Nominatim's ToS
    even under heavy keystroke pressure (client-side debounce + cache
    cooperate to keep this well below the budget in practice).
    """
    # ``payload`` is unused beyond the RBAC gate - kept on the signature
    # to match the convention used by every other read endpoint in this
    # module so security audits can grep for it uniformly.
    _ = payload
    from app.modules.geo_hub.geocoder import _disabled, suggest_addresses

    disabled = _disabled()
    results = [] if disabled else await suggest_addresses(q, limit=limit)
    return GeocodeSuggestResponse(
        query=q,
        geocoder_disabled=disabled,
        suggestions=[
            GeocodeSuggestionResponse(
                display_name=r.display_name,
                lat=r.lat,
                lon=r.lon,
                country_code=r.country_code,
                addresstype=r.addresstype,
                osm_type=r.osm_type,
                bbox=list(r.bbox) if r.bbox else None,
                address_parts=dict(r.address_parts) if r.address_parts else None,
            )
            for r in results
        ],
    )


@router.get(
    "/geocode/cache/stats",
    response_model=GeocodeCacheStatsResponse,
)
async def geocode_cache_stats(
    session: SessionDep,
    _perm: None = Depends(RequirePermission("geo_hub.admin")),
) -> GeocodeCacheStatsResponse:
    """Cache counters for the admin panel.

    Admin-only (``geo_hub.admin``). Exposes total / fresh / stale row
    counts, the running ``hit_count`` sum and the oldest/newest
    cached_at timestamps so an operator can decide whether a purge is
    warranted.
    """
    from app.modules.geo_hub.geocoder import cache_stats

    stats = await cache_stats(session)
    return GeocodeCacheStatsResponse(**stats)


@router.delete(
    "/geocode/cache",
    response_model=GeocodeCachePurgeResponse,
)
async def geocode_cache_purge(
    session: SessionDep,
    older_than_days: int | None = Query(default=30, ge=0, le=3650),
    _perm: None = Depends(RequirePermission("geo_hub.admin")),
) -> GeocodeCachePurgeResponse:
    """Manually invalidate cache rows older than ``older_than_days``.

    Defaults to 30 days (matches ``CACHE_TTL``) so a default call only
    sweeps already-expired rows - a no-op for healthy caches and a
    sanity-restore for caches that were never read often enough to age
    out via the normal TTL miss path. Pass ``older_than_days=0`` to
    flush everything.
    """
    from app.modules.geo_hub.geocoder import purge_cache

    deleted = await purge_cache(session, older_than_days=older_than_days)
    return GeocodeCachePurgeResponse(
        deleted=deleted,
        older_than_days=older_than_days,
    )


@router.delete("/anchors/{anchor_id}", status_code=204)
async def delete_anchor(
    anchor_id: uuid.UUID,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.delete")),
) -> Response:
    await service.delete_anchor(anchor_id, payload=payload)
    return Response(status_code=204)


# ── Tilesets ─────────────────────────────────────────────────────────────


@router.get("/tilesets/", response_model=list[TilesetResponse])
async def list_tilesets(
    project_id: uuid.UUID = Query(...),
    tileset_status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> list[TilesetResponse]:
    rows = await service.list_tilesets_for_project(
        project_id,
        payload=payload,
        offset=offset,
        limit=limit,
        tileset_status=tileset_status,
    )
    return [TilesetResponse.model_validate(r) for r in rows]


@router.post("/tilesets/", response_model=TilesetResponse, status_code=201)
async def create_tileset(
    data: TilesetCreate,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.write")),
) -> TilesetResponse:
    obj = await service.create_tileset(data, payload=payload)
    return TilesetResponse.model_validate(obj)


@router.get("/tilesets/{tileset_id}", response_model=TilesetResponse)
async def get_tileset(
    tileset_id: uuid.UUID,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> TilesetResponse:
    obj = await service.get_tileset(tileset_id)
    await service._verify_project_owner(
        obj.project_id,
        payload,
        not_found_detail="Tileset not found",
    )
    return TilesetResponse.model_validate(obj)


@router.patch("/tilesets/{tileset_id}", response_model=TilesetResponse)
async def update_tileset(
    tileset_id: uuid.UUID,
    data: TilesetUpdate,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.write")),
) -> TilesetResponse:
    obj = await service.update_tileset(tileset_id, data, payload=payload)
    return TilesetResponse.model_validate(obj)


@router.delete("/tilesets/{tileset_id}", status_code=204)
async def delete_tileset(
    tileset_id: uuid.UUID,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.delete")),
) -> Response:
    await service.delete_tileset(tileset_id, payload=payload)
    return Response(status_code=204)


# ── Tile-generation jobs ─────────────────────────────────────────────────


@router.post("/tilesets/generate/", response_model=TileJobResponse, status_code=202)
async def enqueue_tile_job(
    data: TileGenerateRequest,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.job_run")),
) -> TileJobResponse:
    job = await service.enqueue_tile_generation(data, payload=payload)
    return TileJobResponse.model_validate(job)


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=TileJobResponse,
    status_code=200,
)
async def cancel_tile_job(
    job_id: uuid.UUID,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.job_run")),
) -> TileJobResponse:
    job = await service.cancel_tile_job(job_id, payload=payload)
    return TileJobResponse.model_validate(job)


@router.get("/jobs/{job_id}", response_model=TileJobResponse)
async def get_tile_job(
    job_id: uuid.UUID,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> TileJobResponse:
    job = await service.get_job(job_id)
    await service._verify_project_owner(
        job.project_id,
        payload,
        not_found_detail="Job not found",
    )
    return TileJobResponse.model_validate(job)


@router.get("/jobs/", response_model=list[TileJobResponse])
async def list_tile_jobs(
    project_id: uuid.UUID = Query(...),
    state: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> list[TileJobResponse]:
    jobs = await service.list_jobs_for_project(
        project_id,
        payload=payload,
        state=state,
        offset=offset,
        limit=limit,
    )
    return [TileJobResponse.model_validate(j) for j in jobs]


# ── Canonical -> 3D Tileset (one-shot packaging) ────────────────────────


@router.post(
    "/from-canonical/{cad_import_id}",
    response_model=TilesetResponse,
    status_code=200,
)
async def package_canonical_as_tileset(
    cad_import_id: uuid.UUID,
    data: CanonicalToTilesetRequest | None = None,
    development_id: uuid.UUID | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.job_run")),
) -> TilesetResponse:
    obj = await service.package_canonical_as_tileset(
        cad_import_id,
        development_id=development_id,
        project_id=project_id,
        request=data,
        payload=payload,
    )
    return TilesetResponse.model_validate(obj)


# ── Imagery layers ───────────────────────────────────────────────────────


@router.get("/imagery-layers/", response_model=list[ImageryLayerResponse])
async def list_imagery_layers(
    project_id: uuid.UUID = Query(...),
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> list[ImageryLayerResponse]:
    rows = await service.list_imagery_for_project(project_id, payload=payload)
    return [ImageryLayerResponse.model_validate(r) for r in rows]


@router.post(
    "/imagery-layers/",
    response_model=ImageryLayerResponse,
    status_code=201,
)
async def create_imagery_layer(
    data: ImageryLayerCreate,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.write")),
) -> ImageryLayerResponse:
    obj = await service.create_imagery_layer(data, payload=payload)
    return ImageryLayerResponse.model_validate(obj)


@router.patch(
    "/imagery-layers/{layer_id}",
    response_model=ImageryLayerResponse,
)
async def update_imagery_layer(
    layer_id: uuid.UUID,
    data: ImageryLayerUpdate,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.write")),
) -> ImageryLayerResponse:
    obj = await service.update_imagery_layer(layer_id, data, payload=payload)
    return ImageryLayerResponse.model_validate(obj)


@router.delete("/imagery-layers/{layer_id}", status_code=204)
async def delete_imagery_layer(
    layer_id: uuid.UUID,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.delete")),
) -> Response:
    await service.delete_imagery_layer(layer_id, payload=payload)
    return Response(status_code=204)


# ── Terrain sources (system-wide) ────────────────────────────────────────


@router.get("/terrain-sources/", response_model=list[TerrainSourceResponse])
async def list_terrain_sources(
    service: GeoHubService = Depends(_svc),
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> list[TerrainSourceResponse]:
    rows = await service.list_terrain_sources()
    return [TerrainSourceResponse.model_validate(r) for r in rows]


@router.post(
    "/terrain-sources/",
    response_model=TerrainSourceResponse,
    status_code=201,
)
async def create_terrain_source(
    data: TerrainSourceCreate,
    service: GeoHubService = Depends(_svc),
    _perm: None = Depends(RequirePermission("geo_hub.admin")),
) -> TerrainSourceResponse:
    obj = await service.create_terrain_source(data)
    return TerrainSourceResponse.model_validate(obj)


@router.patch(
    "/terrain-sources/{src_id}",
    response_model=TerrainSourceResponse,
)
async def update_terrain_source(
    src_id: uuid.UUID,
    data: TerrainSourceUpdate,
    service: GeoHubService = Depends(_svc),
    _perm: None = Depends(RequirePermission("geo_hub.admin")),
) -> TerrainSourceResponse:
    obj = await service.update_terrain_source(src_id, data)
    return TerrainSourceResponse.model_validate(obj)


@router.delete("/terrain-sources/{src_id}", status_code=204)
async def delete_terrain_source(
    src_id: uuid.UUID,
    service: GeoHubService = Depends(_svc),
    _perm: None = Depends(RequirePermission("geo_hub.admin")),
) -> Response:
    await service.delete_terrain_source(src_id)
    return Response(status_code=204)


# ── Viewpoints ───────────────────────────────────────────────────────────


@router.get("/viewpoints/", response_model=list[ViewpointResponse])
async def list_viewpoints(
    project_id: uuid.UUID = Query(...),
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> list[ViewpointResponse]:
    rows = await service.list_viewpoints(project_id, payload=payload)
    return [ViewpointResponse.model_validate(r) for r in rows]


@router.post(
    "/viewpoints/",
    response_model=ViewpointResponse,
    status_code=201,
)
async def create_viewpoint(
    data: ViewpointCreate,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.write")),
) -> ViewpointResponse:
    obj = await service.save_viewpoint(data, payload=payload)
    return ViewpointResponse.model_validate(obj)


@router.patch("/viewpoints/{vp_id}", response_model=ViewpointResponse)
async def update_viewpoint(
    vp_id: uuid.UUID,
    data: ViewpointUpdate,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.write")),
) -> ViewpointResponse:
    obj = await service.update_viewpoint(vp_id, data, payload=payload)
    return ViewpointResponse.model_validate(obj)


@router.delete("/viewpoints/{vp_id}", status_code=204)
async def delete_viewpoint(
    vp_id: uuid.UUID,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.delete")),
) -> Response:
    await service.delete_viewpoint(vp_id, payload=payload)
    return Response(status_code=204)


# ── Overlays + GeoJSON / KML I/O ─────────────────────────────────────────


@router.get("/overlays/", response_model=list[GeoOverlayResponse])
async def list_overlays(
    project_id: uuid.UUID = Query(...),
    kind: str | None = Query(default=None),
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> list[GeoOverlayResponse]:
    rows = await service.list_overlays(project_id, payload=payload, kind=kind)
    return [GeoOverlayResponse.model_validate(r) for r in rows]


@router.post(
    "/overlays/",
    response_model=GeoOverlayResponse,
    status_code=201,
)
async def create_overlay(
    data: GeoOverlayCreate,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.write")),
) -> GeoOverlayResponse:
    obj = await service.create_overlay(data, payload=payload)
    return GeoOverlayResponse.model_validate(obj)


@router.patch(
    "/overlays/{overlay_id}",
    response_model=GeoOverlayResponse,
)
async def update_overlay(
    overlay_id: uuid.UUID,
    data: GeoOverlayUpdate,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.write")),
) -> GeoOverlayResponse:
    obj = await service.update_overlay(overlay_id, data, payload=payload)
    return GeoOverlayResponse.model_validate(obj)


@router.delete("/overlays/{overlay_id}", status_code=204)
async def delete_overlay(
    overlay_id: uuid.UUID,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.delete")),
) -> Response:
    await service.delete_overlay(overlay_id, payload=payload)
    return Response(status_code=204)


@router.post(
    "/overlays/import-geojson/",
    response_model=GeoOverlayResponse,
    status_code=201,
)
async def import_geojson(
    data: GeoJSONImportRequest,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.write")),
) -> GeoOverlayResponse:
    obj = await service.import_geojson(data, payload=payload)
    return GeoOverlayResponse.model_validate(obj)


@router.post(
    "/overlays/import-kml/",
    response_model=GeoOverlayResponse,
    status_code=201,
)
async def import_kml(
    data: KMLImportRequest,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.write")),
) -> GeoOverlayResponse:
    obj = await service.import_kml(data, payload=payload)
    return GeoOverlayResponse.model_validate(obj)


@router.get("/overlays/export-geojson/", response_model=dict[str, Any])
async def export_geojson(
    project_id: uuid.UUID = Query(...),
    kind: str | None = Query(default=None),
    include: str | None = Query(
        default=None,
        description=(
            "Comma-separated layers to fold into the export: overlays, anchor, "
            "hse, punchlist, diary. Defaults to all when omitted."
        ),
    ),
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> dict[str, Any]:
    """Export a project's whole map as one GeoJSON FeatureCollection.

    Folds vector overlays, the anchor point and the HSE / punchlist /
    diary pin layers into a single collection, each feature tagged with
    an ``oe:layer`` property. Unknown ``include`` tokens are ignored so a
    typo degrades to "export nothing for that token" rather than a 422.
    """
    allowed = {"overlays", "anchor", "hse", "punchlist", "diary"}
    include_set: set[str] | None = None
    if include is not None:
        include_set = {tok.strip() for tok in include.split(",") if tok.strip() in allowed}
    return await service.export_geojson(
        project_id,
        payload=payload,
        kind=kind,
        include=include_set,
    )


# ── Raster overlays (PDF / DWG / image pinned on the globe) ─────────────
#
# Kept on a separate ``/raster-overlays/`` path prefix so they do not
# collide with the existing GeoJSON / KML ``/overlays/`` endpoints. The
# two backings are intentionally distinct: GeoOverlay carries vector
# features for boundaries / scans / clash markers; GeoRasterOverlay
# carries a rasterised image plus four corner cartographic coords.


@router.get(
    "/raster-overlays/",
    response_model=list[GeoRasterOverlayResponse],
)
async def list_raster_overlays(
    project_id: uuid.UUID = Query(...),
    include_hidden: bool = Query(default=True),
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> list[GeoRasterOverlayResponse]:
    rows = await service.list_raster_overlays(
        project_id,
        payload=payload,
        include_hidden=include_hidden,
    )
    return [GeoRasterOverlayResponse.model_validate(r) for r in rows]


@router.get(
    "/raster-overlays/{overlay_id}",
    response_model=GeoRasterOverlayResponse,
)
async def get_raster_overlay(
    overlay_id: uuid.UUID,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> GeoRasterOverlayResponse:
    obj = await service.get_raster_overlay(overlay_id, payload=payload)
    return GeoRasterOverlayResponse.model_validate(obj)


@router.patch(
    "/raster-overlays/{overlay_id}",
    response_model=GeoRasterOverlayResponse,
)
async def update_raster_overlay(
    overlay_id: uuid.UUID,
    data: GeoRasterOverlayUpdate,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.write")),
) -> GeoRasterOverlayResponse:
    obj = await service.update_raster_overlay(
        overlay_id,
        data,
        payload=payload,
    )
    return GeoRasterOverlayResponse.model_validate(obj)


@router.delete("/raster-overlays/{overlay_id}", status_code=204)
async def delete_raster_overlay(
    overlay_id: uuid.UUID,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.delete")),
) -> Response:
    await service.delete_raster_overlay(overlay_id, payload=payload)
    return Response(status_code=204)


@router.post(
    "/raster-overlays/upload-pdf",
    response_model=RasterOverlayUploadResponse,
    status_code=201,
)
async def upload_pdf_raster_overlay(
    project_id: uuid.UUID = Form(...),
    page: int = Form(default=1),
    name: str | None = Form(default=None),
    file: UploadFile = File(...),
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.write")),
) -> RasterOverlayUploadResponse:
    """Upload a PDF, rasterise page ``page`` to PNG, persist an overlay."""
    content = await file.read()
    overlay, page_count = await service.upload_pdf_overlay(
        project_id,
        filename=file.filename or "upload.pdf",
        content=content,
        page=page,
        name=name,
        payload=payload,
    )
    return RasterOverlayUploadResponse(
        overlay=GeoRasterOverlayResponse.model_validate(overlay),
        page_count=page_count,
    )


@router.post(
    "/raster-overlays/upload-image",
    response_model=GeoRasterOverlayResponse,
    status_code=201,
)
async def upload_image_raster_overlay(
    project_id: uuid.UUID = Form(...),
    name: str | None = Form(default=None),
    file: UploadFile = File(...),
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.write")),
) -> GeoRasterOverlayResponse:
    """Upload a PNG/JPEG image and pin it to the project anchor bbox."""
    content = await file.read()
    overlay = await service.upload_image_overlay(
        project_id,
        filename=file.filename or "upload.png",
        content=content,
        name=name,
        payload=payload,
    )
    return GeoRasterOverlayResponse.model_validate(overlay)


@router.post(
    "/raster-overlays/from-dwg/{cad_import_id}",
    response_model=GeoRasterOverlayResponse,
    status_code=201,
)
async def raster_overlay_from_dwg(
    cad_import_id: uuid.UUID,
    project_id: uuid.UUID | None = Query(default=None),
    name: str | None = Query(default=None),
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.write")),
) -> GeoRasterOverlayResponse:
    """Render the canonical-JSON top-view of a converted DWG to PNG."""
    obj = await service.overlay_from_dwg(
        cad_import_id,
        project_id=project_id,
        name=name,
        payload=payload,
    )
    return GeoRasterOverlayResponse.model_validate(obj)


@router.get(
    "/raster-overlays/{overlay_id}/raster.png",
    responses={200: {"content": {"image/png": {}}}},
)
async def get_raster_overlay_image(
    overlay_id: uuid.UUID,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> Response:
    blob = await service.get_raster_overlay_bytes(overlay_id, payload=payload)
    # ``Cache-Control: private`` because the bytes are tenant-scoped -
    # public caches must not store them. ``max-age`` short so Cesium's
    # SingleTileImageryProvider doesn't pin a stale crop.
    return Response(
        content=blob,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get(
    "/tilesets/{tileset_id}/artifact/{filename}",
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def get_tileset_artifact(
    tileset_id: uuid.UUID,
    filename: str,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> Response:
    """Stream a tileset's ``tileset.json`` and tile blobs from storage.

    The DB stores only a storage key for a packaged tileset, so Cesium has
    nothing HTTP-reachable to load (the bare key fell through to the SPA
    catch-all and came back as index.html, which Cesium could not parse).
    This serves the artifacts, tenant-scoped behind ``geo_hub.read``; the
    frontend points Cesium at ``…/tilesets/{id}/artifact/tileset.json`` and
    its relative child-tile requests resolve back to this same route.
    """
    blob, media_type = await service.get_tileset_artifact_bytes(
        tileset_id,
        filename,
        payload=payload,
    )
    return Response(
        content=blob,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


# ── Anchored projects (Global map pin layer) ────────────────────────────


@router.get("/projects", response_model=list[AnchoredProjectResponse])
async def list_anchored_projects(
    limit: int = Query(default=1000, ge=1, le=50000),
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> list[AnchoredProjectResponse]:
    """All locatable projects the caller can access.

    Returns only the minimum needed to render the global Geo Hub: project
    id + name + coords. Non-admin users see their own projects; admins see
    all. A project is included when it has a ``GeoAnchor`` OR its address
    carries usable ``lat``/``lng`` coordinates (the anchor wins when both
    exist). Projects with neither are excluded so the pin layer never
    paints null-island placeholders.
    """
    rows = await service.list_anchored_projects(payload, limit=limit)
    return [AnchoredProjectResponse.model_validate(r) for r in rows]


# ── Map config one-shot bundle ───────────────────────────────────────────


@router.get("/map-config/{project_id}", response_model=MapConfigResponse)
async def get_map_config(
    project_id: uuid.UUID,
    development_id: uuid.UUID | None = Query(default=None),
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> MapConfigResponse:
    """Project-scoped map config.

    When ``development_id`` is supplied, tilesets and overlays are
    filtered down to those linked to that development (via
    ``metadata.development_id`` for tilesets, ``source_kind=development``
    for native dev tilesets, or PropDev's known unit/plot ids). Cross-
    tenant access is collapsed to 404 by the service IDOR helper.
    """
    bundle = await service.map_config(
        project_id,
        payload=payload,
        development_id=development_id,
    )
    return MapConfigResponse.model_validate(bundle)


@router.get("/map-summary/{project_id}", response_model=MapSummaryResponse)
async def get_map_summary(
    project_id: uuid.UUID,
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> MapSummaryResponse:
    """Aggregate counts + breakdowns for the project-map layer legend.

    One round-trip that returns per-layer feature counts (tilesets,
    overlays, raster overlays, viewpoints, HSE / punchlist / diary pins)
    plus small domain breakdowns (HSE severity, punch priority, tileset
    status). The frontend renders this as a layer legend with toggles
    and deep-links to the source module for any layer that is empty.
    Cross-tenant access collapses to 404 via the service IDOR helper.
    """
    summary = await service.map_summary(project_id, payload=payload)
    return MapSummaryResponse.model_validate(summary)


# ── Cross-module geo pin layers ──────────────────────────────────────────


@router.get(
    "/projects/{project_id}/hse-pins",
    response_model=list[HSEPinResponse],
)
async def list_hse_pins(
    project_id: uuid.UUID,
    limit: int = Query(default=500, ge=1, le=2000),
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> list[HSEPinResponse]:
    """Geo-pinned safety incidents for the project."""
    rows = await service.list_hse_pins(project_id, payload=payload, limit=limit)
    return [HSEPinResponse.model_validate(r) for r in rows]


@router.get(
    "/projects/{project_id}/punchlist-pins",
    response_model=list[PunchlistPinResponse],
)
async def list_punchlist_pins(
    project_id: uuid.UUID,
    limit: int = Query(default=500, ge=1, le=2000),
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> list[PunchlistPinResponse]:
    """Geo-pinned punch list items for the project."""
    rows = await service.list_punchlist_pins(
        project_id,
        payload=payload,
        limit=limit,
    )
    return [PunchlistPinResponse.model_validate(r) for r in rows]


@router.get(
    "/projects/{project_id}/diary-photo-pins",
    response_model=list[DiaryPhotoPinResponse],
)
async def list_diary_photo_pins(
    project_id: uuid.UUID,
    limit: int = Query(default=500, ge=1, le=2000),
    service: GeoHubService = Depends(_svc),
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> list[DiaryPhotoPinResponse]:
    """Geo-tagged Daily Diary photos for the project."""
    rows = await service.list_diary_photo_pins(
        project_id,
        payload=payload,
        limit=limit,
    )
    return [DiaryPhotoPinResponse.model_validate(r) for r in rows]


# ── Admin maintenance endpoints ──────────────────────────────────────────


@router.post(
    "/admin/sweep-deleted-raster-overlays",
    response_model=dict,
    status_code=200,
)
async def sweep_deleted_raster_overlays(
    older_than_days: int = Query(default=30, ge=0, le=3650),
    service: GeoHubService = Depends(_svc),
    _perm: None = Depends(RequirePermission("geo_hub.admin")),
) -> dict:
    """Hard-delete soft-deleted raster overlays older than the grace window.

    Frees storage blobs (source + rasterised PNG) before removing the DB row
    so orphaned bytes are actually reclaimed. Defaults to 30 days matching
    the geocode-cache TTL. Pass ``older_than_days=0`` to flush everything
    older than the current second (full purge - use with caution).

    Admin-only (``geo_hub.admin``). Safe to call repeatedly; each pass
    processes only rows whose ``deleted_at`` is before the cutoff.
    """
    return await service.sweep_deleted_raster_overlays(older_than_days=older_than_days)


__all__ = ["router"]
