# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan-editor surface operations: design pads, contours, section samples and the mesh."""

from __future__ import annotations

import asyncio
import math
import uuid
from collections import OrderedDict

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.surfaces_volumes import contours as contour_lib
from app.modules.surfaces_volumes import pad as pad_lib
from app.modules.surfaces_volumes import pad_validators  # noqa: F401 - registers SRV-083
from app.modules.surfaces_volumes.geometry_schemas import (
    ContourLineOut,
    ContoursOut,
    MeshOut,
    PadCheckIn,
    PadCheckOut,
    PadCreate,
    PadOut,
    SampleIn,
    SampleOut,
    SampleRowOut,
)
from app.modules.surfaces_volumes.models import SurveySurface
from app.modules.surfaces_volumes.sampling import sample_polyline
from app.modules.surfaces_volumes.schemas import Finding
from app.modules.surfaces_volumes.service import VolumesService, _surface_out, surface_findings, tin_of

#: Contours per (surface, interval, mesh size); surfaces are rebuilt as new rows, so the id is a stable key.
_CONTOUR_CACHE: OrderedDict[tuple[str, float, int], ContoursOut] = OrderedDict()
_CACHE_SIZE = 32
#: The plan never draws a mesh larger than this; bigger surfaces show contours only.
MAX_MESH_FACES = 120_000


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def pad_context(name: str, outline: list[tuple[float, float]], level: float | None, unresolved: int = 0) -> dict:
    """SRV-083 context of a pad outline."""
    check = pad_lib.check_ring(outline)
    return {
        "pad": {
            "name": name,
            "points": check.closed_points,
            "self_intersections": check.self_intersections,
            "area_m2": check.area_m2,
            "level_set": level is not None and math.isfinite(level),
            "unresolved": unresolved,
        }
    }


class SurfaceGeometryService:
    """Pads, contours, samples and meshes over one request's session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.volumes = VolumesService(session)

    async def surface_in(self, project_id: uuid.UUID | None, surface_id: uuid.UUID) -> SurveySurface:
        s = await self.volumes.get_surface(surface_id)
        if project_id is not None and s.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Surface not found")
        return s

    async def check_pad(self, project_id: uuid.UUID, data: PadCheckIn, locale: str = "en") -> PadCheckOut:
        outline = [(float(e), float(n)) for e, n in data.outline]
        check = pad_lib.check_ring(outline)
        findings = await surface_findings(pad_context(data.name, outline, data.level), str(project_id), locale)
        return PadCheckOut(
            valid=check.valid and data.level is not None,
            area_m2=round(check.area_m2, 3),
            self_intersections=check.self_intersections,
            findings=findings,
        )

    async def create_pad(self, project_id: uuid.UUID, data: PadCreate, user_id: str, locale: str = "en") -> PadOut:
        outline = [(float(e), float(n)) for e, n in data.outline]
        blocking = [
            f
            for f in await surface_findings(pad_context(data.name, outline, data.level), str(project_id), locale)
            if f.severity == "error"
        ]
        if blocking:
            raise _bad("; ".join(f.message for f in blocking))
        ground = None
        epsg = await self.volumes._project_epsg(project_id)
        if data.ground_surface_id is not None:
            g = await self.surface_in(project_id, data.ground_surface_id)
            ground = tin_of(g)
            epsg = g.epsg or epsg
        result = await asyncio.to_thread(
            pad_lib.build_pad,
            outline,
            data.level,
            data.batter_n,
            data.cross_fall_pct,
            data.fall_bearing_deg,
            ground,
        )
        name = data.name.strip() or f"Pad {data.level:g}"
        surface = await self.volumes._store_surface(
            project_id,
            result.tin,
            name=name,
            source="pad",
            user_id=user_id,
            epsg=epsg,
            note=data.note,
            breaklines=[[[round(p[0], 4), round(p[1], 4), round(p[2], 4)] for p in [*result.top, result.top[0]]]],
        )
        findings: list[Finding] = await surface_findings(
            pad_context(name, outline, data.level, result.unresolved), str(project_id), locale
        )
        return PadOut(
            surface=_surface_out(surface),
            top=[(round(e, 4), round(n, 4), round(z, 4)) for e, n, z in result.top],
            daylight=[(round(e, 4), round(n, 4), round(z, 4)) for e, n, z in result.daylight],
            unresolved=result.unresolved,
            findings=findings,
        )

    async def contours(self, surface: SurveySurface, interval: float | None) -> ContoursOut:
        z_min = float(surface.z_min) if surface.z_min is not None else None
        z_max = float(surface.z_max) if surface.z_max is not None else None
        auto = contour_lib.auto_interval(z_min or 0.0, z_max or 0.0)
        step = interval if interval and interval > 0 else auto
        key = (str(surface.id), round(step, 6), len(surface.faces or []))
        hit = _CONTOUR_CACHE.get(key)
        if hit is not None:
            _CONTOUR_CACHE.move_to_end(key)
            return hit
        lines = await asyncio.to_thread(contour_lib.contour_lines, tin_of(surface), step)
        out = ContoursOut(
            surface_id=surface.id,
            interval=step,
            auto_interval=auto,
            index_every=contour_lib.INDEX_EVERY,
            z_min=z_min,
            z_max=z_max,
            lines=[ContourLineOut(z=c.z, index=c.index, closed=c.closed, coords=c.coords) for c in lines],
        )
        _CONTOUR_CACHE[key] = out
        while len(_CONTOUR_CACHE) > _CACHE_SIZE:
            _CONTOUR_CACHE.popitem(last=False)
        return out

    async def sample(self, surface: SurveySurface, data: SampleIn) -> SampleOut:
        line = [(float(e), float(n)) for e, n in data.polyline]
        try:
            rows = await asyncio.to_thread(sample_polyline, tin_of(surface), line, data.interval, list(data.offsets))
        except ValueError as exc:
            raise _bad(str(exc)) from exc
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(line[:-1], line[1:], strict=True))
        return SampleOut(
            surface_id=surface.id,
            length_m=round(length, 4),
            rows=[SampleRowOut(ch=r.ch, offset=r.offset, e=r.e, n=r.n, z=r.z) for r in rows],
        )

    @staticmethod
    def mesh(surface: SurveySurface) -> MeshOut:
        faces = surface.faces or []
        if len(faces) > MAX_MESH_FACES:
            raise _bad(f"{len(faces)} triangles is more than the plan draws ({MAX_MESH_FACES}); use the contours")
        return MeshOut(
            surface_id=surface.id,
            vertices=[(float(v[0]), float(v[1]), float(v[2])) for v in surface.vertices or []],
            faces=[(int(f[0]), int(f[1]), int(f[2])) for f in faces],
            z_min=float(surface.z_min) if surface.z_min is not None else None,
            z_max=float(surface.z_max) if surface.z_max is not None else None,
        )


__all__ = ["MAX_MESH_FACES", "SurfaceGeometryService", "pad_context"]
