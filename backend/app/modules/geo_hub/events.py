# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Geo Hub event registry.

This module owns the three cross-module subscribers that auto-populate
the geo dashboard whenever other modules emit domain events. Each
subscriber:

* validates the event payload shape (best-effort, never raises)
* is idempotent - replays do not double-create rows
* opens its own session because the event bus carries no caller-session
  context
* emits ``geo_hub.subscriber.failed`` on error instead of raising,
  keeping the producing module's transaction safe

Events PUBLISHED by geo_hub (payload schemas in the publishing call):

    geo_hub.anchor.created          {anchor_id, project_id, lat, lon}
    geo_hub.anchor.auto_geocoded    {anchor_id, project_id, lat, lon, precision, source}
    geo_hub.tile_job.queued         {job_id, project_id, source_kind, source_id}
    geo_hub.tile_job.completed      {job_id, project_id, tileset_id, output_uri}
    geo_hub.tile_job.failed         {job_id, project_id, error}
    geo_hub.tileset.ready           {tileset_id, project_id, source_kind, source_id}
    geo_hub.subscriber.failed       {subscriber, error, event_name}

Inbound (we subscribe to)::

    projects.address_set           -> auto-geocode address -> anchor
    safety.incident.created        -> persist incident marker overlay
    ncr.created                    -> pin a located non-conformity

Tile jobs are queued only through ``POST /tilesets/generate/``. Nothing
else is subscribed because no other module publishes an event that
carries a location: clash results, field reports, carbon inventories,
risks and schedule tasks hold no WGS-84 coordinates, and a project
without an address has no place to pin.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.core.events import Event, event_bus
from app.core.json_merge import merge_metadata
from app.database import async_session_factory

logger = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────────────────────


def _coerce_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _coerce_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (TypeError, ValueError):
        return default


async def _fan_out_failure(
    subscriber: str,
    event_name: str,
    exc: BaseException,
) -> None:
    """Best-effort error fanout - never raises itself."""
    try:
        await event_bus.publish(
            "geo_hub.subscriber.failed",
            {
                "subscriber": subscriber,
                "event_name": event_name,
                "error": f"{type(exc).__name__}: {exc}",
            },
            source_module="geo_hub",
        )
    except Exception:  # noqa: BLE001 - never let the recovery path crash
        logger.exception("geo_hub failure-fanout itself failed")


async def _on_project_address_set(event: Event) -> dict[str, Any]:
    """``projects.address_set`` -> auto-geocode + drop an anchor.

    Listens for the address-changed event the projects module fires from
    both ``create_project`` and ``update_project`` whenever the address
    JSONB carries at least a country. Runs the Nominatim geocoder, then:

    * Skips silently when the project already has a non-placeholder
      anchor (lat / lon != 0,0) - manual anchors win over auto ones.
    * Overwrites the placeholder anchor that ``_on_project_created``
      seeds with lat=0 / lon=0 (so the user's first proper address fill
      flips the globe pin to the right spot without UI ceremony).
    * Creates a fresh anchor when none exists.

    All failures land in the failure-fanout - the producing module's
    transaction is already committed by this point so we never raise.
    """
    import asyncio as _asyncio

    from app.modules.geo_hub.geocoder import project_address_from_jsonb

    payload = event.data or {}
    project_id = _coerce_uuid(payload.get("project_id"))
    address_blob = payload.get("address")
    if project_id is None or not isinstance(address_blob, dict):
        return {"status": "ignored", "reason": "missing project_id / address"}
    typed_address = project_address_from_jsonb(address_blob)
    if typed_address is None:
        return {"status": "ignored", "reason": "address has no country"}

    # Yield once so the producing request's session (still holding the
    # SQLite single-writer lock when ``publish_detached`` scheduled us)
    # has a chance to commit + close before we open a fresh one. Without
    # this, aiosqlite races on the same connection pool slot and surfaces
    # as ``RuntimeError: await wasn't used with future`` - caught below
    # and retried with an exponential backoff.
    await _asyncio.sleep(0)

    last_exc: BaseException | None = None
    for attempt in range(4):
        if attempt:
            await _asyncio.sleep(0.05 * (2 ** (attempt - 1)))
        try:
            return await _do_geocode_and_persist(
                project_id,
                typed_address,
                event,
            )
        except RuntimeError as exc:
            # aiosqlite cross-loop / writer-contention surface; retry.
            if "await wasn't used with future" not in str(exc):
                last_exc = exc
                break
            last_exc = exc
            continue
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            break
    logger.warning("geo_hub._on_project_address_set: %s", last_exc)
    if last_exc is not None:
        await _fan_out_failure(
            "_on_project_address_set",
            event.name,
            last_exc,
        )
    return {"status": "error", "error": str(last_exc)}


