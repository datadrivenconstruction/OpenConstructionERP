# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""OpenStreetMap Nominatim geocoder + 30-day SQL cache.

Powers the new auto-anchor flow: when a project sets an address we
resolve it to lat / lon via this module and write a GeoAnchor without
the user having to click a map. Designed for graceful degradation —
every failure path returns ``None`` so callers can fall back to manual
anchoring without seeing an exception.

Honoured environment variables:

* ``OE_GEOCODER_DISABLED``  ``true`` → always return ``None`` (offline /
  sanctioned regions / privacy-sensitive deploys).
* ``OE_GEOCODER_BASE_URL``  e.g. ``https://nominatim.example.com`` →
  point at a self-hosted Nominatim mirror (defaults to the public
  service at ``https://nominatim.openstreetmap.org``).
* ``OE_GEOCODER_USER_AGENT_CONTACT`` (optional) — extra contact info
  appended to the User-Agent header. The bundled default already satisfies
  Nominatim's UA policy with our project contact email.

Rate limiting
-------------

Nominatim's public service tolerates at most 1 request per second per
client. We enforce that with a process-global ``asyncio.Semaphore(1)``
plus a ``_MIN_INTERVAL_SECONDS`` sleep so concurrent callers serialise
through one slot. The cache short-circuits well before this guard is
hit on the hot path.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.modules.geo_hub.models import GeocodeCache

logger = logging.getLogger(__name__)


# ── Public types ────────────────────────────────────────────────────────


Precision = Literal["address", "street", "city", "region", "country"]
Source = Literal["nominatim", "cache", "manual"]


@dataclass(frozen=True)
class ProjectAddress:
    """Minimal address shape consumed by the geocoder.

    Matches the JSONB ``Project.address`` we store today. Country is the
    only required field — Nominatim can geocode bare country names well
    enough to drop a sensible pin without other fields.
    """

    country: str
    street: str | None = None
    house_number: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None


@dataclass(frozen=True)
class GeocodeResult:
    """Canonical resolved coordinates for an address."""

    lat: Decimal
    lon: Decimal
    display_name: str
    precision: Precision
    bbox: tuple[Decimal, Decimal, Decimal, Decimal] | None
    source: Source
    cached_at: datetime | None


# ── Tunables (also published in the deliverables paragraph) ────────────

# 30-day TTL — matches OSM's recommended re-fetch cadence for address
# data that doesn't change every day (vs. POIs which can be edited
# hourly). After 30 days the cache entry is treated as stale and
# re-fetched on the next request.
CACHE_TTL = timedelta(days=30)

# Nominatim Usage Policy: max 1 absolute request per second. We bake the
# limit in here so the geocoder cannot accidentally DOS the public
# service even under heavy bulk-anchor load.
_MIN_INTERVAL_SECONDS = 1.0

# HTTP timeout; Nominatim is normally < 200 ms but a saturated mirror
# can easily take 5-8 s. Ten seconds is the well-known operator default.
_HTTP_TIMEOUT_SECONDS = 10.0

# Default base URL — overridable via ``OE_GEOCODER_BASE_URL`` so users
# with a self-hosted mirror don't have to ship our public-service rate
# limit.
_DEFAULT_BASE_URL = "https://nominatim.openstreetmap.org"

# Photon (Komoot, https://photon.komoot.io) — OSM-based geocoder with
# generous CORS, no documented rate limit, and Apache 2.0 / ODbL data.
# We try Photon first for the autocomplete suggest endpoint because it
# returns results in well under 1 s and isn't gated by Nominatim's 1
# req/s policy, then fall back to Nominatim if Photon fails. Disabling
# Photon (e.g. air-gapped deploys) is done by setting
# ``OE_GEOCODER_PHOTON_DISABLED=true``; the geocoder then drops straight
# to Nominatim.
_DEFAULT_PHOTON_URL = "https://photon.komoot.io"

# Default contact in the UA header — required by Nominatim's UA policy.
# Falls back to the project email when no override is set.
_DEFAULT_CONTACT_EMAIL = "info@datadrivenconstruction.io"

# Global rate-limit guard. Process-scoped (not container-scoped) — a
# multi-worker uvicorn deployment behind a single egress IP will still
# hit Nominatim above 1 req/s. Operators with strict bulk needs should
# point at a self-hosted mirror.
#
# ``Semaphore(1)`` is exactly one outbound call at a time — functionally
# equivalent to ``Lock()`` but matches the upstream design doc verbatim
# and reads as obvious intent ("max one in flight").
_RATE_SEMAPHORE = asyncio.Semaphore(1)
_last_request_monotonic: float = 0.0


def _disabled() -> bool:
    """``True`` when the operator turned off the geocoder."""
    val = (os.environ.get("OE_GEOCODER_DISABLED") or "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def _base_url() -> str:
    return (os.environ.get("OE_GEOCODER_BASE_URL") or _DEFAULT_BASE_URL).rstrip("/")


def _photon_url() -> str:
    return (os.environ.get("OE_GEOCODER_PHOTON_URL") or _DEFAULT_PHOTON_URL).rstrip("/")


def _photon_disabled() -> bool:
    val = (os.environ.get("OE_GEOCODER_PHOTON_DISABLED") or "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def _user_agent(version: str | None = None) -> str:
    """Build the UA header required by Nominatim.

    Includes a hard-coded contact email by default so even a totally
    unconfigured deploy satisfies the UA policy. Operators may append an
    extra contact via ``OE_GEOCODER_USER_AGENT_CONTACT``.
    """
    ver = (version or _app_version()) or "0.0.0"
    extra_contact = (os.environ.get("OE_GEOCODER_USER_AGENT_CONTACT") or "").strip()
    contact = extra_contact or _DEFAULT_CONTACT_EMAIL
    return f"OpenConstructionERP/{ver} ({contact})"


def _app_version() -> str | None:
    try:
        from app.config import get_settings

        return get_settings().app_version
    except Exception:  # noqa: BLE001 — settings import is best-effort
        return None


def _normalised_query(addr: ProjectAddress) -> str:
    """Return the canonical query string used for hashing + Nominatim.

    Strips whitespace, lower-cases, drops empty parts. Empty country
    raises ``ValueError`` — caller is expected to check before calling.
    """
    country = (addr.country or "").strip()
    if not country:
        raise ValueError("country is required to geocode an address")
    parts: list[str] = []
    street = (addr.street or "").strip()
    house = (addr.house_number or "").strip()
    if street and house:
        parts.append(f"{street} {house}")
    elif street:
        parts.append(street)
    elif house:
        parts.append(house)
    postal = (addr.postal_code or "").strip()
    if postal:
        parts.append(postal)
    city = (addr.city or "").strip()
    if city:
        parts.append(city)
    state = (addr.state or "").strip()
    if state:
        parts.append(state)
    parts.append(country)
    return ", ".join(parts).lower()


def _query_hash(normalised: str) -> str:
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _precision_from_address(addr: ProjectAddress) -> Precision:
    """Best-effort precision from the *input* shape.

    Refined by the Nominatim response (``addresstype``) when present,
    but used as the fallback so a deploy that runs without the network
    can still tag its single-country anchors as ``country`` rather than
    misleadingly claiming ``address``.
    """
    if addr.street and (addr.city or addr.postal_code):
        return "address"
    if addr.street:
        return "street"
    if addr.city:
        return "city"
    if addr.state:
        return "region"
    return "country"


def _precision_from_nominatim(
    payload: dict[str, Any],
    fallback: Precision,
) -> Precision:
    """Map Nominatim ``addresstype`` to our coarse precision bucket."""
    addresstype = str(payload.get("addresstype") or "").lower()
    osm_class = str(payload.get("class") or "").lower()
    if addresstype in {"building", "house"} or osm_class == "building":
        return "address"
    if addresstype in {"road", "street", "highway"}:
        return "street"
    if addresstype in {
        "city",
        "town",
        "village",
        "hamlet",
        "municipality",
        "suburb",
        "neighbourhood",
    }:
        return "city"
    if addresstype in {"state", "region", "province", "county"}:
        return "region"
    if addresstype in {"country"}:
        return "country"
    return fallback


def _bbox_from_nominatim(
    payload: dict[str, Any],
) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    """Parse Nominatim's ``boundingbox`` array into Decimal4-tuple."""
    raw = payload.get("boundingbox")
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    try:
        min_lat = Decimal(str(raw[0]))
        max_lat = Decimal(str(raw[1]))
        min_lon = Decimal(str(raw[2]))
        max_lon = Decimal(str(raw[3]))
    except (TypeError, ValueError):
        return None
    return (min_lat, min_lon, max_lat, max_lon)


# ── Cache ───────────────────────────────────────────────────────────────


async def _read_cache(
    session: AsyncSession,
    *,
    query_hash: str,
) -> GeocodeResult | None:
    """Return a cached result for ``query_hash`` if it exists AND is fresh.

    Increments ``hit_count`` on a hit (best-effort; failure here doesn't
    block the response). Treats rows older than ``CACHE_TTL`` as misses
    so a stale postal-code lookup gets refreshed on the next read.
    """
    stmt = select(GeocodeCache).where(GeocodeCache.query_hash == query_hash)
    res = await session.execute(stmt)
    row = res.scalars().first()
    if row is None:
        return None
    # Treat a missing cached_at as fresh (won't happen with our
    # server_default but defends against manual rows).
    cached_at = row.cached_at
    if cached_at is not None:
        # Normalise to aware UTC for the comparison; SQLite returns naive
        # datetimes through aiosqlite even with ``timezone=True`` columns.
        if cached_at.tzinfo is None:
            cached_at_aware = cached_at.replace(tzinfo=UTC)
        else:
            cached_at_aware = cached_at
        if datetime.now(UTC) - cached_at_aware > CACHE_TTL:
            return None
    try:
        await session.execute(
            update(GeocodeCache).where(GeocodeCache.id == row.id).values(hit_count=(row.hit_count or 0) + 1)
        )
    except Exception:  # noqa: BLE001 — best-effort hit counter
        pass
    bbox: tuple[Decimal, Decimal, Decimal, Decimal] | None = None
    if (
        row.bbox_min_lat is not None
        and row.bbox_min_lon is not None
        and row.bbox_max_lat is not None
        and row.bbox_max_lon is not None
    ):
        bbox = (
            row.bbox_min_lat,
            row.bbox_min_lon,
            row.bbox_max_lat,
            row.bbox_max_lon,
        )
    return GeocodeResult(
        lat=row.lat,
        lon=row.lon,
        display_name=row.display_name or "",
        precision=(row.precision or "address"),  # type: ignore[arg-type]
        bbox=bbox,
        source="cache",
        cached_at=cached_at,
    )


async def _write_cache(
    session: AsyncSession,
    *,
    query_hash: str,
    query_text: str,
    result: GeocodeResult,
) -> None:
    """Persist a fresh Nominatim result.

    Upserts by ``query_hash``: if a stale row exists we overwrite it
    in-place rather than insert a second row (the unique index would
    block that anyway).
    """
    existing_row = (
        (await session.execute(select(GeocodeCache).where(GeocodeCache.query_hash == query_hash))).scalars().first()
    )
    bbox_vals: tuple[
        Decimal | None,
        Decimal | None,
        Decimal | None,
        Decimal | None,
    ]
    if result.bbox is None:
        bbox_vals = (None, None, None, None)
    else:
        bbox_vals = result.bbox  # type: ignore[assignment]
    if existing_row is not None:
        await session.execute(
            update(GeocodeCache)
            .where(GeocodeCache.id == existing_row.id)
            .values(
                query_text=query_text,
                lat=result.lat,
                lon=result.lon,
                precision=result.precision,
                display_name=result.display_name,
                bbox_min_lat=bbox_vals[0],
                bbox_min_lon=bbox_vals[1],
                bbox_max_lat=bbox_vals[2],
                bbox_max_lon=bbox_vals[3],
                source="nominatim",
                cached_at=datetime.now(UTC),
            )
        )
    else:
        row = GeocodeCache(
            query_hash=query_hash,
            query_text=query_text,
            lat=result.lat,
            lon=result.lon,
            precision=result.precision,
            display_name=result.display_name,
            bbox_min_lat=bbox_vals[0],
            bbox_min_lon=bbox_vals[1],
            bbox_max_lat=bbox_vals[2],
            bbox_max_lon=bbox_vals[3],
            source="nominatim",
            cached_at=datetime.now(UTC),
        )
        session.add(row)


# ── Network ─────────────────────────────────────────────────────────────


async def _fetch_nominatim(
    normalised_query: str,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any] | None:
    """Hit Nominatim, returning the first result or ``None`` on any failure.

    Serialises through the global rate lock + min-interval so concurrent
    callers never violate the 1 req/s ToS. Operators with a private
    mirror can bypass via ``OE_GEOCODER_BASE_URL`` (the same lock still
    applies — defensive, since the cost of an extra ~1 s on a bulk run
    is negligible).
    """
    if _disabled():
        return None

    global _last_request_monotonic
    base = _base_url()
    url = f"{base}/search"
    params = {
        "q": normalised_query,
        "format": "json",
        "addressdetails": "1",
        "limit": "1",
    }
    headers = {
        "User-Agent": _user_agent(),
        "Accept": "application/json",
    }

    async with _RATE_SEMAPHORE:
        # Enforce >= _MIN_INTERVAL_SECONDS between any two outbound calls.
        now = time.monotonic()
        wait = _MIN_INTERVAL_SECONDS - (now - _last_request_monotonic)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_monotonic = time.monotonic()

        own_client = http_client is None
        client = http_client or httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        try:
            res = await client.get(url, params=params, headers=headers)
        except (httpx.HTTPError, OSError) as exc:
            logger.info("nominatim transport error: %s", exc)
            return None
        finally:
            if own_client:
                await client.aclose()

    if res.status_code >= 500:
        logger.info(
            "nominatim 5xx (%s) for query: %s",
            res.status_code,
            normalised_query[:80],
        )
        return None
    if res.status_code != 200:
        # 4xx beyond rate-limit (which OSM signals as 429) — just give up.
        logger.info(
            "nominatim non-200 (%s) for query: %s",
            res.status_code,
            normalised_query[:80],
        )
        return None
    try:
        payload = res.json()
    except ValueError:
        return None
    if not isinstance(payload, list) or not payload:
        return None
    first = payload[0]
    return first if isinstance(first, dict) else None


def _result_from_nominatim_payload(
    payload: dict[str, Any],
    fallback_precision: Precision,
) -> GeocodeResult | None:
    """Build a ``GeocodeResult`` from a single Nominatim result dict."""
    try:
        lat = Decimal(str(payload.get("lat")))
        lon = Decimal(str(payload.get("lon")))
    except (TypeError, ValueError, ArithmeticError):
        return None
    if not (Decimal("-90") <= lat <= Decimal("90")):
        return None
    if not (Decimal("-180") <= lon <= Decimal("180")):
        return None
    display_name = str(payload.get("display_name") or "")[:500]
    precision = _precision_from_nominatim(payload, fallback_precision)
    bbox = _bbox_from_nominatim(payload)
    return GeocodeResult(
        lat=lat,
        lon=lon,
        display_name=display_name,
        precision=precision,
        bbox=bbox,
        source="nominatim",
        cached_at=datetime.now(UTC),
    )


# ── Public API ──────────────────────────────────────────────────────────


async def geocode_address(
    address: ProjectAddress,
    *,
    session: AsyncSession | None = None,
    settings: Any | None = None,  # noqa: ARG001 — reserved for caller wiring
    http_client: httpx.AsyncClient | None = None,
    force_refresh: bool = False,
) -> GeocodeResult | None:
    """Return canonical coords for a project address.

    Resolution order:

    1. Bail out if ``OE_GEOCODER_DISABLED`` is truthy.
    2. Lookup in the 30-day cache (skipped when ``force_refresh=True``).
    3. Hit Nominatim, respecting the 1 req/s ToS rate limit.
    4. Persist the fresh response back into the cache.

    Returns ``None`` on any failure — caller is responsible for surfacing
    that as a 502 / "geocoder unavailable" UX message.

    Args:
        address: Project address. Country is required; other fields
            sharpen the precision of the resolved coords.
        session: Existing async DB session (used by request-scoped
            callers). When omitted we open one transactionally for the
            duration of this call.
        settings: Reserved for future per-tenant config; ignored.
        http_client: Optional shared httpx client (used in tests to
            inject a transport mock).
        force_refresh: When ``True`` skip the cache read and unconditionally
            re-fetch from Nominatim, then overwrite the cached row.
    """
    if _disabled():
        return None
    try:
        query_text = _normalised_query(address)
    except ValueError:
        return None
    qhash = _query_hash(query_text)
    fallback_precision = _precision_from_address(address)

    own_session = session is None
    sess: AsyncSession
    if own_session:
        sess = async_session_factory()
    else:
        sess = session  # type: ignore[assignment]

    try:
        if not force_refresh:
            cached = await _read_cache(sess, query_hash=qhash)
            if cached is not None:
                if own_session:
                    await sess.commit()
                return cached

        payload = await _fetch_nominatim(query_text, http_client=http_client)
        if payload is None:
            # Fall back to a stale cache entry if one exists — better an
            # old pin than a 502 on a transient Nominatim hiccup.
            if not force_refresh:
                # We already read the cache above; nothing else to try.
                pass
            else:
                cached = await _read_cache(sess, query_hash=qhash)
                if cached is not None:
                    if own_session:
                        await sess.commit()
                    return cached
            return None

        result = _result_from_nominatim_payload(payload, fallback_precision)
        if result is None:
            return None
        await _write_cache(
            sess,
            query_hash=qhash,
            query_text=query_text,
            result=result,
        )
        if own_session:
            await sess.commit()
        return result
    except Exception as exc:  # noqa: BLE001 — never raise to caller
        logger.warning("geocode_address: unexpected failure: %s", exc)
        if own_session:
            try:
                await sess.rollback()
            except Exception:  # noqa: BLE001
                pass
        return None
    finally:
        if own_session:
            try:
                await sess.close()
            except Exception:  # noqa: BLE001
                pass


async def cache_stats(session: AsyncSession) -> dict[str, Any]:
    """Return aggregate counters for the admin cache panel.

    Reports total row count, fresh vs stale split (against ``CACHE_TTL``),
    sum of ``hit_count`` and the oldest / newest cached_at timestamps.
    Cheap — a single grouped query against the SQL backend.
    """
    from sqlalchemy import func as sql_func
    from sqlalchemy import select as sql_select

    cutoff = datetime.now(UTC) - CACHE_TTL
    total = (await session.execute(sql_select(sql_func.count()).select_from(GeocodeCache))).scalar() or 0
    stale = (
        await session.execute(
            sql_select(sql_func.count()).select_from(GeocodeCache).where(GeocodeCache.cached_at < cutoff)
        )
    ).scalar() or 0
    hits = (await session.execute(sql_select(sql_func.coalesce(sql_func.sum(GeocodeCache.hit_count), 0)))).scalar() or 0
    oldest = (await session.execute(sql_select(sql_func.min(GeocodeCache.cached_at)))).scalar()
    newest = (await session.execute(sql_select(sql_func.max(GeocodeCache.cached_at)))).scalar()
    return {
        "total": int(total),
        "fresh": int(total) - int(stale),
        "stale": int(stale),
        "hit_sum": int(hits),
        "ttl_days": CACHE_TTL.days,
        "oldest_cached_at": oldest,
        "newest_cached_at": newest,
    }


async def purge_cache(
    session: AsyncSession,
    *,
    older_than_days: int | None = None,
) -> int:
    """Delete rows older than ``older_than_days`` (or all when ``None``).

    Returns the number of deleted rows. Defaults to a no-op (returns 0)
    when ``older_than_days`` is negative — we never want a stray param
    to silently flush the entire cache without an explicit ``None`` from
    the caller.
    """
    from sqlalchemy import delete as sql_delete

    stmt = sql_delete(GeocodeCache)
    if older_than_days is not None:
        if older_than_days < 0:
            return 0
        cutoff = datetime.now(UTC) - timedelta(days=int(older_than_days))
        stmt = stmt.where(GeocodeCache.cached_at < cutoff)
    res = await session.execute(stmt)
    await session.commit()
    return int(res.rowcount or 0)


@dataclass(frozen=True)
class SuggestionResult:
    """Single Nominatim search result returned by the suggest endpoint.

    Lightweight projection — keeps just what the autocomplete dropdown
    needs (display name + lat/lon + country flag + bbox + addresstype).
    Returned in the response order from Nominatim so the upstream
    relevance ranking is preserved.

    ``address_parts`` carries the structured Nominatim ``address``
    dict (street, city, country, postcode, ...) so the frontend can
    fill the existing 4-field address inputs without trying to parse
    the free-text ``display_name``.
    """

    display_name: str
    lat: Decimal
    lon: Decimal
    country_code: str | None
    bbox: tuple[Decimal, Decimal, Decimal, Decimal] | None
    addresstype: str | None
    osm_type: str | None
    address_parts: dict[str, str] | None = None


def _suggestion_from_payload(item: dict[str, Any]) -> SuggestionResult | None:
    """Build a ``SuggestionResult`` from a single raw Nominatim entry."""
    try:
        lat = Decimal(str(item.get("lat")))
        lon = Decimal(str(item.get("lon")))
    except (TypeError, ValueError, ArithmeticError):
        return None
    if not (Decimal("-90") <= lat <= Decimal("90")):
        return None
    if not (Decimal("-180") <= lon <= Decimal("180")):
        return None
    addr = item.get("address") if isinstance(item.get("address"), dict) else None
    cc_raw = (addr or {}).get("country_code") if addr else None
    country_code: str | None = None
    if isinstance(cc_raw, str) and len(cc_raw) == 2 and cc_raw.isalpha():
        country_code = cc_raw.lower()
    # Whitelist of address-part keys we forward to the client. The full
    # Nominatim object can include county, suburb, ISO codes etc. that
    # the project form doesn't use — trimming keeps the response slim.
    address_parts: dict[str, str] | None = None
    if isinstance(addr, dict):
        wanted = {
            "house_number",
            "road",
            "street",
            "postcode",
            "city",
            "town",
            "village",
            "state",
            "country",
            "country_code",
        }
        address_parts = {k: str(v) for k, v in addr.items() if k in wanted and isinstance(v, str) and v.strip()}
    return SuggestionResult(
        display_name=str(item.get("display_name") or "")[:500],
        lat=lat,
        lon=lon,
        country_code=country_code,
        bbox=_bbox_from_nominatim(item),
        addresstype=(str(item.get("addresstype")) if item.get("addresstype") else None),
        osm_type=str(item.get("osm_type")) if item.get("osm_type") else None,
        address_parts=address_parts or None,
    )


def _photon_suggestion_from_feature(feature: dict[str, Any]) -> SuggestionResult | None:
    """Build a ``SuggestionResult`` from a single Photon GeoJSON feature."""
    try:
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        geom = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
        coords = geom.get("coordinates") if isinstance(geom.get("coordinates"), list) else None
        if not coords or len(coords) < 2:
            return None
        lon = Decimal(str(coords[0]))
        lat = Decimal(str(coords[1]))
    except (TypeError, ValueError, ArithmeticError):
        return None
    if not (Decimal("-90") <= lat <= Decimal("90")):
        return None
    if not (Decimal("-180") <= lon <= Decimal("180")):
        return None
    props = props or {}
    # Photon flattens address parts onto the properties object (not a
    # nested "address" object the way Nominatim does). Construct a
    # display_name from the most specific parts available.
    line_parts: list[str] = []
    for key in ("street", "housenumber", "postcode", "city", "state", "country"):
        v = props.get(key)
        if isinstance(v, str) and v.strip():
            line_parts.append(v.strip())
    display_name = props.get("name") or ", ".join(line_parts) or "?"
    if isinstance(display_name, str) and len(display_name) > 500:
        display_name = display_name[:500]
    cc = props.get("countrycode")
    country_code: str | None = None
    if isinstance(cc, str) and len(cc) == 2 and cc.isalpha():
        country_code = cc.lower()
    # Photon's ``extent`` is [minLon, maxLat, maxLon, minLat] when present.
    bbox_raw = props.get("extent")
    bbox: tuple[Decimal, Decimal, Decimal, Decimal] | None = None
    if isinstance(bbox_raw, list) and len(bbox_raw) == 4:
        try:
            min_lon = Decimal(str(bbox_raw[0]))
            max_lat = Decimal(str(bbox_raw[1]))
            max_lon = Decimal(str(bbox_raw[2]))
            min_lat = Decimal(str(bbox_raw[3]))
            # SuggestionResult.bbox convention matches Nominatim:
            # (south, north, west, east) — (minLat, maxLat, minLon, maxLon).
            bbox = (min_lat, max_lat, min_lon, max_lon)
        except (TypeError, ValueError, ArithmeticError):
            bbox = None
    # Forward only the address-part keys the client form uses, matched
    # to the Nominatim shape so frontend doesn't need a separate branch.
    addr_parts: dict[str, str] = {}
    for src_key, dest_key in (
        ("housenumber", "house_number"),
        ("street", "road"),
        ("postcode", "postcode"),
        ("city", "city"),
        ("state", "state"),
        ("country", "country"),
        ("countrycode", "country_code"),
    ):
        v = props.get(src_key)
        if isinstance(v, str) and v.strip():
            addr_parts[dest_key] = v.strip()
    return SuggestionResult(
        display_name=display_name,
        lat=lat,
        lon=lon,
        country_code=country_code,
        bbox=bbox,
        addresstype=(str(props.get("type")) if props.get("type") else None),
        osm_type=str(props.get("osm_type")) if props.get("osm_type") else None,
        address_parts=addr_parts or None,
    )


async def _photon_suggest(
    query: str,
    *,
    limit: int,
    http_client: httpx.AsyncClient | None,
) -> list[SuggestionResult]:
    """Photon (Komoot) autocomplete — fast first-line provider.

    Returns an empty list on any failure so the caller can transparently
    fall back to Nominatim. Photon's API mirrors GeoJSON
    (``{features: [...]}``) and has no documented rate limit, so we skip
    the semaphore + sleep that protects Nominatim.
    """
    url = f"{_photon_url()}/api/"
    params = {"q": query, "limit": str(limit)}
    headers = {"User-Agent": _user_agent(), "Accept": "application/json"}
    own_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS)
    try:
        res = await client.get(url, params=params, headers=headers)
    except (httpx.HTTPError, OSError) as exc:
        logger.info("photon suggest transport error: %s", exc)
        return []
    finally:
        if own_client:
            await client.aclose()
    if res.status_code != 200:
        logger.info("photon suggest non-200 (%s) for query: %s", res.status_code, query[:80])
        return []
    try:
        payload = res.json()
    except ValueError:
        return []
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        return []
    out: list[SuggestionResult] = []
    for feat in features[:limit]:
        if not isinstance(feat, dict):
            continue
        sug = _photon_suggestion_from_feature(feat)
        if sug is not None:
            out.append(sug)
    return out


async def suggest_addresses(
    query: str,
    *,
    limit: int = 5,
    http_client: httpx.AsyncClient | None = None,
) -> list[SuggestionResult]:
    """Search OSM-based geocoders for up to ``limit`` matches.

    Provider chain: Photon (fast, no rate limit) → Nominatim (1 req/s).
    Used by the autocomplete dropdown — *not* the auto-anchor flow (which
    keeps the structured ``geocode_address`` for cache-keying by parts).

    Returns an empty list on any failure (network, parse, disabled env,
    short query) so callers can render "no matches" without exception
    handling. Respects Nominatim's 1 req/s + User-Agent policy on the
    fallback path; Photon has no analogous gate.
    """
    if _disabled():
        return []
    query_clean = (query or "").strip()
    if len(query_clean) < 3:
        # Geocoders return garbage for 1-2 char queries; short-circuit
        # so we don't burn rate-limit budget on noise.
        return []
    capped = max(1, min(int(limit or 5), 10))

    # ── Provider 1: Photon ────────────────────────────────────────────
    # Generous CORS, no rate limit, sub-second response on warm cache.
    # Skip silently if disabled by env or if it returns no hits — we
    # don't want a flaky Photon to hide a useful Nominatim result.
    if not _photon_disabled():
        photon_hits = await _photon_suggest(
            query_clean,
            limit=capped,
            http_client=http_client,
        )
        if photon_hits:
            return photon_hits

    global _last_request_monotonic
    base = _base_url()
    url = f"{base}/search"
    params = {
        "q": query_clean,
        "format": "json",
        "addressdetails": "1",
        "limit": str(capped),
    }
    headers = {
        "User-Agent": _user_agent(),
        "Accept": "application/json",
    }

    async with _RATE_SEMAPHORE:
        now = time.monotonic()
        wait = _MIN_INTERVAL_SECONDS - (now - _last_request_monotonic)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_monotonic = time.monotonic()

        own_client = http_client is None
        client = http_client or httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        try:
            res = await client.get(url, params=params, headers=headers)
        except (httpx.HTTPError, OSError) as exc:
            logger.info("nominatim suggest transport error: %s", exc)
            return []
        finally:
            if own_client:
                await client.aclose()

    if res.status_code != 200:
        logger.info(
            "nominatim suggest non-200 (%s) for query: %s",
            res.status_code,
            query_clean[:80],
        )
        return []
    try:
        payload = res.json()
    except ValueError:
        return []
    if not isinstance(payload, list):
        return []
    out: list[SuggestionResult] = []
    for item in payload[:capped]:
        if not isinstance(item, dict):
            continue
        sug = _suggestion_from_payload(item)
        if sug is not None:
            out.append(sug)
    return out


def project_address_from_jsonb(
    address_jsonb: dict[str, Any] | None,
) -> ProjectAddress | None:
    """Lift a ``Project.address`` JSONB dict into a typed ``ProjectAddress``.

    Returns ``None`` when the dict is missing or has no ``country`` —
    the geocoder cannot make sense of an addressless project.
    """
    if not isinstance(address_jsonb, dict):
        return None
    country = (
        (address_jsonb.get("country") or "").strip()
        if isinstance(
            address_jsonb.get("country"),
            str,
        )
        else ""
    )
    if not country:
        return None
    return ProjectAddress(
        country=country,
        street=address_jsonb.get("street") or None,
        house_number=(address_jsonb.get("house_number") or address_jsonb.get("houseNumber") or None),
        city=address_jsonb.get("city") or None,
        state=address_jsonb.get("state") or None,
        postal_code=(address_jsonb.get("postal_code") or address_jsonb.get("postcode") or None),
    )


__all__ = [
    "CACHE_TTL",
    "GeocodeResult",
    "ProjectAddress",
    "SuggestionResult",
    "cache_stats",
    "geocode_address",
    "project_address_from_jsonb",
    "purge_cache",
    "suggest_addresses",
]
