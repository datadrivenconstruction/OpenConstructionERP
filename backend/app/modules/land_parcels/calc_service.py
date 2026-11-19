# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Parcel subdivision and merge, the boundary corner register and the setback check.

A split or merge creates new parcels that keep ``parent_ids`` and marks the
parents ``superseded``: they stay as history and drop out of checks and lists.
Nothing is written while SRV-100 reports an error.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException, status

from app.modules.land_parcels import subdivision as sub
from app.modules.land_parcels.calc_schemas import (
    CornerClassOption,
    CornerOut,
    CornerPatch,
    CornerRegisterOut,
    EdgeOut,
    MergeIn,
    PartOut,
    SetbackIn,
    SetbackOut,
    SplitIn,
    SplitOut,
    StakeCornersIn,
    StakeCornersOut,
)
from app.modules.land_parcels.calc_validators import PARCEL_CALC_RULE_SET
from app.modules.land_parcels.models import LandParcel, LandParcelPoint
from app.modules.land_parcels.schemas import BoundaryPointIn, FindingOut, ParcelCreate
from app.modules.land_parcels.service import ParcelService
from app.modules.survey_core import closure_classes as classes_lib

Pt = tuple[float, float]


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _ring(points: Sequence[LandParcelPoint]) -> list[Pt]:
    return [(float(p.e), float(p.n)) for p in points]


def _r(ring: Sequence[Pt]) -> list[list[float]]:
    return [[round(x, 4), round(y, 4)] for x, y in ring]


def corner_rows(parcel: LandParcel, points: Sequence[LandParcelPoint], markets: list[str]) -> list[dict[str, Any]]:
    """SRV-101 context rows: corners that have a class and a stated precision."""
    out = []
    for i, pt in enumerate(points):
        limit = corner_limit(points, i, pt.accuracy_class, markets)
        if limit is None or pt.accuracy_m is None:
            continue
        out.append({"id": str(parcel.id), "label": pt.label, "accuracy_m": float(pt.accuracy_m), "limit_m": limit[0]})
    return out


def corner_limit(points: Sequence[LandParcelPoint], i: int, key: str, markets: list[str]) -> tuple[float, str] | None:
    """Allowance of corner ``i`` under class ``key``: base plus ppm of the shorter adjoining side."""
    cls = classes_lib.find_corner(key, markets) if key else None
    if cls is None:
        return None
    n = len(points)
    here = points[i]
    sides = [
        math.hypot(float(points[j].e) - float(here.e), float(points[j].n) - float(here.n))
        for j in ((i - 1) % n, (i + 1) % n)
        if n > 1 and j != i
    ]
    return sub.rpp_allowance(cls.base_m, cls.ppm, min(sides) if sides else 0.0), cls.label


async def _findings(data: dict[str, Any], locale: str) -> list[FindingOut]:
    from app.core.validation.engine import validation_engine  # noqa: PLC0415

    report = await validation_engine.validate(
        data=data, rule_sets=[PARCEL_CALC_RULE_SET], target_type="land_parcels_calc", target_id="",
        metadata={"locale": locale},
    )  # fmt: skip
    return [
        FindingOut(
            rule_id=r.rule_id,
            severity=str(getattr(r.severity, "value", r.severity)),
            message=r.message,
            suggestion=r.suggestion,
            element_ref=r.element_ref,
        )
        for r in report.results
        if not r.passed
    ]


def _has_error(findings: list[FindingOut]) -> bool:
    return any(f.severity == "error" for f in findings)