async def _do_geocode_and_persist(
    project_id: uuid.UUID,
    typed_address: Any,
    event: Event,
) -> dict[str, Any]:
    """Inner body of ``_on_project_address_set`` - opens a session, geocodes,
    persists. Pulled out so the caller can wrap it in retry-on-aiosqlite."""
    from app.modules.geo_hub.geocoder import geocode_address
    from app.modules.geo_hub.models import GeoAnchor
    from app.modules.geo_hub.repository import GeoAnchorRepository

    async with async_session_factory() as session:
        repo = GeoAnchorRepository(session)
        existing = await repo.get_by_project(project_id)
        if existing is not None and (existing.lat != Decimal("0") or existing.lon != Decimal("0")):
            meta = existing.metadata_ or {}
            if meta.get("geocoded_from") != "project_address":
                # Manual anchor present - don't clobber.
                return {
                    "status": "ignored",
                    "reason": "manual anchor wins over auto",
                    "anchor_id": str(existing.id),
                }
        result = await geocode_address(typed_address, session=session)
        if result is None:
            return {
                "status": "ignored",
                "reason": "geocoder returned no result",
            }
        now = datetime.now(UTC).isoformat()
        geo_meta = {
            "geocoded_from": "project_address",
            "geocode_precision": result.precision,
            "geocode_source": result.source,
            "geocode_display_name": result.display_name,
            "geocoded_at": now,
        }
        address_line = ", ".join(
            part
            for part in (
                typed_address.street,
                typed_address.house_number,
                typed_address.postal_code,
                typed_address.city,
                typed_address.country,
            )
            if part
        )
        if existing is None:
            anchor = GeoAnchor(
                project_id=project_id,
                lat=result.lat,
                lon=result.lon,
                alt=Decimal("0"),
                epsg_code=4326,
                address=address_line or None,
                metadata_=geo_meta,
            )
            await repo.create(anchor)
            anchor_id = anchor.id
        else:
            merged_meta = merge_metadata(existing.metadata_, geo_meta)
            await repo.update_fields(
                existing.id,
                lat=result.lat,
                lon=result.lon,
                epsg_code=4326,
                address=address_line or existing.address,
                metadata_=merged_meta,
            )
            anchor_id = existing.id
        await session.commit()
    await event_bus.publish(
        "geo_hub.anchor.auto_geocoded",
        {
            "anchor_id": str(anchor_id),
            "project_id": str(project_id),
            "lat": str(result.lat),
            "lon": str(result.lon),
            "precision": result.precision,
            "source": result.source,
        },
        source_module="geo_hub",
    )
    return {"status": "ok", "anchor_id": str(anchor_id)}


async def _persist_marker_overlay(
    project_id: uuid.UUID,
    event_id: str,
    *,
    kind: str,
    name: str,
    lat: Decimal,
    lon: Decimal,
    properties: dict[str, Any],
    style: dict[str, Any] | None = None,
) -> uuid.UUID | None:
    """Shared helper for the "drop a pin"-style subscribers."""
    from app.modules.geo_hub.models import GeoOverlay
    from app.modules.geo_hub.repository import GeoOverlayRepository

    async with async_session_factory() as session:
        repo = GeoOverlayRepository(session)
        existing = await repo.find_by_event(event_id)
        if existing is not None:
            return existing.id
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(lon), float(lat)],
            },
            "properties": properties,
        }
        obj = GeoOverlay(
            project_id=project_id,
            name=name,
            kind=kind,
            geojson={"type": "FeatureCollection", "features": [feature]},
            style=style or {},
            is_visible=True,
            source_event_id=event_id,
            metadata_={
                "created_from": properties.get("source_event", "unknown"),
            },
        )
        await repo.create(obj)
        await session.commit()
        return obj.id


