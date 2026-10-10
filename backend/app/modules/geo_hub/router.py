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
import json
import logging
import re
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile

from app.config import get_settings
from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.dependencies import CurrentUserPayload, RequirePermission, SessionDep
from app.modules.geo_hub.ogc_router import ogc_router
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
    GeocodingConsentResponse,
    GeocodingConsentUpdate,
    GeoJSONImportRequest,
    GeoOverlayCreate,
    GeoOverlayResponse,
    GeoOverlayUpdate,
    GeoRasterOverlayResponse,
    GeoRasterOverlayUpdate,
    GlobeImageryResponse,
    GlobeStreetsSource,
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

logger = logging.getLogger(__name__)

router = APIRouter(tags=["geo_hub"])

# OGC API - Features, so QGIS and every other GIS client can read the same
# geometry through the same permission gate the rest of this module uses.
# Landing page: ``/api/v1/geo-hub/ogc``. See ``ogc_router.py``.
router.include_router(ogc_router, prefix="/ogc")


def _svc(session: SessionDep) -> GeoHubService:
    return GeoHubService(session)


# ── Basemap (public) ────────────────────────────────────────────────────────
#
# WHY THE BROWSER NEVER TALKS TO THE TILE HOST. Ad and privacy blockers
# routinely block public tile CDNs by hostname, which leaves the 3D globe and
# the project-card thumbnails blank. We proxy every basemap byte through our
# own origin: the browser only ever fetches same-origin ``/api`` (which
# blockers do not touch) and the server fetches once, with a proper
# User-Agent, and caches. These are intentionally the only public routes in
# this module: ``<img>`` tags and the Cesium / MapLibre loaders cannot attach
# an auth header, and basemap tiles are public imagery.
#
# WHY OPENFREEMAP, AND WHY THIS COMMENT NAMES THE ALTERNATIVES. The upstream
# used to be CARTO's keyless "Voyager" raster. It is keyless no longer: as of
# 2026-08 it answers 200, ``image/png``, ~26 KB of a perfectly decodable image
# of the correct geography with "API KEY REQUIRED" printed diagonally across
# it. Every field of that HTTP response is correct, so a status check, a
# byte-length check and an image-decode check are all green - the refusal
# lives only in the pixels. That is the failure this module is now built
# against, and ``tests/unit/test_basemap_upstream_policy.py`` holds the
# allowlist of upstreams we consider keyless and policy-compatible, with the
# reason for each written down.
#
#   * ``tile.openstreetmap.org`` is NOT an option however well it works
#     today. The OSMF Tile Usage Policy says "We generally do not recommend
#     putting your own caching proxy in front of tile.openstreetmap.org",
#     warns commercial services that "access may be withdrawn at any point",
#     and blocks by User-Agent without notice. It would work now and could
#     disappear under every install at once.
#   * OpenFreeMap is keyless, quota-free, ODbL, and self-hostable, which is
#     the property that matters most: an operator who outgrows the public
#     endpoint points OE_BASEMAP_UPSTREAM at their own copy (see
#     ``_basemap_upstream``).
_BASEMAP_UPSTREAM = "https://tiles.openfreemap.org"
# Paths below are relative to the upstream base so a self-hosted copy that
# mirrors the OpenFreeMap layout is a one-variable switch.
#
# TileJSON that names the CURRENT planet build. The tile path carries a
# version segment (``/planet/20260823_080002_pt/{z}/{x}/{y}.pbf``) that
# rotates as OpenFreeMap re-imports the planet, so it is resolved at runtime
# and never written into this file. Hardcoding it would reproduce the exact
# defect class above: a stale segment answers 200 with an EMPTY body, and an
# empty body is not distinguishable from "nothing here" by status alone.
_PLANET_TILEJSON_PATH = "/planet"
_NATURAL_EARTH_PATH = "/natural_earth/ne2sr/{z}/{x}/{y}.png"
_GLYPH_PATH = "/fonts/{fontstack}/{range}.pbf"
_SPRITE_PATH = "/sprites/ofm_f384/{filename}"


