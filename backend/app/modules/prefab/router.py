# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Off-site / Prefab / DfMA API routes.

Mounted at ``/api/v1/prefab``.

    GET    /stages                       - ordered production stages + unit types
    GET    /stats?project_id=X           - aggregate stats for a project
    GET    /board?project_id=X           - units grouped into columns by stage
    GET    /units?project_id=X           - list units (filter by status / type)
    POST   /units                        - create a unit
    GET    /units/{unit_id}              - get a single unit
    PATCH  /units/{unit_id}              - update a unit (never its status)
    PATCH  /units/{unit_id}/link         - set/clear the BOQ position / assembly link
    DELETE /units/{unit_id}              - delete a unit
    POST   /units/{unit_id}/advance      - advance the unit's production stage
    GET    /units/{unit_id}/events       - production-stage audit timeline

Reads need viewer access (``prefab.read``); create/edit/delete need
``prefab.write``; advancing a stage needs ``prefab.advance``. Every project-
scoped route additionally verifies the caller may access the project.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.prefab.guard import POST_QA_STAGES, STAGE_ORDER, UNIT_TYPES
from app.modules.prefab.schemas import (
    AdvanceStageRequest,
    PrefabBoardResponse,
    PrefabStageInfo,
    PrefabStagesResponse,
    PrefabStatsResponse,
    PrefabUnitCreate,
    PrefabUnitLinkRequest,
    PrefabUnitResponse,
    PrefabUnitUpdate,
    ProductionEventResponse,
)
from app.modules.prefab.service import PrefabService

router = APIRouter()

_READ = Depends(RequirePermission("prefab.read"))
_WRITE = Depends(RequirePermission("prefab.write"))
_ADVANCE = Depends(RequirePermission("prefab.advance"))


def _service(session: AsyncSession) -> PrefabService:
    return PrefabService(session)


# ── Stage vocabulary (static lookup) ──────────────────────────────────────


@router.get("/stages", response_model=PrefabStagesResponse, include_in_schema=False, dependencies=[_READ])
@router.get("/stages/", response_model=PrefabStagesResponse, dependencies=[_READ])
async def list_stages() -> PrefabStagesResponse:
    """Return the ordered production stages and recognised unit types.

    Drives the board columns and the create/advance pickers on the frontend.
    """
    stages = [
        PrefabStageInfo(stage=stage, index=idx, is_post_qa=stage in POST_QA_STAGES)
        for idx, stage in enumerate(STAGE_ORDER)
    ]
    return PrefabStagesResponse(stages=stages, unit_types=list(UNIT_TYPES))


# ── Stats ──────────────────────────────────────────────────────────────────


@router.get("/stats", response_model=PrefabStatsResponse, include_in_schema=False, dependencies=[_READ])
@router.get("/stats/", response_model=PrefabStatsResponse, dependencies=[_READ])
async def prefab_stats(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
) -> PrefabStatsResponse:
    """Aggregate prefab statistics for a project (totals by status and type)."""
    await verify_project_access(project_id, user_id, session)
    return await _service(session).get_stats(project_id)


# ── Board (status kanban) ──────────────────────────────────────────────────


@router.get("/board", response_model=PrefabBoardResponse, include_in_schema=False, dependencies=[_READ])
@router.get("/board/", response_model=PrefabBoardResponse, dependencies=[_READ])
async def prefab_board(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
) -> PrefabBoardResponse:
    """Return the project's units grouped into columns by production stage."""
    await verify_project_access(project_id, user_id, session)
    return await _service(session).get_board(project_id)


# ── Unit list ──────────────────────────────────────────────────────────────


@router.get("/units", response_model=list[PrefabUnitResponse], include_in_schema=False, dependencies=[_READ])
@router.get("/units/", response_model=list[PrefabUnitResponse], dependencies=[_READ])
async def list_units(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    unit_status: str | None = Query(default=None, alias="status"),
    unit_type: str | None = Query(default=None, alias="type"),
) -> list[PrefabUnitResponse]:
    """List prefab units for a project, optionally filtered by status / type."""
    await verify_project_access(project_id, user_id, session)
    service = _service(session)
    units, _ = await service.list_units(
        project_id,
        offset=offset,
        limit=limit,
        status=unit_status,
        unit_type=unit_type,
    )
    return await service.to_responses(units)


