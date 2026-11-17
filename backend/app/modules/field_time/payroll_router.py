# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payroll hours export routes (mounted under /api/v1/field_time/payroll-export/).

GET    /examples/            - Example layouts of the active packs (column layouts only)
GET    /profiles/            - Saved export profiles; POST creates, PUT /{id} edits, DELETE /{id}
GET    /preview/             - Rows, counts and issues for a period without writing anything
POST   /runs/                - Create an immutable run and its file (errors block it)
GET    /runs/                - Recent runs the caller can open in full, newest first (paged)
GET    /runs/{id}/file       - The file of a run, exactly as created, if every project in it is the caller's
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from app.core.active_markets import ActiveMarkets
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, accessible_project_ids, verify_project_access
from app.modules.field_time.payroll_schemas import (
    ExampleListResponse,
    PreviewResponse,
    ProfileCreate,
    ProfileListResponse,
    ProfileResponse,
    RunCreate,
    RunListResponse,
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


async def _require_run_access(session: SessionDep, user_id: str, service: PayrollService, run_id: uuid.UUID) -> None:
    """404 unless the caller may open every project whose hours the run carries."""
    await service.get_run(run_id)
    allowed = await accessible_project_ids(session, user_id)
    if allowed is not None and not (await service.run_project_ids(run_id)) <= allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export run not found")


@router.get("/examples/", response_model=ExampleListResponse, dependencies=[Export])
async def examples(
    service: Service,
    markets: ActiveMarkets,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> ExampleListResponse:
    rows = service.examples(markets)
    return ExampleListResponse(items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit)


# Profiles are company-wide column layouts without a project; the export permission is the gate.
@router.get("/profiles/", response_model=ProfileListResponse, dependencies=[Export])
async def list_profiles(
    service: Service,
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
) -> ProfileListResponse:
    rows = await service.list_profiles()
    return ProfileListResponse(
        items=[ProfileResponse.model_validate(p) for p in rows[offset : offset + limit]],
        total=len(rows),
        offset=offset,
        limit=limit,
    )


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


@router.get("/runs/", response_model=RunListResponse, dependencies=[Export])
async def list_runs(
    service: Service,
    session: SessionDep,
    user_id: CurrentUserId,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> RunListResponse:
    allowed = await accessible_project_ids(session, user_id)
    rows, total = await service.page_runs(allowed, offset, limit)
    return RunListResponse(items=[RunResponse.model_validate(r) for r in rows], total=total, offset=offset, limit=limit)


@router.get("/runs/{run_id}/file", dependencies=[Export])
async def run_file(run_id: uuid.UUID, service: Service, session: SessionDep, user_id: CurrentUserId) -> Response:
    await _require_run_access(session, user_id, service, run_id)
    run, content = await service.run_file(run_id)
    encoding = str((run.profile_snapshot or {}).get("encoding") or "utf-8")
    return Response(
        content=content,
        media_type=f"text/csv; charset={encoding}",
        headers={"Content-Disposition": f'attachment; filename="{run.filename}"'},
    )
