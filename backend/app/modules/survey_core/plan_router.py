# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan editor routes, included in the survey register router (``/api/v1/survey-core``).

Endpoints:
    GET  /projects/{project_id}/view-transform - grid to WGS 84 polynomial for the map (display only)
    GET  /projects/{project_id}/codes          - feature code library (project, active pack or neutral)
    PUT  /projects/{project_id}/codes          - replace the project's library (``items=null`` resets)
    GET  /projects/{project_id}/plan-settings  - conventions: country default and project override
    PUT  /projects/{project_id}/plan-settings  - set or reset the project's conventions
    GET  /projects/{project_id}/plan-points    - points with code, source line and revision
    GET  /projects/{project_id}/sketch         - free drawing of the plan
    GET  /projects/{project_id}/edits          - edit history, newest first
    POST /projects/{project_id}/edits          - save a batch of plan edits (409 on a stale revision)
    POST /edits/{edit_id}/restore              - make an earlier revision current again
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.active_markets import ActiveMarkets
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.survey_core.plan_schemas import (
    CodeLibraryIn,
    CodeLibraryOut,
    EditBatchIn,
    EditListOut,
    PlanPointsOut,
    PlanSettingsIn,
    PlanSettingsOut,
    RestoreIn,
    SaveBatchOut,
    SaveResultOut,
    SketchOut,
    ViewTransformOut,
)
from app.modules.survey_core.plan_service import PlanService

router = APIRouter(tags=["survey_core"])

_READ = [Depends(RequirePermission("survey.read"))]
_WRITE = [Depends(RequirePermission("survey.write"))]


@router.get("/projects/{project_id}/view-transform", response_model=ViewTransformOut, dependencies=_READ)
async def view_transform(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> ViewTransformOut:
    await verify_project_access(project_id, user_id, session)
    return await PlanService(session).view_transform(project_id)


@router.get("/projects/{project_id}/codes", response_model=CodeLibraryOut, dependencies=_READ)
async def get_codes(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> CodeLibraryOut:
    await verify_project_access(project_id, user_id, session)
    return await PlanService(session).codes(project_id, markets)


@router.put("/projects/{project_id}/codes", response_model=CodeLibraryOut, dependencies=_WRITE)
async def put_codes(
    project_id: uuid.UUID, body: CodeLibraryIn, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> CodeLibraryOut:
    await verify_project_access(project_id, user_id, session)
    return await PlanService(session).put_codes(project_id, body, user_id, markets)


@router.get("/projects/{project_id}/plan-settings", response_model=PlanSettingsOut, dependencies=_READ)
async def get_settings(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> PlanSettingsOut:
    await verify_project_access(project_id, user_id, session)
    return await PlanService(session).settings(project_id)


@router.put("/projects/{project_id}/plan-settings", response_model=PlanSettingsOut, dependencies=_WRITE)
async def put_settings(
    project_id: uuid.UUID, body: PlanSettingsIn, session: SessionDep, user_id: CurrentUserId
) -> PlanSettingsOut:
    await verify_project_access(project_id, user_id, session)
    return await PlanService(session).put_settings(project_id, body.conventions, user_id)


@router.get("/projects/{project_id}/plan-points", response_model=PlanPointsOut, dependencies=_READ)
async def plan_points(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> PlanPointsOut:
    await verify_project_access(project_id, user_id, session)
    return PlanPointsOut(items=await PlanService(session).plan_points(project_id))


@router.get("/projects/{project_id}/sketch", response_model=SketchOut, dependencies=_READ)
async def sketch(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> SketchOut:
    await verify_project_access(project_id, user_id, session)
    return SketchOut(features=await PlanService(session).sketch(project_id))


@router.get("/projects/{project_id}/edits", response_model=EditListOut, dependencies=_READ)
async def list_edits(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    entity_type: str = Query("", max_length=32),
    entity_id: str = Query("", max_length=64),
    limit: int = Query(200, ge=1, le=1000),
) -> EditListOut:
    await verify_project_access(project_id, user_id, session)
    return EditListOut(items=await PlanService(session).edits(project_id, entity_type, entity_id, limit))


@router.post("/projects/{project_id}/edits", response_model=SaveBatchOut, dependencies=_WRITE)
async def save_edits(
    project_id: uuid.UUID, body: EditBatchIn, session: SessionDep, user_id: CurrentUserId
) -> SaveBatchOut:
    await verify_project_access(project_id, user_id, session)
    return SaveBatchOut(items=await PlanService(session).save(project_id, body.ops, user_id))


@router.post("/edits/{edit_id}/restore", response_model=SaveResultOut, dependencies=_WRITE)
async def restore_edit(
    edit_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, body: RestoreIn | None = None
) -> SaveResultOut:
    service = PlanService(session)
    edit = await service.get_edit(edit_id)
    if edit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await verify_project_access(edit.project_id, user_id, session)
    return await service.restore(edit, user_id, body.note if body else "")