def _basemap_upstream() -> str:
    """Base URL the proxy fetches from: ``OE_BASEMAP_UPSTREAM`` or OpenFreeMap.

    Read per call rather than frozen into module constants at import, so a
    test that swaps the settings object sees its value. An empty or non-http value
    falls back to the public instance instead of producing URLs httpx would
    reject on every tile.
    """
    configured = (get_settings().basemap_upstream or "").strip().rstrip("/")
    if configured.startswith(("https://", "http://")):
        return configured
    return _BASEMAP_UPSTREAM


# The vector source stops here. MapLibre overzooms past it client-side by
# blowing up the z14 ancestor, so deep zooms stay populated.
_MAX_SOURCE_ZOOM = 14
_NATURAL_EARTH_MAX_ZOOM = 6

_TILE_HEADERS = {
    "User-Agent": "OpenConstructionERP/1.0 (+https://openconstructionerp.com)",
    "Accept": "*/*",
}

# Vendored MapLibre styles. Names are an allowlist, not a filesystem lookup.
_STYLE_DIR = Path(__file__).resolve().parent / "data" / "basemap_styles"
_STYLE_NAMES = frozenset({"liberty", "positron", "dark"})
# The glyph range shape from the MapLibre style spec, e.g. ``0-255``.
_GLYPH_RANGE_RE = re.compile(r"\d{1,5}-\d{1,5}")
# The four names MapLibre derives from one ``sprite`` base.
_SPRITE_FILES = {
    "ofm.json": "application/json",
    "ofm.png": "image/png",
    "ofm@2x.json": "application/json",
    "ofm@2x.png": "image/png",
}
# A basemap tile for a fixed z/x/y is effectively immutable for a week, so we
# let the browser AND any shared cache hold onto it. ``immutable`` stops the
# revalidation round-trip entirely on supporting browsers; the ETag covers the
# rest via conditional GETs (304, empty body).
#
# THE COST OF THAT PROMISE, learned the hard way. ``immutable`` cannot be
# revalidated, by construction: a browser that cached a tile from the old
# CARTO upstream keeps painting it for the full week no matter what the
# server now returns, because it never asks again. Changing the bytes behind
# a URL is therefore NOT enough to retire a bad tile - the URL itself has to
# change. That is why the raster route below lives at ``/basemap/`` and the
# old ``/tiles/`` path is kept only as an alias for external XYZ clients.
_TILE_CACHE_CONTROL = "public, max-age=604800, stale-while-revalidate=86400, immutable"
# Styles and glyphs change with a release, not with a tile, so they get a
# shorter window and no ``immutable``.
_ASSET_CACHE_CONTROL = "public, max-age=86400"


class _ByteBoundedCache:
    """LRU keyed by string, evicting on total BYTES rather than entry count.

    The previous cache counted entries: 4096 of them, annotated "a few MB
    resident". At the ~26 KB a real 256px basemap tile weighs that was 106 MB,
    off by more than an order of magnitude, and it would have been worse for
    the glyph ranges and sprite sheets now sharing this mechanism. Bounding
    the thing we actually care about removes the guess.
    """

    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max_bytes
        self._total = 0
        self._entries: OrderedDict[str, tuple[bytes, str]] = OrderedDict()

    def get(self, key: str) -> tuple[bytes, str] | None:
        hit = self._entries.get(key)
        if hit is not None:
            self._entries.move_to_end(key)
        return hit

    def put(self, key: str, data: bytes, etag: str) -> None:
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._total -= len(previous[0])
        self._entries[key] = (data, etag)
        self._total += len(data)
        while self._total > self._max_bytes and self._entries:
            _evicted_key, (evicted, _etag) = self._entries.popitem(last=False)
            self._total -= len(evicted)

    def clear(self) -> None:
        self._entries.clear()
        self._total = 0

    @property
    def nbytes(self) -> int:
        return self._total

    def __len__(self) -> int:
        return len(self._entries)


