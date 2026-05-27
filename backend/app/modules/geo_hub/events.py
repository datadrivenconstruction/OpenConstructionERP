# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Geo Hub event registry.

This module owns the ten cross-module subscribers that auto-populate
the geo dashboard whenever other modules emit domain events. Each
subscriber:

* validates the event payload shape (best-effort, never raises)
* is idempotent — replays do not double-create rows
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
    property_dev.development.geo_placed  (fan-out)
                                    {development_id, project_id, lat, lon}

Inbound (we subscribe to)::

    projects.created               -> auto-create empty anchor
    projects.address_set           -> auto-geocode address -> anchor
    bim_hub.model.uploaded         -> enqueue tile build
    bim_hub.federation.created     -> enqueue federation tile build
    property_dev.development.created   -> place development on map
    carbon.footprint.computed      -> stamp carbon tint on Tileset
    schedule.task.scheduled        -> stamp 4D dates on Tileset
    clash.detected                 -> persist clash marker overlay
    field_reports.submitted        -> add geo-referenced photo overlay
    safety.incident.created        -> persist incident marker overlay
    risk.zone.flagged              -> persist risk zone overlay
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.core.events import Event, event_bus
from app.database import async_session_factory

logger = logging.getLogger(__name__)

_SUBSCRIBED_FLAG = "_geo_hub_subscribers_registered"


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
    """Best-effort error fanout — never raises itself."""
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
    except Exception:  # noqa: BLE001 — never let the recovery path crash
        logger.exception("geo_hub failure-fanout itself failed")


# ── Subscribers ─────────────────────────────────────────────────────────


