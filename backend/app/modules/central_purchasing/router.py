# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Central purchasing API, mounted at /api/v1/central-purchasing.

The central buyer (``central_purchasing.manage``) works the whole bundle. A project team reads
``/my-shares?project_id=`` for a project it may open, and sees that project's share only.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.central_purchasing.schemas import (
    AwardRequest,
    BundleCreate,
    BundleDetail,
    BundleListResponse,
    BundleUpdate,
    CallOffRequest,
    CallOffResult,
    Catalogue,
    CostLineListResponse,
    LineIn,
    LineUpdate,
    MyShare,
    PreviewRequest,
    ProjectAdd,
    ProjectUpdate,
)
from app.modules.central_purchasing.service import CentralPurchasingService

router = APIRouter(tags=["central_purchasing"])

_MANAGE = Depends(RequirePermission("central_purchasing.manage"))
_AWARD = Depends(RequirePermission("central_purchasing.award"))
_READ_SHARE = Depends(RequirePermission("central_purchasing.read_share"))


def _svc(session: SessionDep) -> CentralPurchasingService:
    return CentralPurchasingService(session)


async def _may_open(session: SessionDep, row: object, user_id: str) -> bool:
    """The bundle's creator, an admin, or a manager who may open every project in it.

    A member of only some of the projects works through ``/my-shares``, which shows that project's
    share and nothing of the others.
    """
    from app.modules.users.repository import UserRepository

    if str(getattr(row, "created_by", "") or "") == str(user_id):
        return True
    try:
        user = await UserRepository(session).get_by_id(uuid.UUID(str(user_id)))
        if user is not None and getattr(user, "role", "") == "admin":
            return True
    except (ValueError, TypeError):
        return False
    links = list(getattr(row, "projects", None) or [])
    if not links:
        return False
    for link in links:
        try:
            await verify_project_access(link.project_id, user_id, session)
        except HTTPException:
            return False
    return True