# Rendered raster tiles. Each is ~15-45 KB of PNG-8, so 48 MB holds well over
# a thousand: a project view plus many pan/zoom steps, per process.
_TILE_CACHE = _ByteBoundedCache(48 * 1024 * 1024)
# Glyph ranges, sprite sheets and Natural Earth relief, proxied verbatim.
# A single glyph range is ~75 KB and a style needs a handful of them.
_ASSET_CACHE = _ByteBoundedCache(32 * 1024 * 1024)
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


def _etag_for(data: bytes) -> str:
    """Strong validator derived from the bytes, so identical content 304s."""
    return f'"{hashlib.sha1(data).hexdigest()}"'  # noqa: S324 - cache validator, not security


def _cached_response(
    data: bytes,
    etag: str,
    media_type: str,
    request: Request,
    cache_control: str = _TILE_CACHE_CONTROL,
) -> Response:
    """Build a cacheable 200 (or a bodiless 304) with validators."""
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"Cache-Control": cache_control, "ETag": etag})
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Cache-Control": cache_control,
            "ETag": etag,
            "Content-Length": str(len(data)),
        },
    )


async def _fetch_upstream(url: str) -> bytes | None:
    """GET ``url`` and return its body, or ``None`` for anything unusable.

    An empty body counts as unusable on purpose. Measured against the live
    upstream: a real but featureless tile (mid-ocean) still carries 58 bytes,
    while a zero-length body is what a request beyond the source's max zoom
    or a malformed path returns. So "200 with nothing in it" is never a
    legitimate answer here, and treating it as one is how a blank map ships.
    """
    try:
        client = await _get_tile_client()
        res = await client.get(url)
    except (httpx.HTTPError, OSError):
        return None
    if res.status_code != 200 or not res.content:
        return None
    return res.content


# ── Planet version resolution ───────────────────────────────────────────────
#
# Resolved from the upstream TileJSON and refreshed on a TTL. This is the one
# piece of state that must never be a literal in the source: OpenFreeMap
# rotates the planet build (the segment is a timestamp), and a stale one
# degrades to empty bodies with a 200 status - invisible to every check that
# does not look at the payload.
_PLANET_TTL_SECONDS = 6 * 60 * 60
_planet_template: str | None = None
_planet_resolved_at: float = 0.0
_planet_lock = asyncio.Lock()


async def _planet_tile_template(*, force: bool = False) -> str | None:
    """Return the current ``{z}/{x}/{y}`` vector tile template, or ``None``.

    Args:
        force: Ignore the cached value and re-read the TileJSON. Used when a
            fetch built from the cached template comes back unusable, so a
            rotation mid-session heals on the next request instead of serving
            blank tiles until the process restarts.
    """
    global _planet_template, _planet_resolved_at

    now = time.monotonic()
    cached = _planet_template
    if not force and cached is not None and (now - _planet_resolved_at) < _PLANET_TTL_SECONDS:
        return cached

    async with _planet_lock:
        # Another coroutine may have refreshed while we waited for the lock.
        if (
            not force
            and _planet_template is not None
            and (time.monotonic() - _planet_resolved_at) < _PLANET_TTL_SECONDS
        ):
            return _planet_template
        upstream = _basemap_upstream()
        body = await _fetch_upstream(upstream + _PLANET_TILEJSON_PATH)
        if body is None:
            # Keep serving the previous template if we have one: a blip on
            # the metadata endpoint should not blank a map that was working.
            return _planet_template
        try:
            tilejson = json.loads(body)
            template = str(tilejson["tiles"][0])
        except (ValueError, KeyError, IndexError, TypeError):
            return _planet_template
        if not template.startswith(upstream):
            # The TileJSON is upstream-controlled input. Refuse a template
            # that would send our fetches somewhere else entirely.
            return _planet_template
        _planet_template = template
        _planet_resolved_at = time.monotonic()
        return template


