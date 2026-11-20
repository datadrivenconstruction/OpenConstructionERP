# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Surface tools: a surface from a LAS/LAZ cloud, and staged volumes over a surface chain."""

from __future__ import annotations

import asyncio
import uuid
from typing import BinaryIO

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.surfaces_volumes import staged as staged_lib
from app.modules.surfaces_volumes.pointcloud import read_cloud_grid
from app.modules.surfaces_volumes.schemas import CloudImportResult, StagedRequest, StagedResult, StageStep
from app.modules.surfaces_volumes.service import (
    MAX_SURFACE_POINTS,
    VolumesService,
    _surface_out,
    surface_findings,
    tin_of,
)
from app.modules.surfaces_volumes.tin import Tin


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


class SurfaceToolsService:
    """Point cloud import and staged volumes over one request's session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.volumes = VolumesService(session)

    async def import_cloud(
        self,
        project_id: uuid.UUID,
        source: BinaryIO,
        *,
        filename: str,
        name: str,
        cell: float,
        stat: str,
        ground_only: bool,
        user_id: str,
        locale: str = "en",
    ) -> CloudImportResult:
        try:
            grid = await asyncio.to_thread(read_cloud_grid, source, cell, stat, ground_only)
        except ValueError as exc:
            raise _bad(str(exc)) from exc
        if grid.cells > MAX_SURFACE_POINTS:
            raise _bad(f"{grid.cells} cells is more than {MAX_SURFACE_POINTS}: choose a larger cell size")
        if grid.cells < 3:
            raise _bad("The cloud fills fewer than three cells: choose a smaller cell size")
        tin = await asyncio.to_thread(Tin.from_points, grid.e, grid.n, grid.z)
        epsg = await self.volumes._project_epsg(project_id)  # noqa: SLF001 - same module family
        note = f"LAS {grid.las_version}, {grid.points_used} of {grid.points_read} points, {stat} per {cell:g} m cell"
        surface = await self.volumes._store_surface(  # noqa: SLF001
            project_id,
            tin,
            name=name or filename or "Point cloud",
            source="pointcloud",
            user_id=user_id,
            epsg=epsg,
            filename=filename,
            note=note,
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
            stat=stat,
            las_version=grid.las_version,
            compressed=grid.compressed,
        )

    async def staged(self, project_id: uuid.UUID, data: StagedRequest, locale: str = "en") -> StagedResult:
        chain: list[tuple[str, Tin]] = []
        epsgs: set[int] = set()
        for i, st in enumerate(data.stages):
            if st.surface_id is not None:
                s = await self.volumes.get_surface(st.surface_id)
                if s.project_id != project_id:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Surface not found")
                if s.epsg:
                    epsgs.add(s.epsg)
                chain.append((st.label or s.name, tin_of(s)))
            elif st.strip_depth_m and chain:
                label = st.label or f"{chain[-1][0]} - {st.strip_depth_m:g} m"
                chain.append((label, staged_lib.strip(chain[-1][1], st.strip_depth_m)))
            else:
                raise _bad(f"Stage {i + 1} needs a surface, or a strip depth after another stage")
        if len(epsgs) > 1:
            raise _bad("The stages are in different coordinate systems")
        factors = {
            k: staged_lib.Factors(loose=v.loose, compacted=v.compacted) for k, v in data.factors.items() if k.strip()
        }
        materials = [st.material.strip() for st in data.stages[1:]]
        ring = [(float(p[0]), float(p[1])) for p in data.boundary] if data.boundary else None
        try:
            steps = await asyncio.to_thread(
                staged_lib.staged_volumes, chain, materials, factors, data.method, data.cell_size_m, ring
            )
        except ValueError as exc:
            raise _bad(str(exc)) from exc
        out: list[StageStep] = []
        cum_cut = cum_fill = 0.0
        for r in steps:
            cum_cut += r.cut
            cum_fill += r.fill
            out.append(
                StageStep(
                    index=r.index,
                    from_label=r.from_label,
                    to_label=r.to_label,
                    surveyed_on=data.stages[r.index].surveyed_on,
                    material=r.material,
                    cut_m3=round(r.cut, 3),
                    fill_m3=round(r.fill, 3),
                    net_m3=round(r.net, 3),
                    coverage_pct=round(r.coverage_pct, 2),
                    cut_loose_m3=round(r.cut_loose, 3) if r.cut_loose is not None else None,
                    fill_bank_needed_m3=round(r.fill_bank_needed, 3) if r.fill_bank_needed is not None else None,
                    cumulative_cut_m3=round(cum_cut, 3),
                    cumulative_fill_m3=round(cum_fill, 3),
                )
            )
        findings = await surface_findings(
            {"stages": [{"material": m, "has_factors": m in factors} for m in materials if m]},
            str(project_id),
            locale,
        )
        return StagedResult(
            steps=out,
            total_cut_m3=round(cum_cut, 3),
            total_fill_m3=round(cum_fill, 3),
            method=data.method,
            findings=findings,
        )


__all__ = ["SurfaceToolsService"]
