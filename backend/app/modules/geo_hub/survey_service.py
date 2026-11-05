# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Site survey captures: dated orthophotos / scans and observed progress per activity.

Thin glue on top of the raster overlay path (orthophotos), the point cloud
module (scans are only linked, never copied or deleted) and the schedule
(planned progress). A human enters every observed percentage; nothing here
infers progress from imagery.
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.i18n import get_locale
from app.modules.geo_hub import survey_logic as logic
from app.modules.geo_hub.geotiff_sniff import GeoTiffError, GeoTiffMeta, sniff_geotiff
from app.modules.geo_hub.models import SurveyCapture, SurveyObservation
from app.modules.geo_hub.raster_pipeline import MAX_RASTER_PIXELS, ImagePixelBudgetExceeded
from app.modules.geo_hub.repository import SurveyCaptureRepository, SurveyObservationRepository
from app.modules.geo_hub.schemas import (
    GeoRasterOverlayCreate,
    SurveyCaptureListResponse,
    SurveyCapturePatch,
    SurveyCaptureResponse,
    SurveyFinding,
    SurveyFromScan,
    SurveyObservationUpsert,
    SurveyProgressListResponse,
    SurveyProgressRow,
)
from app.modules.geo_hub.service import GeoHubService, _extract_user_id
from app.modules.geo_hub.validators import evaluate

logger = logging.getLogger(__name__)

# Upload ceiling for one orthophoto. The bytes are held in memory once, so this
# stays well under the 3 GB server budget; larger sites export a COG overview.
MAX_SURVEY_UPLOAD_BYTES = 256 * 1024 * 1024
PREVIEW_MAX_SIDE_PX = 4096
_TIFF_MAGIC = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")