async def _on_project_created(event: Event) -> dict[str, Any]:
    """``projects.created`` -> create an empty anchor for the project.

    The user hasn't told us where the project actually is yet; we
    seed an anchor with lat=0 / lon=0 / epsg=4326 so the frontend has
    a row to patch instead of a 404. Idempotent on replay.
    """
    from app.modules.geo_hub.models import GeoAnchor
    from app.modules.geo_hub.repository import GeoAnchorRepository

    payload = event.data or {}
    project_id = _coerce_uuid(payload.get("project_id") or payload.get("id"))
    if project_id is None:
        return {"status": "ignored", "reason": "no project_id"}
    try:
        async with async_session_factory() as session:
            repo = GeoAnchorRepository(session)
            existing = await repo.get_by_project(project_id)
            if existing is not None:
                return {"status": "ignored", "reason": "anchor already exists"}
            obj = GeoAnchor(
                project_id=project_id,
                lat=Decimal("0"),
                lon=Decimal("0"),
                alt=Decimal("0"),
                epsg_code=4326,
                metadata_={"created_from": "projects.created"},
            )
            await repo.create(obj)
            await session.commit()
            return {"status": "ok", "anchor_id": str(obj.id)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("geo_hub._on_project_created: %s", exc)
        await _fan_out_failure(
            "_on_project_created",
            event.name,
            exc,
        )
        return {"status": "error", "error": str(exc)}


async def _on_project_address_set(event: Event) -> dict[str, Any]:
    """``projects.address_set`` -> auto-geocode + drop an anchor.

    Listens for the address-changed event the projects module fires from
    both ``create_project`` and ``update_project`` whenever the address
    JSONB carries at least a country. Runs the Nominatim geocoder, then:

    * Skips silently when the project already has a non-placeholder
      anchor (lat / lon != 0,0) — manual anchors win over auto ones.
    * Overwrites the placeholder anchor that ``_on_project_created``
      seeds with lat=0 / lon=0 (so the user's first proper address fill
      flips the globe pin to the right spot without UI ceremony).
    * Creates a fresh anchor when none exists.

    All failures land in the failure-fanout — the producing module's
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
    # as ``RuntimeError: await wasn't used with future`` — caught below
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
    """Inner body of ``_on_project_address_set`` — opens a session, geocodes,
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
                # Manual anchor present — don't clobber.
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
            merged_meta = {**(existing.metadata_ or {}), **geo_meta}
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


async def _on_bim_model_uploaded(event: Event) -> dict[str, Any]:
    """``bim_hub.model.uploaded`` -> queue a tile-generation job."""
    from app.modules.geo_hub.models import TileGenerationJob
    from app.modules.geo_hub.repository import TileJobRepository, TilesetRepository

    payload = event.data or {}
    project_id = _coerce_uuid(payload.get("project_id"))
    source_id = _coerce_uuid(payload.get("model_id") or payload.get("id"))
    if project_id is None or source_id is None:
        return {"status": "ignored", "reason": "missing project_id or model_id"}

    try:
        async with async_session_factory() as session:
            ts_repo = TilesetRepository(session)
            existing = await ts_repo.find_for_source("bim_model", source_id)
            if existing is not None and existing.status == "ready":
                return {
                    "status": "ignored",
                    "reason": "tileset already ready",
                    "tileset_id": str(existing.id),
                }
            job_repo = TileJobRepository(session)
            obj = TileGenerationJob(
                tileset_id=None,
                project_id=project_id,
                source_kind="bim_model",
                source_id=source_id,
                state="queued",
                progress_pct=0,
                metadata_={"created_from": "bim_hub.model.uploaded"},
            )
            await job_repo.create(obj)
            await session.commit()
            return {"status": "ok", "job_id": str(obj.id)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("geo_hub._on_bim_model_uploaded: %s", exc)
        await _fan_out_failure("_on_bim_model_uploaded", event.name, exc)
        return {"status": "error", "error": str(exc)}


async def _on_bim_federation_created(event: Event) -> dict[str, Any]:
    """``bim_hub.federation.created`` -> queue federated tile build."""
    from app.modules.geo_hub.models import TileGenerationJob
    from app.modules.geo_hub.repository import TileJobRepository, TilesetRepository

    payload = event.data or {}
    project_id = _coerce_uuid(payload.get("project_id"))
    source_id = _coerce_uuid(
        payload.get("federation_id") or payload.get("id"),
    )
    if project_id is None or source_id is None:
        return {"status": "ignored", "reason": "missing project_id or federation_id"}

    try:
        async with async_session_factory() as session:
            ts_repo = TilesetRepository(session)
            existing = await ts_repo.find_for_source("federation", source_id)
            if existing is not None and existing.status == "ready":
                return {"status": "ignored", "reason": "tileset already ready"}
            obj = TileGenerationJob(
                project_id=project_id,
                source_kind="federation",
                source_id=source_id,
                state="queued",
                progress_pct=0,
                metadata_={"created_from": "bim_hub.federation.created"},
            )
            await TileJobRepository(session).create(obj)
            await session.commit()
            return {"status": "ok", "job_id": str(obj.id)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("geo_hub._on_bim_federation_created: %s", exc)
        await _fan_out_failure(
            "_on_bim_federation_created",
            event.name,
            exc,
        )
        return {"status": "error", "error": str(exc)}


async def _on_property_dev_development_created(
    event: Event,
) -> dict[str, Any]:
    """``property_dev.development.created`` -> place dev on the map.

    When the Development carries explicit ``lat`` / ``lon`` in its
    payload (e.g. geocoded street address), write them into the
    project's anchor and emit ``property_dev.development.geo_placed``
    downstream so any module that wants to react can.
    """
    from app.modules.geo_hub.models import GeoAnchor
    from app.modules.geo_hub.repository import GeoAnchorRepository

    payload = event.data or {}
    project_id = _coerce_uuid(payload.get("project_id"))
    dev_id = _coerce_uuid(payload.get("development_id") or payload.get("id"))
    if project_id is None or dev_id is None:
        return {"status": "ignored", "reason": "missing project_id or development_id"}
    lat = payload.get("lat")
    lon = payload.get("lon")
    if lat is None or lon is None:
        # Nothing to geocode; the development just exists logically.
        return {"status": "ignored", "reason": "no lat/lon in payload"}

    try:
        lat_dec = _coerce_decimal(lat)
        lon_dec = _coerce_decimal(lon)
        async with async_session_factory() as session:
            repo = GeoAnchorRepository(session)
            existing = await repo.get_by_project(project_id)
            if existing is None:
                obj = GeoAnchor(
                    project_id=project_id,
                    lat=lat_dec,
                    lon=lon_dec,
                    alt=Decimal("0"),
                    epsg_code=4326,
                    metadata_={
                        "created_from": "property_dev.development.created",
                        "development_id": str(dev_id),
                    },
                )
                await repo.create(obj)
                anchor_id = obj.id
            else:
                await repo.update_fields(
                    existing.id,
                    lat=lat_dec,
                    lon=lon_dec,
                    metadata_={
                        **(existing.metadata_ or {}),
                        "development_id": str(dev_id),
                        "updated_from": "property_dev.development.created",
                    },
                )
                anchor_id = existing.id
            await session.commit()
        await event_bus.publish(
            "property_dev.development.geo_placed",
            {
                "development_id": str(dev_id),
                "project_id": str(project_id),
                "lat": str(lat_dec),
                "lon": str(lon_dec),
                "anchor_id": str(anchor_id),
            },
            source_module="geo_hub",
        )
        return {"status": "ok", "anchor_id": str(anchor_id)}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "geo_hub._on_property_dev_development_created: %s",
            exc,
        )
        await _fan_out_failure(
            "_on_property_dev_development_created",
            event.name,
            exc,
        )
        return {"status": "error", "error": str(exc)}


async def _on_carbon_footprint_computed(event: Event) -> dict[str, Any]:
    """``carbon.footprint.computed`` -> stash carbon tint on Tileset.metadata.

    The frontend reads ``Tileset.metadata.carbon_tint`` to colour the
    rendered tile by per-element carbon intensity. We don't materialise
    a new texture — just persist the per-element rgba so the Cesium
    viewer can drive ``Cesium3DTileStyle``.
    """
    from app.modules.geo_hub.repository import TilesetRepository

    payload = event.data or {}
    project_id = _coerce_uuid(payload.get("project_id"))
    source_kind = (payload.get("source_kind") or "bim_model").lower()
    source_id = _coerce_uuid(payload.get("source_id") or payload.get("model_id"))
    tint = payload.get("tint") or payload.get("carbon_tint")
    if project_id is None or source_id is None or tint is None:
        return {"status": "ignored", "reason": "missing project_id / source_id / tint"}

    try:
        async with async_session_factory() as session:
            ts_repo = TilesetRepository(session)
            tileset = await ts_repo.find_for_source(source_kind, source_id)
            if tileset is None:
                return {"status": "ignored", "reason": "no matching tileset"}
            md = dict(tileset.metadata_ or {})
            md["carbon_tint"] = tint
            md["carbon_computed_at"] = datetime.now(UTC).isoformat()
            await ts_repo.update_fields(tileset.id, metadata_=md)
            await session.commit()
            return {"status": "ok", "tileset_id": str(tileset.id)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("geo_hub._on_carbon_footprint_computed: %s", exc)
        await _fan_out_failure(
            "_on_carbon_footprint_computed",
            event.name,
            exc,
        )
        return {"status": "error", "error": str(exc)}


async def _on_schedule_task_scheduled(event: Event) -> dict[str, Any]:
    """``schedule.task.scheduled`` -> stamp 4D dates on the Tileset.

    Schedule emits {task_id, start_date, end_date, element_ids} so the
    Cesium viewer can drive timeline playback. We accumulate the
    dated-element map onto ``Tileset.metadata.temporal`` and the
    frontend reads it through the map-config bundle.
    """
    from app.modules.geo_hub.repository import TilesetRepository

    payload = event.data or {}
    project_id = _coerce_uuid(payload.get("project_id"))
    source_id = _coerce_uuid(
        payload.get("model_id") or payload.get("source_id"),
    )
    task_id = payload.get("task_id")
    start_date = payload.get("start_date") or payload.get("planned_start")
    end_date = payload.get("end_date") or payload.get("planned_end")
    element_ids = payload.get("element_ids") or []
    if project_id is None or source_id is None or not task_id:
        return {"status": "ignored", "reason": "missing project / source / task"}

    try:
        async with async_session_factory() as session:
            ts_repo = TilesetRepository(session)
            tileset = await ts_repo.find_for_source("bim_model", source_id)
            if tileset is None:
                return {"status": "ignored", "reason": "no matching tileset"}
            md = dict(tileset.metadata_ or {})
            temporal = list(md.get("temporal") or [])
            # Idempotent dedup by task_id.
            temporal = [t for t in temporal if t.get("task_id") != task_id]
            temporal.append(
                {
                    "task_id": str(task_id),
                    "start_date": start_date,
                    "end_date": end_date,
                    "element_ids": list(element_ids),
                },
            )
            md["temporal"] = temporal
            await ts_repo.update_fields(tileset.id, metadata_=md)
            await session.commit()
            return {"status": "ok", "tileset_id": str(tileset.id)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("geo_hub._on_schedule_task_scheduled: %s", exc)
        await _fan_out_failure(
            "_on_schedule_task_scheduled",
            event.name,
            exc,
        )
        return {"status": "error", "error": str(exc)}


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
    """Shared helper for the four "drop a pin"-style subscribers."""
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


async def _on_clash_detected(event: Event) -> dict[str, Any]:
    """``clash.detected`` -> persist a clash marker overlay."""
    payload = event.data or {}
    project_id = _coerce_uuid(payload.get("project_id"))
    clash_id = payload.get("clash_id") or event.id
    lat = payload.get("lat")
    lon = payload.get("lon")
    if project_id is None or lat is None or lon is None:
        return {"status": "ignored", "reason": "missing project / lat / lon"}

    try:
        ovid = await _persist_marker_overlay(
            project_id,
            f"clash:{clash_id}",
            kind="clash_marker",
            name=f"Clash {clash_id}",
            lat=_coerce_decimal(lat),
            lon=_coerce_decimal(lon),
            properties={
                "source_event": "clash.detected",
                "clash_id": str(clash_id),
                "severity": payload.get("severity", "medium"),
                "elements": payload.get("elements", []),
            },
            style={
                "iconColor": "#FF3D5A",
                "iconSize": 28,
                "label": "Clash",
            },
        )
        return (
            {"status": "ok", "overlay_id": str(ovid)}
            if ovid
            else {
                "status": "ignored",
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("geo_hub._on_clash_detected: %s", exc)
        await _fan_out_failure("_on_clash_detected", event.name, exc)
        return {"status": "error", "error": str(exc)}


async def _on_field_report_submitted(event: Event) -> dict[str, Any]:
    """``field_reports.submitted`` -> geo-reference the photo overlay."""
    payload = event.data or {}
    project_id = _coerce_uuid(payload.get("project_id"))
    report_id = payload.get("report_id") or payload.get("id") or event.id
    lat = payload.get("lat") or payload.get("gps_lat")
    lon = payload.get("lon") or payload.get("gps_lon")
    if project_id is None or lat is None or lon is None:
        return {"status": "ignored", "reason": "missing project / GPS"}

    try:
        ovid = await _persist_marker_overlay(
            project_id,
            f"field_report:{report_id}",
            kind="field_report",
            name=payload.get("title", "Field report"),
            lat=_coerce_decimal(lat),
            lon=_coerce_decimal(lon),
            properties={
                "source_event": "field_reports.submitted",
                "report_id": str(report_id),
                "thumbnail_url": payload.get("thumbnail_url", ""),
                "taken_at": payload.get("taken_at"),
            },
            style={"iconColor": "#3D7BFF", "iconSize": 22},
        )
        return (
            {"status": "ok", "overlay_id": str(ovid)}
            if ovid
            else {
                "status": "ignored",
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("geo_hub._on_field_report_submitted: %s", exc)
        await _fan_out_failure(
            "_on_field_report_submitted",
            event.name,
            exc,
        )
        return {"status": "error", "error": str(exc)}


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


async def _on_risk_zone_flagged(event: Event) -> dict[str, Any]:
    """``risk.zone.flagged`` -> add a polygon overlay for the risk zone."""
    from app.modules.geo_hub.models import GeoOverlay
    from app.modules.geo_hub.repository import GeoOverlayRepository

    payload = event.data or {}
    project_id = _coerce_uuid(payload.get("project_id"))
    zone_id = payload.get("zone_id") or payload.get("id") or event.id
    polygon = payload.get("polygon") or payload.get("geojson")
    if project_id is None or polygon is None:
        return {"status": "ignored", "reason": "missing project / polygon"}

    event_id = f"risk_zone:{zone_id}"
    try:
        async with async_session_factory() as session:
            repo = GeoOverlayRepository(session)
            existing = await repo.find_by_event(event_id)
            if existing is not None:
                return {"status": "ok", "overlay_id": str(existing.id)}
            if isinstance(polygon, dict) and polygon.get("type") == "Feature":
                features = [polygon]
            elif isinstance(polygon, dict) and polygon.get("type") == "FeatureCollection":
                features = list(polygon.get("features") or [])
            else:
                features = [
                    {
                        "type": "Feature",
                        "geometry": polygon,
                        "properties": {
                            "source_event": "risk.zone.flagged",
                            "zone_id": str(zone_id),
                            "risk_category": payload.get("risk_category", ""),
                        },
                    },
                ]
            obj = GeoOverlay(
                project_id=project_id,
                name=payload.get("name") or f"Risk zone {zone_id}",
                kind=(payload.get("kind") if payload.get("kind") in {"flood_zone", "risk_zone"} else "risk_zone"),
                geojson={"type": "FeatureCollection", "features": features},
                style={
                    "fillColor": "#A8001B",
                    "fillOpacity": 0.30,
                    "outlineColor": "#7F0014",
                },
                is_visible=True,
                source_event_id=event_id,
                metadata_={
                    "created_from": "risk.zone.flagged",
                    "zone_id": str(zone_id),
                },
            )
            await repo.create(obj)
            await session.commit()
            return {"status": "ok", "overlay_id": str(obj.id)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("geo_hub._on_risk_zone_flagged: %s", exc)
        await _fan_out_failure("_on_risk_zone_flagged", event.name, exc)
        return {"status": "error", "error": str(exc)}


# ── Registration ────────────────────────────────────────────────────────


_SUBSCRIPTIONS: tuple[tuple[str, Any], ...] = (
    ("projects.created", _on_project_created),
    ("projects.address_set", _on_project_address_set),
    ("bim_hub.model.uploaded", _on_bim_model_uploaded),
    ("bim_hub.federation.created", _on_bim_federation_created),
    ("property_dev.development.created", _on_property_dev_development_created),
    ("carbon.footprint.computed", _on_carbon_footprint_computed),
    ("schedule.task.scheduled", _on_schedule_task_scheduled),
    ("clash.detected", _on_clash_detected),
    ("field_reports.submitted", _on_field_report_submitted),
    ("safety.incident.created", _on_safety_incident_created),
    ("risk.zone.flagged", _on_risk_zone_flagged),
)


def register_subscribers() -> None:
    """Wire the ten cross-module subscribers. Idempotent."""
    flag = getattr(event_bus, _SUBSCRIBED_FLAG, False)
    if flag:
        return
    for event_name, handler in _SUBSCRIPTIONS:
        event_bus.subscribe(event_name, handler)
    setattr(event_bus, _SUBSCRIBED_FLAG, True)
    logger.info("geo_hub: %d cross-module subscribers registered", len(_SUBSCRIPTIONS))


__all__ = [
    "register_subscribers",
]
