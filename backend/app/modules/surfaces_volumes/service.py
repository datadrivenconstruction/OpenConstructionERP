# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Surfaces and volumes business logic.

The computer suggests, the surveyor confirms: a new calculation is a draft
with a confidence score; only someone holding ``survey.confirm`` confirms it,
errors block that, and every warning has to be acknowledged by rule id. A
confirmed result is locked. Sending it to a BOQ line or a progress entry writes
an audit row and a line on the result's History.
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import numpy as np
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.surfaces_volumes import volumes as vol
from app.modules.surfaces_volumes.landxml import parse_landxml
from app.modules.surfaces_volumes.models import SurveySurface, SurveyVolume, SurveyVolumeEvent
from app.modules.surfaces_volumes.repository import VolumesRepository
from app.modules.surfaces_volumes.schemas import (
    BoqPositionHit,
    ConfirmRequest,
    Finding,
    LandXmlImport,
    LandXmlResult,
    RecordProgress,
    RecordProgressResult,
    SendToBoq,
    SendToBoqResult,
    SurfaceFromPoints,
    SurfaceOut,
    VolumeCreate,
    VolumeDetail,
    VolumeDuplicate,
    VolumeEventOut,
    VolumeOut,
    VolumeSummary,
    VolumeUpdate,
)
from app.modules.surfaces_volumes.tin import Tin
from app.modules.surfaces_volumes.validators import VOLUME_RULE_SET

logger = logging.getLogger(__name__)

#: A surface kept inline in the database; bigger ones go through the scan converter.
MAX_SURFACE_POINTS = 200_000
FORMULA = "survey.volume({code})"