def reset_basemap_state() -> None:
    """Drop cached tiles and the resolved planet version. For tests."""
    global _planet_template, _planet_resolved_at
    _planet_template = None
    _planet_resolved_at = 0.0
    _TILE_CACHE.clear()
    _ASSET_CACHE.clear()


async def _fetch_vector_tile(z: int, x: int, y: int) -> bytes | None:
    """Fetch one upstream vector tile, re-resolving the planet version once.

    The retry is deliberately keyed on the fetch failing rather than on the
    body being empty: an over-zoomed request legitimately returns an empty
    body, and re-resolving on that would hammer the TileJSON endpoint from
    every deep zoom. Callers clamp to ``_MAX_SOURCE_ZOOM`` before getting
    here, so a failure at this point really does suggest a stale template.
    """
    template = await _planet_tile_template()
    if template is None:
        return None
    body = await _fetch_upstream(template.format(z=z, x=x, y=y))
    if body is not None:
        return body
    refreshed = await _planet_tile_template(force=True)
    if refreshed is None or refreshed == template:
        return None
    return await _fetch_upstream(refreshed.format(z=z, x=x, y=y))


def _blank_tile() -> Response:
    """Transparent, non-cacheable tile so a failure reads as a clean gap."""
    return Response(content=_BLANK_TILE, media_type="image/png", headers=_BLANK_TILE_HEADERS)


def _valid_xyz(z: int, x: int, y: int, *, max_zoom: int = 22) -> bool:
    """Reject anything outside the web-mercator grid for this zoom."""
    if not (0 <= z <= max_zoom):
        return False
    bound = (1 << z) - 1
    return 0 <= x <= bound and 0 <= y <= bound


async def _relief_tile(z: int, x: int, y: int, request: Request) -> Response:
    """Serve one shaded-relief raster tile, proxied without rendering."""
    if not _valid_xyz(z, x, y, max_zoom=_NATURAL_EARTH_MAX_ZOOM):
        return _blank_tile()
    key = f"ne/{z}/{x}/{y}"
    hit = _TILE_CACHE.get(key)
    if hit is not None:
        return _cached_response(hit[0], hit[1], "image/png", request)
    data = await _fetch_upstream(_basemap_upstream() + _NATURAL_EARTH_PATH.format(z=z, x=x, y=y))
    if data is None:
        return _blank_tile()
    etag = _etag_for(data)
    _TILE_CACHE.put(key, data, etag)
    return _cached_response(data, etag, "image/png", request)


@router.get(
    "/basemap/{z}/{x}/{y}.png",
    summary="XYZ raster basemap tile (paste this into QGIS as an XYZ layer)",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}, "description": "One 256px basemap tile."}},
)
@router.get("/tiles/{z}/{x}/{y}.png", include_in_schema=False)
async def proxy_basemap_tile(z: int, x: int, y: int, request: Request) -> Response:
    """Serve one XYZ raster basemap tile: Natural Earth shaded relief.

    To add this basemap in QGIS: Browser panel, right-click **XYZ Tiles**,
    **New Connection**, and paste this URL template::

        https://<your-host>/api/v1/geo-hub/basemap/{z}/{x}/{y}.png

    Leave the QGIS authentication field empty - this route is public on
    purpose (see the section comment: ``<img>`` tags and the Cesium tile
    loader cannot attach an auth header, and basemap tiles are public
    imagery anyway). Set Max Zoom Level to 6, which is all this source has.

    This is a **basemap**, not your data: it gives your project layers
    something to sit on. Your own projects, overlays and viewpoints come
    from the OGC API - Features service at ``/api/v1/geo-hub/ogc``, which
    does require authentication and does apply per-project permissions.

    WHY RELIEF AND NOT STREETS. Every raster street basemap that was
    keyless has stopped being keyless, which is the defect this route was
    rewritten to fix. Nobody currently ships one that also permits
    proxying, and depending on one that might quietly start demanding a key
    is exactly how the previous upstream failed: it kept answering 200 with
    a valid PNG and printed "API KEY REQUIRED" across the picture, so no
    status or decode check noticed. Shaded relief is public domain, needs
    no key, and cannot be withdrawn from under us. The interactive maps are
    unaffected - they read vector tiles and render streets client-side. The
    two surfaces that cannot consume vector data, the ``<img>`` card
    thumbnail and the Cesium globe, show relief instead of streets. That is
    a real and deliberate downgrade in detail, taken over serving a
    watermarked tile.

    Any failure returns a transparent, non-cacheable tile so the map
    degrades to a clean gap instead of a broken image and can retry later.
    """
    return await _relief_tile(z, x, y, request)