def _http(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def _findings(results: list[Any]) -> list[SurveyFinding]:
    out = []
    for r in results:
        msg = r.message if not r.suggestion else f"{r.message} {r.suggestion}"
        out.append(SurveyFinding(rule_id=r.rule_id, severity=str(r.severity.value), message=msg))
    return out


def _render_preview(content: bytes) -> tuple[bytes, int, int]:
    """Decode once and return a PNG no larger than ``PREVIEW_MAX_SIDE_PX`` per side."""
    from PIL import Image

    with Image.open(io.BytesIO(content)) as img:
        img.load()
        if img.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
            img = img.convert("I").point(lambda v: v * (1 / 256)).convert("L")
        elif img.mode not in ("L", "RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        img.thumbnail((PREVIEW_MAX_SIDE_PX, PREVIEW_MAX_SIDE_PX), Image.Resampling.BILINEAR, reducing_gap=2.0)
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=False)
        return out.getvalue(), img.width, img.height


class SurveyService:
    """Business logic for survey captures; project access goes through the geo hub IDOR check."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.geo = GeoHubService(session)
        self.captures = SurveyCaptureRepository(session)
        self.observations = SurveyObservationRepository(session)

    # ── access ──────────────────────────────────────────────────────────

    async def _project(self, project_id: uuid.UUID, payload: dict[str, Any] | None) -> Any:
        await self.geo._verify_project_owner(project_id, payload, not_found_detail="Project not found")
        from app.modules.projects.repository import ProjectRepository

        return await ProjectRepository(self.session).get_by_id(project_id)

    async def get_capture(self, capture_id: uuid.UUID, payload: dict[str, Any] | None) -> SurveyCapture:
        obj = await self.captures.get_by_id(capture_id)
        if obj is None:
            raise _http(404, "Survey not found")
        await self.geo._verify_project_owner(obj.project_id, payload, not_found_detail="Survey not found")
        return obj

    # ── validation input ────────────────────────────────────────────────

    async def _anchor(self, project_id: uuid.UUID) -> dict[str, float] | None:
        anchor = await self.geo.anchors.get_by_project(project_id)
        if anchor is None:
            return None
        return {"lat": float(anchor.lat), "lon": float(anchor.lon)}

    @staticmethod
    def _bbox_of(cap: SurveyCapture) -> tuple[float, float, float, float] | None:
        vals = (cap.bbox_min_lon, cap.bbox_min_lat, cap.bbox_max_lon, cap.bbox_max_lat)
        return None if any(v is None for v in vals) else tuple(float(v) for v in vals)  # type: ignore[return-value]

    async def _capture_input(self, project: Any, cap: SurveyCapture, captured_on: date | None = None) -> dict[str, Any]:
        return {
            "capture": {
                "id": str(cap.id) if cap.id else None,
                "kind": cap.kind,
                "captured_on": captured_on or cap.captured_on,
                "today": datetime.now(UTC).date(),
                "project_start": project.planned_start_date,
                "project_end": project.planned_end_date,
                "crs_epsg": cap.crs_epsg,
                "bbox": self._bbox_of(cap),
                "anchor": await self._anchor(project.id),
                "gsd_cm": cap.gsd_cm,
            }
        }

    async def _findings_for(self, project: Any, cap: SurveyCapture, captured_on: date | None = None) -> list[Any]:
        data = await self._capture_input(project, cap, captured_on)
        return await evaluate(data, locale=get_locale(), target_id=str(cap.id or ""))

    @staticmethod
    def _errors(results: list[Any]) -> list[Any]:
        return [r for r in results if r.severity.value == "error"]

    def _response(self, cap: SurveyCapture, results: list[Any]) -> SurveyCaptureResponse:
        resp = SurveyCaptureResponse.model_validate(cap)
        resp.warnings = list((cap.metadata_ or {}).get("warnings") or [])
        resp.findings = _findings(results)
        return resp

    # ── create ──────────────────────────────────────────────────────────

    async def create_orthophoto(
        self,
        project_id: uuid.UUID,
        *,
        filename: str,
        content: bytes,
        captured_on: date,
        platform: str,
        name: str | None,
        payload: dict[str, Any] | None,
    ) -> SurveyCaptureResponse:
        project = await self._project(project_id, payload)
        if not (filename or "").lower().endswith((".tif", ".tiff")):
            raise _http(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only .tif / .tiff GeoTIFF files are accepted")
        if len(content) > MAX_SURVEY_UPLOAD_BYTES:
            raise _http(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The GeoTIFF is over the upload limit")
        if not content.startswith(_TIFF_MAGIC):
            raise _http(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "The file is not a TIFF")
        meta = await self._sniff(content)
        if meta.width * meta.height > MAX_RASTER_PIXELS:
            raise _http(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "The GeoTIFF has too many pixels to preview. Export a lower resolution or a COG overview.",
            )

        cap = self._build_capture(project, "orthophoto", platform, captured_on, name or filename, payload)
        self._apply_meta(cap, meta, filename)
        results = await self._findings_for(project, cap)
        if self._errors(results):
            raise _http(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "; ".join(f.message for f in _findings(self._errors(results)))
            )

        preview = await self._preview(content)
        source_key, raster_key = await self.geo._store_overlay_blobs(
            project_id=project_id, filename=filename, source_bytes=content, raster_bytes=preview[0]
        )
        corners = self._corners(meta.bbox_wgs84)
        overlay = await self.geo.create_raster_overlay(
            GeoRasterOverlayCreate(
                project_id=project_id,
                name=cap.name,
                source_kind="image",
                source_blob_url=source_key,
                raster_blob_url=raster_key,
                raster_width_px=preview[1],
                raster_height_px=preview[2],
                corners_geojson=corners,
                metadata={
                    "original_filename": filename,
                    "format": "geotiff",
                    "survey_captured_on": captured_on.isoformat(),
                },
            ),
            payload=payload,
        )
        cap.overlay_id = overlay.id
        cap.metadata_ = {**cap.metadata_, "preview_px": [preview[1], preview[2]], "placed": bool(corners)}
        await self.captures.create(cap)
        await self._announce_created(cap)
        return self._response(cap, results)

    async def create_from_scan(self, data: SurveyFromScan, payload: dict[str, Any] | None) -> SurveyCaptureResponse:
        try:
            from app.modules.pointcloud.models import ScanDataset
        except ImportError as exc:  # optional module not installed
            raise _http(status.HTTP_501_NOT_IMPLEMENTED, "The point cloud module is not installed") from exc
        scan = await self.session.get(ScanDataset, data.scan_id)
        if scan is None:
            raise _http(404, "Scan not found")
        project = await self._project(scan.project_id, payload)
        meta = scan.scan_metadata or {}
        captured = data.captured_on
        if captured is None:
            for key in ("captured_on", "capture_date", "scan_date", "date"):
                captured = logic.parse_date(meta.get(key))
                if captured:
                    break
        captured = captured or (scan.created_at.date() if scan.created_at else datetime.now(UTC).date())

        cap = self._build_capture(
            project,
            "point_cloud",
            data.platform,
            captured,
            data.name or str(meta.get("name") or f"Scan {str(scan.id)[:8]}"),
            payload,
        )
        cap.scan_id = scan.id
        cap.crs_epsg = scan.crs_epsg
        cap.bbox_min_lat, cap.bbox_min_lon = scan.bbox_min_lat, scan.bbox_min_lon
        cap.bbox_max_lat, cap.bbox_max_lon = scan.bbox_max_lat, scan.bbox_max_lon
        results = await self._findings_for(project, cap)
        if self._errors(results):
            raise _http(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "; ".join(f.message for f in _findings(self._errors(results)))
            )
        await self.captures.create(cap)
        await self._announce_created(cap)
        return self._response(cap, results)

    @staticmethod
    def _build_capture(
        project: Any, kind: str, platform: str, captured_on: date, name: str, payload: dict[str, Any] | None
    ) -> SurveyCapture:
        return SurveyCapture(
            project_id=project.id,
            tenant_id=project.owner_id,
            kind=kind,
            platform=platform,
            captured_on=captured_on,
            name=(name or "")[:255],
            metadata_={},
            created_by=_extract_user_id(payload),
        )

    @staticmethod
    def _apply_meta(cap: SurveyCapture, meta: GeoTiffMeta, filename: str) -> None:
        cap.width_px, cap.height_px, cap.crs_epsg = meta.width, meta.height, meta.crs_epsg
        if meta.gsd_m is not None:
            cap.gsd_cm = Decimal(str(round(min(meta.gsd_m * 100.0, 999_999.0), 2)))
        if meta.bbox_wgs84 is not None:
            min_lon, min_lat, max_lon, max_lat = meta.bbox_wgs84
            cap.bbox_min_lon, cap.bbox_min_lat = Decimal(f"{min_lon:.7f}"), Decimal(f"{min_lat:.7f}")
            cap.bbox_max_lon, cap.bbox_max_lat = Decimal(f"{max_lon:.7f}"), Decimal(f"{max_lat:.7f}")
        cap.metadata_ = {
            "original_filename": filename,
            "band_count": meta.band_count,
            "is_cog": meta.is_cog,
            "warnings": list(meta.warnings),
        }

    @staticmethod
    def _corners(bbox: tuple[float, float, float, float] | None) -> list[list[float]]:
        if bbox is None:
            return []
        min_lon, min_lat, max_lon, max_lat = bbox
        return [[min_lon, max_lat], [max_lon, max_lat], [max_lon, min_lat], [min_lon, min_lat]]

    @staticmethod
    async def _sniff(content: bytes) -> GeoTiffMeta:
        try:
            return await asyncio.to_thread(sniff_geotiff, content)
        except ImagePixelBudgetExceeded as exc:
            raise _http(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "The GeoTIFF declares more pixels than can be processed. Export a lower resolution or a COG overview.",
            ) from exc
        except GeoTiffError as exc:
            raise _http(status.HTTP_422_UNPROCESSABLE_CONTENT, f"GeoTIFF not readable: {exc}") from exc

    @staticmethod
    async def _preview(content: bytes) -> tuple[bytes, int, int]:
        try:
            return await asyncio.to_thread(_render_preview, content)
        except ImagePixelBudgetExceeded as exc:
            raise _http(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The GeoTIFF is too large to preview") from exc
        except Exception as exc:  # noqa: BLE001 - any decode failure is an unreadable file to the client
            logger.info("survey preview failed: %s", exc)
            raise _http(status.HTTP_422_UNPROCESSABLE_CONTENT, "The GeoTIFF pixels could not be rendered") from exc

    async def _announce_created(self, cap: SurveyCapture) -> None:
        await event_bus.publish(
            "geo_hub.survey.created",
            {
                "survey_id": str(cap.id),
                "project_id": str(cap.project_id),
                "kind": cap.kind,
                "captured_on": cap.captured_on.isoformat(),
            },
            source_module="geo_hub",
        )

    # ── read / update / delete ──────────────────────────────────────────

    async def list_captures(
        self, project_id: uuid.UUID, payload: dict[str, Any] | None, *, offset: int = 0, limit: int = 200
    ) -> SurveyCaptureListResponse:
        await self._project(project_id, payload)
        rows = await self.captures.list_for_project(project_id, offset=offset, limit=limit)
        return SurveyCaptureListResponse(
            items=[self._response(r, []) for r in rows],
            total=await self.captures.count_for_project(project_id),
            offset=offset,
            limit=limit,
        )

    async def get_response(self, capture_id: uuid.UUID, payload: dict[str, Any] | None) -> SurveyCaptureResponse:
        cap = await self.get_capture(capture_id, payload)
        project = await self._project(cap.project_id, payload)
        return self._response(cap, await self._findings_for(project, cap))

    async def update_capture(
        self, capture_id: uuid.UUID, data: SurveyCapturePatch, payload: dict[str, Any] | None
    ) -> SurveyCaptureResponse:
        cap = await self.get_capture(capture_id, payload)
        project = await self._project(cap.project_id, payload)
        fields = data.model_dump(exclude_unset=True, exclude_none=True)
        # Judge the new date before touching the row, so a refused edit leaves the session clean.
        results = await self._findings_for(project, cap, fields.get("captured_on"))
        if self._errors(results):
            raise _http(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "; ".join(f.message for f in _findings(self._errors(results)))
            )
        for key, value in fields.items():
            setattr(cap, key, value)
        await self.session.flush()
        return self._response(cap, results)

    async def delete_capture(self, capture_id: uuid.UUID, payload: dict[str, Any] | None) -> None:
        """Remove the capture and the overlay it created; a linked scan is never touched."""
        cap = await self.get_capture(capture_id, payload)
        overlay_id = cap.overlay_id if cap.kind in ("orthophoto", "dsm") else None
        overlay = await self.geo.raster_overlays.get_by_id(overlay_id) if overlay_id else None
        await self.session.execute(sql_delete(SurveyObservation).where(SurveyObservation.capture_id == cap.id))
        await self.session.delete(cap)
        await self.session.flush()
        if overlay is not None and not await self.captures.count_for_overlay(overlay.id):
            keys = {k for k in (overlay.source_blob_url, overlay.raster_blob_url) if k}
            await self.geo.raster_overlays.delete(overlay.id)
            from app.core.storage import get_storage_backend

            backend = get_storage_backend()
            for key in keys:
                try:
                    await backend.delete(key)
                except Exception:  # noqa: BLE001 - an orphan blob is a sweep matter, not a failed delete
                    logger.warning("survey blob delete failed for %s", key)

    # ── observations ────────────────────────────────────────────────────

    async def _activity_in_project(self, activity_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        try:
            from app.modules.schedule.models import Activity, Schedule
        except ImportError:
            return False
        stmt = (
            select(Activity.id)
            .join(Schedule, Schedule.id == Activity.schedule_id)
            .where(Activity.id == activity_id, Schedule.project_id == project_id)
        )
        return (await self.session.execute(stmt)).first() is not None

    async def upsert_observation(
        self,
        capture_id: uuid.UUID,
        activity_id: uuid.UUID,
        data: SurveyObservationUpsert,
        payload: dict[str, Any] | None,
    ) -> SurveyObservation:
        cap = await self.get_capture(capture_id, payload)
        results = await evaluate(
            {
                "observation": {
                    "observed_pct": data.observed_pct,
                    "activity_in_project": await self._activity_in_project(activity_id, cap.project_id),
                }
            },
            locale=get_locale(),
            target_id=str(capture_id),
        )
        errors = self._errors(results)
        if errors:
            missing = any(r.rule_id.endswith("observation_requires_activity_in_project") for r in errors)
            raise _http(
                404 if missing else status.HTTP_422_UNPROCESSABLE_CONTENT,
                "; ".join(f.message for f in _findings(errors)),
            )

        user_id, now = _extract_user_id(payload), datetime.now(UTC)
        pct = Decimal(data.observed_pct).quantize(Decimal("0.01"))
        row = await self.observations.get_for(capture_id, activity_id)
        if row is None:
            row = await self.observations.create(
                SurveyObservation(
                    capture_id=capture_id,
                    activity_id=activity_id,
                    observed_pct=pct,
                    note=data.note,
                    confirmed_by=user_id,
                    confirmed_at=now,
                )
            )
        else:
            await self.observations.update_fields(
                row.id, observed_pct=pct, note=data.note, confirmed_by=user_id, confirmed_at=now
            )
        await event_bus.publish(
            "geo_hub.survey.observation.updated",
            {
                "survey_id": str(capture_id),
                "project_id": str(cap.project_id),
                "activity_id": str(activity_id),
                "observed_pct": str(pct),
            },
            source_module="geo_hub",
        )
        return row

    # ── progress ────────────────────────────────────────────────────────

    async def progress(
        self, capture_id: uuid.UUID, payload: dict[str, Any] | None, *, offset: int = 0, limit: int = 500
    ) -> SurveyProgressListResponse:
        """Planned vs observed progress for every schedule activity on the capture date."""
        cap = await self.get_capture(capture_id, payload)
        project = await self._project(cap.project_id, payload)
        tolerance = logic.tolerance_from(getattr(project, "metadata_", None))
        try:
            from app.modules.schedule.models import Activity, Schedule, ScheduleBaseline
        except ImportError:
            return SurveyProgressListResponse(items=[], total=0, offset=offset, limit=limit)

        total = (
            await self.session.execute(
                select(func.count(Activity.id))
                .join(Schedule, Schedule.id == Activity.schedule_id)
                .where(Schedule.project_id == cap.project_id)
            )
        ).scalar_one()
        acts = (
            await self.session.execute(
                select(
                    Activity.id,
                    Activity.schedule_id,
                    Activity.name,
                    Activity.wbs_code,
                    Activity.start_date,
                    Activity.end_date,
                )
                .join(Schedule, Schedule.id == Activity.schedule_id)
                .where(Schedule.project_id == cap.project_id)
                .order_by(Activity.sort_order, Activity.start_date, Activity.id)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        baselines = (
            (
                await self.session.execute(
                    select(ScheduleBaseline).where(
                        ScheduleBaseline.project_id == cap.project_id, ScheduleBaseline.is_active.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
        base: dict[tuple[str, str], tuple[Any, Any]] = {}
        for b in sorted(baselines, key=lambda r: str(r.baseline_date or "")):
            for aid, dates in logic.baseline_dates(b.snapshot_data).items():
                base[(str(b.schedule_id or ""), aid)] = dates
                base[("", aid)] = dates
        observed = {o.activity_id: o for o in await self.observations.list_for_capture(cap.id)}

        rows: list[SurveyProgressRow] = []
        for a in acts:
            start, end = (
                base.get((str(a.schedule_id), str(a.id))) or base.get(("", str(a.id))) or (a.start_date, a.end_date)
            )
            planned = logic.planned_pct_on_date(start, end, cap.captured_on)
            obs = observed.get(a.id)
            observed_pct = float(obs.observed_pct) if obs is not None else None
            variance = round(observed_pct - planned, 2) if observed_pct is not None else None
            rows.append(
                SurveyProgressRow(
                    activity_id=a.id,
                    code=a.wbs_code or str(a.id)[:8],
                    name=a.name,
                    planned_pct_on_date=planned,
                    observed_pct=observed_pct,
                    variance_pct=variance,
                    status=logic.status_for(variance, tolerance),
                    note=obs.note if obs is not None else "",
                )
            )
        return SurveyProgressListResponse(items=rows, total=int(total), offset=offset, limit=limit)