# ── Unit create ────────────────────────────────────────────────────────────


@router.post("/units/", response_model=PrefabUnitResponse, status_code=201, dependencies=[_WRITE])
async def create_unit(
    data: PrefabUnitCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> PrefabUnitResponse:
    """Create a new off-site unit."""
    await verify_project_access(data.project_id, user_id, session)
    service = _service(session)
    unit = await service.create_unit(data, user_id=user_id)
    await session.commit()
    return await service.to_response(unit)


# ── Unit get ───────────────────────────────────────────────────────────────


@router.get("/units/{unit_id}", response_model=PrefabUnitResponse, dependencies=[_READ])
async def get_unit(
    unit_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> PrefabUnitResponse:
    """Get a single off-site unit."""
    service = _service(session)
    unit = await service.get_unit(unit_id)
    await verify_project_access(unit.project_id, user_id, session)
    return await service.to_response(unit)


# ── Unit update ────────────────────────────────────────────────────────────


@router.patch("/units/{unit_id}", response_model=PrefabUnitResponse, dependencies=[_WRITE])
async def update_unit(
    unit_id: uuid.UUID,
    data: PrefabUnitUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> PrefabUnitResponse:
    """Update an off-site unit (status changes go through /advance)."""
    service = _service(session)
    existing = await service.get_unit(unit_id)
    await verify_project_access(existing.project_id, user_id, session)
    unit = await service.update_unit(unit_id, data)
    await session.commit()
    return await service.to_response(unit)


# ── Unit cost link (BOQ position / assembly) ───────────────────────────────


@router.patch("/units/{unit_id}/link", response_model=PrefabUnitResponse, dependencies=[_WRITE])
async def link_unit(
    unit_id: uuid.UUID,
    data: PrefabUnitLinkRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> PrefabUnitResponse:
    """Set or clear a unit's cost links to a BOQ position and/or an assembly.

    The response carries the derived cost view (cost basis, source, production
    progress and a simple earned-value hint) so off-site production reflects
    real cost and earned value.
    """
    service = _service(session)
    existing = await service.get_unit(unit_id)
    await verify_project_access(existing.project_id, user_id, session)
    response = await service.set_link(unit_id, data)
    await session.commit()
    return response


# ── Unit delete ────────────────────────────────────────────────────────────


@router.delete("/units/{unit_id}", status_code=204, dependencies=[_WRITE])
async def delete_unit(
    unit_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> None:
    """Delete an off-site unit and its production-event history."""
    service = _service(session)
    existing = await service.get_unit(unit_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_unit(unit_id)
    await session.commit()


# ── Advance stage ──────────────────────────────────────────────────────────


@router.post("/units/{unit_id}/advance/", response_model=PrefabUnitResponse, dependencies=[_ADVANCE])
async def advance_stage(
    unit_id: uuid.UUID,
    data: AdvanceStageRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> PrefabUnitResponse:
    """Advance a unit's production stage.

    Enforces the ordered lifecycle and the QA gate - a unit cannot reach
    dispatched / delivered / installed until it has passed QA. Records a
    ProductionEvent audit row and emits domain events on dispatch / install.
    """
    service = _service(session)
    existing = await service.get_unit(unit_id)
    await verify_project_access(existing.project_id, user_id, session)
    unit = await service.advance_stage(unit_id, data, user_id=user_id)
    await session.commit()
    return await service.to_response(unit)


# ── Production-event timeline ──────────────────────────────────────────────


@router.get(
    "/units/{unit_id}/events/",
    response_model=list[ProductionEventResponse],
    dependencies=[_READ],
)
async def list_unit_events(
    unit_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> list[ProductionEventResponse]:
    """Return the production-stage audit timeline for a unit, newest first."""
    service = _service(session)
    unit = await service.get_unit(unit_id)
    await verify_project_access(unit.project_id, user_id, session)
    rows = await service.get_unit_events(unit_id)
    return [ProductionEventResponse.model_validate(r) for r in rows]