class ParcelCalcService(ParcelService):
    """Subdivision, merge, corners and setbacks over the parcel register."""

    async def _points(self, parcel: LandParcel) -> list[LandParcelPoint]:
        return (await self.repo.points_by_parcel([parcel.id])).get(parcel.id, [])

    async def _child(self, parent_ids: list[LandParcel], ref: str, ring: Sequence[Pt], user_id: str) -> LandParcel:
        first = parent_ids[0]
        child = await self.create_parcel(
            first.project_id,
            ParcelCreate(
                parcel_ref=ref,
                status=first.status,  # type: ignore[arg-type]
                points=[BoundaryPointIn(label=f"{ref}-{i + 1}", e=x, n=y) for i, (x, y) in enumerate(ring)],
            ),
            user_id,
        )
        child.parent_ids = [str(p.id) for p in parent_ids]
        await self.session.flush()
        return child

    async def _supersede(
        self, parents: list[LandParcel], children: list[LandParcel], action: str, user_id: str
    ) -> None:
        for p in parents:
            p.superseded = True
            await self._audit(
                action, "land_parcel", p.id, user_id,
                {"parcel_ref": p.parcel_ref, "children": [c.parcel_ref for c in children]},
            )  # fmt: skip
        await self.session.flush()

    async def split(self, parcel: LandParcel, body: SplitIn, user_id: str, locale: str) -> SplitOut:
        if parcel.superseded:
            raise _bad("This parcel was already split or merged")
        ring = _ring(await self._points(parcel))
        if len(ring) < 3:
            raise _bad("The parcel has no boundary to split")
        try:
            if body.mode == "line":
                if body.a is None or body.b is None:
                    raise _bad("A split by line needs two points")
                cut = sub.split_by_line(ring, body.a, body.b)
                part, rest, line, position = cut.left, cut.right, cut.cut, None
            elif body.target_area is None:
                raise _bad("A split to area needs the target area")
            elif body.mode == "parallel":
                res = sub.split_parallel(ring, body.side, body.target_area)
                part, rest, line, position = res.part, res.rest, res.cut, res.position
            else:
                if body.pivot is None:
                    raise _bad("A rotating cut needs the pivot point")
                res = sub.split_rotating(ring, body.pivot, body.target_area)
                part, rest, line, position = res.part, res.rest, res.cut, res.position
        except sub.SubdivisionError as exc:
            raise _bad(str(exc)) from exc
        parent_area = sub.area(ring)
        refs = [*body.refs, f"{parcel.parcel_ref}/1", f"{parcel.parcel_ref}/2"]
        refs = [r.strip() for r in refs if r.strip()][:2]
        parts = [
            PartOut(ref=refs[0], area=sub.area(part), ring=_r(part)),
            PartOut(ref=refs[1], area=sub.area(rest), ring=_r(rest)),
        ]
        findings = await _findings(
            {
                "subdivisions": [
                    {"ref": str(parcel.id), "parent_area": parent_area, "a": parts[0].area, "b": parts[1].area}
                ]
            },
            locale,
        )
        out = SplitOut(
            parent_area=round(parent_area, 4),
            parts=parts,
            cut=_r(list(line)),
            cut_length=round(math.dist(*line), 4),
            position=round(position, 4) if position is not None else None,
            findings=findings,
        )
        if body.preview or _has_error(findings):
            return out
        children = [await self._child([parcel], p.ref, [tuple(c) for c in p.ring], user_id) for p in parts]  # type: ignore[misc]
        await self._supersede([parcel], children, "split", user_id)
        for p, c in zip(parts, children, strict=True):
            p.parcel_id = c.id
        out.saved = True
        return out

    async def merge(self, project_id: uuid.UUID, body: MergeIn, user_id: str, locale: str) -> SplitOut:
        parents = [await self.get_parcel(i) for i in body.parcel_ids]
        if any(p.project_id != project_id for p in parents):
            raise _bad("Both parcels must belong to this project")
        if any(p.superseded for p in parents) or parents[0].id == parents[1].id:
            raise _bad("Pick two live parcels")
        rings = [_ring(await self._points(p)) for p in parents]
        try:
            merged = sub.merge(rings[0], rings[1])
        except sub.SubdivisionError as exc:
            raise _bad(str(exc)) from exc
        ref = body.ref.strip() or f"{parents[0].parcel_ref}+{parents[1].parcel_ref}"
        areas = [sub.area(r) for r in rings]
        whole = sub.area(merged)
        findings = await _findings(
            {"subdivisions": [{"ref": ref, "parent_area": whole, "a": areas[0], "b": areas[1]}]}, locale
        )
        out = SplitOut(
            parent_area=round(whole, 4), parts=[PartOut(ref=ref, area=whole, ring=_r(merged))], findings=findings
        )
        if body.preview or _has_error(findings):
            return out
        child = await self._child(parents, ref, merged, user_id)
        await self._supersede(parents, [child], "merge", user_id)
        out.parts[0].parcel_id = child.id
        out.saved = True
        return out

    async def corners(self, parcel: LandParcel, markets: list[str], locale: str) -> CornerRegisterOut:
        points = await self._points(parcel)
        rows = []
        for i, pt in enumerate(points):
            limit = corner_limit(points, i, pt.accuracy_class, markets)
            rows.append(
                CornerOut(
                    seq=pt.seq,
                    label=pt.label,
                    e=float(pt.e),
                    n=float(pt.n),
                    mark=pt.mark or "",
                    corner_status=pt.corner_status or "",
                    accuracy_class=pt.accuracy_class or "",
                    accuracy_m=float(pt.accuracy_m) if pt.accuracy_m is not None else None,
                    limit_m=round(limit[0], 4) if limit else None,
                    class_label=limit[1] if limit else "",
                )
            )
        for row, found in zip(rows, await self._corner_findings(parcel, points, markets, locale), strict=True):
            row.findings = found
        return CornerRegisterOut(
            parcel_id=parcel.id,
            parcel_ref=parcel.parcel_ref,
            corners=rows,
            classes=[
                CornerClassOption(
                    key=c.key, label=c.label, source=c.source, status=c.status, base_m=c.base_m, ppm=c.ppm
                )
                for c in classes_lib.corner_classes(markets)
            ],
        )

    async def _corner_findings(
        self, parcel: LandParcel, points: list[LandParcelPoint], markets: list[str], locale: str
    ) -> list[list[FindingOut]]:
        out: list[list[FindingOut]] = []
        for pt in points:
            rows = [r for r in corner_rows(parcel, points, markets) if r["label"] == pt.label]
            out.append(await _findings({"corners": rows}, locale) if rows else [])
        return out

    async def patch_corner(
        self, parcel: LandParcel, seq: int, body: CornerPatch, markets: list[str], user_id: str, locale: str
    ) -> CornerRegisterOut:
        points = await self._points(parcel)
        pt = next((p for p in points if p.seq == seq), None)
        if pt is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Corner not found")
        if body.accuracy_class and classes_lib.find_corner(body.accuracy_class, markets) is None:
            raise _bad("Unknown precision class for this market")
        old = {"corner_status": pt.corner_status, "accuracy_class": pt.accuracy_class, "mark": pt.mark,
               "accuracy_m": str(pt.accuracy_m) if pt.accuracy_m is not None else None}  # fmt: skip
        for key in ("corner_status", "accuracy_class", "mark"):
            value = getattr(body, key)
            if value is not None:
                setattr(pt, key, value)
        if body.clear_accuracy:
            pt.accuracy_m = None
        elif body.accuracy_m is not None:
            from decimal import Decimal  # noqa: PLC0415

            pt.accuracy_m = Decimal(str(round(body.accuracy_m, 4)))
        await self.session.flush()
        await self._audit("update", "land_parcel_corner", parcel.id, user_id,
                          {"seq": seq, "old": old, "new": body.model_dump(exclude_none=True)})  # fmt: skip
        return await self.corners(parcel, markets, locale)

    async def setback(self, parcel: LandParcel, body: SetbackIn, locale: str) -> SetbackOut:
        points = await self._points(parcel)
        ring = _ring(points)
        if len(ring) < 3:
            raise _bad("The parcel has no boundary")
        edges = sub.setback_distances(body.footprint, ring)
        n = len(points)
        rows = [
            EdgeOut(
                edge=e.edge,
                label=f"{points[e.edge].label}-{points[(e.edge + 1) % n].label}",
                distance=round(e.distance, 3),
                encroaches=e.encroaches,
                ok=e.distance >= body.setback_m - 1e-9,
            )
            for e in edges
        ]
        findings = await _findings(
            {
                "setbacks": [
                    {"ref": str(parcel.id), "footprint": body.name, "boundary": r.label, "distance": r.distance,
                     "setback": body.setback_m}
                    for r in rows
                ]
            },
            locale,
        )  # fmt: skip
        return SetbackOut(
            min_distance=min(r.distance for r in rows) if rows else 0.0,
            setback_m=body.setback_m,
            edges=rows,
            findings=findings,
        )

    async def stake_corners(
        self, parcel: LandParcel, body: StakeCornersIn, markets: list[str], user_id: str
    ) -> StakeCornersOut:
        from app.modules.setting_out.schemas import RequestCreate, StakeCreate  # noqa: PLC0415
        from app.modules.setting_out.service import SettingOutService  # noqa: PLC0415

        points = await self._points(parcel)
        if not points:
            raise _bad("The parcel has no corners to stake")
        svc = SettingOutService(self.session)
        created = await svc.create_request(
            parcel.project_id,
            RequestCreate(
                name=body.name.strip() or f"Corners {parcel.parcel_ref}",
                item_type="boundary_corner",
                tolerance_key=body.tolerance_key,
                element_ref_label=parcel.parcel_ref,
            ),
            user_id,
            markets,
        )
        req = await svc.get_request(created.id)
        for pt in points:
            await svc.add_stake(req, StakeCreate(point_id=pt.label or str(pt.seq), e=float(pt.e), n=float(pt.n),
                                                 code="corner"), user_id)  # fmt: skip
        return StakeCornersOut(request_id=req.id, code=req.code, stakes=len(points))


__all__ = ["ParcelCalcService", "corner_limit", "corner_rows"]
