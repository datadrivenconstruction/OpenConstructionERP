# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payroll hours export routes (mounted under /api/v1/field_time/payroll-export/).

GET    /examples/            - Example layouts of the active packs (column layouts only)
GET    /profiles/            - Saved export profiles; POST creates, PUT /{id} edits, DELETE /{id}
GET    /preview/             - Rows, counts and issues for a period without writing anything
POST   /runs/                - Create an immutable run and its file (errors block it)
GET    /runs/                - Recent runs, newest first
GET    /runs/{id}/file       - The file of a run, exactly as created
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.core.active_markets import ActiveMarkets
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, accessible_project_ids, verify_project_access
from app.modules.field_time.payroll_schemas import (
    ExampleOut,
    PreviewResponse,
    ProfileCreate,
    ProfileResponse,
    RunCreate,
    RunResponse,
)
from app.modules.field_time.payroll_service import PayrollService

router = APIRouter(prefix="/payroll-export", tags=["field_time_payroll_export"])

Export = Depends(RequirePermission("field_time.export_payroll"))


def _service(session: SessionDep) -> PayrollService:
    return PayrollService(session)


Service = Annotated[PayrollService, Depends(_service)]


async def _scope(session: SessionDep, user_id: str, project_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """The projects a run covers: the chosen ones, or every live project the caller may open."""
    for pid in project_ids:
        await verify_project_access(pid, user_id, session)
    if project_ids:
        return set(project_ids)
    return await accessible_project_ids(session, user_id, live_only=True) or set()


@router.get("/examples/", response_model=list[ExampleOut], dependencies=[Export])
async def examples(service: Service, markets: ActiveMarkets) -> list[ExampleOut]:
    return service.examples(markets)


@router.get("/profiles/", response_model=list[ProfileResponse], dependencies=[Export])
async def list_profiles(service: Service) -> list[ProfileResponse]:
    return [ProfileResponse.model_validate(p) for p in await service.list_profiles()]


@router.post("/profiles/", response_model=ProfileResponse, status_code=201, dependencies=[Export])
async def create_profile(data: ProfileCreate, service: Service) -> ProfileResponse:
    return ProfileResponse.model_validate(await service.save_profile(data))


@router.put("/profiles/{profile_id}", response_model=ProfileResponse, dependencies=[Export])
async def update_profile(profile_id: uuid.UUID, data: ProfileCreate, service: Service) -> ProfileResponse:
    return ProfileResponse.model_validate(await service.save_profile(data, profile_id))


@router.delete("/profiles/{profile_id}", status_code=204, dependencies=[Export])
async def delete_profile(profile_id: uuid.UUID, service: Service) -> None:
    await service.delete_profile(profile_id)


@router.get("/preview/", response_model=PreviewResponse, dependencies=[Export])
async def preview(
    service: Service,
    session: SessionDep,
    user_id: CurrentUserId,
    profile_id: uuid.UUID,
    period_from: date,
    period_to: date,
    project_id: Annotated[list[uuid.UUID] | None, Query()] = None,
) -> PreviewResponse:
    scope = await _scope(session, user_id, project_id or [])
    return service.preview(await service.plan(profile_id, period_from, period_to, scope))


@router.post("/runs/", response_model=RunResponse, status_code=201, dependencies=[Export])
async def create_run(data: RunCreate, service: Service, session: SessionDep, user_id: CurrentUserId) -> RunResponse:
    scope = await _scope(session, user_id, data.project_ids)
    run = await service.create_run(data.profile_id, data.period_from, data.period_to, scope, uuid.UUID(user_id))
    return RunResponse.model_validate(run)


@router.get("/runs/", response_model=list[RunResponse], dependencies=[Export])
async def list_runs(service: Service) -> list[RunResponse]:
    return [RunResponse.model_validate(r) for r in await service.list_runs()]


@router.get("/runs/{run_id}/file", dependencies=[Export])
async def run_file(run_id: uuid.UUID, service: Service) -> Response:
    run, content = await service.run_file(run_id)
    encoding = str((run.profile_snapshot or {}).get("encoding") or "utf-8")
    return Response(
        content=content,
        media_type=f"text/csv; charset={encoding}",
        headers={"Content-Disposition": f'attachment; filename="{run.filename}"'},
    )
