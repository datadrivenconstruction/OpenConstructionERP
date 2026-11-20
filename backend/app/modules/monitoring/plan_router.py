# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Monitoring points on the survey plan, included in the monitoring router.

Endpoints:
    GET  /projects/{project_id}/plan                     - points with plan position, alert level, last displacement
    PUT  /points/{point_id}/position                     - set where a point sits on the plan
    POST /projects/{project_id}/demo/riverside/positions - place the Riverside wall pins on the pit wall

A point's plan position is its newest reading with E/N, else the mark kept in the survey point
register under the point's code (set ``Monitoring marks``, kind ``control``, method
``monitoring``). A settlement pin read in Z only is placed once and keeps its mark. Points with
neither are listed as not on the plan.
"""

from __future__ import annotations

import csv
import io
import uuid
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.active_markets import ActiveMarkets
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.monitoring.models import MonitoringEpoch, MonitoringReading
from app.modules.monitoring.service import MonitoringService
from app.modules.survey_core.models import SurveyPoint, SurveyPointSet

router = APIRouter(tags=["monitoring"])

_READ = [Depends(RequirePermission("survey.read"))]
_WRITE = [Depends(RequirePermission("survey.write"))]

MARK_SET = "Monitoring marks"
MARK_METHOD = "monitoring"
DEMO_POSITIONS = Path(__file__).resolve().parent / "demo" / "riverside" / "points_en.csv"


class PlanPoint(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    point_type: str
    level: str
    displacement_mm: float | None = None
    rate_mm_day: float | None = None
    latest_at: str | None = None
    e: float | None = None
    n: float | None = None
    #: ``reading`` | ``mark`` | ""
    position_source: str = ""
    #: Plan displacement since the baseline, mm; null when no two readings carry E/N.
    de_mm: float | None = None
    dn_mm: float | None = None


class PlanOut(BaseModel):
    items: list[PlanPoint]
    off_plan: int


class PositionIn(BaseModel):
    e: float = Field(ge=-1e8, le=1e8)
    n: float = Field(ge=-1e8, le=1e8)


async def _readings_en(session, project_id: uuid.UUID) -> dict[uuid.UUID, list[tuple[float, float]]]:  # noqa: ANN001
    rows = await session.execute(
        select(MonitoringReading.point_id, MonitoringReading.e, MonitoringReading.n)
        .join(MonitoringEpoch, MonitoringEpoch.id == MonitoringReading.epoch_id)
        .where(
            MonitoringReading.project_id == project_id,
            MonitoringReading.e.is_not(None),
            MonitoringReading.n.is_not(None),
        )
        .order_by(MonitoringEpoch.observed_at)
    )
    out: dict[uuid.UUID, list[tuple[float, float]]] = {}
    for pid, e, n in rows.all():
        out.setdefault(pid, []).append((float(e), float(n)))
    return out


async def _marks(session, project_id: uuid.UUID) -> dict[str, SurveyPoint]:  # noqa: ANN001
    rows = await session.execute(
        select(SurveyPoint).where(SurveyPoint.project_id == project_id, SurveyPoint.method == MARK_METHOD)
    )
    return {p.point_id: p for p in rows.scalars().all()}


async def _mark_set(session, project_id: uuid.UUID, user_id: str) -> SurveyPointSet:  # noqa: ANN001
    found = await session.execute(
        select(SurveyPointSet).where(SurveyPointSet.project_id == project_id, SurveyPointSet.name == MARK_SET)
    )
    point_set = found.scalars().first()
    if point_set is None:
        point_set = SurveyPointSet(project_id=project_id, name=MARK_SET, file_format="manual")
        session.add(point_set)
        await session.flush()
    return point_set


async def plan(session, project_id: uuid.UUID, markets: list[str]) -> PlanOut:  # noqa: ANN001
    points = await MonitoringService(session).list_points(project_id, markets)
    track = await _readings_en(session, project_id)
    marks = await _marks(session, project_id)
    items = []
    for p in points:
        seq = track.get(p.id, [])
        mark = marks.get(p.code)
        item = PlanPoint(
            id=p.id,
            code=p.code,
            name=p.name,
            point_type=p.point_type,
            level=p.level,
            displacement_mm=p.displacement_mm,
            rate_mm_day=p.rate_mm_day,
            latest_at=p.latest_at.isoformat() if p.latest_at else None,
        )
        if seq:
            item.e, item.n, item.position_source = seq[-1][0], seq[-1][1], "reading"
            if len(seq) > 1:
                item.de_mm = round((seq[-1][0] - seq[0][0]) * 1000.0, 1)
                item.dn_mm = round((seq[-1][1] - seq[0][1]) * 1000.0, 1)
        elif mark is not None:
            item.e, item.n, item.position_source = float(mark.e), float(mark.n), "mark"
        items.append(item)
    return PlanOut(items=items, off_plan=sum(1 for i in items if i.e is None))


async def set_position(session, point_id: uuid.UUID, body: PositionIn, user_id: str) -> PlanPoint:  # noqa: ANN001
    service = MonitoringService(session)
    point = await service.get_point(point_id)
    marks = await _marks(session, point.project_id)
    mark = marks.get(point.code)
    if mark is None:
        point_set = await _mark_set(session, point.project_id, user_id)
        mark = SurveyPoint(
            project_id=point.project_id,
            point_set_id=point_set.id,
            point_id=point.code,
            e=Decimal(str(round(body.e, 4))),
            n=Decimal(str(round(body.n, 4))),
            kind="control",
            description=point.name,
            method=MARK_METHOD,
            inputs={"monitoring_point_id": str(point.id)},
        )
        session.add(mark)
        point_set.point_count += 1
    else:
        mark.e, mark.n = Decimal(str(round(body.e, 4))), Decimal(str(round(body.n, 4)))
    await session.flush()
    await service._audit("update", point.id, user_id, {"plan_position": {"e": body.e, "n": body.n}})
    return PlanPoint(
        id=point.id,
        code=point.code,
        name=point.name,
        point_type=point.point_type,
        level="none",
        e=body.e,
        n=body.n,
        position_source="mark",
    )


@router.get("/projects/{project_id}/plan", response_model=PlanOut, dependencies=_READ)
async def get_plan(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> PlanOut:
    await verify_project_access(project_id, user_id, session)
    return await plan(session, project_id, markets)


@router.put("/points/{point_id}/position", response_model=PlanPoint, dependencies=_WRITE)
async def put_position(point_id: uuid.UUID, body: PositionIn, session: SessionDep, user_id: CurrentUserId) -> PlanPoint:
    point = await MonitoringService(session).get_point(point_id)
    await verify_project_access(point.project_id, user_id, session)
    return await set_position(session, point_id, body, user_id)


@router.post("/projects/{project_id}/demo/riverside/positions", response_model=PlanOut, dependencies=_WRITE)
async def demo_positions(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> PlanOut:
    """Marks for the demo wall pins; points not loaded yet are skipped."""
    await verify_project_access(project_id, user_id, session)
    by_code = {p.code: p for p in await MonitoringService(session).list_points(project_id, markets)}
    reader = csv.DictReader(io.StringIO(DEMO_POSITIONS.read_text(encoding="utf-8")))
    for row in reader:
        p = by_code.get(row["point"])
        if p is not None:
            await set_position(session, p.id, PositionIn(e=float(row["e"]), n=float(row["n"])), user_id)
    return await plan(session, project_id, markets)


__all__ = ["PlanOut", "PlanPoint", "router"]