@router.get(
    "/vector-tiles/{z}/{x}/{y}.pbf",
    summary="XYZ vector basemap tile (OpenMapTiles schema)",
    response_class=Response,
    responses={200: {"content": {"application/vnd.mapbox-vector-tile": {}}}},
)
async def proxy_vector_tile(z: int, x: int, y: int, request: Request) -> Response:
    """Proxy one OpenMapTiles vector tile through our own origin.

    This is what the interactive MapLibre maps read. Same reasoning as the
    raster route: same-origin so blockers cannot reach it, coordinates
    clamped so it can never be pointed at an arbitrary URL, and the planet
    version resolved at runtime rather than baked in.

    A request past the source's max zoom returns 204 rather than an empty
    200. MapLibre overzooms client-side from the deepest tile it has, so
    telling it plainly that there is nothing here is better than handing it
    a zero-length body it has to guess about.
    """
    if not _valid_xyz(z, x, y):
        return Response(status_code=204)
    if z > _MAX_SOURCE_ZOOM:
        return Response(status_code=204)

    key = f"v/{z}/{x}/{y}"
    hit = _TILE_CACHE.get(key)
    if hit is not None:
        return _cached_response(hit[0], hit[1], "application/vnd.mapbox-vector-tile", request)

    body = await _fetch_vector_tile(z, x, y)
    if body is None:
        return Response(status_code=204)
    etag = _etag_for(body)
    _TILE_CACHE.put(key, body, etag)
    return _cached_response(body, etag, "application/vnd.mapbox-vector-tile", request)


async def _proxy_asset(key: str, url: str, media_type: str, request: Request) -> Response:
    """Cache-and-serve one immutable upstream asset (glyphs, sprite, relief)."""
    hit = _ASSET_CACHE.get(key)
    if hit is not None:
        return _cached_response(hit[0], hit[1], media_type, request, _ASSET_CACHE_CONTROL)
    body = await _fetch_upstream(url)
    if body is None:
        return Response(status_code=404)
    etag = _etag_for(body)
    _ASSET_CACHE.put(key, body, etag)
    return _cached_response(body, etag, media_type, request, _ASSET_CACHE_CONTROL)


@router.get(
    "/fonts/{fontstack}/{glyph_range}.pbf",
    summary="Glyph range for the vector basemap labels",
    response_class=Response,
)
async def proxy_glyphs(fontstack: str, glyph_range: str, request: Request) -> Response:
    """Proxy one MapLibre glyph range (a PBF of rendered label glyphs).

    Without this the vendored style's ``glyphs`` URL would have to point at
    the tile host and the browser would talk to it directly, which is the
    whole thing we are avoiding. ``glyph_range`` is validated against the
    spec's ``start-end`` shape so this cannot be walked into an arbitrary
    upstream path.
    """
    if not _GLYPH_RANGE_RE.fullmatch(glyph_range):
        return Response(status_code=404)
    if len(fontstack) > 200 or "/" in fontstack or ".." in fontstack:
        return Response(status_code=404)
    return await _proxy_asset(
        f"glyph/{fontstack}/{glyph_range}",
        _basemap_upstream() + _GLYPH_PATH.format(fontstack=quote(fontstack, safe=""), range=glyph_range),
        "application/x-protobuf",
        request,
    )


