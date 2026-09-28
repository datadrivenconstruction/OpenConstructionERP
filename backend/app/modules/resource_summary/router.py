# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Resource Summary API routes.

Mounted at ``/api/v1/resource-summary``. One procurement-ready rollup of an
estimate's resource demand:

    GET  /projects/{project_id}            - the aggregated procurement statement
    GET  /projects/{project_id}/csv        - the same statement as a CSV download
    GET  /projects/{project_id}/buy-list   - materials grouped into a purchase list
    POST /projects/{project_id}/snapshots  - freeze the current statement (manager)
    GET  /projects/{project_id}/snapshots  - list frozen statements

Reads need viewer access to the project; saving a snapshot is a manager action.
Every route verifies project access first, so a caller can never read the resource
demand of a project they cannot see.
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.resource_summary.aggregate import render_csv
from app.modules.resource_summary.schemas import (
    MaterialBuyListResponse,
    ResourceSnapshotDetail,
    ResourceSnapshotSummary,
    ResourceStatementResponse,
)
from app.modules.resource_summary.service import ResourceSummaryService

router = APIRouter()

_READ = Depends(RequirePermission("resource_summary.read"))
_SNAPSHOT = Depends(RequirePermission("resource_summary.snapshot"))


def _service(session: AsyncSession) -> ResourceSummaryService:
    return ResourceSummaryService(session)


@router.get(
    "/projects/{project_id}",
    response_model=ResourceStatementResponse,
    dependencies=[_READ],
)
async def get_resource_statement(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> ResourceStatementResponse:
    """Aggregate every position's stored resource split into one procurement statement."""
    await verify_project_access(project_id, user_id, session)
    statement, generated_at = await _service(session).generate(project_id)
    return ResourceStatementResponse.from_statement(
        statement,
        project_id=project_id,
        generated_at=generated_at,
    )


@router.get(
    "/projects/{project_id}/csv",
    response_class=Response,
    response_model=None,
    dependencies=[_READ],
)
async def export_resource_statement_csv(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> Response:
    """Download the procurement statement as a spreadsheet-friendly CSV."""
    await verify_project_access(project_id, user_id, session)
    statement, _generated_at = await _service(session).generate(project_id)
    # Writing the file walks every resource line and is pure CPU, so it runs in a
    # worker thread; the statement is a plain dataclass tree, not ORM rows.
    body = await asyncio.to_thread(render_csv, statement)
    filename = f"resource-statement-{project_id}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/projects/{project_id}/buy-list",
    response_model=MaterialBuyListResponse,
    dependencies=[_READ],
)
async def get_material_buy_list(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> MaterialBuyListResponse:
    """Group the estimate's material resource lines into a procurement buy-list."""
    await verify_project_access(project_id, user_id, session)
    buy_list, generated_at = await _service(session).generate_buy_list(project_id)
    return MaterialBuyListResponse.from_buy_list(
        buy_list,
        project_id=project_id,
        generated_at=generated_at,
    )


@router.post(
    "/projects/{project_id}/snapshots",
    response_model=ResourceSnapshotDetail,
    dependencies=[_SNAPSHOT],
)
async def create_resource_snapshot(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> ResourceSnapshotDetail:
    """Freeze the current procurement statement as a stored snapshot (manager)."""
    await verify_project_access(project_id, user_id, session)
    snapshot = await _service(session).save_snapshot(project_id)
    return ResourceSnapshotDetail(
        id=snapshot.id,
        generated_at=snapshot.generated_at,
        currency=snapshot.currency,
        total_cost=snapshot.total_cost,
        line_count=snapshot.line_count,
        payload=snapshot.payload or {},
    )


@router.get(
    "/projects/{project_id}/snapshots",
    response_model=list[ResourceSnapshotSummary],
    dependencies=[_READ],
)
async def list_resource_snapshots(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> list[ResourceSnapshotSummary]:
    """List a project's saved procurement statements, most recent first."""
    await verify_project_access(project_id, user_id, session)
    snapshots = await _service(session).list_snapshots(project_id)
    return [ResourceSnapshotSummary.model_validate(snap) for snap in snapshots]
