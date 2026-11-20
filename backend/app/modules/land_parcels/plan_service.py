# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan-editor operations on land: work zones drawn on the plan, the boundary point register, the demo."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from app.modules.land_parcels.cadastre import boundary_point_register
from app.modules.land_parcels.geometry import intersection_area, open_ring
from app.modules.land_parcels.models import LandParcelSettings, LandWorkZone
from app.modules.land_parcels.schemas import (
    BoundaryPointIn,
    BoundaryPointRegister,
    BoundaryPointRow,
    DemoLoadResult,
    ParcelCreate,
    TouchedParcel,
    WorkZoneDetail,
    WorkZoneIn,
)
from app.modules.land_parcels.service import ParcelService
from app.modules.land_parcels.validators import MIN_OVERLAP_M2

DEMO_DIR = Path(__file__).resolve().parent / "demo" / "riverside"
DEMO_PARCELS = DEMO_DIR / "plan_parcels.geojson"
DEMO_ZONE = DEMO_DIR / "plan_work_zone.geojson"
#: The demo's project settings, so that its deliberate errors fire: 0.1 % area tolerance, 0.5 m gap width.
DEMO_AREA_TOLERANCE_PCT = Decimal("0.1")
DEMO_GAP_M = Decimal("0.5")


def _ring_of(raw: list) -> list[list[float]]:
    return [[round(float(p[0]), 4), round(float(p[1]), 4)] for p in open_ring([tuple(p[:2]) for p in raw])]


