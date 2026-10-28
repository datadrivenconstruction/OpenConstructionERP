# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payroll​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ export period routes (included under ``/api/v1/payroll``).

GET   /rule-profiles/                          - overtime and allowance profiles (data)
GET   /dashboard/                               - period widget figures
POST  /projects/{project_id}/periods/          - build a period from approved timesheets
GET   /projects/{project_id}/periods/          - list periods
GET   /periods/{period_id}                      - period with lines, events, findings
POST  /periods/{period_id}/rebuild/             - rebuild an open period
POST  /periods/{period_id}/lock/                - lock (blocks timesheet edits)
POST  /periods/{period_id}/reopen/              - reopen with a reason
GET   /periods/{period_id}/export?format=...    - csv | xlsx | json | lodas
POST  /periods/{period_id}/post-costs/          - gross plus burden to project actuals
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.payroll import pay_rules
from app.modules.payroll.period_service import PayrollPeriodService
from app.modules.payroll.validators import evaluate_period

router = APIRouter(tags=["payroll"])
_READ = Depends(RequirePermission("payroll.read"))
_MANAGE = Depends(RequirePermission("payroll.manage"))


class PeriodCreate(BaseModel):
    period_start: date
    period_end: date
    label: str = Field(default="", max_length=120)
    rule_profile: str | None = Field(default=None, max_length=60)


class ReopenRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class PeriodListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    offset: int = 0
    limit: int = 50


class PeriodLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID | None
    employee_number: str
    employee_name: str
    work_date: date
    cost_code: str
    pay_type: str
    hours: Decimal
    rate: Decimal
    multiplier: Decimal
    amount: Decimal
    overtime_approved: bool

    @field_serializer("hours", "rate", "multiplier", "amount")
    def _money(self, value: Decimal) -> str:
        return str(value)


class PeriodEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    action: str
    reason: str
    actor_id: uuid.UUID | None
    created_at: datetime | None = None
    details: dict[str, Any] = {}


async def _project_of(service: PayrollPeriodService, period_id: uuid.UUID, user_id: str, session: Any):
    period = await service.get(period_id)
    await verify_project_access(period.project_id, user_id, session)
    return period


async def _detail(service: PayrollPeriodService, period_id: uuid.UUID) -> dict[str, Any]:
    period = await service.get(period_id)
    findings = await evaluate_period(await service.validation_snapshot(period), target_id=str(period.id))
    return {
        **service.header(period),
        "locked_at": period.locked_at,
        "exported_at": period.exported_at,
        "posted_ref": period.posted_ref,
        "certified_payroll_weeks": await service.certified_weeks(period),
        "totals_by_type": (period.metadata_ or {}).get("totals_by_type") or {},
        "lines": [PeriodLineOut.model_validate(ln).model_dump() for ln in await service.lines(period.id)],
        "events": [PeriodEventOut.model_validate(e).model_dump() for e in await service.events(period.id)],
        "findings": [
            {
                "rule_id": f.rule_id,
                "severity": str(getattr(f.severity, "value", f.severity)),
                "message": f.message,
                "element_ref": f.element_ref,
            }
            for f in findings
        ],
    }


@router.get("/rule-profiles/", dependencies=[_READ])
async def rule_profiles() -> list[dict[str, Any]]:
    """Overtime, allowance and burden profiles per country or collective agreement."""
    return [
        {k: v for k, v in p.items() if k != "datev_lodas"} | {"has_lodas": bool(p.get("datev_lodas"))}
        for p in pay_rules.load_profiles().values()
    ]


@router.get("/dashboard/", dependencies=[_READ])
async def period_dashboard(
    session: SessionDep, user_id: CurrentUserId, project_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """Figures for the payroll dashboard widget."""
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    return await PayrollPeriodService(session).dashboard(project_id)


@router.post("/projects/{project_id}/periods/", status_code=201, dependencies=[_MANAGE])
async def create_period(
    project_id: uuid.UUID, data: PeriodCreate, user_id: CurrentUserId, session: SessionDep
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    service = PayrollPeriodService(session)
    period = await service.create(
        project_id,
        period_start=data.period_start,
        period_end=data.period_end,
        label=data.label,
        rule_profile=data.rule_profile,
        user_id=user_id,
    )
    return await _detail(service, period.id)


@router.get("/projects/{project_id}/periods/", response_model=PeriodListResponse, dependencies=[_READ])
async def list_periods(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
) -> PeriodListResponse:
    await verify_project_access(project_id, user_id, session)
    service = PayrollPeriodService(session)
    rows, total = await service.list_for_project(project_id, offset, limit)
    return PeriodListResponse(items=[service.header(p) for p in rows], total=total, offset=offset, limit=limit)


@router.get("/periods/{period_id}", dependencies=[_READ])
async def get_period(period_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> dict[str, Any]:
    service = PayrollPeriodService(session)
    await _project_of(service, period_id, user_id, session)
    return await _detail(service, period_id)


@router.post("/periods/{period_id}/rebuild/", dependencies=[_MANAGE])
async def rebuild_period(period_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> dict[str, Any]:
    service = PayrollPeriodService(session)
    await _project_of(service, period_id, user_id, session)
    await service.rebuild(period_id, user_id)
    return await _detail(service, period_id)


@router.post("/periods/{period_id}/lock/", dependencies=[_MANAGE])
async def lock_period(period_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> dict[str, Any]:
    service = PayrollPeriodService(session)
    await _project_of(service, period_id, user_id, session)
    await service.lock(period_id, user_id)
    return await _detail(service, period_id)


@router.post("/periods/{period_id}/reopen/", dependencies=[_MANAGE])
async def reopen_period(
    period_id: uuid.UUID, data: ReopenRequest, user_id: CurrentUserId, session: SessionDep
) -> dict[str, Any]:
    service = PayrollPeriodService(session)
    await _project_of(service, period_id, user_id, session)
    await service.reopen(period_id, data.reason, user_id)
    return await _detail(service, period_id)


@router.get("/periods/{period_id}/export", dependencies=[_MANAGE], response_model=None)
async def export_period(
    period_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    format: str = Query("csv", pattern="^(csv|xlsx|json|lodas)$"),  # noqa: A002 - public query name
    columns: str | None = Query(None, description="Comma separated column names for csv and xlsx"),
    consultant_number: str = Query("", max_length=7),
    client_number: str = Query("", max_length=5),
) -> Response:
    service = PayrollPeriodService(session)
    await _project_of(service, period_id, user_id, session)
    cols = [c.strip() for c in columns.split(",") if c.strip()] if columns else None
    content, media, name = await service.export(
        period_id,
        format,
        columns=cols,
        consultant_number=consultant_number,
        client_number=client_number,
        user_id=user_id,
    )
    return Response(
        content=content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )


@router.post("/periods/{period_id}/post-costs/", dependencies=[_MANAGE])
async def post_period_costs(period_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> dict[str, Any]:
    service = PayrollPeriodService(session)
    await _project_of(service, period_id, user_id, session)
    await service.post_costs(period_id, user_id)
    return await _detail(service, period_id)
