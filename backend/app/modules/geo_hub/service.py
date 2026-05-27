# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Geo Hub business logic + FSM transitions + IDOR closures."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.modules.geo_hub.geojson_io import (
    kml_looks_like_kml,
    kml_to_geojson,
    validate_geojson,
)
from app.modules.geo_hub.models import (
    GeoAnchor,
    GeoOverlay,
    GeoRasterOverlay,
    GeoViewpoint,
    ImageryLayer,
    TerrainSource,
    TileGenerationJob,
    Tileset,
)
from app.modules.geo_hub.repository import (
    GeoAnchorRepository,
    GeoOverlayRepository,
    GeoRasterOverlayRepository,
    ImageryLayerRepository,
    TerrainSourceRepository,
    TileJobRepository,
    TilesetRepository,
    ViewpointRepository,
)
from app.modules.geo_hub.schemas import (
    CanonicalToTilesetRequest,
    GeoAnchorCreate,
    GeoAnchorUpdate,
    GeoJSONImportRequest,
    GeoOverlayCreate,
    GeoOverlayUpdate,
    GeoRasterOverlayCreate,
    GeoRasterOverlayUpdate,
    ImageryLayerCreate,
    ImageryLayerUpdate,
    KMLImportRequest,
    TerrainSourceCreate,
    TerrainSourceUpdate,
    TileGenerateRequest,
    TilesetCreate,
    TilesetUpdate,
    ViewpointCreate,
    ViewpointUpdate,
)
from app.modules.geo_hub.tile_pipeline import (
    build_tile_artifacts,
    upload_artifacts,
)

logger = logging.getLogger(__name__)


# ── FSMs ────────────────────────────────────────────────────────────────


# TileGenerationJob state transitions. ``queued -> running`` is the
# only forward path that exposes ``cancelled`` as a side-exit so a
# user can abort a long-running tile build.
_JOB_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"running", "cancelled", "failed"},
    "running": {"completed", "failed", "cancelled"},
    "completed": set(),
    "failed": {"queued"},  # allow retry
    "cancelled": {"queued"},  # allow restart
}


def _validate_job_transition(current: str, target: str) -> None:
    allowed = _JOB_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"Invalid TileGenerationJob transition {current!r} -> {target!r}. Allowed: {sorted(allowed)}"),
        )


# Tileset lifecycle — mirrors the job FSM in the obvious way.
_TILESET_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"generating", "obsolete"},
    "generating": {"ready", "failed", "obsolete"},
    "ready": {"obsolete", "generating"},
    "failed": {"draft", "obsolete"},
    "obsolete": set(),
}


def _validate_tileset_transition(current: str, target: str) -> None:
    allowed = _TILESET_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"Invalid Tileset transition {current!r} -> {target!r}. Allowed: {sorted(allowed)}"),
        )


# ── Helpers ─────────────────────────────────────────────────────────────


def _dump(model: Any) -> dict[str, Any]:
    """``model.model_dump(exclude_unset=True)`` with ``metadata`` -> ``metadata_``."""
    if model is None:
        return {}
    data = model.model_dump(exclude_unset=True)
    if "metadata" in data:
        data["metadata_"] = data.pop("metadata")
    return data


# ── Service ─────────────────────────────────────────────────────────────