@router.get(
    "/sprite/{filename}",
    summary="Sprite sheet for the vector basemap icons",
    response_class=Response,
)
async def proxy_sprite(filename: str, request: Request) -> Response:
    """Proxy the style's sprite sheet and its index.

    MapLibre derives four names from one ``sprite`` base - ``ofm.json``,
    ``ofm.png`` and the ``@2x`` pair - so all four are allowlisted by exact
    name rather than by pattern.
    """
    media_type = _SPRITE_FILES.get(filename)
    if media_type is None:
        return Response(status_code=404)
    return await _proxy_asset(
        f"sprite/{filename}",
        _basemap_upstream() + _SPRITE_PATH.format(filename=filename),
        media_type,
        request,
    )


@router.get(
    "/natural-earth/{z}/{x}/{y}.png",
    summary="Natural Earth shaded relief under the low zooms",
    response_class=Response,
)
async def proxy_natural_earth(z: int, x: int, y: int, request: Request) -> Response:
    """Proxy the low-zoom relief raster (public-domain Natural Earth).

    Same bytes as ``/basemap/``. The vendored styles no longer draw it (the
    relief layer made zoomed-out street maps read as terrain maps), but the
    path stays so a browser still holding an older cached style, or an XYZ
    client configured against it, keeps getting tiles instead of errors.
    """
    return await _relief_tile(z, x, y, request)


# ── Globe street imagery (operator-supplied) ────────────────────────────────
#
# The 3D globe takes raster XYZ imagery only, and no keyless public raster
# street service permits app use (see the section comment above), so by
# default it draws shaded relief. An operator who runs a raster tile server,
# or licenses one, sets ``OE_GLOBE_STREET_TILES_URL`` and the matching
# ``OE_GLOBE_STREET_TILES_ATTRIBUTION`` and the globe shows streets. Nothing
# about the upstream is hardcoded here, so the host policy gate has nothing
# new to allow: the operator chose the server and answers for its terms.
_GLOBE_STREETS_TILE_URL = "/api/v1/geo-hub/globe-streets/{z}/{x}/{y}.png"
_GLOBE_STREETS_MAX_ZOOM_CEILING = 22
_GLOBE_WARNED: set[str] = set()

# Image signatures a raster tile may carry. Anything else (an HTML error
# page, a JSON quota message) is a failure, not a tile.
_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)


def _image_media_type(data: bytes) -> str | None:
    """Media type of a PNG, JPEG or WebP body, ``None`` for anything else."""
    for signature, media_type in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _globe_street_source() -> tuple[str, str, int] | None:
    """The configured ``(template, attribution, max_zoom)``, or ``None``.

    A template is used only when it is http(s), carries all of ``{z}``,
    ``{x}`` and ``{y}``, and comes with an attribution. A half-configured
    source falls back to relief rather than drawing an uncredited map or
    requesting a URL that can never resolve.
    """
    settings = get_settings()
    template = (settings.globe_street_tiles_url or "").strip()
    attribution = (settings.globe_street_tiles_attribution or "").strip()
    if not template:
        return None
    usable = (
        template.startswith(("https://", "http://"))
        and all(part in template for part in ("{z}", "{x}", "{y}"))
        and bool(attribution)
    )
    if not usable:
        # Once per value: this runs on every tile request.
        if template not in _GLOBE_WARNED:
            _GLOBE_WARNED.add(template)
            logger.warning(
                "OE_GLOBE_STREET_TILES_URL is set but ignored: it needs an http(s) {z}/{x}/{y} "
                "template and OE_GLOBE_STREET_TILES_ATTRIBUTION; the globe shows relief instead",
            )
        return None
    max_zoom = min(max(int(settings.globe_street_tiles_max_zoom), 0), _GLOBE_STREETS_MAX_ZOOM_CEILING)
    return template, attribution, max_zoom


