# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A stockpile on the plan, included by the stockpiles router (same prefix and permissions).

Endpoints:
    GET /stockpiles/{stockpile_id}/plan - toe and crest of a survey (latest by default) and its height map
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.stockpiles.plan import pile_outline
from app.modules.stockpiles.service import StockpileService
from app.modules.surfaces_volumes.service import tin_of

router = APIRouter(tags=["stockpiles"])

_READ = [Depends(RequirePermission("survey.read"))]


class StockpilePlanOut(BaseModel):
    stockpile_id: uuid.UUID
    code: str
    name: str
    material: str = ""
    survey_id: uuid.UUID | None = None
    surveyed_on: str | None = None
    volume_m3: str | None = None
    tonnes: str | None = None
    base_surface_id: uuid.UUID | None = None
    pile_surface_id: uuid.UUID | None = None
    toe: list[tuple[float, float]] = Field(default_factory=list)
    crest: list[tuple[float, float]] = Field(default_factory=list)
    max_height_m: float = 0.0
    footprint_m2: float = 0.0
    heat: dict[str, Any] | None = None
    #: The surveys of this pile, newest first, for the period picker.
    surveys: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/stockpiles/{stockpile_id}/plan", response_model=StockpilePlanOut, dependencies=_READ)
async def stockpile_plan(
    stockpile_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    survey_id: uuid.UUID | None = Query(None),
) -> StockpilePlanOut:
    service = StockpileService(session)
    p = await service.get_stockpile(stockpile_id)
    await verify_project_access(p.project_id, user_id, session)
    surveys = sorted(await service.repo.surveys_of(p.id), key=lambda s: (s.surveyed_on, s.created_at), reverse=True)
    chosen = next((s for s in surveys if s.id == survey_id), None) if survey_id else (surveys[0] if surveys else None)
    if survey_id and chosen is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found")
    out = StockpilePlanOut(
        stockpile_id=p.id,
        code=p.code,
        name=p.name,
        material=p.material,
        base_surface_id=p.base_surface_id,
        surveys=[
            {"id": str(s.id), "surveyed_on": s.surveyed_on.isoformat(), "volume_m3": format(s.volume_m3, "f")}
            for s in surveys
        ],
    )
    if chosen is None:
        return out
    out.survey_id = chosen.id
    out.surveyed_on = chosen.surveyed_on.isoformat()
    out.volume_m3 = format(chosen.volume_m3, "f")
    out.tonnes = format(chosen.tonnes, "f")
    out.pile_surface_id = chosen.pile_surface_id
    if chosen.pile_surface_id is None or p.base_surface_id is None:
        return out
    pile = await service.volumes.get_surface(chosen.pile_surface_id)
    base = await service.volumes.get_surface(p.base_surface_id)
    outline = await asyncio.to_thread(pile_outline, tin_of(pile), tin_of(base))
    out.toe, out.crest, out.heat = outline.toe, outline.crest, outline.heat
    out.max_height_m, out.footprint_m2 = outline.max_height_m, outline.footprint_m2
    return out