class GeoHubService:
    """Business logic + workflow orchestration."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.anchors = GeoAnchorRepository(session)
        self.tilesets = TilesetRepository(session)
        self.imagery = ImageryLayerRepository(session)
        self.terrain = TerrainSourceRepository(session)
        self.viewpoints = ViewpointRepository(session)
        self.overlays = GeoOverlayRepository(session)
        self.raster_overlays = GeoRasterOverlayRepository(session)
        self.jobs = TileJobRepository(session)

    # ── IDOR helper ─────────────────────────────────────────────────────

    async def _verify_project_owner(
        self,
        project_id: uuid.UUID,
        payload: dict[str, Any] | None,
        *,
        not_found_detail: str = "Not found",
    ) -> None:
        """404 (not 403) cross-tenant accesses.

        Admins bypass. Anonymous callers (no payload) raise 404 so this
        helper composes with ``RequirePermission`` without leaking.
        Resolves project -> owner_id; on mismatch we collapse the
        response to "not found" so the endpoint cannot be turned into
        a UUID-existence oracle.
        """
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=not_found_detail,
            )
        if payload.get("role") == "admin":
            return
        user_id = payload.get("sub") or payload.get("user_id")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=not_found_detail,
            )
        from app.modules.projects.repository import ProjectRepository

        project = await ProjectRepository(self.session).get_by_id(project_id)
        if project is None or str(project.owner_id) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=not_found_detail,
            )

    # ── Auto-anchor from address ────────────────────────────────────────

    async def anchor_from_address(
        self,
        project_id: uuid.UUID,
        *,
        payload: dict[str, Any] | None = None,
        force: bool = False,
    ) -> tuple[GeoAnchor, str, str, str]:
        """Resolve ``project.address`` -> ``GeoAnchor``.

        Returns ``(anchor, precision, source, display_name)``.

        Raises ``HTTPException`` with explicit status codes:

        * 404 — project not found or cross-tenant access.
        * 409 — anchor already exists and ``force`` is False.
        * 422 — project address missing or has no country.
        * 502 — geocoder unavailable + no cached fallback.
        """
        from app.modules.geo_hub.geocoder import (
            geocode_address,
            project_address_from_jsonb,
        )
        from app.modules.projects.repository import ProjectRepository

        await self._verify_project_owner(
            project_id,
            payload,
            not_found_detail=translate(
                "errors.project_not_found",
                locale=get_locale(),
            ),
        )
        project = await ProjectRepository(self.session).get_by_id(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate(
                    "errors.project_not_found",
                    locale=get_locale(),
                ),
            )

        existing = await self.anchors.get_by_project(project_id)
        if existing is not None and not force:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "anchor_exists",
                    "message": "Project already has an anchor",
                    "anchor_id": str(existing.id),
                },
            )

        address = project_address_from_jsonb(project.address)
        if address is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "address_missing",
                    "message": (
                        "Project address is empty or missing a country — "
                        "fill in at least the country before auto-anchoring."
                    ),
                },
            )

        result = await geocode_address(address, session=self.session)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "geocoder_unavailable",
                    "message": ("Geocoder did not return a usable result. Try again later or anchor manually."),
                },
            )

        address_line = ", ".join(
            part
            for part in (
                address.street,
                address.house_number,
                address.postal_code,
                address.city,
                address.country,
            )
            if part
        )

        if existing is not None:
            # Overwrite in place (force=True path).
            existing.lat = result.lat
            existing.lon = result.lon
            existing.epsg_code = 4326
            existing.address = address_line or existing.address
            metadata = dict(existing.metadata_ or {})
            metadata.update(
                {
                    "geocoded_from": "project_address",
                    "geocode_precision": result.precision,
                    "geocode_source": result.source,
                    "geocode_display_name": result.display_name,
                    "geocoded_at": datetime.now(UTC).isoformat(),
                },
            )
            existing.metadata_ = metadata
            await self.session.flush()
            await self.session.refresh(existing)
            anchor = existing
        else:
            anchor = GeoAnchor(
                project_id=project_id,
                lat=result.lat,
                lon=result.lon,
                alt=Decimal("0"),
                epsg_code=4326,
                address=address_line or None,
                metadata_={
                    "geocoded_from": "project_address",
                    "geocode_precision": result.precision,
                    "geocode_source": result.source,
                    "geocode_display_name": result.display_name,
                    "geocoded_at": datetime.now(UTC).isoformat(),
                },
            )
            anchor = await self.anchors.create(anchor)

        await event_bus.publish(
            "geo_hub.anchor.auto_geocoded",
            {
                "anchor_id": str(anchor.id),
                "project_id": str(project_id),
                "lat": str(result.lat),
                "lon": str(result.lon),
                "precision": result.precision,
                "source": result.source,
            },
            source_module="geo_hub",
        )
        return anchor, result.precision, result.source, result.display_name

    async def bulk_anchor_from_address(
        self,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Auto-anchor every accessible project that lacks an anchor.

        Iterates the caller's projects (admins see every non-archived
        project, regular users see only their own), skips ones that
        already have an anchor or have no address, and runs the same
        geocode-and-persist flow per project. Returns a structured
        summary the UI can render as a toast / progress card.
        """
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        from sqlalchemy import select

        from app.modules.projects.models import Project

        is_admin = payload.get("role") == "admin"
        user_id = payload.get("sub") or payload.get("user_id")
        if user_id is None and not is_admin:
            return {
                "succeeded": 0,
                "skipped": 0,
                "failed": 0,
                "results": [],
            }

        stmt = select(Project).where(Project.status != "archived").where(Project.address.is_not(None))
        if not is_admin:
            stmt = stmt.where(Project.owner_id == user_id)
        # Hard cap so a runaway admin doesn't pin Nominatim for hours;
        # callers can re-run if they need more.
        stmt = stmt.limit(200)
        rows = (await self.session.execute(stmt)).scalars().all()

        results: list[dict[str, Any]] = []
        succeeded = skipped = failed = 0
        for project in rows:
            existing = await self.anchors.get_by_project(project.id)
            # Treat (0, 0) placeholder anchors (created by the
            # ``projects.created`` subscriber before the user filled in
            # an address) as "no real anchor" so the bulk sweep actually
            # geocodes them. Otherwise the first bulk run after a fresh
            # ``project.created`` event silently skips every project.
            is_placeholder = bool(
                existing is not None and existing.lat == Decimal("0") and existing.lon == Decimal("0")
            )
            if existing is not None and not is_placeholder:
                skipped += 1
                results.append(
                    {
                        "project_id": project.id,
                        "project_name": project.name,
                        "status": "skipped",
                        "reason": "anchor_exists",
                        "anchor_id": existing.id,
                        "precision": None,
                    },
                )
                continue
            try:
                anchor, precision, source, _display = await self.anchor_from_address(
                    project.id,
                    payload=payload,
                    force=is_placeholder,
                )
            except HTTPException as exc:
                # Re-classify common no-op outcomes as "skipped" instead
                # of "failed" so the UI doesn't scream about an address
                # that simply hasn't been filled in yet.
                detail = exc.detail if isinstance(exc.detail, dict) else {}
                code = detail.get("code") if isinstance(detail, dict) else None
                if exc.status_code in (422,):
                    skipped += 1
                    results.append(
                        {
                            "project_id": project.id,
                            "project_name": project.name,
                            "status": "skipped",
                            "reason": code or "address_missing",
                            "anchor_id": None,
                            "precision": None,
                        },
                    )
                    continue
                failed += 1
                results.append(
                    {
                        "project_id": project.id,
                        "project_name": project.name,
                        "status": "failed",
                        "reason": code or "error",
                        "anchor_id": None,
                        "precision": None,
                    },
                )
                continue
            succeeded += 1
            results.append(
                {
                    "project_id": project.id,
                    "project_name": project.name,
                    "status": "ok",
                    "reason": None,
                    "anchor_id": anchor.id,
                    "precision": precision,
                },
            )
            _ = source  # silence lint — surfaced per-project in events only
        return {
            "succeeded": succeeded,
            "skipped": skipped,
            "failed": failed,
            "results": results,
        }

    # ── GeoAnchor ────────────────────────────────────────────────────────

    async def create_anchor(
        self,
        data: GeoAnchorCreate,
        payload: dict[str, Any] | None = None,
    ) -> GeoAnchor:
        await self._verify_project_owner(
            data.project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        existing = await self.anchors.get_by_project(data.project_id)
        if existing is not None:
            # Idempotent: project already has an anchor — overwrite in
            # place. Mutate the ORM attributes directly so we avoid the
            # ``expire_all()`` cycle in ``update_fields`` which can
            # break lazy-load attribute access in the same request.
            existing.lat = data.lat
            existing.lon = data.lon
            existing.alt = data.alt
            existing.epsg_code = data.epsg_code
            existing.region_code = data.region_code
            existing.address = data.address
            existing.accuracy_m = data.accuracy_m
            existing.metadata_ = data.metadata
            await self.session.flush()
            await self.session.refresh(existing)
            return existing
        obj = GeoAnchor(
            project_id=data.project_id,
            lat=data.lat,
            lon=data.lon,
            alt=data.alt,
            epsg_code=data.epsg_code,
            region_code=data.region_code,
            address=data.address,
            accuracy_m=data.accuracy_m,
            metadata_=data.metadata,
        )
        obj = await self.anchors.create(obj)
        await event_bus.publish(
            "geo_hub.anchor.created",
            {
                "anchor_id": str(obj.id),
                "project_id": str(obj.project_id),
                "lat": str(obj.lat),
                "lon": str(obj.lon),
            },
            source_module="geo_hub",
        )
        return obj

    async def get_anchor(self, anchor_id: uuid.UUID) -> GeoAnchor:
        obj = await self.anchors.get_by_id(anchor_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Anchor not found")
        return obj

    async def get_anchor_for_project(
        self,
        project_id: uuid.UUID,
    ) -> GeoAnchor | None:
        return await self.anchors.get_by_project(project_id)

    async def update_anchor(
        self,
        anchor_id: uuid.UUID,
        data: GeoAnchorUpdate,
        payload: dict[str, Any] | None = None,
    ) -> GeoAnchor:
        obj = await self.get_anchor(anchor_id)
        await self._verify_project_owner(
            obj.project_id,
            payload,
            not_found_detail="Anchor not found",
        )
        await self.anchors.update_fields(anchor_id, **_dump(data))
        return await self.get_anchor(anchor_id)

    async def delete_anchor(
        self,
        anchor_id: uuid.UUID,
        payload: dict[str, Any] | None = None,
    ) -> None:
        obj = await self.get_anchor(anchor_id)
        await self._verify_project_owner(
            obj.project_id,
            payload,
            not_found_detail="Anchor not found",
        )
        await self.anchors.delete(anchor_id)

    # ── Tileset ──────────────────────────────────────────────────────────

    async def create_tileset(
        self,
        data: TilesetCreate,
        payload: dict[str, Any] | None = None,
    ) -> Tileset:
        await self._verify_project_owner(
            data.project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        obj = Tileset(
            project_id=data.project_id,
            source_kind=data.source_kind,
            source_id=data.source_id,
            name=data.name,
            bucket=data.bucket,
            prefix=data.prefix,
            tileset_json_uri=data.tileset_json_uri,
            bounding_volume=data.bounding_volume,
            geometric_error=data.geometric_error,
            tile_format=data.tile_format,
            tile_count=data.tile_count,
            total_bytes=data.total_bytes,
            status=data.status,
            metadata_=data.metadata,
        )
        return await self.tilesets.create(obj)

    async def get_tileset(self, tileset_id: uuid.UUID) -> Tileset:
        obj = await self.tilesets.get_by_id(tileset_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Tileset not found")
        return obj

    async def update_tileset(
        self,
        tileset_id: uuid.UUID,
        data: TilesetUpdate,
        payload: dict[str, Any] | None = None,
    ) -> Tileset:
        obj = await self.get_tileset(tileset_id)
        await self._verify_project_owner(
            obj.project_id,
            payload,
            not_found_detail="Tileset not found",
        )
        if data.status is not None:
            _validate_tileset_transition(obj.status, data.status)
        await self.tilesets.update_fields(tileset_id, **_dump(data))
        return await self.get_tileset(tileset_id)

    async def list_tilesets_for_project(
        self,
        project_id: uuid.UUID,
        *,
        payload: dict[str, Any] | None = None,
        offset: int = 0,
        limit: int = 50,
        tileset_status: str | None = None,
    ) -> list[Tileset]:
        await self._verify_project_owner(
            project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        return await self.tilesets.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=tileset_status,
        )

    async def delete_tileset(
        self,
        tileset_id: uuid.UUID,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Delete a tileset row AND its storage artefacts.

        Pre-v5.2.9 this only removed the DB row, leaving the
        ``tilesets/{id}/tileset.json`` and ``…/tile_0.b3dm`` blobs orphaned
        forever — a slow disk leak that broke the "delete frees storage"
        contract surfaced to the user. We now sweep the per-tileset prefix
        through the storage backend before removing the row. Failures are
        logged but never abort the DB delete: a stuck blob is a sysadmin
        problem, never a reason to keep dead metadata in the user's sidebar.
        """
        obj = await self.get_tileset(tileset_id)
        await self._verify_project_owner(
            obj.project_id,
            payload,
            not_found_detail="Tileset not found",
        )
        # Storage cleanup runs first because a successful DB delete with a
        # failed blob delete leaves the user with a "lost" tileset they
        # can't see but that's still consuming bytes. Doing storage first
        # means a transient backend error surfaces as a 500 and the user
        # can retry; the row stays visible for next attempt.
        try:
            from app.core.storage import get_storage_backend

            backend = get_storage_backend()
            # ``prefix`` is the canonical layout used by ``upload_artifacts``
            # (``tilesets/{tileset_id}/*``) and ``package_canonical_as_tileset``
            # (``prefix=tilesets/{tileset_id}``). Be defensive: fall back to
            # the canonical layout when the row's ``prefix`` was never set
            # (older rows pre-v5.0.0).
            sweep_prefix = obj.prefix or f"tilesets/{tileset_id}"
            await backend.delete_prefix(sweep_prefix)
        except Exception as exc:  # noqa: BLE001 — log + continue
            logger.warning(
                "geo_hub: storage cleanup failed for tileset %s: %s",
                tileset_id,
                exc,
            )
        await self.tilesets.delete(tileset_id)
        await event_bus.publish(
            "geo_hub.tileset.deleted",
            {
                "tileset_id": str(tileset_id),
                "project_id": str(obj.project_id),
                "source_kind": obj.source_kind,
            },
            source_module="geo_hub",
        )

    # ── TileGenerationJob ────────────────────────────────────────────────

    async def enqueue_tile_generation(
        self,
        data: TileGenerateRequest,
        payload: dict[str, Any] | None = None,
    ) -> TileGenerationJob:
        await self._verify_project_owner(
            data.project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        # IDOR guard: scope the reuse lookup to the caller's project so a
        # ``(source_kind, source_id)`` pair belonging to another tenant
        # cannot be reattached to this tenant's job (which would leak
        # ``tileset_json_uri`` of the foreign tileset via ``output_uri``).
        existing = await self.tilesets.find_for_source(
            data.source_kind,
            data.source_id,
            project_id=data.project_id,
        )
        if existing is not None and existing.status == "ready" and not data.force:
            # Idempotent: hand the user back the existing tileset by
            # creating a no-op "completed" job that points at it.
            job = TileGenerationJob(
                tileset_id=existing.id,
                project_id=data.project_id,
                source_kind=data.source_kind,
                source_id=data.source_id,
                requested_by=_extract_user_id(payload),
                state="completed",
                progress_pct=100,
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                output_uri=existing.tileset_json_uri,
                metadata_={"reused": True, "tileset_id": str(existing.id)},
            )
            return await self.jobs.create(job)

        # Spin up a queued job. The actual pipeline runs detached so
        # the request returns immediately with the job id and the
        # frontend polls ``GET /jobs/{id}`` for progress.
        job = TileGenerationJob(
            tileset_id=None,
            project_id=data.project_id,
            source_kind=data.source_kind,
            source_id=data.source_id,
            requested_by=_extract_user_id(payload),
            state="queued",
            progress_pct=0,
            metadata_={"force": data.force},
        )
        job = await self.jobs.create(job)
        await event_bus.publish(
            "geo_hub.tile_job.queued",
            {
                "job_id": str(job.id),
                "project_id": str(job.project_id),
                "source_kind": job.source_kind,
                "source_id": str(job.source_id),
            },
            source_module="geo_hub",
        )
        return job

    async def cancel_tile_job(
        self,
        job_id: uuid.UUID,
        payload: dict[str, Any] | None = None,
    ) -> TileGenerationJob:
        job = await self.jobs.get_by_id(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        await self._verify_project_owner(
            job.project_id,
            payload,
            not_found_detail="Job not found",
        )
        _validate_job_transition(job.state, "cancelled")
        await self.jobs.update_fields(
            job_id,
            state="cancelled",
            completed_at=datetime.now(UTC),
        )
        return await self.jobs.get_by_id(job_id)

    async def get_job(self, job_id: uuid.UUID) -> TileGenerationJob:
        obj = await self.jobs.get_by_id(job_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return obj

    async def list_jobs_for_project(
        self,
        project_id: uuid.UUID,
        *,
        payload: dict[str, Any] | None = None,
        state: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[TileGenerationJob]:
        await self._verify_project_owner(
            project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        return await self.jobs.list_for_project(
            project_id,
            state=state,
            offset=offset,
            limit=limit,
        )

    # ── ImageryLayer ─────────────────────────────────────────────────────

    async def create_imagery_layer(
        self,
        data: ImageryLayerCreate,
        payload: dict[str, Any] | None = None,
    ) -> ImageryLayer:
        await self._verify_project_owner(
            data.project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        if data.default_for_project:
            await self.imagery.clear_default_for_project(data.project_id)
        obj = ImageryLayer(
            project_id=data.project_id,
            name=data.name,
            provider=data.provider,
            url_template=data.url_template,
            attribution=data.attribution,
            requires_api_key=data.requires_api_key,
            default_for_project=data.default_for_project,
            is_visible=data.is_visible,
            metadata_=data.metadata,
        )
        return await self.imagery.create(obj)

    async def get_imagery_layer(self, layer_id: uuid.UUID) -> ImageryLayer:
        obj = await self.imagery.get_by_id(layer_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Imagery layer not found")
        return obj

    async def update_imagery_layer(
        self,
        layer_id: uuid.UUID,
        data: ImageryLayerUpdate,
        payload: dict[str, Any] | None = None,
    ) -> ImageryLayer:
        obj = await self.get_imagery_layer(layer_id)
        await self._verify_project_owner(
            obj.project_id,
            payload,
            not_found_detail="Imagery layer not found",
        )
        if data.default_for_project is True:
            await self.imagery.clear_default_for_project(obj.project_id)
        await self.imagery.update_fields(layer_id, **_dump(data))
        return await self.get_imagery_layer(layer_id)

    async def list_imagery_for_project(
        self,
        project_id: uuid.UUID,
        payload: dict[str, Any] | None = None,
    ) -> list[ImageryLayer]:
        await self._verify_project_owner(
            project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        return await self.imagery.list_for_project(project_id)

    async def delete_imagery_layer(
        self,
        layer_id: uuid.UUID,
        payload: dict[str, Any] | None = None,
    ) -> None:
        obj = await self.get_imagery_layer(layer_id)
        await self._verify_project_owner(
            obj.project_id,
            payload,
            not_found_detail="Imagery layer not found",
        )
        await self.imagery.delete(layer_id)

    # ── TerrainSource (system-wide) ──────────────────────────────────────

    async def create_terrain_source(
        self,
        data: TerrainSourceCreate,
    ) -> TerrainSource:
        if data.is_default:
            await self.terrain.clear_default()
        obj = TerrainSource(
            name=data.name,
            provider=data.provider,
            endpoint=data.endpoint,
            ion_token=data.ion_token,
            is_default=data.is_default,
            metadata_=data.metadata,
        )
        return await self.terrain.create(obj)

    async def get_terrain_source(self, src_id: uuid.UUID) -> TerrainSource:
        obj = await self.terrain.get_by_id(src_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Terrain source not found")
        return obj

    async def update_terrain_source(
        self,
        src_id: uuid.UUID,
        data: TerrainSourceUpdate,
    ) -> TerrainSource:
        obj = await self.get_terrain_source(src_id)
        if data.is_default is True:
            await self.terrain.clear_default()
        await self.terrain.update_fields(src_id, **_dump(data))
        return await self.get_terrain_source(src_id)

    async def list_terrain_sources(self) -> list[TerrainSource]:
        return await self.terrain.list_all()

    async def delete_terrain_source(self, src_id: uuid.UUID) -> None:
        await self.get_terrain_source(src_id)
        await self.terrain.delete(src_id)

    # ── Viewpoint ────────────────────────────────────────────────────────

    async def save_viewpoint(
        self,
        data: ViewpointCreate,
        payload: dict[str, Any] | None = None,
    ) -> GeoViewpoint:
        await self._verify_project_owner(
            data.project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        obj = GeoViewpoint(
            project_id=data.project_id,
            name=data.name,
            description=data.description,
            camera_lat=data.camera_lat,
            camera_lon=data.camera_lon,
            camera_alt=data.camera_alt,
            heading=data.heading,
            pitch=data.pitch,
            roll=data.roll,
            created_by=_extract_user_id(payload),
            metadata_=data.metadata,
        )
        return await self.viewpoints.create(obj)

    async def get_viewpoint(self, vp_id: uuid.UUID) -> GeoViewpoint:
        obj = await self.viewpoints.get_by_id(vp_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Viewpoint not found")
        return obj

    async def update_viewpoint(
        self,
        vp_id: uuid.UUID,
        data: ViewpointUpdate,
        payload: dict[str, Any] | None = None,
    ) -> GeoViewpoint:
        obj = await self.get_viewpoint(vp_id)
        await self._verify_project_owner(
            obj.project_id,
            payload,
            not_found_detail="Viewpoint not found",
        )
        await self.viewpoints.update_fields(vp_id, **_dump(data))
        return await self.get_viewpoint(vp_id)

    async def list_viewpoints(
        self,
        project_id: uuid.UUID,
        payload: dict[str, Any] | None = None,
    ) -> list[GeoViewpoint]:
        await self._verify_project_owner(
            project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        return await self.viewpoints.list_for_project(project_id)

    async def delete_viewpoint(
        self,
        vp_id: uuid.UUID,
        payload: dict[str, Any] | None = None,
    ) -> None:
        obj = await self.get_viewpoint(vp_id)
        await self._verify_project_owner(
            obj.project_id,
            payload,
            not_found_detail="Viewpoint not found",
        )
        await self.viewpoints.delete(vp_id)

    # ── Overlay + GeoJSON / KML I/O ─────────────────────────────────────

    async def create_overlay(
        self,
        data: GeoOverlayCreate,
        payload: dict[str, Any] | None = None,
    ) -> GeoOverlay:
        await self._verify_project_owner(
            data.project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        if data.geojson:
            try:
                data_geojson = validate_geojson(data.geojson)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        else:
            data_geojson = {"type": "FeatureCollection", "features": []}
        obj = GeoOverlay(
            project_id=data.project_id,
            name=data.name,
            kind=data.kind,
            geojson=data_geojson,
            source_file=data.source_file,
            style=data.style,
            is_visible=data.is_visible,
            metadata_=data.metadata,
        )
        return await self.overlays.create(obj)

    async def update_overlay(
        self,
        overlay_id: uuid.UUID,
        data: GeoOverlayUpdate,
        payload: dict[str, Any] | None = None,
    ) -> GeoOverlay:
        obj = await self.overlays.get_by_id(overlay_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Overlay not found")
        await self._verify_project_owner(
            obj.project_id,
            payload,
            not_found_detail="Overlay not found",
        )
        if data.geojson is not None:
            try:
                validate_geojson(data.geojson)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        await self.overlays.update_fields(overlay_id, **_dump(data))
        return await self.overlays.get_by_id(overlay_id)

    async def import_geojson(
        self,
        req: GeoJSONImportRequest,
        payload: dict[str, Any] | None = None,
    ) -> GeoOverlay:
        await self._verify_project_owner(
            req.project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        try:
            geojson = validate_geojson(req.geojson)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        obj = GeoOverlay(
            project_id=req.project_id,
            name=req.name or "Imported GeoJSON",
            kind=req.kind,
            geojson=geojson,
            style=req.style,
            is_visible=True,
            metadata_={
                "imported_from": "geojson",
                "feature_count": len(geojson.get("features", [])),
            },
        )
        return await self.overlays.create(obj)

    async def import_kml(
        self,
        req: KMLImportRequest,
        payload: dict[str, Any] | None = None,
    ) -> GeoOverlay:
        await self._verify_project_owner(
            req.project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        # Magic-byte gate: reject obviously non-KML payloads with 415
        # before the XML parser sees them. The wrapping JSON request
        # body shields us from anything but a string here, so we just
        # need to verify it looks like XML/KML.
        if not kml_looks_like_kml(req.kml):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="kml payload does not look like KML (expected <?xml or <kml)",
            )
        try:
            geojson = kml_to_geojson(req.kml.encode("utf-8"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        obj = GeoOverlay(
            project_id=req.project_id,
            name=req.name or "Imported KML",
            kind=req.kind,
            geojson=geojson,
            style=req.style,
            is_visible=True,
            metadata_={
                "imported_from": "kml",
                "feature_count": len(geojson.get("features", [])),
            },
        )
        return await self.overlays.create(obj)

    async def list_overlays(
        self,
        project_id: uuid.UUID,
        payload: dict[str, Any] | None = None,
        *,
        kind: str | None = None,
    ) -> list[GeoOverlay]:
        await self._verify_project_owner(
            project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        return await self.overlays.list_for_project(project_id, kind=kind)

    async def export_geojson(
        self,
        project_id: uuid.UUID,
        payload: dict[str, Any] | None = None,
        *,
        kind: str | None = None,
    ) -> dict[str, Any]:
        """Merge every overlay for the project into one FeatureCollection."""
        await self._verify_project_owner(
            project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        overlays = await self.overlays.list_for_project(
            project_id,
            kind=kind,
            limit=1000,
        )
        merged_features: list[dict[str, Any]] = []
        for ov in overlays:
            data = ov.geojson or {}
            for feat in data.get("features") or []:
                merged_features.append(feat)
        return {"type": "FeatureCollection", "features": merged_features}

    async def delete_overlay(
        self,
        overlay_id: uuid.UUID,
        payload: dict[str, Any] | None = None,
    ) -> None:
        obj = await self.overlays.get_by_id(overlay_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Overlay not found")
        await self._verify_project_owner(
            obj.project_id,
            payload,
            not_found_detail="Overlay not found",
        )
        await self.overlays.delete(overlay_id)

    # ── GeoRasterOverlay (PDF / DWG / image on the globe) ──────────────

    async def list_raster_overlays(
        self,
        project_id: uuid.UUID,
        *,
        payload: dict[str, Any] | None = None,
        include_hidden: bool = True,
    ) -> list[GeoRasterOverlay]:
        await self._verify_project_owner(
            project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        return await self.raster_overlays.list_for_project(
            project_id,
            include_hidden=include_hidden,
        )

    async def get_raster_overlay(
        self,
        overlay_id: uuid.UUID,
        *,
        payload: dict[str, Any] | None = None,
    ) -> GeoRasterOverlay:
        obj = await self.raster_overlays.get_active(overlay_id)
        if obj is None:
            raise HTTPException(status_code=404, detail="Overlay not found")
        await self._verify_project_owner(
            obj.project_id,
            payload,
            not_found_detail="Overlay not found",
        )
        return obj

    async def create_raster_overlay(
        self,
        data: GeoRasterOverlayCreate,
        *,
        payload: dict[str, Any] | None = None,
    ) -> GeoRasterOverlay:
        await self._verify_project_owner(
            data.project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        corners = data.corners_geojson or await self._default_corners_for_project(
            data.project_id,
        )
        obj = GeoRasterOverlay(
            project_id=data.project_id,
            name=data.name,
            source_kind=data.source_kind,
            source_blob_url=data.source_blob_url,
            source_page=data.source_page,
            raster_blob_url=data.raster_blob_url,
            raster_width_px=data.raster_width_px,
            raster_height_px=data.raster_height_px,
            corners_geojson=corners,
            rotation_deg=data.rotation_deg,
            opacity=data.opacity,
            crop_polygon_geojson=data.crop_polygon_geojson,
            z_order=data.z_order,
            visible=data.visible,
            created_by=_extract_user_id(payload),
            metadata_=data.metadata,
        )
        return await self.raster_overlays.create(obj)

    async def update_raster_overlay(
        self,
        overlay_id: uuid.UUID,
        data: GeoRasterOverlayUpdate,
        *,
        payload: dict[str, Any] | None = None,
    ) -> GeoRasterOverlay:
        # IDOR-check by reading once before the update; ``expire_all`` in
        # ``update_fields`` would otherwise invalidate the ORM attribute
        # cache and trigger a lazy-load that explodes with ``MissingGreenlet``
        # under an async session.
        await self.get_raster_overlay(overlay_id, payload=payload)
        await self.raster_overlays.update_fields(overlay_id, **_dump(data))
        return await self.get_raster_overlay(overlay_id, payload=payload)

    async def delete_raster_overlay(
        self,
        overlay_id: uuid.UUID,
        *,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Soft-delete the overlay row.

        Storage blobs are kept on the soft-delete path so a future
        "Restore" feature can revive the overlay without re-uploading.
        Hard cleanup of orphaned blobs is handled by
        :meth:`sweep_deleted_raster_overlays` (call from a maintenance
        job or admin endpoint after a grace period).
        """
        obj = await self.get_raster_overlay(overlay_id, payload=payload)
        await self.raster_overlays.soft_delete(obj.id)

    async def sweep_deleted_raster_overlays(
        self,
        *,
        older_than_days: int = 30,
    ) -> dict[str, int]:
        """Hard-delete soft-deleted raster overlays older than the grace window.

        Sweeps the storage blobs (source + rasterised PNG) before removing
        the DB row so the disk is actually freed. Returns a summary dict
        with ``swept`` (rows removed) and ``blob_errors`` (blob deletes
        that failed — usually a "key not found" because the row was
        already partially cleaned up).

        Designed to be safe to call repeatedly: each pass picks up where
        the last left off. The grace window defaults to 30 days, matching
        the geocode cache TTL so operators have one mental model for
        soft-deleted data lifetimes across the module.
        """
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import delete as sql_delete
        from sqlalchemy import select as sql_select

        from app.modules.geo_hub.models import GeoRasterOverlay

        if older_than_days < 0:
            return {"swept": 0, "blob_errors": 0}
        cutoff = datetime.now(UTC) - timedelta(days=int(older_than_days))
        rows = (
            (
                await self.session.execute(
                    sql_select(GeoRasterOverlay)
                    .where(GeoRasterOverlay.deleted_at.is_not(None))
                    .where(GeoRasterOverlay.deleted_at < cutoff)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return {"swept": 0, "blob_errors": 0}
        from app.core.storage import get_storage_backend

        backend = get_storage_backend()
        blob_errors = 0
        ids: list[uuid.UUID] = []
        for r in rows:
            for key in (r.source_blob_url, r.raster_blob_url):
                if not key:
                    continue
                try:
                    await backend.delete(key)
                except Exception:  # noqa: BLE001 — log + continue
                    blob_errors += 1
                    logger.debug(
                        "geo_hub.sweeper: blob delete failed for key=%s",
                        key,
                    )
            ids.append(r.id)
        if ids:
            await self.session.execute(
                sql_delete(GeoRasterOverlay).where(
                    GeoRasterOverlay.id.in_(ids),
                )
            )
            await self.session.flush()
        return {"swept": len(ids), "blob_errors": blob_errors}

    async def upload_pdf_overlay(
        self,
        project_id: uuid.UUID,
        *,
        filename: str,
        content: bytes,
        page: int = 1,
        name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> tuple[GeoRasterOverlay, int]:
        """Validate the PDF, rasterise the requested page, persist overlay."""
        from app.core.file_signature import (
            SIGNATURE_BYTES_REQUIRED,
            FileSignatureMismatch,
        )
        from app.core.file_signature import require as require_signature
        from app.modules.geo_hub.raster_pipeline import pdf_to_png

        try:
            require_signature(
                content[:SIGNATURE_BYTES_REQUIRED],
                frozenset({"pdf"}),
                filename=filename,
            )
        except FileSignatureMismatch as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=str(exc),
            ) from exc

        try:
            png_bytes, w, h, page_count = pdf_to_png(content, page=page)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"PDF rasterisation failed: {exc}",
            ) from exc

        source_key, raster_key = await self._store_overlay_blobs(
            project_id=project_id,
            filename=filename,
            source_bytes=content,
            raster_bytes=png_bytes,
        )

        overlay = await self.create_raster_overlay(
            GeoRasterOverlayCreate(
                project_id=project_id,
                name=name or filename,
                source_kind="pdf",
                source_blob_url=source_key,
                source_page=page,
                raster_blob_url=raster_key,
                raster_width_px=w,
                raster_height_px=h,
                metadata={
                    "original_filename": filename,
                    "page_count": page_count,
                },
            ),
            payload=payload,
        )
        return overlay, page_count

    async def upload_image_overlay(
        self,
        project_id: uuid.UUID,
        *,
        filename: str,
        content: bytes,
        name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> GeoRasterOverlay:
        """Validate PNG/JPEG bytes, persist the image as both source + raster."""
        from app.core.file_signature import (
            SIGNATURE_BYTES_REQUIRED,
            FileSignatureMismatch,
        )
        from app.core.file_signature import require as require_signature
        from app.modules.geo_hub.raster_pipeline import image_dimensions

        try:
            require_signature(
                content[:SIGNATURE_BYTES_REQUIRED],
                frozenset({"png", "jpeg"}),
                filename=filename,
            )
        except FileSignatureMismatch as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=str(exc),
            ) from exc

        try:
            w, h = image_dimensions(content)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Image not parseable: {exc}",
            ) from exc

        # For images source == raster — store once, point both at it.
        source_key, _ = await self._store_overlay_blobs(
            project_id=project_id,
            filename=filename,
            source_bytes=content,
            raster_bytes=None,
        )
        return await self.create_raster_overlay(
            GeoRasterOverlayCreate(
                project_id=project_id,
                name=name or filename,
                source_kind="image",
                source_blob_url=source_key,
                raster_blob_url=source_key,
                raster_width_px=w,
                raster_height_px=h,
                metadata={"original_filename": filename},
            ),
            payload=payload,
        )

    async def overlay_from_dwg(
        self,
        cad_import_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
        name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> GeoRasterOverlay:
        """Rasterise an already-converted DWG (canonical JSON) and persist."""
        import json as _json

        from app.modules.bim_hub.repository import BIMModelRepository
        from app.modules.geo_hub.raster_pipeline import dwg_top_view_to_png

        bim_model = await BIMModelRepository(self.session).get(cad_import_id)
        if bim_model is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="cad_import_not_found",
            )
        resolved_project_id = project_id or bim_model.project_id
        if str(resolved_project_id) != str(bim_model.project_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="cad_import_not_found",
            )
        await self._verify_project_owner(
            resolved_project_id,
            payload,
            not_found_detail="cad_import_not_found",
        )

        canonical: dict[str, Any] = {}
        if bim_model.canonical_file_path:
            try:
                from app.core.storage import get_storage_backend

                backend = get_storage_backend()
                blob = await backend.get(bim_model.canonical_file_path)
                canonical = _json.loads(blob.decode("utf-8"))
            except (FileNotFoundError, ValueError, OSError, _json.JSONDecodeError):
                logger.warning(
                    "geo_hub: canonical_file_path unreadable for %s",
                    bim_model.id,
                )

        try:
            png_bytes, w, h = dwg_top_view_to_png(canonical)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"DWG rasterisation failed: {exc}",
            ) from exc

        # Persist the rasterised PNG only; the source remains the BIM
        # model's canonical file path (a back-reference, not a fresh
        # upload).
        source_key, raster_key = await self._store_overlay_blobs(
            project_id=resolved_project_id,
            filename=f"{bim_model.name or 'dwg'}.png",
            source_bytes=None,
            raster_bytes=png_bytes,
        )
        return await self.create_raster_overlay(
            GeoRasterOverlayCreate(
                project_id=resolved_project_id,
                name=name or bim_model.name or "DWG overlay",
                source_kind="dwg",
                source_blob_url=bim_model.canonical_file_path,
                raster_blob_url=raster_key,
                raster_width_px=w,
                raster_height_px=h,
                metadata={
                    "cad_import_id": str(cad_import_id),
                    "bim_model_name": bim_model.name or "",
                },
            ),
            payload=payload,
        )

    async def get_raster_overlay_bytes(
        self,
        overlay_id: uuid.UUID,
        *,
        payload: dict[str, Any] | None = None,
    ) -> bytes:
        """IDOR-checked PNG fetch used by ``GET …/raster.png``."""
        obj = await self.get_raster_overlay(overlay_id, payload=payload)
        if not obj.raster_blob_url:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="raster_missing",
            )
        try:
            from app.core.storage import get_storage_backend

            backend = get_storage_backend()
            return await backend.get(obj.raster_blob_url)
        except (FileNotFoundError, OSError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="raster_missing",
            ) from exc

    async def _default_corners_for_project(
        self,
        project_id: uuid.UUID,
    ) -> list[list[float]]:
        """Return a small bbox centered on the project anchor.

        ~250 m square (a rough city-block) — large enough to be visible
        on a satellite map, small enough that the user immediately sees
        they need to drag it into place. Falls back to a placeholder
        bbox near 0,0 when the project has no anchor yet.
        """
        anchor = await self.anchors.get_by_project(project_id)
        if anchor is None:
            return [
                [0.0011, 0.0011],
                [0.0011, -0.0011],
                [-0.0011, -0.0011],
                [-0.0011, 0.0011],
            ]
        lat = float(anchor.lat)
        lon = float(anchor.lon)
        # ~250 m at the equator. We let it scale-distort at high
        # latitudes because the user is expected to drag corners anyway.
        delta = 0.00225
        return [
            [lon - delta, lat + delta],
            [lon + delta, lat + delta],
            [lon + delta, lat - delta],
            [lon - delta, lat - delta],
        ]

    async def _store_overlay_blobs(
        self,
        *,
        project_id: uuid.UUID,
        filename: str,
        source_bytes: bytes | None,
        raster_bytes: bytes | None,
    ) -> tuple[str | None, str | None]:
        """Write source + raster blobs through the configured storage backend.

        Returns ``(source_key_or_None, raster_key_or_None)``. Either may
        be ``None`` when the caller did not supply that side (image
        passthrough reuses one blob for both; DWG never uploads a fresh
        source).
        """
        from app.core.storage import get_storage_backend

        backend = get_storage_backend()
        # Keys are deliberately scoped under a per-project prefix so a
        # future per-project delete sweep can take them out wholesale.
        base = f"geo_hub/overlays/{project_id}"
        safe_name = _safe_filename(filename)
        unique = uuid.uuid4().hex[:12]
        source_key: str | None = None
        raster_key: str | None = None
        if source_bytes is not None:
            source_key = f"{base}/{unique}-source-{safe_name}"
            await backend.put(source_key, source_bytes)
        if raster_bytes is not None:
            raster_key = f"{base}/{unique}-raster.png"
            await backend.put(raster_key, raster_bytes)
        return source_key, raster_key

    # ── Canonical -> 3D Tileset packaging ───────────────────────────────

    async def package_canonical_as_tileset(
        self,
        cad_import_id: uuid.UUID,
        *,
        development_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        request: CanonicalToTilesetRequest | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Tileset:
        """Convert an already-canonical BIM/CAD import into a 3D Tileset.

        Resolves the anchor (development -> project fallback) then runs
        the existing ``tile_pipeline`` end-to-end and persists a Tileset
        row pointing at the uploaded ``tileset.json``.
        """
        from app.modules.bim_hub.repository import (
            BIMElementRepository,
            BIMModelRepository,
        )

        bim_model = await BIMModelRepository(self.session).get(cad_import_id)
        if bim_model is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="cad_import_not_found",
            )

        resolved_project_id = project_id or bim_model.project_id
        if str(resolved_project_id) != str(bim_model.project_id):
            # IDOR — project mismatch collapses to 404.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="cad_import_not_found",
            )
        await self._verify_project_owner(
            resolved_project_id,
            payload,
            not_found_detail="cad_import_not_found",
        )

        if development_id is not None:
            from app.modules.property_dev.models import Development

            dev = await self.session.get(Development, development_id)
            if dev is None or str(dev.project_id) != str(resolved_project_id):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="development_not_found",
                )

        anchor = await self.anchors.get_by_project(resolved_project_id)
        if anchor is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="no_anchor_for_project",
            )

        elements = await self._load_canonical_elements_for_bim_model(
            bim_model,
            BIMElementRepository(self.session),
        )
        if not elements:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="canonical_elements_empty",
            )

        req = request or CanonicalToTilesetRequest()
        anchor_lat = float(anchor.lat)
        anchor_lon = float(anchor.lon)
        anchor_alt = float(anchor.alt)
        heading = float(req.heading_deg or Decimal("0"))

        if heading:
            # Rotate every element AABB around the *combined* footprint
            # centre, not the local origin (0, 0, 0). Canonical exports
            # are not guaranteed to be project-centred — many converters
            # use site coordinates with the origin at the surveyor's
            # benchmark which can be hundreds of metres from the
            # building. Rotating around the origin then translates the
            # whole project away from the anchor; rotating around the
            # combined centre keeps the building anchored.
            from app.modules.geo_hub.tile_pipeline import compute_aabb

            combined = compute_aabb(elements)
            if combined.is_empty():
                pivot_x = pivot_y = 0.0
            else:
                pivot_x = (combined.min_x + combined.max_x) / 2.0
                pivot_y = (combined.min_y + combined.max_y) / 2.0
            rotated = [_rotate_element(e, heading, pivot_x=pivot_x, pivot_y=pivot_y) for e in elements]
        else:
            rotated = elements

        tileset_json, b3dm_bytes, build = build_tile_artifacts(
            rotated,
            anchor_lat=anchor_lat,
            anchor_lon=anchor_lon,
            anchor_alt=anchor_alt,
        )
        # Refuse to persist a tileset that has no usable geometry — the
        # b3dm wrapper would still serialize, the region would collapse
        # to the anchor point, and Cesium would render an invisible tile.
        # That state would also poison the reuse short-circuit on the
        # next generate call. Better to fail loudly so the caller fixes
        # the upstream import.
        if build.feature_count == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="canonical_elements_have_no_geometry",
            )
        tileset_id = uuid.uuid4()
        tileset_uri, _content_uri = await upload_artifacts(
            tileset_id=tileset_id,
            tileset_json=tileset_json,
            b3dm_bytes=b3dm_bytes,
        )

        meta: dict[str, Any] = {
            "cad_import_id": str(cad_import_id),
            "anchor_id": str(anchor.id),
            "heading_deg": float(req.heading_deg or Decimal("0")),
            "feature_count": build.feature_count,
            "triangle_count": build.triangle_count,
        }
        if development_id is not None:
            meta["development_id"] = str(development_id)
        if req.tags:
            meta["tags"] = list(req.tags)

        obj = Tileset(
            id=tileset_id,
            project_id=resolved_project_id,
            source_kind="bim_model",
            source_id=cad_import_id,
            name=req.name or bim_model.name or "",
            bucket="",
            prefix=f"tilesets/{tileset_id}",
            tileset_json_uri=tileset_uri,
            bounding_volume={
                "region": tileset_json["root"]["boundingVolume"]["region"],
            },
            geometric_error=Decimal(
                str(tileset_json.get("geometricError", 0)),
            ),
            tile_format="b3dm",
            tile_count=1,
            total_bytes=len(b3dm_bytes),
            status="ready",
            generated_at=datetime.now(UTC),
            metadata_=meta,
        )
        obj = await self.tilesets.create(obj)
        await event_bus.publish(
            "geo_hub.tileset.packaged_from_canonical",
            {
                "tileset_id": str(obj.id),
                "project_id": str(resolved_project_id),
                "cad_import_id": str(cad_import_id),
                "feature_count": build.feature_count,
            },
            source_module="geo_hub",
        )
        return obj

    async def _load_canonical_elements_for_bim_model(
        self,
        bim_model: Any,
        element_repo: Any,
    ) -> list[dict[str, Any]]:
        """Resolve canonical-format elements for a BIMModel.

        Prefers the converter's emitted canonical JSON file (when
        ``canonical_file_path`` is set) and falls back to synthesising
        elements from the ``BIMElement`` rows stored in the DB.
        """
        import json as _json

        if bim_model.canonical_file_path:
            try:
                from app.core.storage import get_storage_backend

                backend = get_storage_backend()
                blob = await backend.get(bim_model.canonical_file_path)
                parsed = _json.loads(blob.decode("utf-8"))
                elems = parsed.get("elements") or []
                if isinstance(elems, list) and elems:
                    return [e for e in elems if isinstance(e, dict)]
            except (FileNotFoundError, ValueError, OSError, _json.JSONDecodeError):
                logger.warning(
                    "geo_hub: canonical_file_path unreadable for bim_model %s",
                    bim_model.id,
                )

        elements, _total = await element_repo.list_for_model(
            bim_model.id,
            offset=0,
            limit=10_000,
        )
        return [_bim_element_to_canonical(e) for e in elements]

    # ── Anchored-projects (Global map pin layer) ────────────────────────

    async def list_anchored_projects(
        self,
        payload: dict[str, Any] | None,
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Return anchored projects the caller can access.

        Powers the global Geo Hub's project-pin layer — non-admin users
        see only their own projects, admins see everything. Projects
        without a ``GeoAnchor`` are excluded so the pin layer never
        contains zero-coord placeholders. Cheap single-join query.
        """
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        from sqlalchemy import select

        from app.modules.projects.models import Project

        is_admin = payload.get("role") == "admin"
        user_id = payload.get("sub") or payload.get("user_id")
        if user_id is None and not is_admin:
            return []

        stmt = (
            select(GeoAnchor, Project)
            .join(Project, Project.id == GeoAnchor.project_id)
            .where(Project.status != "archived")
        )
        if not is_admin:
            # 404-safe scoping: non-admins only see projects they own.
            # Cast user_id through ``str`` because JWT subs can arrive as
            # either UUID or string depending on the auth path.
            stmt = stmt.where(Project.owner_id == user_id)
        stmt = stmt.order_by(Project.created_at.desc()).limit(limit)

        result = await self.session.execute(stmt)
        rows = result.all()

        def _project_address_text(addr: Any) -> str | None:
            """Render the project's JSONB address as a single line.

            Used by the frontend to detect drift between the typed
            address and the geocoded ``anchor.address`` — when the user
            edits the project address after the first geocode the two
            strings diverge and we surface a "Re-anchor" chip.
            """
            if not isinstance(addr, dict):
                return None
            parts = [
                addr.get("street"),
                addr.get("house_number") or addr.get("houseNumber"),
                addr.get("postal_code") or addr.get("postcode"),
                addr.get("city"),
                addr.get("state"),
                addr.get("country"),
            ]
            line = ", ".join(p for p in parts if isinstance(p, str) and p.strip())
            return line or None

        return [
            {
                "project_id": project.id,
                "project_name": project.name,
                "anchor_id": anchor.id,
                "lat": anchor.lat,
                "lon": anchor.lon,
                "alt": anchor.alt,
                "region_code": anchor.region_code,
                "address": anchor.address,
                "project_type": project.project_type,
                "status": project.status,
                "project_address_text": _project_address_text(project.address),
            }
            for (anchor, project) in rows
        ]

    # ── Map-config one-shot bundle ──────────────────────────────────────

    async def map_config(
        self,
        project_id: uuid.UUID,
        payload: dict[str, Any] | None = None,
        *,
        development_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Single round-trip bundle for the Cesium viewer boot path.

        When ``development_id`` is set the result is narrowed to tilesets
        and overlays linked to that development — either by stamped
        ``metadata.development_id`` (PropDev-anchored tilesets), by
        ``source_kind="development"`` with the matching ``source_id``
        (native development tilesets), or by an overlay whose
        ``metadata.development_id`` matches. Cross-development tilesets
        within the same project are hidden so the dev-scoped map doesn't
        leak unrelated buildings into the buyer's view.
        """
        await self._verify_project_owner(
            project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )

        if development_id is not None:
            # Validate the development belongs to this project — IDOR
            # closure (a malicious caller could pass a stranger's dev id
            # otherwise and have it silently filter the map to nothing).
            from app.modules.property_dev.models import Development

            dev = await self.session.get(Development, development_id)
            if dev is None or str(dev.project_id) != str(project_id):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="development_not_found",
                )

        anchor = await self.anchors.get_by_project(project_id)
        imagery = await self.imagery.list_for_project(project_id)
        terrain = await self.terrain.get_default()
        # Push dev_id filter into SQL on the tileset list so a PropDev
        # customer with many tilesets per project doesn't load 50 only to
        # throw 49 away. The overlay-side filter still happens in Python
        # because GeoOverlay.metadata is opaque JSON — but that path is
        # bounded by the 200-row hard cap and SQLite has no portable
        # JSON-extract on arbitrary metadata.development_id.
        tilesets = await self.tilesets.list_for_project(
            project_id,
            limit=50,
            development_id=(str(development_id) if development_id is not None else None),
        )
        overlays = await self.overlays.list_for_project(
            project_id,
            limit=200,
        )
        viewpoints = await self.viewpoints.list_for_project(project_id)
        active_jobs = await self.jobs.list_active_for_project(project_id)

        if development_id is not None:
            dev_str = str(development_id)

            def _ov_matches(o: Any) -> bool:
                meta = o.metadata_ or {}
                if isinstance(meta, dict):
                    val = meta.get("development_id")
                    if isinstance(val, str) and val == dev_str:
                        return True
                return False

            overlays = [o for o in overlays if _ov_matches(o)]

        return {
            "project_id": project_id,
            "anchor": anchor,
            "imagery_layers": imagery,
            "terrain_source": terrain,
            "tilesets": tilesets,
            "overlays": overlays,
            "viewpoints": viewpoints,
            "active_jobs": active_jobs,
        }

    # ── Cross-module pin layers (HSE / Punchlist / Diary photos) ────────
    #
    # These endpoints expose a thin read projection of other modules'
    # geo-tagged rows so the Cesium / Leaflet viewer can render them as
    # per-module layers. Each query is project-scoped and IDOR-gated
    # through ``_verify_project_owner`` — cross-tenant access returns 404,
    # never 403.
    #
    # We deliberately don't go through HTTP to the other modules — they
    # share the same SQLAlchemy session, and a SQL-level select is the
    # cheap path. We import the models lazily so geo_hub keeps its
    # dependency graph clean (the manifest only depends on bim_hub +
    # projects; HSE / punchlist / daily_diary are not declared dependents).

    async def list_hse_pins(
        self,
        project_id: uuid.UUID,
        payload: dict[str, Any] | None = None,
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Return geo-pinned safety incidents for the project."""
        await self._verify_project_owner(
            project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        from sqlalchemy import select

        from app.modules.safety.models import SafetyIncident

        result = await self.session.execute(
            select(SafetyIncident)
            .where(SafetyIncident.project_id == project_id)
            .where(SafetyIncident.geo_lat.is_not(None))
            .where(SafetyIncident.geo_lon.is_not(None))
            .order_by(SafetyIncident.incident_number)
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            {
                "incident_id": r.id,
                "incident_number": r.incident_number,
                "title": r.title or None,
                "incident_type": r.incident_type,
                "severity": r.severity,
                "status": r.status,
                "lat": r.geo_lat,
                "lon": r.geo_lon,
            }
            for r in rows
        ]

    async def list_punchlist_pins(
        self,
        project_id: uuid.UUID,
        payload: dict[str, Any] | None = None,
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Return geo-pinned punch list items for the project."""
        await self._verify_project_owner(
            project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        from sqlalchemy import select

        from app.modules.punchlist.models import PunchItem

        result = await self.session.execute(
            select(PunchItem)
            .where(PunchItem.project_id == project_id)
            .where(PunchItem.geo_lat.is_not(None))
            .where(PunchItem.geo_lon.is_not(None))
            .order_by(PunchItem.created_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            {
                "item_id": r.id,
                "title": r.title,
                "priority": r.priority,
                "status": r.status,
                "category": r.category,
                "lat": r.geo_lat,
                "lon": r.geo_lon,
            }
            for r in rows
        ]

    async def list_diary_photo_pins(
        self,
        project_id: uuid.UUID,
        payload: dict[str, Any] | None = None,
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Return geo-tagged Daily Diary photos for the project."""
        await self._verify_project_owner(
            project_id,
            payload,
            not_found_detail=translate("errors.project_not_found", locale=get_locale()),
        )
        from sqlalchemy import select

        from app.modules.daily_diary.models import DiaryPhoto

        result = await self.session.execute(
            select(DiaryPhoto)
            .where(DiaryPhoto.project_id == project_id)
            .where(DiaryPhoto.lat.is_not(None))
            .where(DiaryPhoto.lng.is_not(None))
            .where(DiaryPhoto.is_archived.is_(False))
            .order_by(DiaryPhoto.taken_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            {
                "photo_id": r.id,
                "diary_id": r.diary_id,
                "taken_at": r.taken_at,
                "thumbnail_url": r.thumbnail_url,
                "file_url": r.file_url,
                "is_360": r.is_360,
                "is_drone": r.is_drone,
                "lat": r.lat,
                "lon": r.lng,
            }
            for r in rows
        ]


def _bim_element_to_canonical(element: Any) -> dict[str, Any]:
    """Project a BIMElement ORM row onto the canonical-format element dict."""
    props = element.properties or {}
    quantities = element.quantities or {}
    bbox = element.bounding_box or {}
    classification: dict[str, Any] = {}
    for key in ("din276", "nrm", "masterformat", "uniclass"):
        val = props.get(key) or props.get(key.upper()) or props.get(f"classification.{key}")
        if val:
            classification[key] = val

    geometry: dict[str, Any] = {}
    if isinstance(bbox, dict):
        min_pt = bbox.get("min") or bbox.get("min_point")
        max_pt = bbox.get("max") or bbox.get("max_point")
        if (
            isinstance(min_pt, (list, tuple))
            and isinstance(max_pt, (list, tuple))
            and len(min_pt) >= 3
            and len(max_pt) >= 3
        ):
            try:
                geometry["aabb"] = [
                    float(min_pt[0]),
                    float(min_pt[1]),
                    float(min_pt[2]),
                    float(max_pt[0]),
                    float(max_pt[1]),
                    float(max_pt[2]),
                ]
            except (TypeError, ValueError):
                pass
    if "area_m2" in quantities:
        geometry["area_m2"] = quantities.get("area_m2")
    if "volume_m3" in quantities:
        geometry["volume_m3"] = quantities.get("volume_m3")
    if "length_m" in quantities:
        geometry["length_m"] = quantities.get("length_m")
    if "height_m" in quantities:
        geometry["height_m"] = quantities.get("height_m")

    return {
        "id": element.stable_id,
        "category": element.element_type or "unknown",
        "classification": classification,
        "geometry": geometry,
        "quantities": dict(quantities),
        "relations": {"level": element.storey, "discipline": element.discipline},
        "validation_status": "passed",
    }


def _rotate_element(
    element: dict[str, Any],
    heading_deg: float,
    *,
    pivot_x: float = 0.0,
    pivot_y: float = 0.0,
) -> dict[str, Any]:
    """Rotate a canonical element's AABB around the local Z (up) axis.

    Rotates the four XY corners around (``pivot_x``, ``pivot_y``) — the
    caller is expected to pass the project's combined-AABB centre so a
    site-coordinate canonical export does not drift away from its
    geographic anchor under non-zero heading. Replaces the AABB with
    the axis-aligned envelope of the rotated box so the downstream
    pipeline still sees an AABB. Loses orientation fidelity by design —
    heading is a coarse hint, not a transform.
    """
    import math as _math

    geom = element.get("geometry") or {}
    aabb = geom.get("aabb")
    if not (isinstance(aabb, list) and len(aabb) == 6):
        return element
    try:
        min_x, min_y, min_z, max_x, max_y, max_z = (float(v) for v in aabb)
    except (TypeError, ValueError):
        return element
    rad = _math.radians(heading_deg)
    cos_r = _math.cos(rad)
    sin_r = _math.sin(rad)
    # Rotate around the supplied pivot: shift -> rotate -> shift back.
    corners_xy = [
        (min_x - pivot_x, min_y - pivot_y),
        (max_x - pivot_x, min_y - pivot_y),
        (max_x - pivot_x, max_y - pivot_y),
        (min_x - pivot_x, max_y - pivot_y),
    ]
    xs = [cx * cos_r - cy * sin_r + pivot_x for cx, cy in corners_xy]
    ys = [cx * sin_r + cy * cos_r + pivot_y for cx, cy in corners_xy]
    new_geom = dict(geom)
    new_geom["aabb"] = [
        min(xs),
        min(ys),
        min_z,
        max(xs),
        max(ys),
        max_z,
    ]
    new_element = dict(element)
    new_element["geometry"] = new_geom
    return new_element


def _safe_filename(name: str) -> str:
    """Return a filename stripped of path separators + non-ASCII bytes.

    Storage keys are flat strings — backends differ wildly on what they
    accept. We allow ASCII alphanumerics, dots, dashes, underscores;
    everything else collapses to ``_``. Length is capped so a
    pathological filename can't blow past S3 key limits.
    """
    import re

    base = re.sub(r"[^A-Za-z0-9._\-]+", "_", name or "file")
    base = base.strip("._-") or "file"
    return base[:120]


def _extract_user_id(
    payload: dict[str, Any] | None,
) -> uuid.UUID | None:
    if payload is None:
        return None
    value = payload.get("sub") or payload.get("user_id")
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


__all__ = ["GeoHubService"]