@router.get(
    "/globe-imagery/",
    response_model=GlobeImageryResponse,
    summary="Base imagery the 3D globe draws",
)
async def globe_imagery() -> GlobeImageryResponse:
    """Say whether the globe has raster street tiles or shows relief.

    Public like the tile routes: it names a same-origin tile path and a
    credit, nothing about the upstream server.
    """
    source = _globe_street_source()
    if source is None:
        return GlobeImageryResponse()
    _template, attribution, max_zoom = source
    return GlobeImageryResponse(
        streets=GlobeStreetsSource(tile_url=_GLOBE_STREETS_TILE_URL, attribution=attribution, max_zoom=max_zoom),
    )


@router.get(
    "/globe-streets/{z}/{x}/{y}.png",
    summary="Operator-configured raster street tile for the 3D globe",
    response_class=Response,
)
async def proxy_globe_street_tile(z: int, x: int, y: int, request: Request) -> Response:
    """Proxy one tile from ``OE_GLOBE_STREET_TILES_URL``.

    Returns a transparent tile when nothing is configured, the coordinates
    are off the grid, or the upstream answers with anything that is not an
    image. Cached for a day rather than as immutable, so switching the
    provider reaches browsers without a path change.
    """
    source = _globe_street_source()
    if source is None:
        return _blank_tile()
    template, _attribution, max_zoom = source
    if not _valid_xyz(z, x, y, max_zoom=max_zoom):
        return _blank_tile()
    # The template is in the key so a changed provider never serves the old one's tiles.
    key = f"gs/{hashlib.sha1(template.encode()).hexdigest()[:12]}/{z}/{x}/{y}"  # noqa: S324 - cache key
    hit = _TILE_CACHE.get(key)
    if hit is not None:
        media_type = _image_media_type(hit[0]) or "image/png"
        return _cached_response(hit[0], hit[1], media_type, request, _ASSET_CACHE_CONTROL)
    data = await _fetch_upstream(template.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y)))
    media_type = _image_media_type(data) if data else None
    if data is None or media_type is None:
        return _blank_tile()
    etag = _etag_for(data)
    _TILE_CACHE.put(key, data, etag)
    return _cached_response(data, etag, media_type, request, _ASSET_CACHE_CONTROL)


def _request_origin(request: Request) -> str:
    """Scheme and host the caller actually used, honouring a reverse proxy.

    Behind TLS termination the app itself speaks plain HTTP, so
    ``request.url.scheme`` says "http" while the browser is on "https". A
    style that hands an https page a set of http URLs is blocked as mixed
    content and the map goes blank, so the forwarded headers win where the
    deployment sets them.
    """
    forwarded = request.headers.get("x-forwarded-proto", "")
    scheme = forwarded.split(",")[0].strip() or request.url.scheme
    host = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
    return f"{scheme}://{host or request.headers.get('host') or request.url.netloc}"


def absolutise_style(text: str, origin: str) -> bytes:
    """Point every root-relative URL in a style at ``origin``.

    WHY THIS EXISTS AT ALL. Root-relative URLs look same-origin and are, for
    anything the main thread fetches: the low-zoom relief raster loaded
    perfectly with them. MapLibre loads vector tiles, glyphs and sprites in a
    Web Worker instead, and a worker has no document base, so the relative
    form dies there with "Failed to parse URL from
    /api/v1/geo-hub/vector-tiles/12/2046/1362.pbf". Nothing about that is
    visible from the server: the style is served 200, no tile is ever
    requested, no request fails because none is made, and the map paints its
    background colour and stops. It was found by screenshotting a real
    browser and seeing a white rectangle.

    Rewriting here rather than in the committed file keeps the file free of
    any hostname, so it stays correct on localhost, on a LAN address and
    behind a domain without a rebuild.
    """
    return text.replace('"/api/v1/geo-hub/', f'"{origin}/api/v1/geo-hub/').encode("utf-8")


