# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Road and rail stake list from a LandXML alignment and profile, included in the setting-out router.

Endpoint:
    POST /road/stake-list - stake rows every N m with design level and cut/fill (nothing saved)
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.dependencies import RequirePermission
from app.modules.setting_out.design_io import parse_landxml
from app.modules.setting_out.road_geometry import stake_list
from app.modules.setting_out.road_validators import ROAD_RULE_SET
from app.modules.setting_out.schemas import Finding

router = APIRouter(tags=["setting_out"])

_READ = [Depends(RequirePermission("survey.read"))]


class MeasuredLevel(BaseModel):
    chainage: float
    offset: float = 0.0
    z: float


class StakeListIn(BaseModel):
    landxml: str = Field(min_length=1, max_length=20_000_000)
    alignment_name: str = Field(default="", max_length=255)
    interval: float = Field(default=20.0, gt=0, le=10_000)
    offsets: list[float] = Field(default_factory=lambda: [0.0], min_length=1, max_length=20)
    start: float | None = None
    end: float | None = None
    crossfall_pct: float = Field(default=0.0, ge=-20, le=20)
    measured: list[MeasuredLevel] = Field(default_factory=list, max_length=20_000)
    #: ``stake``: ground above design is cut. ``as_built``: built above design is fill.
    mode: Literal["stake", "as_built"] = "stake"


class StakeRowOut(BaseModel):
    chainage: float
    offset: float
    e: float
    n: float
    design_z: float | None = None
    measured_z: float | None = None
    dz_mm: float | None = None
    cut_fill: str = ""


class StakeListOut(BaseModel):
    alignment_length: float
    start_chainage: float
    has_profile: bool
    rows: list[StakeRowOut]
    problems: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)


def _ranges(chainages: list[float], interval: float) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for ch in chainages:
        if out and ch - out[-1][1] <= interval + 1e-6:
            out[-1] = (out[-1][0], ch)
        else:
            out.append((ch, ch))
    return out


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


@router.post("/road/stake-list", response_model=StakeListOut, dependencies=_READ)
async def road_stake_list(body: StakeListIn, locale: str = Query("en", max_length=10)) -> StakeListOut:
    design = parse_landxml(body.landxml, body.alignment_name)
    if design.alignment is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="; ".join(p.message for p in design.problems) or "No alignment in this file",
        )
    al = design.alignment
    try:
        result = stake_list(
            al,
            design.profile,
            body.interval,
            body.offsets,
            body.start,
            body.end,
            body.crossfall_pct,
            {(round(m.chainage, 3), round(m.offset, 3)): m.z for m in body.measured},
            body.mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    findings = await _findings(
        {
            "uncovered": [{"ref": "profile", "from": a, "to": b} for a, b in _ranges(result.uncovered, body.interval)],
            "spirals_skipped": [{"ref": "alignment", "element": n} for n in design.spirals_skipped],
        },
        locale,
    )
    return StakeListOut(
        alignment_length=round(al.length, 4),
        start_chainage=al.start_chainage,
        has_profile=design.profile is not None,
        rows=[StakeRowOut(**{k: getattr(r, k) for k in StakeRowOut.model_fields}) for r in result.rows],
        problems=[p.message for p in design.problems],
        findings=findings,
    )
