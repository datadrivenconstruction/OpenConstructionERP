# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The mine on the plan, included by the mine router (same prefix and permissions).

Endpoints:
    GET /projects/{project_id}/plan - blast block outlines, and per unit of a period the volume record
                                      whose surfaces give the pit contours and the period's cut/fill map
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.mine_survey.plan import block_outline
from app.modules.mine_survey.repository import MineRepository
from app.modules.surfaces_volumes.models import SurveyVolume

router = APIRouter(tags=["mine_survey"])

_READ = [Depends(RequirePermission("survey.read"))]


class BlastBlockOut(BaseModel):
    pattern_id: uuid.UUID
    code: str
    name: str
    unit_id: uuid.UUID | None = None
    ring: list[tuple[float, float]] = Field(default_factory=list)
    holes: list[tuple[float, float]] = Field(default_factory=list)
    hole_spacing_m: float = 0.0


class ReconciliationRow(BaseModel):
    entry_id: uuid.UUID
    unit_id: uuid.UUID
    unit_code: str
    unit_name: str
    unit_type: str
    plan_m3: str
    volume_id: uuid.UUID | None = None
    volume_code: str = ""
    base_surface_id: uuid.UUID | None = None
    compare_surface_id: uuid.UUID | None = None
    cut_m3: str | None = None
    fill_m3: str | None = None
    net_m3: str | None = None


class MinePlanOut(BaseModel):
    periods: list[dict[str, Any]] = Field(default_factory=list)
    period_id: uuid.UUID | None = None
    blast_blocks: list[BlastBlockOut] = Field(default_factory=list)
    reconciliation: list[ReconciliationRow] = Field(default_factory=list)
    #: The latest measured surface of the period, for the pit and bench contours.
    pit_surface_id: uuid.UUID | None = None


@router.get("/projects/{project_id}/plan", response_model=MinePlanOut, dependencies=_READ)
async def mine_plan(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    period_id: uuid.UUID | None = Query(None),
) -> MinePlanOut:
    await verify_project_access(project_id, user_id, session)
    repo = MineRepository(session)
    periods = sorted(await repo.list_periods(project_id), key=lambda p: p.period_start, reverse=True)
    period = next((p for p in periods if p.id == period_id), None) if period_id else (periods[0] if periods else None)
    if period_id and period is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Period not found")
    blocks = []
    for pat in await repo.list_patterns(project_id):
        holes = [(float(h.design_e), float(h.design_n)) for h in await repo.holes_of(pat.id)]
        ring, spacing = block_outline(holes)
        blocks.append(
            BlastBlockOut(
                pattern_id=pat.id,
                code=pat.code,
                name=pat.name,
                unit_id=pat.unit_id,
                ring=ring,
                holes=holes,
                hole_spacing_m=round(spacing, 3),
            )
        )
    out = MinePlanOut(
        periods=[{"id": str(p.id), "label": p.label, "period_end": p.period_end.isoformat()} for p in periods],
        period_id=period.id if period else None,
        blast_blocks=blocks,
    )
    if period is None:
        return out
    units = {u.id: u for u in await repo.list_units(project_id)}
    for entry in await repo.entries_of(period.id):
        unit = units.get(entry.unit_id)
        if unit is None:
            continue
        row = ReconciliationRow(
            entry_id=entry.id,
            unit_id=unit.id,
            unit_code=unit.code,
            unit_name=unit.name,
            unit_type=unit.unit_type,
            plan_m3=format(entry.plan_m3, "f"),
        )
        vol = await session.get(SurveyVolume, entry.actual_volume_id) if entry.actual_volume_id else None
        if vol is not None:
            row.volume_id, row.volume_code = vol.id, vol.code
            row.base_surface_id, row.compare_surface_id = vol.base_surface_id, vol.compare_surface_id
            row.cut_m3, row.fill_m3, row.net_m3 = (format(v, "f") for v in (vol.cut_m3, vol.fill_m3, vol.net_m3))
            out.pit_surface_id = vol.compare_surface_id or out.pit_surface_id
        out.reconciliation.append(row)
    return out