@router.get(
    "/basemap-style/{name}.json",
    summary="MapLibre style for the vector basemap, same-origin throughout",
    response_class=Response,
)
async def basemap_style(name: str, request: Request) -> Response:
    """Serve a vendored MapLibre style whose every URL points back at us.

    The style is committed rather than fetched-and-rewritten at boot. A
    style JSON names the URLs the browser will go on to fetch - the vector
    source, the glyph template and the sprite base - and if any one of them keeps its upstream host the
    browser talks to that host directly while the map still renders, so the
    regression is invisible. Vendoring puts all of them in the diff.
    Refresh with ``backend/scripts/vendor_basemap_styles.py``.
    """
    path = _STYLE_DIR / f"{name}.json"
    # Allowlisted by name; ``name`` never reaches the filesystem otherwise.
    if name not in _STYLE_NAMES or not path.is_file():
        return Response(status_code=404)
    body = absolutise_style(path.read_text(encoding="utf-8"), _request_origin(request))
    return _cached_response(body, _etag_for(body), "application/json", request, _ASSET_CACHE_CONTROL)


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
    from app.modules.geo_hub.consent import resolve_outbound
    from app.modules.geo_hub.geocoder import suggest_addresses

    disabled = not (await resolve_outbound()).allowed
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


# ── Geocoding consent (asked once per installation) ────────────────────


async def _consent_response(session: Any, payload: Any) -> GeocodingConsentResponse:
    from app.core.permissions import permission_registry
    from app.modules.geo_hub.consent import _read_choice, decide

    try:
        answer = await _read_choice(session)
    except Exception:  # noqa: BLE001 - unreadable answer reads as "not asked"
        answer = None
    out = decide(answer)
    role = (payload or {}).get("role", "") if isinstance(payload, dict) else ""
    can_decide = out.state not in ("env_disabled", "env_mirror") and permission_registry.role_has_permission(
        role, "geo_hub.admin"
    )
    return GeocodingConsentResponse(
        state=out.state,
        mirror_url=answer[1] if answer and out.state == "mirror" else None,
        nominatim_url=out.nominatim_url,
        photon_url=out.photon_url,
        can_decide=can_decide,
    )


@router.get("/geocoding-consent", response_model=GeocodingConsentResponse)
async def get_geocoding_consent(
    session: SessionDep,
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.read")),
) -> GeocodingConsentResponse:
    """Whether addresses may be sent to a geocoder, so the UI knows to ask."""
    return await _consent_response(session, payload)


@router.put("/geocoding-consent", response_model=GeocodingConsentResponse)
async def put_geocoding_consent(
    body: GeocodingConsentUpdate,
    session: SessionDep,
    payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("geo_hub.admin")),
) -> GeocodingConsentResponse:
    """Record the installation's answer: allow, deny, or use an own mirror."""
    from fastapi import HTTPException

    from app.modules.geo_hub.consent import invalidate_cache, save_choice

    if body.choice == "mirror" and not body.mirror_url:
        raise HTTPException(status_code=422, detail="mirror_url is required for the mirror choice")
    user_id = (payload or {}).get("sub") if isinstance(payload, dict) else None
    await save_choice(session, body.choice, body.mirror_url, str(user_id) if user_id else None)  # type: ignore[arg-type]
    await session.commit()
    invalidate_cache()
    return await _consent_response(session, payload)


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
) -> Response:
    # IDOR before RBAC. Resolve the overlay through the ownership-checked
    # getter FIRST so a cross-tenant id collapses to 404 (existence masked)
    # before the stricter delete-permission gate runs. If we let
    # ``RequirePermission("geo_hub.delete")`` run first (as a route
    # dependency), an editor in another tenant would get 403 — leaking that
    # the row exists. Same-tenant callers who can see the overlay but lack
    # geo_hub.delete still get 403 from the explicit gate below, preserving
    # the MANAGER+ delete contract (test_geo_hub_security).
    await service.get_raster_overlay(overlay_id, payload=payload)
    await RequirePermission("geo_hub.delete")(payload)
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
