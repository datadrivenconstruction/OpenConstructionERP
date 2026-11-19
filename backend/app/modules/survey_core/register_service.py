# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Point register operations: one point's detail and edit, bulk actions, export, control checks.

A point whose set built a surface that a confirmed volume uses is locked: the
confirmed number must keep reading the same, so it is changed by a new import,
never by an edit.
"""

from __future__ import annotations

import logging
import math
import uuid
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.survey_core import point_export
from app.modules.survey_core.models import SurveyControlCheck, SurveyPoint, SurveyPointSet
from app.modules.survey_core.register_schemas import (
    BulkRequest,
    BulkResult,
    ControlCheckIn,
    ControlCheckOut,
    ControlListResponse,
    ControlRow,
    ExportRequest,
    PointDetail,
    PointUpdate,
    UsedBy,
)

logger = logging.getLogger(__name__)

CONTROL_KINDS = ("control", "benchmark")
_LOCKED_STATUSES = ("confirmed", "sent")


def _f(v: Decimal | float | None) -> float | None:
    return None if v is None else float(v)


def _d(v: float | None, places: str = "0.0001") -> Decimal | None:
    return None if v is None else Decimal(str(v)).quantize(Decimal(places))


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def residual(known: tuple[float, float, float | None], measured: tuple[float, float, float | None]) -> dict[str, Any]:
    """Measured minus known, in mm: dE, dN, dZ (None without both heights) and the plan distance."""
    de = (measured[0] - known[0]) * 1000.0
    dn = (measured[1] - known[1]) * 1000.0
    dz = (measured[2] - known[2]) * 1000.0 if measured[2] is not None and known[2] is not None else None
    return {
        "de_mm": round(de, 1),
        "dn_mm": round(dn, 1),
        "dz_mm": None if dz is None else round(dz, 1),
        "d2d_mm": round(math.hypot(de, dn), 1),
    }


def verdict(d2d_mm: float, tol_mm: float | None) -> str:
    if not tol_mm:
        return "no_tolerance"
    return "pass" if d2d_mm <= tol_mm else "fail"


class RegisterService:
    """Stateless point register operations over one request's session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Point detail and edit ──────────────────────────────────────────────

    async def get_point(self, point_uuid: uuid.UUID) -> SurveyPoint:
        p = await self.session.get(SurveyPoint, point_uuid)
        if p is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Point not found")
        return p

    async def _used_by(self, set_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[UsedBy]]:
        """Surfaces built from these sets, and whether a confirmed volume uses each."""
        out: dict[uuid.UUID, list[UsedBy]] = {}
        try:
            from app.modules.surfaces_volumes.models import SurveySurface, SurveyVolume  # noqa: PLC0415
        except ImportError:  # pragma: no cover - surfaces is an optional neighbour
            return out
        surfaces = (
            (await self.session.execute(select(SurveySurface).where(SurveySurface.point_set_id.in_(set_ids))))
            .scalars()
            .all()
        )
        if not surfaces:
            return out
        ids = [s.id for s in surfaces]
        vols = (
            (
                await self.session.execute(
                    select(SurveyVolume).where(
                        (SurveyVolume.base_surface_id.in_(ids)) | (SurveyVolume.compare_surface_id.in_(ids))
                    )
                )
            )
            .scalars()
            .all()
        )
        for s in surfaces:
            uses = [v for v in vols if s.id in (v.base_surface_id, v.compare_surface_id)]
            locked = any(v.status in _LOCKED_STATUSES for v in uses)
            rows = out.setdefault(s.point_set_id, [])  # type: ignore[arg-type]
            rows.append(UsedBy(kind="surface", code=s.code, name=s.name, locked=locked))
            rows.extend(
                UsedBy(kind="volume", code=v.code, name=v.name, locked=v.status in _LOCKED_STATUSES) for v in uses
            )
        return out

    async def _locked_sets(self, set_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        used = await self._used_by(set_ids)
        return {sid for sid, rows in used.items() if any(r.locked for r in rows)}

    async def detail(self, p: SurveyPoint) -> PointDetail:
        s = await self.session.get(SurveyPointSet, p.point_set_id)
        used = (await self._used_by([p.point_set_id])).get(p.point_set_id, [])
        return PointDetail(
            id=p.id,
            point_set_id=p.point_set_id,
            point_id=p.point_id,
            e=float(p.e),
            n=float(p.n),
            z=_f(p.z),
            code=p.code,
            kind=p.kind,
            sigma=_f(p.sigma),
            description=p.description,
            set_name=s.name if s else "",
            source_filename=s.source_filename if s else "",
            source_line=p.source_line,
            survey_date=s.survey_date if s else None,
            stored_epsg=s.stored_epsg if s else None,
            created_at=getattr(p, "created_at", None),
            updated_at=getattr(p, "updated_at", None),
            used_by=used,
            locked=any(u.locked for u in used),
        )

    async def update(self, p: SurveyPoint, data: PointUpdate, user_id: str) -> PointDetail:
        if p.point_set_id in await self._locked_sets([p.point_set_id]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A confirmed result uses this point: import a corrected file instead of editing",
            )
        old = {"point_id": p.point_id, "e": float(p.e), "n": float(p.n), "z": _f(p.z), "code": p.code, "kind": p.kind}
        if data.point_id is not None:
            p.point_id = data.point_id.strip()
        if data.e is not None:
            p.e = _d(data.e)  # type: ignore[assignment]
        if data.n is not None:
            p.n = _d(data.n)  # type: ignore[assignment]
        if data.clear_z:
            p.z = None
        elif data.z is not None:
            p.z = _d(data.z)
        if data.code is not None:
            p.code = data.code.strip()
        if data.kind is not None:
            p.kind = data.kind
        if data.description is not None:
            p.description = data.description
        if data.sigma is not None:
            p.sigma = _d(data.sigma)
        await self.session.flush()
        await self._audit("update", p.project_id, user_id, {"point": str(p.id), "old": old})
        return await self.detail(p)

    async def delete_point(self, p: SurveyPoint, user_id: str) -> None:
        result = await self.bulk(p.project_id, BulkRequest(ids=[p.id], action="delete"), user_id)
        if result.skipped_locked:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A confirmed result uses this point")

    # ── Bulk ───────────────────────────────────────────────────────────────

    async def _points(self, project_id: uuid.UUID, ids: list[uuid.UUID]) -> list[SurveyPoint]:
        q = select(SurveyPoint).where(SurveyPoint.project_id == project_id)
        if ids:
            q = q.where(SurveyPoint.id.in_(ids))
        q = q.order_by(SurveyPoint.point_set_id, SurveyPoint.source_line, SurveyPoint.point_id)
        return list((await self.session.execute(q)).scalars().all())

    async def _recount(self, set_ids: set[uuid.UUID]) -> None:
        for sid in set_ids:
            s = await self.session.get(SurveyPointSet, sid)
            if s is not None:
                s.point_count = int(
                    (
                        await self.session.execute(
                            select(func.count()).select_from(SurveyPoint).where(SurveyPoint.point_set_id == sid)
                        )
                    ).scalar_one()
                )

    async def bulk(self, project_id: uuid.UUID, data: BulkRequest, user_id: str) -> BulkResult:
        points = await self._points(project_id, list(data.ids))
        locked = await self._locked_sets(list({p.point_set_id for p in points}))
        free = [p for p in points if p.point_set_id not in locked]
        touched = {p.point_set_id for p in free}
        if data.action == "set_code":
            for p in free:
                p.code = data.value.strip()
        elif data.action == "set_kind":
            if data.value not in point_export_kinds():
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown point kind")
            for p in free:
                p.kind = data.value
        elif data.action == "move_to_set":
            target = await self.session.get(SurveyPointSet, data.target_set_id) if data.target_set_id else None
            if target is None or target.project_id != project_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Point set not found")
            if target.id in locked or target.id in await self._locked_sets([target.id]):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A confirmed result uses that set")
            sources = {
                s.id: s
                for s in (
                    await self.session.execute(
                        select(SurveyPointSet).where(SurveyPointSet.id.in_(touched or {target.id}))
                    )
                )
                .scalars()
                .all()
            }
            if any(s.stored_epsg != target.stored_epsg for s in sources.values()):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="The target set is in another coordinate system",
                )
            for p in free:
                p.point_set_id = target.id
            touched.add(target.id)
        elif data.action == "delete":
            if free:
                await self.session.execute(delete(SurveyPoint).where(SurveyPoint.id.in_([p.id for p in free])))
        await self.session.flush()
        await self._recount(touched)
        await self.session.flush()
        await self._audit(
            f"bulk_{data.action}",
            project_id,
            user_id,
            {"count": len(free), "value": data.value, "target_set_id": str(data.target_set_id or "")},
        )
        return BulkResult(action=data.action, affected=len(free), skipped_locked=len(points) - len(free))

    # ── Export ─────────────────────────────────────────────────────────────

    async def export(self, project_id: uuid.UUID, data: ExportRequest) -> tuple[bytes, str, str]:
        """``(body, media type, file extension)`` for the chosen points, in their stored coordinates."""
        points = await self._points(project_id, list(data.ids))
        if not points:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No points to export")
        rows = [
            point_export.ExportPoint(p.point_id, float(p.e), float(p.n), _f(p.z), p.code, p.description) for p in points
        ]
        if data.format == "dxf":
            return point_export.to_dxf(rows).encode("utf-8"), "application/dxf", "dxf"
        if data.format == "landxml":
            from app.modules.survey_core.repository import SurveyRepository  # noqa: PLC0415

            crs = await SurveyRepository(self.session).get_crs(project_id)
            epsg = crs.horizontal_epsg if crs and not crs.is_local_grid else None
            return point_export.to_landxml(rows, epsg=epsg).encode("utf-8"), "application/xml", "xml"
        text = point_export.to_csv(rows, data.preset, data.delimiter, data.header)
        return text.encode("utf-8"), "text/csv", "csv" if data.delimiter in (",", ";") else "txt"

    # ── Control ────────────────────────────────────────────────────────────

    async def _tolerance(self, project_id: uuid.UUID) -> tuple[float | None, str]:
        from app.modules.survey_core.service import SurveyService  # noqa: PLC0415

        prof = await SurveyService(self.session).profile(project_id)
        return prof.control_tol_mm, prof.label

    @staticmethod
    def _check_out(c: SurveyControlCheck, cp: SurveyPoint, tol: float | None) -> ControlCheckOut:
        r = residual((float(cp.e), float(cp.n), _f(cp.z)), (float(c.e), float(c.n), _f(c.z)))
        return ControlCheckOut(
            id=c.id,
            control_point_id=c.control_point_id,
            measured_point_id=c.measured_point_id,
            e=float(c.e),
            n=float(c.n),
            z=_f(c.z),
            verdict=verdict(r["d2d_mm"], tol),  # type: ignore[arg-type]
            note=c.note,
            created_at=getattr(c, "created_at", None),
            **r,
        )

    async def control(self, project_id: uuid.UUID) -> ControlListResponse:
        from app.modules.survey_core.service import _point_out  # noqa: PLC0415

        tol, label = await self._tolerance(project_id)
        cps = (
            (
                await self.session.execute(
                    select(SurveyPoint)
                    .where(SurveyPoint.project_id == project_id, SurveyPoint.kind.in_(CONTROL_KINDS))
                    .order_by(SurveyPoint.point_id)
                )
            )
            .scalars()
            .all()
        )
        checks = (
            (
                await self.session.execute(
                    select(SurveyControlCheck)
                    .where(SurveyControlCheck.project_id == project_id)
                    .order_by(SurveyControlCheck.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        by_cp: dict[uuid.UUID, list[SurveyControlCheck]] = {}
        for c in checks:
            by_cp.setdefault(c.control_point_id, []).append(c)
        items = []
        for cp in cps:
            outs = [self._check_out(c, cp, tol) for c in by_cp.get(cp.id, [])]
            items.append(ControlRow(point=_point_out(cp), checks=outs, latest=outs[0] if outs else None))
        failing = sum(1 for i in items if i.latest and i.latest.verdict == "fail")
        return ControlListResponse(
            items=items, total=len(items), tolerance_mm=tol, profile_label=label, failing=failing
        )

    async def check_rows(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """Latest check per control point for SRV-012."""
        listing = await self.control(project_id)
        return [
            {"point_id": i.point.point_id, "d2d_mm": i.latest.d2d_mm, "tol_mm": listing.tolerance_mm}
            for i in listing.items
            if i.latest is not None
        ]

    async def add_check(self, project_id: uuid.UUID, data: ControlCheckIn, user_id: str) -> ControlCheckOut:
        cp = await self.get_point(data.control_point_id)
        if cp.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Point not found")
        if cp.kind not in CONTROL_KINDS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Only a control point or benchmark is checked"
            )
        if data.measured_point_id is not None:
            m = await self.get_point(data.measured_point_id)
            if m.project_id != project_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Point not found")
            if m.id == cp.id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Pick a measured point, not the control"
                )
            e, n, z = float(m.e), float(m.n), _f(m.z)
        elif data.e is not None and data.n is not None:
            e, n, z = data.e, data.n, data.z
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Give a measured point or E and N"
            )
        row = SurveyControlCheck(
            project_id=project_id,
            control_point_id=cp.id,
            measured_point_id=data.measured_point_id,
            e=_d(e),
            n=_d(n),
            z=_d(z),
            note=data.note.strip(),
            created_by=_uuid(user_id),
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        tol, _label = await self._tolerance(project_id)
        await self._audit("control_check", project_id, user_id, {"control": cp.point_id, "check": str(row.id)})
        return self._check_out(row, cp, tol)

    async def delete_check(self, project_id: uuid.UUID, check_id: uuid.UUID) -> None:
        row = await self.session.get(SurveyControlCheck, check_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Check not found")
        await self.session.delete(row)
        await self.session.flush()

    # ── Audit ──────────────────────────────────────────────────────────────

    async def _audit(self, action: str, project_id: uuid.UUID, user_id: str, details: dict[str, Any]) -> None:
        try:
            from app.core.audit import audit_log  # noqa: PLC0415

            await audit_log(
                self.session,
                action=action,
                entity_type="survey_point",
                entity_id=str(project_id),
                user_id=str(_uuid(user_id)) if _uuid(user_id) else None,
                details={"project_id": str(project_id), **details},
            )
        except Exception:  # noqa: BLE001 - the audit trail must not undo the change it records
            logger.exception("survey register: audit entry failed")


def point_export_kinds() -> tuple[str, ...]:
    from app.modules.survey_core.point_io import KINDS  # noqa: PLC0415

    return KINDS


__all__ = ["CONTROL_KINDS", "RegisterService", "residual", "verdict"]