class ParcelPlanService(ParcelService):
    """Work zones, the boundary point register and the demo over one request's session."""

    async def _touched(self, project_id: uuid.UUID, ring: list) -> list[TouchedParcel]:
        parcels, points = await self._rows(project_id)
        out: list[TouchedParcel] = []
        zone = [(float(e), float(n)) for e, n in ring]
        for p in parcels:
            pr = [(float(pt.e), float(pt.n)) for pt in points.get(p.id, [])]
            if len(pr) < 3:
                continue
            area = intersection_area(zone, pr)
            if area >= MIN_OVERLAP_M2:
                out.append(
                    TouchedParcel(
                        parcel_id=p.id,
                        parcel_ref=p.parcel_ref,
                        status=p.status,
                        overlap_m2=round(area, 2),
                        blocking=p.status != "acquired",
                    )
                )
        return out

    async def zone_detail(self, zone: LandWorkZone, markets: list[str], locale: str = "en") -> WorkZoneDetail:
        touched = await self._touched(zone.project_id, zone.ring)
        refs = {str(t.parcel_id) for t in touched if t.blocking}
        report = await self.validate(zone.project_id, markets, locale)
        findings = [f for f in report.findings if f.rule_id == "PAR-003" and (f.element_ref or "") in refs]
        return WorkZoneDetail(
            id=zone.id,
            name=zone.name,
            epsg=zone.epsg,
            source_filename=zone.source_filename,
            vertex_count=len(open_ring(zone.ring)),
            ring=[(float(e), float(n)) for e, n in zone.ring],
            touched=touched,
            findings=findings,
        )

    async def create_zone(self, project_id: uuid.UUID, data: WorkZoneIn, user_id: str) -> LandWorkZone:
        epsg = await self._require_crs(project_id)
        ring = _ring_of(data.ring)
        if len(ring) < 3:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="A work zone needs three corners")
        zone = LandWorkZone(project_id=project_id, name=data.name.strip()[:255], ring=ring, epsg=epsg)
        await self.repo.add(zone)
        await self._audit("create", "land_work_zone", zone.id, user_id, {"name": zone.name, "vertices": len(ring)})
        await self._edit("work_zone", zone, "create", None, {"name": zone.name, "ring": ring}, user_id)
        return zone

    async def update_zone(
        self, zone: LandWorkZone, data: WorkZoneIn, user_id: str, base_rev: int | None = None
    ) -> LandWorkZone:
        ring = _ring_of(data.ring)
        if len(ring) < 3:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="A work zone needs three corners")
        before = {"name": zone.name, "ring": zone.ring}
        zone.name = data.name.strip()[:255]
        zone.ring = ring
        await self.session.flush()
        after = {"name": zone.name, "ring": ring}
        await self._audit("update", "land_work_zone", zone.id, user_id, {"old": before, "new": after})
        await self._edit("work_zone", zone, "update", before, after, user_id, base_rev)
        return zone

    async def _edit(
        self,
        entity_type: str,
        row: Any,
        op: str,
        before: dict | None,
        after: dict | None,
        user_id: str,
        base_rev: int | None = None,
    ) -> None:
        """One plan revision row through survey_core's ``record_edit`` (409 on a stale revision)."""
        from app.modules.survey_core.plan_service import record_edit  # noqa: PLC0415

        await record_edit(
            self.session,
            row.project_id,
            entity_type=entity_type,
            entity_id=str(row.id),
            op=op,
            before=before,
            after=after,
            user_id=user_id,
            base_rev=base_rev,
        )

    async def plan_grid(self, project_id: uuid.UUID, markets: list[str]) -> dict[str, Any]:
        """Parcels and work zones in project grid metres for the plan editor, with what its live checks read."""
        profile = await self.profile(project_id, markets)
        ctx = await self._context(project_id, profile, markets)
        parcels, points = await self._rows(project_id)
        corners = {
            p.id: [
                {"label": pt.label, "e": float(pt.e), "n": float(pt.n), "mark": pt.mark} for pt in points.get(p.id, [])
            ]
            for p in parcels
        }
        by_id = {str(p.id): p for p in parcels}
        epsg, _local = await self._crs(project_id)
        return {
            "epsg": epsg,
            "id_pattern": profile.id_pattern,
            "gap_tolerance_m": ctx["settings"]["gap_tolerance_m"],
            "parcels": [
                {
                    "id": row["id"],
                    "ref": row["ref"],
                    "name": by_id[row["id"]].name,
                    "status": row["status"],
                    "legal_area": row["legal_area"],
                    "computed_area": row["computed_area"],
                    "tolerance_m2": row["tolerance_m2"],
                    "points": corners.get(by_id[row["id"]].id, []),
                }
                for row in ctx["parcels"]
            ],
            "zones": [
                {"id": z["id"], "name": z["name"], "ring": [[float(e), float(n)] for e, n in z["ring"]]}
                for z in ctx["work_zones"]
            ],
        }

    # ── Boundary point register ────────────────────────────────────────────

    async def boundary_points(self, project_id: uuid.UUID, markets: list[str]) -> BoundaryPointRegister:
        profile = await self.profile(project_id, markets)
        parcels, points = await self._rows(project_id)
        rows = boundary_point_register(
            [
                {
                    "ref": p.parcel_ref,
                    "points": [
                        {
                            "label": pt.label,
                            "e": pt.e,
                            "n": pt.n,
                            "mark": pt.mark,
                            "accuracy_m": float(pt.accuracy_m) if pt.accuracy_m is not None else None,
                            "corner_status": pt.corner_status,
                        }
                        for pt in points.get(p.id, [])
                    ],
                }
                for p in parcels
            ],
            profile.marks,
        )
        items = [BoundaryPointRow(**r) for r in rows]
        return BoundaryPointRegister(
            items=items,
            total=len(items),
            monumented=sum(1 for r in items if r.monumented),
            unmarked=sum(1 for r in items if r.monumented is False or not r.mark),
            conflicts=sum(1 for r in items if r.mark_conflict),
        )

    # ── Demo ───────────────────────────────────────────────────────────────

    async def load_demo(self, project_id: uuid.UUID, user_id: str) -> DemoLoadResult:
        """Six riverside parcels with three deliberate errors and a haul road over three of them; idempotent."""
        fc = json.loads(DEMO_PARCELS.read_text(encoding="utf-8"))
        refs = {f["properties"]["parcel_id"] for f in fc["features"]}
        existing = {p.parcel_ref for p in await self.repo.list_parcels(project_id)}
        if refs & existing:
            return DemoLoadResult(parcels=0, work_zones=0, skipped=True)
        await self._require_crs(project_id)
        for f in fc["features"]:
            props = f["properties"]
            ring = f["geometry"]["coordinates"][0]
            corners = props.get("corners") or []
            pts = [
                BoundaryPointIn(
                    label=corners[i]["label"] if i < len(corners) else "",
                    e=float(c[0]),
                    n=float(c[1]),
                    mark=corners[i]["mark"] if i < len(corners) else "",
                )
                for i, c in enumerate(ring[:-1])
            ]
            await self.create_parcel(
                project_id,
                ParcelCreate(
                    parcel_ref=props["parcel_id"],
                    name=props.get("name", ""),
                    legal_area=Decimal(str(props["legal_area"])),
                    status=props.get("status", "needed"),
                    acquisition_cost=Decimal(str(props["acquisition_cost"])),
                    points=pts,
                ),
                user_id,
            )
        zone_fc = json.loads(DEMO_ZONE.read_text(encoding="utf-8"))
        for zf in zone_fc["features"]:
            await self.create_zone(
                project_id, WorkZoneIn(name=zf["properties"]["name"], ring=zf["geometry"]["coordinates"][0]), user_id
            )
        settings = await self.repo.get_settings(project_id)
        if settings is None:
            settings = LandParcelSettings(project_id=project_id)
            self.session.add(settings)
        settings.area_tolerance_pct = DEMO_AREA_TOLERANCE_PCT
        settings.gap_tolerance_m = DEMO_GAP_M
        await self.session.flush()
        await self._audit("demo", "land_parcel", project_id, user_id, {"parcels": len(fc["features"])})
        return DemoLoadResult(parcels=len(fc["features"]), work_zones=len(zone_fc["features"]))


__all__ = ["DEMO_PARCELS", "DEMO_ZONE", "ParcelPlanService"]
