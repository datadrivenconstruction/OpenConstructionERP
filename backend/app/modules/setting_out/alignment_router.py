# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Alignment by intersection points, included in the setting-out router.

Endpoints:
    POST /alignment/preview                           - tangent points, arcs, ticks and SRV-072/073 (nothing saved)
    PUT  /requests/{request_id}/alignment             - store the IP design as the request's stakeable alignment
    POST /projects/{project_id}/demo/riverside/road   - load the Riverside access road (R 120/60/45 m)

The stored JSON is the one ``alignment_from_json`` reads, plus the IPs and design speed, so the
stake list, the chainage calculator and the road panel pick the alignment up at once.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.active_markets import ActiveMarkets
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.setting_out import alignment_design as ad
from app.modules.setting_out import tolerances as tol_lib
from app.modules.setting_out.road_validators import ROAD_RULE_SET
from app.modules.setting_out.schemas import Finding, RequestCreate
from app.modules.setting_out.service import SettingOutService

router = APIRouter(tags=["setting_out"])

_READ = [Depends(RequirePermission("survey.read"))]
_WRITE = [Depends(RequirePermission("survey.write"))]
_LOCALE = Query("en", max_length=10)

DEMO_ROAD_NAME = "Access road A"


class IpIn(BaseModel):
    e: float = Field(ge=-1e8, le=1e8)
    n: float = Field(ge=-1e8, le=1e8)
    radius: float = Field(default=0.0, ge=0, le=100_000)
    name: str = Field(default="", max_length=32)


class AlignmentDesignIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(default="", max_length=255)
    ips: list[IpIn] = Field(min_length=2, max_length=500)
    start_chainage: float = Field(default=0.0, ge=-1e7, le=1e7)
    design_speed_kmh: float | None = Field(default=None, gt=0, le=400)
    tick_interval: float = Field(default=20.0, gt=0, le=10_000)
    label_interval: float = Field(default=100.0, gt=0, le=100_000)


class CurveOut(BaseModel):
    ref: str
    ip_index: int
    radius: float
    deflection_deg: float
    left: bool
    tangent: float
    arc_length: float
    external: float
    tc: list[float]
    ct: list[float]
    centre: list[float]
    tc_chainage: float
    ct_chainage: float
    below_min: bool = False


class OverlapOut(BaseModel):
    a: str
    b: str
    need: float
    have: float


class MinRadiusOut(BaseModel):
    radius_m: float
    speed_kmh: float
    source: str
    reference: str
    country: str = ""


class TickOut(BaseModel):
    chainage: float
    e: float
    n: float
    labelled: bool


class AlignmentDesignOut(BaseModel):
    length: float
    start_chainage: float
    fits: bool
    curves: list[CurveOut]
    overlaps: list[OverlapOut]
    min_radius: MinRadiusOut | None = None
    ticks: list[TickOut] = Field(default_factory=list)
    #: The stored shape (elements + ips); null while curves overlap.
    alignment: dict[str, Any] | None = None
    findings: list[Finding] = Field(default_factory=list)
    saved: bool = False