async def _open_bundle_or_404(svc: CentralPurchasingService, session: SessionDep, bundle_id: uuid.UUID, user_id: str):
    """Load a bundle the caller may open; another company's bundle answers 404, like a missing one."""
    row = await svc.get(bundle_id)
    if not await _may_open(session, row, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bundle not found")
    return row


@router.get("/my-shares", response_model=list[MyShare], dependencies=[_READ_SHARE])
async def my_shares(session: SessionDep, user_id: CurrentUserId, project_id: uuid.UUID = Query(...)) -> list[MyShare]:
    """The project's shares of published and awarded bundles: its quantities, budget and own document."""
    await verify_project_access(project_id, user_id, session)
    return await _svc(session).my_shares(project_id)


@router.get("/catalogues", response_model=list[Catalogue], dependencies=[_MANAGE])
async def catalogues(
    session: SessionDep, user_id: CurrentUserId, bundle_id: uuid.UUID | None = Query(default=None)
) -> list[Catalogue]:
    """Cost code catalogues the group's markets contribute; empty when no pack applies."""
    svc = _svc(session)
    row = await _open_bundle_or_404(svc, session, bundle_id, user_id) if bundle_id else None
    return await svc.catalogues(row)


@router.get("/cost-lines", response_model=CostLineListResponse, dependencies=[_MANAGE])
async def cost_lines(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> CostLineListResponse:
    await verify_project_access(project_id, user_id, session)
    rows = await _svc(session).cost_line_options(project_id)
    return CostLineListResponse(items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit)


@router.get("/", response_model=BundleListResponse, dependencies=[_MANAGE])
async def list_bundles(
    session: SessionDep,
    user_id: CurrentUserId,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> BundleListResponse:
    svc = _svc(session)
    rows = {r.id: r for r in await svc.repo.list()}
    visible = [s for s in await svc.summaries() if s.id in rows and await _may_open(session, rows[s.id], user_id)]
    return BundleListResponse(items=visible[offset : offset + limit], total=len(visible), offset=offset, limit=limit)


@router.post("/", response_model=BundleDetail, status_code=201, dependencies=[_MANAGE])
async def create_bundle(data: BundleCreate, session: SessionDep, user_id: CurrentUserId) -> BundleDetail:
    svc = _svc(session)
    row = await svc.create(data, user_id)
    return await svc.detail(row)


@router.get("/{bundle_id}", response_model=BundleDetail, dependencies=[_MANAGE])
async def get_bundle(bundle_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> BundleDetail:
    svc = _svc(session)
    return await svc.detail(await _open_bundle_or_404(svc, session, bundle_id, user_id))


@router.patch("/{bundle_id}", response_model=BundleDetail, dependencies=[_MANAGE])
async def update_bundle(
    bundle_id: uuid.UUID, data: BundleUpdate, session: SessionDep, user_id: CurrentUserId
) -> BundleDetail:
    svc = _svc(session)
    row = await svc.update(await _open_bundle_or_404(svc, session, bundle_id, user_id), data)
    return await svc.detail(row)


@router.delete("/{bundle_id}", status_code=204, dependencies=[_MANAGE])
async def delete_bundle(bundle_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> None:
    svc = _svc(session)
    await svc.delete(await _open_bundle_or_404(svc, session, bundle_id, user_id))


@router.post("/{bundle_id}/preview", response_model=BundleDetail, dependencies=[_MANAGE])
async def preview(
    bundle_id: uuid.UUID, data: PreviewRequest, session: SessionDep, user_id: CurrentUserId
) -> BundleDetail:
    """The award split for terms not saved yet; nothing is written."""
    svc = _svc(session)
    return await svc.detail(await _open_bundle_or_404(svc, session, bundle_id, user_id), data)


@router.post("/{bundle_id}/projects", response_model=BundleDetail, dependencies=[_MANAGE])
async def add_project(
    bundle_id: uuid.UUID, data: ProjectAdd, session: SessionDep, user_id: CurrentUserId
) -> BundleDetail:
    await verify_project_access(data.project_id, user_id, session)
    svc = _svc(session)
    row = await _open_bundle_or_404(svc, session, bundle_id, user_id)
    await svc.add_project(row, data)
    return await svc.detail(row)


@router.patch("/{bundle_id}/projects/{bp_id}", response_model=BundleDetail, dependencies=[_MANAGE])
async def update_project(
    bundle_id: uuid.UUID, bp_id: uuid.UUID, data: ProjectUpdate, session: SessionDep, user_id: CurrentUserId
) -> BundleDetail:
    svc = _svc(session)
    row = await _open_bundle_or_404(svc, session, bundle_id, user_id)
    await svc.update_project(row, bp_id, data)
    return await svc.detail(row)


@router.delete("/{bundle_id}/projects/{bp_id}", response_model=BundleDetail, dependencies=[_MANAGE])
async def remove_project(
    bundle_id: uuid.UUID, bp_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> BundleDetail:
    svc = _svc(session)
    row = await _open_bundle_or_404(svc, session, bundle_id, user_id)
    await svc.remove_project(row, bp_id)
    return await svc.detail(row)


@router.post("/{bundle_id}/lines", response_model=BundleDetail, dependencies=[_MANAGE])
async def add_line(bundle_id: uuid.UUID, data: LineIn, session: SessionDep, user_id: CurrentUserId) -> BundleDetail:
    svc = _svc(session)
    row = await _open_bundle_or_404(svc, session, bundle_id, user_id)
    await svc.add_line(row, data)
    return await svc.detail(row)


@router.patch("/{bundle_id}/lines/{line_id}", response_model=BundleDetail, dependencies=[_MANAGE])
async def update_line(
    bundle_id: uuid.UUID, line_id: uuid.UUID, data: LineUpdate, session: SessionDep, user_id: CurrentUserId
) -> BundleDetail:
    svc = _svc(session)
    row = await _open_bundle_or_404(svc, session, bundle_id, user_id)
    await svc.update_line(row, line_id, data)
    return await svc.detail(row)


@router.delete("/{bundle_id}/lines/{line_id}", response_model=BundleDetail, dependencies=[_MANAGE])
async def delete_line(
    bundle_id: uuid.UUID, line_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> BundleDetail:
    svc = _svc(session)
    row = await _open_bundle_or_404(svc, session, bundle_id, user_id)
    await svc.delete_line(row, line_id)
    return await svc.detail(row)


@router.post("/{bundle_id}/publish", response_model=BundleDetail, dependencies=[_MANAGE])
async def publish(bundle_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> BundleDetail:
    svc = _svc(session)
    row = await svc.publish(await _open_bundle_or_404(svc, session, bundle_id, user_id))
    return await svc.detail(row)


@router.post("/{bundle_id}/award", response_model=BundleDetail, dependencies=[_MANAGE, _AWARD])
async def award(bundle_id: uuid.UUID, data: AwardRequest, session: SessionDep, user_id: CurrentUserId) -> BundleDetail:
    """Draft the per-project documents (or the framework agreements); nothing is signed."""
    svc = _svc(session)
    row = await svc.award(await _open_bundle_or_404(svc, session, bundle_id, user_id), data, user_id)
    return await svc.detail(row)


@router.post("/{bundle_id}/call-offs", response_model=CallOffResult, status_code=201, dependencies=[_MANAGE])
async def call_off(
    bundle_id: uuid.UUID, data: CallOffRequest, session: SessionDep, user_id: CurrentUserId
) -> CallOffResult:
    await verify_project_access(data.project_id, user_id, session)
    svc = _svc(session)
    return await svc.call_off(await _open_bundle_or_404(svc, session, bundle_id, user_id), data, user_id)
