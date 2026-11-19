# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mine survey depth: material split, drive advance and profiles, blast patterns.

The material split clips a unit's actual (a Volumes calculation) by its ore,
waste and low-grade polygons and prices each part at its own density. Drives get
their advance from face pickups and their over/underbreak from measured profiles
against the design section. Blast patterns hold design collars and depths and
judge the as-drilled holes against the pattern's tolerances. Every tolerance is
config: none has a core default.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mine_survey import calc
from app.modules.mine_survey.models import (
    MineBlastHole,
    MineBlastPattern,
    MineDriveFace,
    MineDriveProfile,
    MineMaterial,
    MinePeriod,
    MinePeriodEntry,
    MineUnit,
)
from app.modules.mine_survey.repository import MineRepository
from app.modules.mine_survey.schemas import (
    DrilledImport,
    DriveDetail,
    DriveSummary,
    FaceIn,
    FaceOut,
    Finding,
    HoleOut,
    MaterialImport,
    MaterialImportResult,
    MaterialIn,
    MaterialOut,
    PatternCreate,
    PatternDetail,
    PatternOut,
    PatternUpdate,
    ProfileImport,
    ProfileIn,
    ProfileOut,
)
from app.modules.mine_survey.validators import BLAST_RULE_SET

logger = logging.getLogger(__name__)
_MATERIALS = set(calc.MATERIALS)


