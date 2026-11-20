# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A stored scan as a surface, against a design, and as a cut/fill quantity.

Three jobs over a scan in the register, E57, LAS or LAZ alike:

* grid it into a survey surface, the same surface the Volumes page builds from
  an uploaded LAS file;
* compare it point by point against a design surface (a TIN or the design pad)
  with the vertical tolerance of a setting-out profile, store the result as a
  :class:`ScanRegistration` (``target_ref = "surface:<id>"``, RMS in mm, points
  out of tolerance, coverage) with the full report as JSON next to the scan, and
  colour the cloud for the viewer;
* turn the scan into cut and fill against the design: a preview first, then a
  draft volume that the surveyor confirms and sends to a BOQ position through
  the existing volume workflow.

The cloud is always streamed (:mod:`app.modules.pointcloud.stream`); nothing
here holds a whole cloud in memory.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.modules.pointcloud import scan_design as sd
from app.modules.pointcloud.deviation import classify_deviation
from app.modules.pointcloud.models import ScanDataset, ScanRegistration
from app.modules.pointcloud.scan_design_schemas import (
    CutFillCreated,
    CutFillPreview,
    CutFillRequest,
    DeviationReportList,
    DeviationReportOut,
    DeviationRequest,
    ScanSurfaceRequest,
)
from app.modules.pointcloud.service import PointCloudService, _spill_stream_to_temp
from app.modules.pointcloud.stream import CHUNK_POINTS, CloudReaderMissing, iter_chunks, quick_info
from app.modules.surfaces_volumes.schemas import CloudImportResult, Finding, VolumeCreate

logger = logging.getLogger(__name__)

TARGET_PREFIX = "surface:"
VIEWABLE = ("uploaded", "converting", "ready")
_IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def _err(code: int, detail: Any) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def _bad(detail: str) -> HTTPException:
    return _err(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)


def reader_missing(exc: CloudReaderMissing) -> HTTPException:
    """501 with advice the reader can act on where they are (pip, uv tool, or desktop)."""
    from app.core.self_upgrade import DESKTOP_NO_EXTRA, repair_hint  # noqa: PLC0415

    return _err(
        status.HTTP_501_NOT_IMPLEMENTED,
        {
            "reason": "reader_unavailable",
            "format": exc.fmt,
            "message": (
                f"{exc.fmt.upper()} needs the optional {exc.reader} reader. LAS and LAZ work out of the box; "
                + repair_hint(
                    "add E57 with 'pip install \"openconstructionerp[pointcloud]\"' "
                    "(or 'uv tool install \"openconstructionerp[pointcloud]\"' for the one-line installer), "
                    "then restart.",
                    DESKTOP_NO_EXTRA,
                )
            ),
        },
    )


# ── Pure runs, executed in a worker thread ─────────────────────────────────


def run_deviation(path: str, fmt: str, tin: Any, tol_mm: float, ground_only: bool) -> tuple[sd.DeviationStats, bool]:
    """Stream ``path`` against ``tin``; returns the stats and whether every class had to be used."""
    design = sd.design_grid(tin)
    declared, area = quick_info(path, fmt)
    floor = sd.heat_cell_floor(area or tin.area(), declared)
    every = sd.DeviationAccumulator(design, tol_mm, floor)
    ground = sd.DeviationAccumulator(design, tol_mm, floor) if ground_only else None
    has_classes = False
    for ch in iter_chunks(path, fmt, CHUNK_POINTS):
        every.add(ch.x, ch.y, ch.z)
        if ground is not None and ch.cls is not None:
            has_classes = True
            g = ch.cls == 2
            ground.add(ch.x[g], ch.y[g], ch.z[g])
    if ground is not None and has_classes and ground.n > 0:
        stats = ground.result()
        stats.points_read = every.read
        return stats, False
    return every.result(), bool(ground_only)