def _err(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def _bad(detail: str) -> HTTPException:
    return _err(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)


def _d(value: float | None, places: str = "0.001") -> Decimal | None:
    return None if value is None else Decimal(repr(float(value))).quantize(Decimal(places))


def _f(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _next_code(prefix: str, codes: list[str]) -> str:
    top = 0
    for c in codes:
        if c.startswith(prefix):
            tail = c[len(prefix) :]
            if tail.isdigit():
                top = max(top, int(tail))
    return f"{prefix}{top + 1:03d}"


def tin_of(surface: SurveySurface) -> Tin:
    """The stored surface as a :class:`Tin`."""
    verts = surface.vertices or []
    e = [float(v[0]) for v in verts]
    n = [float(v[1]) for v in verts]
    z = [float(v[2]) for v in verts]
    if surface.faces:
        return Tin.from_faces(e, n, z, [tuple(f) for f in surface.faces])
    return Tin.from_points(e, n, z)


def _surface_out(s: SurveySurface, in_use: int = 0) -> SurfaceOut:
    out = SurfaceOut.model_validate(s)
    out.area_m2 = float(s.area_m2 or 0)
    out.z_min, out.z_max = _f(s.z_min), _f(s.z_max)
    out.in_use = in_use
    out.breakline_count = len(s.breaklines or [])
    return out


async def surface_findings(data: dict[str, Any], project_id: str, locale: str = "en") -> list[Finding]:
    """SRV-080..082 over a surface build or a staged run."""
    from app.core.validation.engine import validation_engine  # noqa: PLC0415
    from app.modules.surfaces_volumes.surface_validators import SURFACE_RULE_SET  # noqa: PLC0415

    report = await validation_engine.validate(
        data=data,
        rule_sets=[SURFACE_RULE_SET],
        target_type="survey_surface",
        target_id=str((data.get("surface") or {}).get("code") or ""),
        project_id=project_id,
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
        for r in report.results
        if not r.passed
    ]


def quantity_of(v: SurveyVolume, kind: str) -> float:
    """The m3 a send or progress entry carries: cut, fill, net or loose cut."""
    cut, fill = float(v.cut_m3 or 0), float(v.fill_m3 or 0)
    if kind == "fill":
        return fill
    if kind == "net":
        return cut - fill
    if kind == "loose_cut":
        return cut * float(v.swell_factor or 1)
    return cut


class VolumesService:
    """Stateless operations over one request's session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = VolumesRepository(session)

    # ── Context from survey_core ───────────────────────────────────────────

    async def _project_epsg(self, project_id: uuid.UUID) -> int | None:
        from app.modules.survey_core.repository import SurveyRepository  # noqa: PLC0415

        crs = await SurveyRepository(self.session).get_crs(project_id)
        return crs.horizontal_epsg if crs and not crs.is_local_grid else None

    async def _coverage_floor(self, project_id: uuid.UUID) -> float | None:
        from app.modules.survey_core.service import SurveyService  # noqa: PLC0415

        return (await SurveyService(self.session).profile(project_id)).coverage_min_pct

    async def _audit(self, action: str, v: SurveyVolume, user_id: str, details: dict[str, Any]) -> None:
        try:
            from app.core.audit import audit_log  # noqa: PLC0415

            await audit_log(
                self.session,
                action=action,
                entity_type="survey_volume",
                entity_id=str(v.id),
                user_id=str(_uuid(user_id)) if _uuid(user_id) else None,
                details={"code": v.code, "project_id": str(v.project_id), **details},
            )
        except Exception:  # noqa: BLE001 - the audit trail must not undo the change it records
            logger.exception("volumes: audit entry for %s failed", v.id)

    async def _event(
        self,
        v: SurveyVolume,
        action: str,
        user_id: str,
        *,
        target_type: str = "",
        target_id: str = "",
        quantity: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        uid = _uuid(user_id)
        self.session.add(
            SurveyVolumeEvent(
                project_id=v.project_id,
                volume_id=v.id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                quantity=_d(quantity),
                details=details or {},
                user_id=uid,
                user_name=await self.repo.user_name(uid),
            )
        )
        await self.session.flush()

    # ── Surfaces ───────────────────────────────────────────────────────────

    async def list_surfaces(self, project_id: uuid.UUID) -> list[SurfaceOut]:
        usage = await self.repo.surface_usage(project_id)
        return [_surface_out(s, usage.get(s.id, 0)) for s in await self.repo.list_surfaces(project_id)]

    async def get_surface(self, surface_id: uuid.UUID) -> SurveySurface:
        s = await self.repo.get_surface(surface_id)
        if s is None:
            raise _err(status.HTTP_404_NOT_FOUND, "Not found")
        return s

    async def _store_surface(
        self,
        project_id: uuid.UUID,
        tin: Tin,
        *,
        name: str,
        source: str,
        user_id: str,
        epsg: int | None,
        point_set_id: uuid.UUID | None = None,
        filename: str = "",
        note: str = "",
        tier: str | None = None,
        breaklines: list | None = None,
    ) -> SurveySurface:
        if tin.point_count > MAX_SURFACE_POINTS:
            raise _bad(f"{tin.point_count} points is more than {MAX_SURFACE_POINTS}: decimate the surface first")
        if tin.triangle_count == 0:
            raise _bad("These points do not form a surface: at least three points not on one line are needed")
        codes = await self.repo.codes(SurveySurface, project_id)
        surface = SurveySurface(
            project_id=project_id,
            code=_next_code("S-", codes),
            name=name.strip()[:255],
            source=source,
            point_set_id=point_set_id,
            source_filename=filename[:255],
            epsg=epsg,
            accuracy_tier=tier,
            point_count=tin.point_count,
            triangle_count=tin.triangle_count,
            area_m2=_d(tin.area()),
            z_min=_d(float(tin.z.min()), "0.0001"),
            z_max=_d(float(tin.z.max()), "0.0001"),
            vertices=[
                [round(float(a), 4), round(float(b), 4), round(float(c), 4)]
                for a, b, c in zip(tin.e, tin.n, tin.z, strict=True)
            ],
            faces=[[int(i), int(j), int(k)] for i, j, k in tin.tri],
            note=note,
            created_by=_uuid(user_id),
            breaklines=breaklines or None,
        )
        await self.repo.add(surface)
        return surface

    async def surface_from_points(self, project_id: uuid.UUID, data: SurfaceFromPoints, user_id: str) -> SurfaceOut:
        from app.modules.survey_core.models import SurveyPointSet  # noqa: PLC0415

        sets = [await self.session.get(SurveyPointSet, sid) for sid in data.point_set_ids]
        if any(s is None or s.project_id != project_id for s in sets):
            raise _err(status.HTTP_404_NOT_FOUND, "Point set not found")
        epsgs = {s.stored_epsg for s in sets if s is not None}
        if len(epsgs) > 1:
            raise _bad("The point sets are in different coordinate systems")
        pts = [(e, n, z) for e, n, z in await self.repo.point_rows(list(data.point_set_ids)) if z is not None]
        if len(pts) < 3:
            raise _bad("A surface needs at least three points with a height")
        lines = [[(float(a), float(b), float(c)) for a, b, c in line] for line in data.breaklines]
        if data.breakline_codes:
            strung: dict[str, list[tuple[float, float, float]]] = {}
            for code, e, n, z in await self.repo.coded_rows(list(data.point_set_ids), list(data.breakline_codes)):
                strung.setdefault(code, []).append((e, n, z))
            lines.extend(line for line in strung.values() if len(line) >= 2)
        if lines or data.boundary:
            tin = Tin.from_points_with_breaklines(
                [p[0] for p in pts], [p[1] for p in pts], [p[2] for p in pts], lines, data.boundary
            )
        else:
            tin = Tin.from_points([p[0] for p in pts], [p[1] for p in pts], [p[2] for p in pts])
        surface = await self._store_surface(
            project_id,
            tin,
            name=data.name,
            source="points",
            user_id=user_id,
            epsg=next(iter(epsgs)),
            point_set_id=data.point_set_ids[0],
            filename=sets[0].source_filename if sets[0] else "",
            note=data.note,
            breaklines=[[[round(a, 4), round(b, 4), round(c, 4)] for a, b, c in line] for line in lines],
        )
        out = _surface_out(surface)
        out.findings = await surface_findings(
            {"surface": {"code": surface.code, "missed_segments": tin.missed_segments}}, str(project_id)
        )
        return out

    async def import_landxml(self, project_id: uuid.UUID, data: LandXmlImport, user_id: str) -> LandXmlResult:
        try:
            parsed = parse_landxml(data.text)
        except ValueError as exc:
            raise _bad(str(exc)) from exc
        if not parsed.surfaces:
            raise _bad("The LandXML file has no surface")
        project_epsg = await self._project_epsg(project_id)
        if parsed.epsg and project_epsg and parsed.epsg != project_epsg:
            raise _bad(
                f"The file is in EPSG {parsed.epsg} and the project in EPSG {project_epsg}: "
                "export the surface in the project system; nothing is converted silently"
            )
        out = []
        for i, s in enumerate(parsed.surfaces):
            tin = Tin.from_faces(s.e, s.n, s.z, s.faces) if s.faces else Tin.from_points(s.e, s.n, s.z)
            name = data.name if data.name and len(parsed.surfaces) == 1 else s.name
            stored = await self._store_surface(
                project_id,
                tin,
                name=name or f"Surface {i + 1}",
                source="landxml",
                user_id=user_id,
                epsg=parsed.epsg or project_epsg,
                filename=data.filename,
            )
            out.append(_surface_out(stored))
        return LandXmlResult(
            surfaces=out, problems=parsed.problems, declared_epsg=parsed.epsg, project_epsg=project_epsg
        )

    async def delete_surface(self, surface: SurveySurface) -> None:
        if await self.repo.locked_usage(surface.id):
            raise _err(status.HTTP_409_CONFLICT, "A confirmed calculation uses this surface")
        await self.repo.delete(surface)

    # ── Calculations ───────────────────────────────────────────────────────

    async def _surfaces_for(self, project_id: uuid.UUID, base_id: uuid.UUID | None, compare_id: uuid.UUID | None):
        if base_id is None or compare_id is None:
            raise _bad("A surface of this calculation was deleted: duplicate it with two surfaces")
        if base_id == compare_id:
            raise _bad("Base and compare must be two different surfaces")
        base = await self.get_surface(base_id)
        compare = await self.get_surface(compare_id)
        if base.project_id != project_id or compare.project_id != project_id:
            raise _err(status.HTTP_404_NOT_FOUND, "Surface not found")
        if base.epsg and compare.epsg and base.epsg != compare.epsg:
            raise _bad(f"The surfaces are in EPSG {base.epsg} and EPSG {compare.epsg}")
        return base, compare

    async def _compute(self, v: SurveyVolume) -> None:
        base, compare = await self._surfaces_for(v.project_id, v.base_surface_id, v.compare_surface_id)
        cell = float(v.cell_size_m) if (v.cell_size_m and not v.cell_auto) else None
        ring = [(float(p[0]), float(p[1])) for p in v.boundary] if v.boundary else None
        try:
            r = vol.compute(tin_of(base), tin_of(compare), v.method, cell, ring)
        except ValueError as exc:
            raise _bad(str(exc)) from exc
        tier = compare.accuracy_tier if vol.is_coarse(compare.accuracy_tier) else base.accuracy_tier
        v.base_name, v.compare_name = base.name, compare.name
        v.cell_size_m = _d(r.cell_size) if r.cell_size else None
        v.cut_m3, v.fill_m3, v.net_m3 = _d(r.cut), _d(r.fill), _d(r.net)  # type: ignore[assignment]
        v.calc_area_m2, v.covered_area_m2 = _d(r.calc_area), _d(r.covered_area)  # type: ignore[assignment]
        v.coverage_pct = _d(r.coverage_pct, "0.01")  # type: ignore[assignment]
        v.crs_epsg = base.epsg or compare.epsg
        v.accuracy_tier = tier
        v.confidence = vol.confidence(r.coverage_pct, tier, bool(v.crs_epsg))
        v.heat = r.heat
        v.sections = r.sections or None
        v.computed_at = datetime.now(UTC)

    async def _context(self, v: SurveyVolume, last_sent: str = "") -> dict[str, Any]:
        return {
            "volume": {
                "code": v.code,
                "coverage_pct": _f(v.coverage_pct),
                "coverage_min_pct": await self._coverage_floor(v.project_id),
                "accuracy_tier": v.accuracy_tier,
                "override_reason": v.override_reason,
                "last_sent_quantity": last_sent,
                "swell_factor": _f(v.swell_factor),
            }
        }

    async def findings(self, v: SurveyVolume, locale: str = "en") -> list[Finding]:
        from app.core.validation.engine import validation_engine  # noqa: PLC0415

        last = ""
        for ev in reversed(await self.repo.events(v.id)):
            if ev.action == "sent_boq":
                last = str((ev.details or {}).get("quantity_kind") or "")
                break
        report = await validation_engine.validate(
            data=await self._context(v, last),
            rule_sets=[VOLUME_RULE_SET],
            target_type="survey_volume",
            target_id=str(v.id),
            project_id=str(v.project_id),
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
            for r in report.results
            if not r.passed
        ]

    async def _out(self, v: SurveyVolume, locale: str = "en", detail: bool = False) -> VolumeOut | VolumeDetail:
        from app.modules.survey_core import crs as crs_lib  # noqa: PLC0415

        name = ""
        if v.crs_epsg:
            try:
                name = crs_lib.describe(v.crs_epsg).name
            except ValueError:
                name = ""
        cut, fill = float(v.cut_m3 or 0), float(v.fill_m3 or 0)
        data = {
            "id": v.id,
            "project_id": v.project_id,
            "code": v.code,
            "name": v.name,
            "base_surface_id": v.base_surface_id,
            "compare_surface_id": v.compare_surface_id,
            "base_name": v.base_name,
            "compare_name": v.compare_name,
            "method": v.method,
            "cell_size_m": _f(v.cell_size_m),
            "cell_auto": v.cell_auto,
            "boundary": v.boundary,
            "material": v.material,
            "swell_factor": float(v.swell_factor or 1),
            "shrink_factor": float(v.shrink_factor or 1),
            "cut_m3": cut,
            "fill_m3": fill,
            "net_m3": float(v.net_m3 or 0),
            "loose_cut_m3": round(cut * float(v.swell_factor or 1), 3),
            "fill_bank_m3": round(fill / float(v.shrink_factor or 1), 3),
            "calc_area_m2": float(v.calc_area_m2 or 0),
            "covered_area_m2": float(v.covered_area_m2 or 0),
            "coverage_pct": float(v.coverage_pct or 0),
            "confidence": v.confidence,
            "crs_epsg": v.crs_epsg,
            "crs_name": name,
            "accuracy_tier": v.accuracy_tier,
            "status": v.status,
            "confirmed_by": v.confirmed_by,
            "confirmed_by_name": v.confirmed_by_name,
            "confirmed_at": v.confirmed_at,
            "override_reason": v.override_reason,
            "duplicated_from_id": v.duplicated_from_id,
            "boq_position_id": v.boq_position_id,
            "computed_at": v.computed_at,
            "created_at": v.created_at,
            "findings": await self.findings(v, locale),
        }
        if detail:
            return VolumeDetail(**data, heat=v.heat, sections=v.sections)
        return VolumeOut(**data)

    async def list_volumes(self, project_id: uuid.UUID, locale: str = "en") -> list[VolumeOut]:
        return [await self._out(v, locale) for v in await self.repo.list_volumes(project_id)]

    async def get_volume(self, volume_id: uuid.UUID) -> SurveyVolume:
        v = await self.repo.get_volume(volume_id)
        if v is None:
            raise _err(status.HTTP_404_NOT_FOUND, "Not found")
        return v

    async def detail(self, v: SurveyVolume, locale: str = "en") -> VolumeDetail:
        return await self._out(v, locale, detail=True)  # type: ignore[return-value]

    async def create_volume(self, project_id: uuid.UUID, data: VolumeCreate, user_id: str) -> VolumeDetail:
        codes = await self.repo.codes(SurveyVolume, project_id)
        v = SurveyVolume(
            project_id=project_id,
            code=_next_code("V-", codes),
            name=data.name.strip(),
            base_surface_id=data.base_surface_id,
            compare_surface_id=data.compare_surface_id,
            method=data.method,
            cell_size_m=_d(data.cell_size_m) if data.cell_size_m else None,
            cell_auto=data.cell_size_m is None,
            boundary=[list(p) for p in data.boundary] if data.boundary else None,
            material=data.material,
            swell_factor=_d(data.swell_factor),  # type: ignore[arg-type]
            shrink_factor=_d(data.shrink_factor),  # type: ignore[arg-type]
            override_reason=data.override_reason.strip(),
            status="draft",
            created_by=_uuid(user_id),
        )
        await self._compute(v)
        await self.repo.add(v)
        await self._event(v, "computed", user_id, quantity=float(v.cut_m3), details=self._params(v))
        if v.override_reason:
            await self._event(v, "override", user_id, details={"rule": "VOL-003", "reason": v.override_reason})
            await self._audit("update", v, user_id, {"override": "VOL-003", "reason": v.override_reason})
        return await self.detail(v)

    @staticmethod
    def _params(v: SurveyVolume) -> dict[str, Any]:
        return {
            "method": v.method,
            "cell_size_m": _f(v.cell_size_m),
            "cell_auto": v.cell_auto,
            "swell_factor": _f(v.swell_factor),
            "shrink_factor": _f(v.shrink_factor),
            "boundary": bool(v.boundary),
            "cut_m3": _f(v.cut_m3),
            "fill_m3": _f(v.fill_m3),
            "coverage_pct": _f(v.coverage_pct),
        }

    @staticmethod
    def _locked(v: SurveyVolume) -> None:
        if v.status != "draft":
            raise _err(status.HTTP_409_CONFLICT, "A confirmed result is locked: duplicate it to change anything")

    async def update_volume(self, v: SurveyVolume, data: VolumeUpdate, user_id: str) -> VolumeDetail:
        self._locked(v)
        if data.name is not None:
            v.name = data.name.strip()
        if data.method is not None:
            v.method = data.method
        if data.cell_auto:
            v.cell_auto, v.cell_size_m = True, None
        elif data.cell_size_m is not None:
            v.cell_auto, v.cell_size_m = False, _d(data.cell_size_m)
        if data.clear_boundary:
            v.boundary = None
        elif data.boundary is not None:
            if len(data.boundary) < 3:
                raise _bad("A boundary needs at least three corners")
            v.boundary = [list(p) for p in data.boundary]
        if data.material is not None:
            v.material = data.material
        if data.swell_factor is not None:
            v.swell_factor = _d(data.swell_factor)  # type: ignore[assignment]
        if data.shrink_factor is not None:
            v.shrink_factor = _d(data.shrink_factor)  # type: ignore[assignment]
        reason_changed = data.override_reason is not None and data.override_reason.strip() != v.override_reason
        if data.override_reason is not None:
            v.override_reason = data.override_reason.strip()
        await self._compute(v)
        await self.session.flush()
        await self._event(v, "computed", user_id, quantity=float(v.cut_m3), details=self._params(v))
        if reason_changed and v.override_reason:
            await self._event(v, "override", user_id, details={"rule": "VOL-003", "reason": v.override_reason})
            await self._audit("update", v, user_id, {"override": "VOL-003", "reason": v.override_reason})
        return await self.detail(v)

    async def delete_volume(self, v: SurveyVolume) -> None:
        self._locked(v)
        await self.repo.delete(v)

    async def confirm(self, v: SurveyVolume, data: ConfirmRequest, user_id: str, locale: str = "en") -> VolumeDetail:
        self._locked(v)
        found = await self.findings(v, locale)
        errors = [f.rule_id for f in found if f.severity == "error"]
        if errors:
            raise _err(status.HTTP_409_CONFLICT, f"Fix {', '.join(errors)} before confirming")
        warnings = sorted({f.rule_id for f in found if f.severity == "warning"})
        missing = [w for w in warnings if w not in data.acknowledge]
        if missing:
            raise _err(status.HTTP_409_CONFLICT, f"Acknowledge {', '.join(missing)} before confirming")
        uid = _uuid(user_id)
        v.status = "confirmed"
        v.confirmed_by = uid
        v.confirmed_by_name = await self.repo.user_name(uid)
        v.confirmed_at = datetime.now(UTC)
        v.acknowledged = warnings
        await self.session.flush()
        await self._event(v, "confirmed", user_id, quantity=float(v.cut_m3), details={"acknowledged": warnings})
        await self._audit("approve", v, user_id, {"acknowledged": warnings, **self._params(v)})
        return await self.detail(v, locale)

    async def duplicate(self, v: SurveyVolume, data: VolumeDuplicate, user_id: str) -> VolumeDetail:
        codes = await self.repo.codes(SurveyVolume, v.project_id)
        copy = SurveyVolume(
            project_id=v.project_id,
            code=_next_code("V-", codes),
            name=(data.name or f"{v.name} (copy)").strip()[:255],
            base_surface_id=v.base_surface_id,
            compare_surface_id=v.compare_surface_id,
            method=data.method or v.method,
            cell_size_m=_d(data.cell_size_m) if data.cell_size_m else v.cell_size_m,
            cell_auto=v.cell_auto if data.cell_size_m is None else False,
            boundary=v.boundary,
            material=data.material if data.material is not None else v.material,
            swell_factor=_d(data.swell_factor) if data.swell_factor is not None else v.swell_factor,  # type: ignore[arg-type]
            shrink_factor=_d(data.shrink_factor) if data.shrink_factor is not None else v.shrink_factor,  # type: ignore[arg-type]
            override_reason=v.override_reason,
            status="draft",
            duplicated_from_id=v.id,
            created_by=_uuid(user_id),
        )
        await self._compute(copy)
        await self.repo.add(copy)
        await self._event(
            copy, "duplicated", user_id, target_type="survey_volume", target_id=v.code, details=self._params(copy)
        )
        await self._event(v, "duplicated", user_id, target_type="survey_volume", target_id=copy.code)
        return await self.detail(copy)

    async def history(self, v: SurveyVolume) -> list[VolumeEventOut]:
        out = []
        for ev in await self.repo.events(v.id):
            item = VolumeEventOut.model_validate(ev)
            item.quantity = _f(ev.quantity)
            out.append(item)
        return out

    # ── Sending results onward ─────────────────────────────────────────────

    @staticmethod
    def _sendable(v: SurveyVolume) -> None:
        if v.status not in ("confirmed", "sent"):
            raise _err(status.HTTP_409_CONFLICT, "Confirm the result before sending it anywhere")

    def source_chip(self, v: SurveyVolume, kind: str) -> dict[str, Any]:
        """What travels with a quantity so the estimator can trace it."""
        return {
            "kind": "survey.volume",
            "ref": v.code,
            "volume_id": str(v.id),
            "formula": FORMULA.format(code=v.code),
            "quantity_kind": kind,
            "method": v.method,
            "cell_size_m": _f(v.cell_size_m),
            "crs_epsg": v.crs_epsg,
            "coverage_pct": _f(v.coverage_pct),
            "accuracy_tier": v.accuracy_tier,
            "confirmed_by": v.confirmed_by_name,
            "confirmed_at": v.confirmed_at.isoformat() if v.confirmed_at else None,
        }

    async def _position_in_project(self, v: SurveyVolume, position_id: uuid.UUID) -> tuple[Any, Any]:
        found = await self.repo.boq_position(position_id)
        if found is None or found[1].project_id != v.project_id:
            raise _err(status.HTTP_404_NOT_FOUND, "BOQ position not found in this project")
        return found

    async def search_positions(self, project_id: uuid.UUID, q: str, unit: str) -> list[BoqPositionHit]:
        return [
            BoqPositionHit(
                id=p.id,
                boq_id=p.boq_id,
                boq_name=boq_name,
                ordinal=p.ordinal,
                description=p.description,
                unit=p.unit,
                quantity=str(p.quantity),
            )
            for p, boq_name in await self.repo.search_positions(project_id, q, unit)
        ]

    async def send_to_boq(self, v: SurveyVolume, data: SendToBoq, user_id: str, locale: str = "en") -> SendToBoqResult:
        from app.modules.boq.schemas import PositionUpdate  # noqa: PLC0415
        from app.modules.boq.service import BOQService  # noqa: PLC0415

        self._sendable(v)
        if any(f.severity == "error" for f in await self.findings(v, locale)):
            raise _err(status.HTTP_409_CONFLICT, "The result has errors: it cannot feed a BOQ quantity")
        position, _boq = await self._position_in_project(v, data.position_id)
        sent = round(quantity_of(v, data.quantity), 3)
        if sent < 0:
            raise _bad("Net volume is fill: send the fill quantity instead")
        old = float(position.quantity or 0)
        new = sent if data.mode == "replace" else round(old + sent, 3)
        chip = self.source_chip(v, data.quantity)
        meta = dict(position.metadata_ or {})
        meta["quantity_source"] = chip
        updated = await BOQService(self.session).update_position(
            position.id, PositionUpdate(quantity=new, metadata=meta), actor_id=_uuid(user_id)
        )
        v.status = "sent"
        v.boq_position_id = position.id
        await self.session.flush()
        details = {
            "mode": data.mode,
            "quantity_kind": data.quantity,
            "old": old,
            "new": new,
            "ordinal": position.ordinal,
        }
        await self._event(
            v,
            "sent_boq",
            user_id,
            target_type="boq_position",
            target_id=str(position.id),
            quantity=sent,
            details=details,
        )
        await self._audit("update", v, user_id, {"sent_to": "boq_position", "position_id": str(position.id), **details})
        return SendToBoqResult(
            position_id=position.id,
            ordinal=updated.ordinal,
            description=updated.description,
            unit=updated.unit,
            quantity=f"{float(updated.quantity):.3f}",
            sent_m3=sent,
            formula=chip["formula"],
            source=chip,
            findings=await self.findings(v, locale),
        )

    async def record_progress(self, v: SurveyVolume, data: RecordProgress, user_id: str) -> RecordProgressResult:
        from app.modules.progress.schemas import ProgressEntryCreate  # noqa: PLC0415
        from app.modules.progress.service import ProgressService  # noqa: PLC0415

        self._sendable(v)
        pid = data.position_id or v.boq_position_id
        if pid is None:
            raise _bad("Send the result to a BOQ position first, or pick the position to record against")
        position, _boq = await self._position_in_project(v, pid)
        qty = round(quantity_of(v, data.quantity), 3)
        design = float(position.quantity or 0)
        pct = 100.0 if design <= 0 else min(100.0, max(0.0, 100.0 * qty / design))
        period = data.period_label.strip() or datetime.now(UTC).strftime("%Y-%m")
        note = data.notes.strip() or f"{FORMULA.format(code=v.code)} = {qty:,.1f} m3"
        entry = await ProgressService(self.session).record_entry(
            ProgressEntryCreate(
                project_id=v.project_id,
                boq_position_id=position.id,
                period_label=period,
                percent_complete=round(pct, 3),
                notes=note,
                metadata={"quantity_source": self.source_chip(v, data.quantity), "quantity_m3": qty},
            ),
            user_id=user_id,
        )
        await self._event(
            v,
            "progress",
            user_id,
            target_type="progress_entry",
            target_id=str(entry.id),
            quantity=qty,
            details={"period": period, "percent_complete": round(pct, 3), "position_id": str(position.id)},
        )
        await self._audit("update", v, user_id, {"sent_to": "progress_entry", "entry_id": str(entry.id), "m3": qty})
        return RecordProgressResult(
            entry_id=entry.id,
            position_id=position.id,
            percent_complete=round(pct, 3),
            quantity_m3=qty,
            period_label=period,
        )

    async def note_report(self, v: SurveyVolume, user_id: str) -> None:
        await self._event(v, "report", user_id, target_type="pdf", target_id=f"{v.code}.pdf")

    # ── Summary ────────────────────────────────────────────────────────────

    async def summary(self, project_id: uuid.UUID) -> VolumeSummary:
        items = await self.repo.list_volumes(project_id)
        done = [v for v in items if v.status != "draft"]
        basis = done or items
        findings = 0
        for v in items:
            findings += sum(1 for f in await self.findings(v) if f.severity in ("error", "warning"))
        cut = sum(float(v.cut_m3 or 0) for v in basis)
        fill = sum(float(v.fill_m3 or 0) for v in basis)
        area = sum(float(v.calc_area_m2 or 0) for v in basis)
        covered = sum(float(v.covered_area_m2 or 0) for v in basis)
        return VolumeSummary(
            calculations=len(items),
            confirmed=len(done),
            cut_m3=round(cut, 3),
            fill_m3=round(fill, 3),
            net_m3=round(cut - fill, 3),
            coverage_pct=round(100.0 * covered / area, 2) if area > 0 else None,
            surfaces=len(await self.repo.list_surfaces(project_id)),
            findings=findings,
        )

    # ── Plan view ──────────────────────────────────────────────────────────

    async def plan(self, project_id: uuid.UUID, volume_id: uuid.UUID | None = None) -> dict[str, Any]:
        """GeoJSON in WGS 84 for the map: survey points, surface outlines and, for one volume, its heat cells."""
        from app.modules.survey_core import crs as crs_lib  # noqa: PLC0415
        from app.modules.survey_core.service import SurveyService  # noqa: PLC0415

        out = await SurveyService(self.session).plan(project_id)
        epsg = out["properties"]["epsg"]
        to_ll = crs_lib.wgs84_projector(epsg)
        features: list[dict[str, Any]] = out["features"]
        for s in await self.repo.list_surfaces(project_id):
            tin = tin_of(s)
            lines = []
            for a, b in tin.outline():
                p0, p1 = to_ll([tin.e[a], tin.e[b]], [tin.n[a], tin.n[b]])
                lines.append([list(p0), list(p1)])
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "MultiLineString", "coordinates": lines},
                    "properties": {"layer": "surfaces", "id": s.code, "name": s.name},
                }
            )
            for line in s.breaklines or []:
                coords = to_ll([float(v[0]) for v in line], [float(v[1]) for v in line])
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": [list(c) for c in coords]},
                        "properties": {"layer": "breaklines", "id": s.code, "name": s.name},
                    }
                )
        if volume_id is not None:
            v = await self.get_volume(volume_id)
            if v.project_id != project_id:
                raise _err(status.HTTP_404_NOT_FOUND, "Not found")
            features.extend(_heat_features(v.heat, to_ll))
        return out


def _heat_features(heat: dict | None, to_ll) -> list[dict[str, Any]]:
    if not heat:
        return []
    nx, ny, cell = int(heat["nx"]), int(heat["ny"]), float(heat["cell"])
    x0, y0 = float(heat["origin_e"]), float(heat["origin_n"])
    gx, gy = np.meshgrid(x0 + np.arange(nx + 1) * cell, y0 + np.arange(ny + 1) * cell)
    corners = to_ll(gx.ravel(), gy.ravel())
    out = []
    values = heat.get("dh") or []
    for j in range(ny):
        for i in range(nx):
            dh = values[j * nx + i] if j * nx + i < len(values) else None
            if dh is None or (isinstance(dh, float) and math.isnan(dh)):
                continue
            k = j * (nx + 1) + i
            ring = [corners[k], corners[k + 1], corners[k + nx + 2], corners[k + nx + 1], corners[k]]
            out.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]},
                    "properties": {
                        "layer": "heat",
                        "dh": dh,
                        "side": "cut" if dh > 0 else "fill" if dh < 0 else "zero",
                    },
                }
            )
    return out


__all__ = ["FORMULA", "MAX_SURFACE_POINTS", "VolumesService", "quantity_of", "surface_findings", "tin_of"]