def _err(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def _f(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)


def _q(value: float | Decimal | None, places: str) -> Decimal | None:
    return None if value is None else calc.dec(value).quantize(Decimal(places), ROUND_HALF_UP)


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _ring_area(ring: list[tuple[float, float]]) -> float:
    from app.modules.surfaces_volumes.volumes import polygon_area  # noqa: PLC0415

    return polygon_area(ring)


def _findings(report: Any) -> list[Finding]:
    return [
        Finding(
            rule_id=r.rule_id,
            severity=str(getattr(r.severity, "value", r.severity)),
            message=r.message,
            suggestion=r.suggestion,
            element_ref=r.element_ref,
        )
        for r in report.results
        if not r.passed
    ]


def _geojson_polygons(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Outer rings of the (Multi)Polygon features with their properties."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Not a GeoJSON file: {exc.msg}") from exc
    feats = doc.get("features", []) if isinstance(doc, dict) and doc.get("type") == "FeatureCollection" else [doc]
    out: list[dict[str, Any]] = []
    problems: list[str] = []
    for i, f in enumerate(feats, start=1):
        geom = (f or {}).get("geometry") or {}
        props = (f or {}).get("properties") or {}
        polys = [geom.get("coordinates")] if geom.get("type") == "Polygon" else geom.get("coordinates") or []
        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            problems.append(f"feature {i}: not a polygon")
            continue
        for poly in polys:
            ring = [(float(c[0]), float(c[1])) for c in (poly or [[]])[0] if len(c) >= 2]
            if len(ring) < 3:
                problems.append(f"feature {i}: fewer than three vertices")
                continue
            out.append({"ring": ring, "props": props})
    return out, problems


class MineDepthService:
    """Material split, drives and blast patterns of the mine survey."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = MineRepository(session)

    async def _unit(self, unit_id: uuid.UUID) -> MineUnit:
        u = await self.repo.get_unit(unit_id)
        if u is None:
            raise _err(status.HTTP_404_NOT_FOUND, "Unit not found")
        return u

    # ── Materials ──────────────────────────────────────────────────────────

    @staticmethod
    def _material_out(m: MineMaterial) -> MaterialOut:
        ring = [(float(p[0]), float(p[1])) for p in m.ring or []]
        return MaterialOut(
            id=m.id,
            unit_id=m.unit_id,
            material=m.material,
            name=m.name,
            density_t_m3=_f(m.density_t_m3),
            ring=ring,
            area_m2=round(_ring_area(ring), 3),
            source=m.source,
            source_filename=m.source_filename,
        )

    async def list_materials(self, unit_id: uuid.UUID) -> list[MaterialOut]:
        return [self._material_out(m) for m in await self.repo.materials_of(unit_id)]

    async def add_material(self, u: MineUnit, data: MaterialIn, user_id: str, source: str = "manual") -> MaterialOut:
        if _ring_area(list(data.ring)) <= 0:
            raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, "The polygon has no area")
        m = MineMaterial(
            project_id=u.project_id,
            unit_id=u.id,
            material=data.material,
            name=(data.name or data.material).strip()[:255],
            density_t_m3=_q(data.density_t_m3, "0.0001"),
            ring=[[round(x, 4), round(y, 4)] for x, y in data.ring],
            source=source,
            created_by=_uuid(user_id),
        )
        await self.repo.add(m)
        return self._material_out(m)

    async def import_materials(self, u: MineUnit, data: MaterialImport, user_id: str) -> MaterialImportResult:
        """GeoJSON polygons, or closed polylines of a drawing layer mapped to a material."""
        from app.modules.surfaces_volumes.drawing_lines import drawing_lines  # noqa: PLC0415

        found: list[dict[str, Any]] = []
        problems: list[str] = []
        source, filename = "geojson", data.filename
        if data.drawing_id is not None:
            if not data.layers:
                raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, "Map at least one drawing layer to a material")
            source = "drawing"
            for line in await drawing_lines(self.session, u.project_id, data.drawing_id, set(data.layers)):
                if not line.closed and line.points[0] != line.points[-1]:
                    problems.append(f"layer {line.layer}: an open line is not a polygon")
                    continue
                mat = data.layers[line.layer]
                found.append({"ring": line.points, "props": {"material": mat, "name": line.layer}})
        elif data.text.strip():
            found, problems = _geojson_polygons(data.text)
        else:
            raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give a GeoJSON file or a drawing")
        if data.replace:
            for m in await self.repo.materials_of(u.id):
                await self.repo.delete(m)
        out: list[MaterialOut] = []
        for i, f in enumerate(found, start=1):
            props = f["props"]
            mat = str(props.get("material") or "ore").strip().lower().replace(" ", "_")
            if mat not in _MATERIALS:
                problems.append(f"polygon {i}: material {mat!r} is not ore, waste, low_grade or other")
                continue
            dens = props.get("density_t_m3", data.densities.get(mat))
            try:
                density = float(dens) if dens not in (None, "") else None
            except (TypeError, ValueError):
                density = None
            if density is not None and not (0 < density <= 30):
                density = None
            m = await self.add_material(
                u,
                MaterialIn(material=mat, name=str(props.get("name") or ""), density_t_m3=density, ring=f["ring"]),
                user_id,
                source,
            )
            row = await self.session.get(MineMaterial, m.id)
            if row is not None:
                row.source_filename = filename[:255]
            out.append(m.model_copy(update={"source_filename": filename[:255]}))
        await self.session.flush()
        return MaterialImportResult(items=out, problems=problems)

    async def get_material(self, material_id: uuid.UUID) -> MineMaterial:
        m = await self.session.get(MineMaterial, material_id)
        if m is None:
            raise _err(status.HTTP_404_NOT_FOUND, "Material polygon not found")
        return m

    async def split_entry(self, e: MinePeriodEntry) -> dict[str, Any]:
        """Clip the entry's actual by each material polygon of its unit and store the split on the entry."""
        from app.modules.surfaces_volumes import volumes as vol  # noqa: PLC0415
        from app.modules.surfaces_volumes.models import SurveyVolume  # noqa: PLC0415
        from app.modules.surfaces_volumes.service import VolumesService, tin_of  # noqa: PLC0415

        if e.actual_volume_id is None:
            raise _err(status.HTTP_409_CONFLICT, "Compute the actual first: the split clips its volume")
        v = await self.session.get(SurveyVolume, e.actual_volume_id)
        if v is None:
            raise _err(status.HTTP_409_CONFLICT, "Compute the actual first: the split clips its volume")
        materials = await self.repo.materials_of(e.unit_id)
        if not materials:
            raise _err(status.HTTP_409_CONFLICT, "The unit has no material polygons: import them first")
        service = VolumesService(self.session)
        base, compare = await service._surfaces_for(v.project_id, v.base_surface_id, v.compare_surface_id)  # noqa: SLF001
        tb, tc = tin_of(base), tin_of(compare)
        cell = float(v.cell_size_m) if v.cell_size_m else None
        parts: list[tuple[str, str, Decimal, Decimal | None]] = []
        for m in materials:
            ring = [(float(p[0]), float(p[1])) for p in m.ring]
            try:
                r = vol.compute(tb, tc, "grid", cell, ring)
            except ValueError as exc:
                raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
            parts.append((m.material, m.name, calc.dec(round(r.cut, 3)), m.density_t_m3))
        split = calc.material_split(parts, v.cut_m3)
        stored = {
            "parts": [
                {
                    "material": p.material,
                    "name": p.name,
                    "volume_m3": float(p.volume_m3),
                    "density_t_m3": _f(p.density_t_m3),
                    "tonnes": _f(p.tonnes),
                }
                for p in split.parts
            ],
            "total_m3": float(split.total_m3),
            "assigned_m3": float(split.assigned_m3),
            "unassigned_m3": float(split.unassigned_m3),
            "coverage_pct": _f(split.coverage_pct),
            "tonnes": _f(split.tonnes),
            "volume_id": str(v.id),
        }
        e.details = {**(e.details or {}), "material_split": stored}
        await self.session.flush()
        return stored

    # ── Drives ─────────────────────────────────────────────────────────────

    @staticmethod
    def _face_out(f: MineDriveFace) -> FaceOut:
        return FaceOut(
            id=f.id,
            unit_id=f.unit_id,
            period_id=f.period_id,
            chainage_m=float(f.chainage_m),
            picked_on=f.picked_on,
            note=f.note,
        )

    @staticmethod
    def _inside(u: MineUnit, ch: Decimal) -> bool | None:
        if u.design_ch_from_m is None or u.design_ch_to_m is None:
            return None
        lo, hi = sorted((u.design_ch_from_m, u.design_ch_to_m))
        return lo <= ch <= hi

    def _profile_out(self, u: MineUnit, p: MineDriveProfile) -> ProfileOut:
        design = p.design_area_m2 or u.design_area_m2
        over = None
        if design:
            over = float(((p.actual_area_m2 - design) / design * 100).quantize(Decimal("0.01"), ROUND_HALF_UP))
        return ProfileOut(
            id=p.id,
            unit_id=p.unit_id,
            period_id=p.period_id,
            chainage_m=float(p.chainage_m),
            actual_area_m2=float(p.actual_area_m2),
            design_area_m2=_f(p.design_area_m2),
            overbreak_pct=over,
            inside_design=self._inside(u, p.chainage_m),
        )

    async def add_face(self, u: MineUnit, data: FaceIn) -> FaceOut:
        f = MineDriveFace(
            project_id=u.project_id,
            unit_id=u.id,
            period_id=data.period_id,
            chainage_m=_q(data.chainage_m, "0.001"),
            picked_on=data.picked_on,
            note=data.note,
        )
        await self.repo.add(f)
        await self._sync_advance(u, data.period_id)
        return self._face_out(f)

    async def _sync_advance(self, u: MineUnit, period_id: uuid.UUID | None) -> None:
        """Write the advance from the period's face pickups onto the period line (never typed over a pickup)."""
        if period_id is None:
            return
        adv = calc.drive_advance([f.chainage_m for f in await self.repo.faces_of(u.id, period_id)])
        e = await self.repo.entry_for(period_id, u.id)
        if e is not None and adv is not None:
            e.actual_advance_m = adv  # type: ignore[assignment]
            await self.session.flush()

    async def add_profile(self, u: MineUnit, data: ProfileIn) -> ProfileOut:
        area = data.actual_area_m2 if data.actual_area_m2 is not None else float(calc.section_area(list(data.ring)))
        if area <= 0:
            raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, "The profile outline has no area")
        p = MineDriveProfile(
            project_id=u.project_id,
            unit_id=u.id,
            period_id=data.period_id,
            chainage_m=_q(data.chainage_m, "0.001"),
            actual_area_m2=_q(area, "0.001"),
            design_area_m2=_q(data.design_area_m2, "0.001"),
            source="outline" if data.actual_area_m2 is None else "manual",
        )
        await self.repo.add(p)
        return self._profile_out(u, p)

    async def import_profiles(self, u: MineUnit, data: ProfileImport) -> tuple[list[ProfileOut], list[str]]:
        """CSV with ``chainage`` and ``area`` (optional ``design_area``); bad rows are reported, never guessed."""
        body = data.text.lstrip("﻿")
        delim = ";" if body[:2048].count(";") > body[:2048].count(",") else ","
        out: list[ProfileOut] = []
        problems: list[str] = []
        for i, row in enumerate(csv.DictReader(io.StringIO(body), delimiter=delim), start=2):
            r = {(k or "").strip().lower(): (v or "").strip().replace(",", ".") for k, v in row.items()}
            try:
                ch = float(r.get("chainage") or r.get("ch") or "")
                area = float(r.get("area") or r.get("actual_area") or "")
                design = float(r["design_area"]) if r.get("design_area") else None
            except ValueError:
                problems.append(f"line {i}")
                continue
            if ch < 0 or area <= 0:
                problems.append(f"line {i}")
                continue
            out.append(
                await self.add_profile(
                    u, ProfileIn(chainage_m=ch, actual_area_m2=area, design_area_m2=design, period_id=data.period_id)
                )
            )
        return out, problems

    async def drive_summary(self, u: MineUnit, period_id: uuid.UUID | None) -> DriveSummary:
        faces = await self.repo.faces_of(u.id, period_id)
        profiles = await self.repo.profiles_of(u.id, period_id)
        advance = calc.drive_advance([f.chainage_m for f in faces])
        density = u.density_t_m3
        design = u.design_area_m2
        r = None
        if profiles and design:
            chs = [p.chainage_m for p in profiles]
            length = advance if advance is not None else (max(chs) - min(chs))
            r = calc.drive_profiles(design, [p.actual_area_m2 for p in profiles], length, density)
        return DriveSummary(
            faces=len(faces),
            advance_m=_f(advance),
            profiles=len(profiles),
            design_area_m2=_f(design),
            mean_actual_m2=_f(r.mean_actual_m2) if r else None,
            overbreak_pct=_f(r.overbreak_pct) if r else None,
            excess_m3=_f(r.excess_m3) if r else None,
            excess_t=_f(r.excess_t) if r else None,
            under_count=r.under_count if r else 0,
        )

    async def drive_context(self, u: MineUnit, p: MinePeriod | None) -> dict[str, Any]:
        """The ``drive`` section of the mine rule payload (empty for surface units)."""
        if u.unit_type not in calc.UNDERGROUND:
            return {}
        profiles = await self.repo.profiles_of(u.id, p.id if p else None)
        tol = p.overbreak_tol_pct if p else None
        outside = [float(x.chainage_m) for x in profiles if self._inside(u, x.chainage_m) is False]
        ctx: dict[str, Any] = {"unit": u.name, "outside": outside, "tol_pct": _f(tol)}
        if profiles and u.design_area_m2:
            r = calc.drive_profiles(u.design_area_m2, [x.actual_area_m2 for x in profiles], 1, None, tol)
            if r is not None:
                ctx["overbreak_pct"] = float(r.overbreak_pct)
                ctx["under_count"] = r.under_count if tol is not None else 0
        return ctx

    async def drive_detail(self, u: MineUnit, period: MinePeriod | None, locale: str = "en") -> DriveDetail:
        from app.core.validation.engine import validation_engine  # noqa: PLC0415
        from app.modules.mine_survey.service import MineService  # noqa: PLC0415
        from app.modules.mine_survey.validators import MINE_RULE_SET  # noqa: PLC0415

        pid = period.id if period else None
        report = await validation_engine.validate(
            data={"entry": {}, "drive": await self.drive_context(u, period)},
            rule_sets=[MINE_RULE_SET],
            target_type="mine_unit",
            target_id=str(u.id),
            project_id=str(u.project_id),
            metadata={"locale": locale},
        )
        return DriveDetail(
            unit=MineService(self.session)._unit_out(u),  # noqa: SLF001
            faces=[self._face_out(f) for f in await self.repo.faces_of(u.id, pid)],
            profiles=[self._profile_out(u, x) for x in await self.repo.profiles_of(u.id, pid)],
            summary=await self.drive_summary(u, pid),
            findings=_findings(report),
        )

    # ── Blast patterns ─────────────────────────────────────────────────────

    async def get_pattern(self, pattern_id: uuid.UUID) -> MineBlastPattern:
        p = await self.session.get(MineBlastPattern, pattern_id)
        if p is None:
            raise _err(status.HTTP_404_NOT_FOUND, "Blast pattern not found")
        return p

    @staticmethod
    def _check(p: MineBlastPattern, h: MineBlastHole) -> calc.HoleCheck:
        return calc.hole_check(
            h.design_e,
            h.design_n,
            h.design_depth_m,
            h.drilled_e,
            h.drilled_n,
            h.drilled_depth_m,
            p.collar_tol_m,
            p.depth_tol_m,
        )

    def _hole_out(self, p: MineBlastPattern, h: MineBlastHole) -> HoleOut:
        c = self._check(p, h)
        return HoleOut(
            id=h.id,
            hole_id=h.hole_id,
            design_e=float(h.design_e),
            design_n=float(h.design_n),
            design_z=_f(h.design_z),
            design_depth_m=_f(h.design_depth_m),
            drilled_e=_f(h.drilled_e),
            drilled_n=_f(h.drilled_n),
            drilled_z=_f(h.drilled_z),
            drilled_depth_m=_f(h.drilled_depth_m),
            collar_offset_m=_f(c.collar_offset_m),
            depth_diff_m=_f(c.depth_diff_m),
            collar_ok=c.collar_ok,
            depth_ok=c.depth_ok,
        )

    def _pattern_out(self, p: MineBlastPattern, holes: list[MineBlastHole]) -> PatternOut:
        checks = [self._check(p, h) for h in holes]
        return PatternOut(
            id=p.id,
            project_id=p.project_id,
            unit_id=p.unit_id,
            code=p.code,
            name=p.name,
            collar_tol_m=_f(p.collar_tol_m),
            depth_tol_m=_f(p.depth_tol_m),
            note=p.note,
            holes=len(holes),
            drilled=sum(1 for h in holes if h.drilled_e is not None or h.drilled_depth_m is not None),
            failed=sum(1 for c in checks if c.collar_ok is False or c.depth_ok is False),
        )

    async def list_patterns(self, project_id: uuid.UUID) -> list[PatternOut]:
        return [self._pattern_out(p, await self.repo.holes_of(p.id)) for p in await self.repo.list_patterns(project_id)]

    async def pattern_detail(
        self, p: MineBlastPattern, locale: str = "en", problems: list[str] | None = None
    ) -> PatternDetail:
        from app.core.validation.engine import validation_engine  # noqa: PLC0415

        holes = await self.repo.holes_of(p.id)
        items = [self._hole_out(p, h) for h in holes]
        report = await validation_engine.validate(
            data={
                "holes": [
                    {
                        "id": h.hole_id,
                        "collar_ok": h.collar_ok,
                        "depth_ok": h.depth_ok,
                        "collar_offset": f"{h.collar_offset_m:.3f}" if h.collar_offset_m is not None else "",
                        "depth_diff": f"{h.depth_diff_m:+.3f}" if h.depth_diff_m is not None else "",
                        "collar_tol": f"{p.collar_tol_m}" if p.collar_tol_m is not None else "",
                        "depth_tol": f"{p.depth_tol_m}" if p.depth_tol_m is not None else "",
                    }
                    for h in items
                ]
            },
            rule_sets=[BLAST_RULE_SET],
            target_type="mine_blast_pattern",
            target_id=str(p.id),
            project_id=str(p.project_id),
            metadata={"locale": locale},
        )
        return PatternDetail(
            **self._pattern_out(p, holes).model_dump(), items=items, findings=_findings(report), problems=problems or []
        )

    async def create_pattern(
        self, project_id: uuid.UUID, data: PatternCreate, user_id: str
    ) -> tuple[MineBlastPattern, list[str]]:
        top = 0
        for c in await self.repo.pattern_codes(project_id):
            if c.startswith("BP-") and c[3:].isdigit():
                top = max(top, int(c[3:]))
        p = MineBlastPattern(
            project_id=project_id,
            unit_id=data.unit_id,
            code=f"BP-{top + 1:03d}",
            name=data.name.strip(),
            collar_tol_m=_q(data.collar_tol_m, "0.001"),
            depth_tol_m=_q(data.depth_tol_m, "0.001"),
            note=data.note,
            created_by=_uuid(user_id),
        )
        await self.repo.add(p)
        problems: list[str] = []
        if data.design_text.strip():
            rows, problems = calc.parse_holes(data.design_text)
            seen: set[str] = set()
            for r in rows:
                if r.hole in seen:
                    problems.append(f"hole {r.hole}: listed twice, the first one is kept")
                    continue
                seen.add(r.hole)
                self.session.add(
                    MineBlastHole(
                        project_id=project_id,
                        pattern_id=p.id,
                        hole_id=r.hole[:64],
                        design_e=r.e,
                        design_n=r.n,
                        design_z=r.z,
                        design_depth_m=r.depth_m,
                    )
                )
            await self.session.flush()
        return p, problems

    async def update_pattern(self, p: MineBlastPattern, data: PatternUpdate) -> None:
        sent = data.model_fields_set
        if data.name is not None:
            p.name = data.name.strip()
        for name in ("collar_tol_m", "depth_tol_m"):
            if name in sent:
                setattr(p, name, _q(getattr(data, name), "0.001"))
        if data.note is not None:
            p.note = data.note
        await self.session.flush()

    async def import_drilled(self, p: MineBlastPattern, data: DrilledImport) -> list[str]:
        rows, problems = calc.parse_holes(data.text)
        holes = {h.hole_id: h for h in await self.repo.holes_of(p.id)}
        for r in rows:
            h = holes.get(r.hole)
            if h is None:
                problems.append(f"hole {r.hole}: not in the pattern")
                continue
            h.drilled_e, h.drilled_n, h.drilled_z, h.drilled_depth_m = r.e, r.n, r.z, r.depth_m
            h.drilled_on = data.drilled_on or date.today()
        await self.session.flush()
        return problems

    async def stake_list(self, p: MineBlastPattern) -> str:
        """Design collars as a PNEZD CSV for the instrument (depth in the description)."""
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        for h in await self.repo.holes_of(p.id):
            depth = f"depth {h.design_depth_m}" if h.design_depth_m is not None else ""
            w.writerow(
                [
                    h.hole_id,
                    f"{h.design_n:.3f}",
                    f"{h.design_e:.3f}",
                    f"{h.design_z:.3f}" if h.design_z is not None else "",
                    depth,
                ]
            )
        return buf.getvalue()


__all__ = ["MineDepthService"]