async def _findings(data: dict[str, Any], locale: str) -> list[Finding]:
    from app.core.validation.engine import validation_engine  # noqa: PLC0415

    report = await validation_engine.validate(
        data=data, rule_sets=[ROAD_RULE_SET], target_type="setting_out_road", target_id="", metadata={"locale": locale}
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


async def compute(body: AlignmentDesignIn, markets: list[str], locale: str) -> AlignmentDesignOut:
    """Design, ticks and findings of one IP alignment (no database)."""
    try:
        design = ad.design_from_ips(
            [ad.Ip(p.e, p.n, p.radius, p.name) for p in body.ips],
            body.start_chainage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    rmin = ad.min_radius(body.design_speed_kmh, markets)
    ticks: list[TickOut] = []
    if design.alignment is not None:
        end = body.start_chainage + design.length
        for ch, labelled in ad.ticks(body.start_chainage, end, body.tick_interval, body.label_interval):
            e, n = design.alignment.point_at(min(ch, end))
            ticks.append(TickOut(chainage=ch, e=round(e, 4), n=round(n, 4), labelled=labelled))
    findings = await _findings(ad.check_payload(design, rmin), locale)
    return AlignmentDesignOut(
        length=round(design.length, 4),
        start_chainage=body.start_chainage,
        fits=design.fits,
        curves=[
            CurveOut(
                ref=c.ref,
                ip_index=c.ip_index,
                radius=c.radius,
                deflection_deg=round(c.deflection_deg, 6),
                left=c.left,
                tangent=round(c.tangent, 4),
                arc_length=round(c.arc_length, 4),
                external=round(c.external, 4),
                tc=[round(v, 4) for v in c.tc],
                ct=[round(v, 4) for v in c.ct],
                centre=[round(v, 4) for v in c.centre],
                tc_chainage=round(c.tc_chainage, 4),
                ct_chainage=round(c.ct_chainage, 4),
                below_min=rmin is not None and c.radius < rmin.radius_m - 1e-9,
            )
            for c in design.curves
        ],
        overlaps=[OverlapOut(a=o.a, b=o.b, need=o.need, have=o.have) for o in design.overlaps],
        min_radius=MinRadiusOut(**vars(rmin)) if rmin else None,
        ticks=ticks,
        alignment=ad.to_json(design, body.name, body.design_speed_kmh) if design.fits else None,
        findings=findings,
    )


async def save(
    service: SettingOutService, req: Any, body: AlignmentDesignIn, markets: list[str], user_id: str, locale: str
) -> AlignmentDesignOut:
    out = await compute(body, markets, locale)
    if out.alignment is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="; ".join(f.message for f in out.findings if f.rule_id == "SRV-073") or "Curves overlap",
        )
    before = req.alignment
    req.alignment = out.alignment
    await service.session.flush()
    await service._audit(
        "update",
        req.id,
        user_id,
        {
            "alignment": {"ips": len(body.ips), "length": out.length, "name": body.name},
            "had_alignment": before is not None,
        },
    )
    out.saved = True
    return out


@router.post("/alignment/preview", response_model=AlignmentDesignOut, dependencies=_READ)
async def preview(body: AlignmentDesignIn, markets: ActiveMarkets, locale: str = _LOCALE) -> AlignmentDesignOut:
    return await compute(body, markets, locale)


@router.put("/requests/{request_id}/alignment", response_model=AlignmentDesignOut, dependencies=_WRITE)
async def put_alignment(
    request_id: uuid.UUID,
    body: AlignmentDesignIn,
    session: SessionDep,
    user_id: CurrentUserId,
    markets: ActiveMarkets,
    locale: str = _LOCALE,
) -> AlignmentDesignOut:
    service = SettingOutService(session)
    req = await service.get_request(request_id)
    await verify_project_access(req.project_id, user_id, session)
    return await save(service, req, body, markets, user_id, locale)


@router.post("/projects/{project_id}/demo/riverside/road", response_model=AlignmentDesignOut, dependencies=_WRITE)
async def load_demo_road(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets, locale: str = _LOCALE
) -> AlignmentDesignOut:
    """Request "Access road A" with the demo alignment; idempotent, the 45 m curve gives SRV-072."""
    await verify_project_access(project_id, user_id, session)
    service = SettingOutService(session)
    data = json.loads(ad.DEMO_ROAD.read_text(encoding="utf-8"))
    body = AlignmentDesignIn(
        name=data["name"],
        ips=[IpIn(**ip) for ip in data["ips"]],
        start_chainage=data["start_chainage"],
        design_speed_kmh=data["design_speed_kmh"],
    )
    req = next((r for r in await service.repo.list_requests(project_id) if r.name == DEMO_ROAD_NAME), None)
    if req is None:
        created = await service.create_request(
            project_id,
            RequestCreate(
                name=DEMO_ROAD_NAME, item_type="centreline", tolerance_key=tol_lib.DEMO_KEY, control_ref="CP1, CP2"
            ),
            user_id,
            ["*"],
        )
        req = await service.get_request(created.id)
    elif req.alignment and req.alignment.get("ips"):
        return await compute(
            body.model_copy(update={"ips": [IpIn(**ip) for ip in req.alignment["ips"]]}), markets, locale
        )
    return await save(service, req, body, markets, user_id, locale)


__all__ = ["AlignmentDesignIn", "AlignmentDesignOut", "compute", "router"]