def run_sample(
    path: str, fmt: str, tin: Any, tol_mm: float, ground_only: bool, max_points: int
) -> tuple[np.ndarray, np.ndarray, int]:
    """Every n-th point coloured by deviation; non-ground points stay grey when ground only is on."""
    declared, _area = quick_info(path, fmt)
    if not declared:
        declared = sum(len(ch.x) for ch in iter_chunks(path, fmt, CHUNK_POINTS))
    design = sd.design_grid(tin)
    keep = sd.SampleCollector(declared, max_points)
    for ch in iter_chunks(path, fmt, CHUNK_POINTS):
        dz = (ch.z - design.sample(ch.x, ch.y)) * 1000.0
        if ground_only and ch.cls is not None and (ch.cls == 2).any():
            dz = np.where(ch.cls == 2, dz, np.nan)
        keep.add(ch.x, ch.y, ch.z, dz)
    xyz, dz = keep.arrays()
    return xyz, sd.heat_rgb(dz, tol_mm), declared


def pack_heat_points(xyz: np.ndarray, rgb: np.ndarray, total: int) -> bytes:
    """OEPC buffer the viewer already reads, colour channel = deviation band."""
    from app.modules.pointcloud.decode import PointDecodeError, _finalise  # noqa: PLC0415
    from app.modules.pointcloud.wire import pack_points  # noqa: PLC0415

    try:
        decoded = _finalise(xyz, rgb, None, total_count=total)
    except PointDecodeError as exc:
        raise _bad(str(exc)) from exc
    return pack_points(decoded)