async def _on_safety_incident_created(event: Event) -> dict[str, Any]:
    """``safety.incident.created`` -> drop an incident marker."""
    payload = event.data or {}
    project_id = _coerce_uuid(payload.get("project_id"))
    incident_id = payload.get("incident_id") or payload.get("id") or event.id
    lat = payload.get("lat")
    lon = payload.get("lon")
    if project_id is None or lat is None or lon is None:
        return {"status": "ignored", "reason": "missing project / lat / lon"}

    try:
        ovid = await _persist_marker_overlay(
            project_id,
            f"incident:{incident_id}",
            kind="incident",
            name=payload.get("title") or f"Incident {incident_id}",
            lat=_coerce_decimal(lat),
            lon=_coerce_decimal(lon),
            properties={
                "source_event": "safety.incident.created",
                "incident_id": str(incident_id),
                "severity": payload.get("severity", "medium"),
                "category": payload.get("category", ""),
            },
            style={"iconColor": "#FFB400", "iconSize": 26, "label": "Safety"},
        )
        return (
            {"status": "ok", "overlay_id": str(ovid)}
            if ovid
            else {
                "status": "ignored",
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("geo_hub._on_safety_incident_created: %s", exc)
        await _fan_out_failure(
            "_on_safety_incident_created",
            event.name,
            exc,
        )
        return {"status": "error", "error": str(exc)}


#: Pin colour by NCR severity, so a map of a project reads at a glance.
#: Anything unrecognised falls back to the "major" tone rather than being
#: dropped - an unknown severity is still a non-conformity worth seeing.
_NCR_SEVERITY_COLOURS: dict[str, str] = {
    "critical": "#B00020",
    "major": "#E2571E",
    "minor": "#F2A93B",
    "observation": "#7A8B99",
}


async def _ncr_exists(ncr_id: str) -> bool:
    """True when the NCR the event describes is committed and visible.

    This is a regression detector, NOT a gate. ``ncr.created`` is published
    from an ``after_commit`` hook, so by the time this subscriber runs the
    row must be durable; if it is not, the ordering guarantee has broken
    somewhere and that is worth a warning in the log. The pin is written
    either way - the event payload carries everything needed to draw it, so
    refusing to draw would trade a rare stale marker for a routine missing
    one, which is the worse failure of the two.
    """
    from app.modules.ncr.models import NCR

    parsed = _coerce_uuid(ncr_id)
    if parsed is None:
        return False
    async with async_session_factory() as session:
        return await session.get(NCR, parsed) is not None


async def _on_ncr_created(event: Event) -> dict[str, Any]:
    """``ncr.created`` -> drop a pin where the non-conformity was found.

    An NCR without coordinates is the ordinary case, not an error: most are
    raised from a desk against a drawing. Those are skipped quietly. An NCR
    that carries a position gets a marker so "an inspector flags a
    non-conformity and it appears on the map" is literally true.

    The coordinates come out of the event payload, never out of a read of
    ``oe_ncr_ncr``. That is deliberate: this subscriber runs in its own
    session with no view of the publisher's transaction, so a payload that
    only carried an id would make the pin depend on commit timing.
    """
    payload = event.data or {}
    project_id = _coerce_uuid(payload.get("project_id"))
    ncr_id = payload.get("ncr_id") or payload.get("id") or event.id
    lat = payload.get("lat")
    lon = payload.get("lon")
    if project_id is None:
        # An NCR always belongs to a project, so a payload without one is a
        # malformed publish rather than a normal skip. Say so out loud.
        logger.warning(
            "geo_hub._on_ncr_created: ncr.created carried no project_id (ncr_id=%s)",
            ncr_id,
        )
        return {"status": "ignored", "reason": "missing project_id"}
    if lat is None or lon is None:
        return {"status": "ignored", "reason": "no location recorded"}

    severity = str(payload.get("severity") or "major")
    try:
        if not await _ncr_exists(str(ncr_id)):
            logger.warning(
                "geo_hub._on_ncr_created: NCR %s is not visible yet - pinning anyway, "
                "but ncr.created should be published after its transaction commits",
                ncr_id,
            )
        ovid = await _persist_marker_overlay(
            project_id,
            f"ncr:{ncr_id}",
            kind="ncr",
            name=payload.get("title") or f"NCR {payload.get('ncr_number') or ncr_id}",
            lat=_coerce_decimal(lat),
            lon=_coerce_decimal(lon),
            properties={
                "source_event": "ncr.created",
                "ncr_id": str(ncr_id),
                "ncr_number": payload.get("ncr_number", ""),
                "severity": severity,
                "ncr_type": payload.get("ncr_type", ""),
                "status": payload.get("status", ""),
                "location_description": payload.get("location_description") or "",
                "accuracy_m": payload.get("accuracy_m"),
            },
            style={
                "iconColor": _NCR_SEVERITY_COLOURS.get(severity, _NCR_SEVERITY_COLOURS["major"]),
                "iconSize": 26,
                "label": "NCR",
            },
        )
        return {"status": "ok", "overlay_id": str(ovid)} if ovid else {"status": "ignored"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("geo_hub._on_ncr_created: %s", exc)
        await _fan_out_failure("_on_ncr_created", event.name, exc)
        return {"status": "error", "error": str(exc)}


# ── Registration ────────────────────────────────────────────────────────


_SUBSCRIPTIONS: tuple[tuple[str, Any], ...] = (
    ("projects.address_set", _on_project_address_set),
    ("safety.incident.created", _on_safety_incident_created),
    ("ncr.created", _on_ncr_created),
)


def register_subscribers() -> None:
    """Wire the cross-module subscribers. Idempotent."""
    for event_name, handler in _SUBSCRIPTIONS:
        event_bus.subscribe_once(event_name, handler)
    logger.info("geo_hub: %d cross-module subscribers registered", len(_SUBSCRIPTIONS))


__all__ = [
    "register_subscribers",
]