class ScanDesignService:
    """Scan to surface, scan against design, and scan to cut/fill quantities."""

    def __init__(self, session: AsyncSession) -> None:
        from app.modules.surfaces_volumes.service import VolumesService  # noqa: PLC0415

        self.session = session
        self.pc = PointCloudService(session)
        self.volumes = VolumesService(session)

    # ── Files ──────────────────────────────────────────────────────────────

    @contextlib.asynccontextmanager
    async def _scan_file(self, scan: ScanDataset) -> AsyncIterator[tuple[str, str]]:
        """A local path to the raw scan (spooled from object storage when needed) and its format."""
        fmt = (scan.original_format or "").lower()
        if scan.status not in VIEWABLE:
            raise _err(status.HTTP_409_CONFLICT, {"reason": "scan_not_ready", "status": scan.status})
        local = self.pc._local_path_for(scan.upload_key)  # noqa: SLF001 - same module
        if local is not None and Path(local).exists():
            yield str(local), fmt
            return
        cap = int(getattr(get_settings(), "pointcloud_max_proxied_bytes", 2 * 1024 * 1024 * 1024))
        async with contextlib.aclosing(self.pc.storage.open_stream(scan.upload_key)) as stream:
            tmp = await _spill_stream_to_temp(stream, suffix=f".{fmt or 'bin'}", max_bytes=cap)
        try:
            yield tmp, fmt
        finally:
            with contextlib.suppress(OSError):
                await asyncio.to_thread(os.unlink, tmp)

    async def _design(self, project_id: uuid.UUID, surface_id: uuid.UUID) -> tuple[Any, Any]:
        from app.modules.surfaces_volumes.service import tin_of  # noqa: PLC0415

        surface = await self.volumes.get_surface(surface_id)
        if surface.project_id != project_id:
            raise _err(status.HTTP_404_NOT_FOUND, "Surface not found")
        return surface, tin_of(surface)

    # ── Tolerance ──────────────────────────────────────────────────────────

    async def tolerance(self, project_id: uuid.UUID, key: str, item_type: str, markets: list[str]) -> dict[str, Any]:
        """The vertical tolerance of a setting-out profile (demo, active pack, or project)."""
        from app.modules.setting_out.service import SettingOutService  # noqa: PLC0415

        profiles = await SettingOutService(self.session).profiles(project_id, markets)
        profile = next((p for p in profiles if p.key == key), None)
        if profile is None:
            raise _bad("Unknown tolerance profile")
        value = profile.items.get(item_type) or profile.items.get("default")
        if value is None or value.v_mm is None or value.v_mm <= 0:
            raise _bad(f"Profile {profile.name} has no vertical tolerance for {item_type}")
        return {
            "key": profile.key,
            "label": profile.name,
            "source": profile.source,
            "item_type": item_type,
            "v_mm": float(value.v_mm),
            "reference": profile.reference,
        }

    # ── Surface from a stored scan, and from an E57 upload ─────────────────

    async def _surface_from_path(
        self,
        project_id: uuid.UUID,
        path: str,
        fmt: str,
        *,
        filename: str,
        body: ScanSurfaceRequest,
        user_id: str,
        tier: str | None,
        locale: str,
    ) -> CloudImportResult:
        from app.modules.pointcloud.grid import cloud_grid  # noqa: PLC0415
        from app.modules.surfaces_volumes.service import (  # noqa: PLC0415
            MAX_SURFACE_POINTS,
            _surface_out,
            surface_findings,
        )
        from app.modules.surfaces_volumes.tin import Tin  # noqa: PLC0415

        try:
            grid = await asyncio.to_thread(cloud_grid, path, fmt, body.cell_size_m, body.stat, body.ground_only)
        except CloudReaderMissing as exc:
            raise reader_missing(exc) from exc
        except ValueError as exc:
            raise _bad(str(exc)) from exc
        if grid.cells > MAX_SURFACE_POINTS:
            raise _bad(f"{grid.cells} cells is more than {MAX_SURFACE_POINTS}: choose a larger cell size")
        if grid.cells < 3:
            raise _bad("The cloud fills fewer than three cells: choose a smaller cell size")
        tin = await asyncio.to_thread(Tin.from_points, grid.e, grid.n, grid.z)
        epsg = await self.volumes._project_epsg(project_id)  # noqa: SLF001 - surfaces keeps no public twin
        version = grid.las_version if grid.las_version.startswith("E57") else f"LAS {grid.las_version}"
        note = (
            f"{version}, {grid.points_used} of {grid.points_read} points, {body.stat} per {body.cell_size_m:g} m cell"
        )
        surface = await self.volumes._store_surface(  # noqa: SLF001 - same store as the LAS upload
            project_id,
            tin,
            name=body.name or filename or "Point cloud",
            source="pointcloud",
            user_id=user_id,
            epsg=epsg,
            filename=filename,
            note=note,
            tier=tier,
        )
        out = _surface_out(surface)
        out.findings = await surface_findings(
            {"surface": {"code": surface.code, "used_all_classes": grid.used_all_classes}}, str(project_id), locale
        )
        return CloudImportResult(
            surface=out,
            points_read=grid.points_read,
            points_used=grid.points_used,
            ground_points=grid.ground_points,
            used_all_classes=grid.used_all_classes,
            cells=grid.cells,
            cell_size_m=grid.cell_size,
            stat=body.stat,
            las_version=version,
            compressed=grid.compressed,
        )

    async def scan_surface(
        self, scan_id: uuid.UUID, body: ScanSurfaceRequest, payload: dict[str, Any], user_id: str, locale: str = "en"
    ) -> CloudImportResult:
        """Grid a scan from the register into a survey surface."""
        scan = await self.pc.get_scan(scan_id, payload=payload)
        project_id, tier, name = scan.project_id, scan.accuracy_tier, scan.upload_key.rsplit("/", 1)[-1]
        async with self._scan_file(scan) as (path, fmt):
            return await self._surface_from_path(
                project_id, path, fmt, filename=name, body=body, user_id=user_id, tier=tier, locale=locale
            )

    async def upload_surface(
        self,
        project_id: uuid.UUID,
        source: BinaryIO,
        filename: str,
        body: ScanSurfaceRequest,
        user_id: str,
        locale: str = "en",
    ) -> CloudImportResult:
        """An uploaded E57 (or LAS/LAZ) file straight to a surface; the upload is spooled to disk."""
        import shutil  # noqa: PLC0415
        import tempfile  # noqa: PLC0415

        fmt = Path(filename).suffix.lower().lstrip(".")

        def _spool() -> str:
            fd, tmp = tempfile.mkstemp(suffix=f".{fmt}")
            with os.fdopen(fd, "wb") as out:
                shutil.copyfileobj(source, out, 1024 * 1024)
            return tmp

        tmp = await asyncio.to_thread(_spool)
        try:
            return await self._surface_from_path(
                project_id, tmp, fmt, filename=filename, body=body, user_id=user_id, tier=None, locale=locale
            )
        finally:
            with contextlib.suppress(OSError):
                await asyncio.to_thread(os.unlink, tmp)

    # ── Scan against design ────────────────────────────────────────────────

    @staticmethod
    def _blob_key(scan: ScanDataset, reg_id: uuid.UUID) -> str:
        prefix = scan.upload_key.rsplit("/", 1)[0] if "/" in scan.upload_key else f"pointcloud/{scan.id}"
        return f"{prefix}/deviation/{reg_id}.json"

    async def deviation_findings(self, report: dict[str, Any], locale: str = "en") -> list[Finding]:
        """PCD-001..003 over a stored report."""
        from app.core.validation.engine import validation_engine  # noqa: PLC0415
        from app.modules.pointcloud.deviation_rules import DEVIATION_RULE_SET  # noqa: PLC0415

        st = report["stats"]
        compared = int(st.get("points_compared") or 0)
        out_pct = None if not compared else round(100.0 * int(st.get("out_count") or 0) / compared, 2)
        data = {
            "deviation": {
                "ref": report.get("surface_code") or "",
                "points_compared": compared,
                "out_pct": out_pct,
                "threshold_pct": report.get("threshold_pct"),
                "tolerance_mm": st.get("tolerance_mm"),
                "coverage_pct": st.get("coverage_pct"),
            }
        }
        result = await validation_engine.validate(
            data=data,
            rule_sets=[DEVIATION_RULE_SET],
            target_type="scan_deviation",
            target_id=str(report.get("id") or ""),
            project_id=str(report.get("project_id") or ""),
            metadata={"locale": locale},
        )
        return [
            Finding(
                rule_id=r.rule_id,
                severity=str(getattr(r.severity, "value", r.severity)),
                message=r.message,
                suggestion=r.suggestion,
                element_ref=r.element_ref,
            )
            for r in result.results
            if not r.passed
        ]

    async def _out(self, report: dict[str, Any], locale: str, with_heat: bool) -> DeviationReportOut:
        st = report["stats"]
        severity = classify_deviation(
            rms_mm=st.get("rms_mm"),
            tolerance_mm=st.get("tolerance_mm"),
            out_of_tolerance_count=st.get("out_count"),
            coverage_pct=st.get("coverage_pct"),
        )
        data = {k: v for k, v in report.items() if k not in ("heat", "stats")}
        return DeviationReportOut(
            **data,
            stats={k: v for k, v in st.items() if k != "heat"},
            severity=severity,
            findings=await self.deviation_findings(report, locale),
            heat=report.get("heat") if with_heat else None,
        )

    async def compare(
        self,
        scan_id: uuid.UUID,
        body: DeviationRequest,
        payload: dict[str, Any],
        user_id: str,
        markets: list[str],
        locale: str = "en",
    ) -> DeviationReportOut:
        """Run the comparison, store it, and return the report with its findings."""
        scan = await self.pc.get_scan(scan_id, payload=payload)
        project_id = scan.project_id
        surface, tin = await self._design(project_id, body.surface_id)
        tol = await self.tolerance(project_id, body.tolerance_key, body.item_type, markets)
        async with self._scan_file(scan) as (path, fmt):
            try:
                stats, used_all = await asyncio.to_thread(run_deviation, path, fmt, tin, tol["v_mm"], body.ground_only)
            except CloudReaderMissing as exc:
                raise reader_missing(exc) from exc
            except ValueError as exc:
                raise _bad(str(exc)) from exc
        reg_id = uuid.uuid4()
        raw = stats.as_dict()
        heat = raw.pop("heat")
        report: dict[str, Any] = {
            "id": str(reg_id),
            "scan_id": str(scan.id),
            "project_id": str(project_id),
            "surface_id": str(surface.id),
            "surface_code": surface.code,
            "surface_name": surface.name,
            "tolerance": tol,
            "threshold_pct": body.threshold_pct,
            "ground_only": body.ground_only,
            "used_all_classes": used_all,
            "stats": raw,
            "heat": heat,
            "created_at": datetime.now(UTC).isoformat(),
            "created_by": user_id,
        }
        key = self._blob_key(scan, reg_id)
        await self.pc.storage.put(key, json.dumps(report).encode("utf-8"))
        cov = Decimal(str(stats.coverage_pct)).quantize(Decimal("0.001"))
        self.session.add(
            ScanRegistration(
                id=reg_id,
                scan_id=scan.id,
                target_ref=f"{TARGET_PREFIX}{surface.id}",
                transform_matrix=list(_IDENTITY),
                rms_error=None if stats.rms_mm is None else Decimal(str(stats.rms_mm)).quantize(Decimal("0.0001")),
                deviation_map_uri=key,
                out_of_tolerance_count=stats.out_count,
                coverage_pct=cov,
                confidence=min(cov / Decimal(100), Decimal(1)).quantize(Decimal("0.001")),
            )
        )
        await self.session.flush()
        return await self._out(report, locale, with_heat=True)

    async def _report(self, reg_id: uuid.UUID, payload: dict[str, Any]) -> tuple[dict[str, Any], ScanDataset]:
        reg = await self.pc.registrations.get_by_id(reg_id)
        if reg is None or not str(reg.target_ref).startswith(TARGET_PREFIX) or not reg.deviation_map_uri:
            raise _err(status.HTTP_404_NOT_FOUND, "Report not found")
        scan = await self.pc.get_scan(reg.scan_id, payload=payload)
        try:
            report = json.loads(await self.pc.storage.get(reg.deviation_map_uri))
        except Exception as exc:  # noqa: BLE001 - a missing blob reads as a missing report
            raise _err(status.HTTP_404_NOT_FOUND, "Report not found") from exc
        return report, scan

    async def get_report(self, reg_id: uuid.UUID, payload: dict[str, Any], locale: str = "en") -> DeviationReportOut:
        """One stored comparison with its heat grid."""
        report, _scan = await self._report(reg_id, payload)
        return await self._out(report, locale, with_heat=True)

    async def list_reports(
        self, scan_id: uuid.UUID, payload: dict[str, Any], locale: str = "en"
    ) -> DeviationReportList:
        """Every comparison of a scan, newest first, without heat grids."""
        scan = await self.pc.get_scan(scan_id, payload=payload)
        items: list[DeviationReportOut] = []
        for reg in await self.pc.registrations.list_for_scan(scan.id, limit=200):
            if not str(reg.target_ref).startswith(TARGET_PREFIX) or not reg.deviation_map_uri:
                continue
            try:
                report = json.loads(await self.pc.storage.get(reg.deviation_map_uri))
            except Exception:  # noqa: BLE001 - skip a report whose blob is gone
                logger.warning("pointcloud: deviation report blob missing for %s", reg.id)
                continue
            items.append(await self._out(report, locale, with_heat=False))
        return DeviationReportList(items=items, total=len(items))

    async def report_points(
        self, reg_id: uuid.UUID, payload: dict[str, Any], max_points: int
    ) -> tuple[bytes, int, int]:
        """OEPC buffer of the scan coloured by deviation band; returns (buffer, total, returned)."""
        report, scan = await self._report(reg_id, payload)
        _surface, tin = await self._design(scan.project_id, uuid.UUID(report["surface_id"]))
        tol = float(report["tolerance"]["v_mm"])
        async with self._scan_file(scan) as (path, fmt):
            try:
                xyz, rgb, total = await asyncio.to_thread(
                    run_sample, path, fmt, tin, tol, bool(report.get("ground_only")), max_points
                )
            except CloudReaderMissing as exc:
                raise reader_missing(exc) from exc
            except ValueError as exc:
                raise _bad(str(exc)) from exc
        buffer = await asyncio.to_thread(pack_heat_points, xyz, rgb, total)
        return buffer, total, len(xyz)

    async def report_export(
        self, reg_id: uuid.UUID, payload: dict[str, Any], fmt: str, locale: str = "en"
    ) -> tuple[bytes, str, str]:
        """``(content, media type, file name)`` of the report as CSV or PDF."""
        from app.modules.pointcloud.deviation_report import report_csv, report_pdf  # noqa: PLC0415

        report, scan = await self._report(reg_id, payload)
        out = await self._out(report, locale, with_heat=True)
        stem = f"deviation_{report.get('surface_code') or 'surface'}_{str(reg_id)[:8]}"
        if fmt == "csv":
            return report_csv(out), "text/csv; charset=utf-8", f"{stem}.csv"
        content = await asyncio.to_thread(report_pdf, out, scan.upload_key.rsplit("/", 1)[-1], locale)
        return content, "application/pdf", f"{stem}.pdf"

    # ── Cut and fill to the BOQ ────────────────────────────────────────────

    async def cutfill_preview(
        self, scan_id: uuid.UUID, body: CutFillRequest, payload: dict[str, Any]
    ) -> CutFillPreview:
        """Cut and fill of the gridded scan against the design, nothing stored."""
        from app.modules.pointcloud.grid import cloud_grid  # noqa: PLC0415
        from app.modules.surfaces_volumes import volumes as vol  # noqa: PLC0415
        from app.modules.surfaces_volumes.tin import Tin  # noqa: PLC0415

        scan = await self.pc.get_scan(scan_id, payload=payload)
        surface, design = await self._design(scan.project_id, body.surface_id)
        async with self._scan_file(scan) as (path, fmt):
            try:
                grid = await asyncio.to_thread(cloud_grid, path, fmt, body.cell_size_m, body.stat, body.ground_only)
            except CloudReaderMissing as exc:
                raise reader_missing(exc) from exc
            except ValueError as exc:
                raise _bad(str(exc)) from exc
        if grid.cells < 3:
            raise _bad("The cloud fills fewer than three cells: choose a smaller cell size")
        tin = await asyncio.to_thread(Tin.from_points, grid.e, grid.n, grid.z)
        try:
            r = await asyncio.to_thread(vol.compute, tin, design, body.method, body.cell_size_m, None)
        except ValueError as exc:
            raise _bad(str(exc)) from exc
        return CutFillPreview(
            surface_id=surface.id,
            surface_name=surface.name,
            method=body.method,
            cell_size_m=body.cell_size_m,
            cut_m3=round(r.cut, 3),
            fill_m3=round(r.fill, 3),
            net_m3=round(r.net, 3),
            coverage_pct=round(r.coverage_pct, 2),
            points_read=grid.points_read,
            cells=grid.cells,
            used_all_classes=grid.used_all_classes,
        )

    async def cutfill_create(
        self, scan_id: uuid.UUID, body: CutFillRequest, payload: dict[str, Any], user_id: str, locale: str = "en"
    ) -> CutFillCreated:
        """Store the scan surface and a draft volume (scan above design = cut) for confirm and send."""
        scan = await self.pc.get_scan(scan_id, payload=payload)
        project_id = scan.project_id
        design, _tin = await self._design(project_id, body.surface_id)
        made = await self.scan_surface(
            scan_id,
            ScanSurfaceRequest(
                name=body.name or f"Scan {scan.upload_key.rsplit('/', 1)[-1]}",
                cell_size_m=body.cell_size_m,
                stat=body.stat,
                ground_only=body.ground_only,
            ),
            payload,
            user_id,
            locale,
        )
        detail = await self.volumes.create_volume(
            project_id,
            VolumeCreate(
                name=(body.name or f"{made.surface.name} vs {design.name}")[:255],
                base_surface_id=made.surface.id,
                compare_surface_id=design.id,
                method=body.method,
                cell_size_m=body.cell_size_m,
            ),
            user_id,
        )
        return CutFillCreated(
            scan_surface_id=made.surface.id,
            scan_surface_code=made.surface.code,
            volume_id=detail.id,
            volume_code=detail.code,
            status=detail.status,
            cut_m3=detail.cut_m3,
            fill_m3=detail.fill_m3,
            net_m3=detail.net_m3,
            coverage_pct=float(detail.coverage_pct or 0),
            findings=[*made.surface.findings, *detail.findings],
        )


__all__ = ["TARGET_PREFIX", "ScanDesignService", "pack_heat_points", "run_deviation", "run_sample"]
