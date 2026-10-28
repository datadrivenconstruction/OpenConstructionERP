# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Portfolio tree API (T3.3).

Mounted by the module loader at ``/api/v1/portfolio``. The tree read is pruned
to the caller's accessible projects; project attach/detach run
``verify_project_access`` on the specific project. RBAC gates: ``portfolio.read``
for reads, ``portfolio.manage`` for writes.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.portfolio.schemas import (
    AttachProjectRequest,
    CrossLinkCreate,
    CrossLinkResponse,
    NodeCreate,
    NodePatch,
    NodeResponse,
    PortfolioCpmResponse,
    TreeNode,
)
from app.modules.portfolio.service import PortfolioService

router = APIRouter(tags=["portfolio"])


def _get_service(session: SessionDep) -> PortfolioService:
    return PortfolioService(session)


@router.get(
    "/tree/",
    response_model=list[TreeNode],
    summary="Access-pruned portfolio / programme tree",
    dependencies=[Depends(RequirePermission("portfolio.read"))],
)
async def get_tree(
    user_id: CurrentUserId,
    service: PortfolioService = Depends(_get_service),
) -> list[TreeNode]:
    tree = await service.get_tree(user_id)
    return [TreeNode.model_validate(node) for node in tree]


@router.post(
    "/nodes/",
    response_model=NodeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a portfolio / programme node",
    dependencies=[Depends(RequirePermission("portfolio.manage"))],
)
async def create_node(
    body: NodeCreate,
    user_id: CurrentUserId,
    service: PortfolioService = Depends(_get_service),
) -> NodeResponse:
    node = await service.create_node(body, user_id)
    return NodeResponse.model_validate(node)


@router.patch(
    "/nodes/{node_id}/",
    response_model=NodeResponse,
    summary="Rename / reparent / reorder a node",
    dependencies=[Depends(RequirePermission("portfolio.manage"))],
)
async def patch_node(
    node_id: uuid.UUID,
    body: NodePatch,
    user_id: CurrentUserId,
    service: PortfolioService = Depends(_get_service),
) -> NodeResponse:
    node = await service.patch_node(node_id, body, user_id)
    return NodeResponse.model_validate(node)


@router.delete(
    "/nodes/{node_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a node (memberships cascade; projects untouched)",
    dependencies=[Depends(RequirePermission("portfolio.manage"))],
)
async def delete_node(
    node_id: uuid.UUID,
    user_id: CurrentUserId,
    service: PortfolioService = Depends(_get_service),
) -> Response:
    await service.delete_node(node_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/nodes/{node_id}/projects/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="File a project under a node (must be accessible to the caller)",
    dependencies=[Depends(RequirePermission("portfolio.manage"))],
)
async def attach_project(
    node_id: uuid.UUID,
    body: AttachProjectRequest,
    user_id: CurrentUserId,
    service: PortfolioService = Depends(_get_service),
) -> Response:
    await service.attach_project(node_id, body.project_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/nodes/{node_id}/projects/{project_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a project from a node (non-destructive)",
    dependencies=[Depends(RequirePermission("portfolio.manage"))],
)
async def detach_project(
    node_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    service: PortfolioService = Depends(_get_service),
) -> Response:
    await service.detach_project(node_id, project_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/cross-links/",
    response_model=CrossLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a cross-schedule dependency (needs access to both projects)",
    dependencies=[Depends(RequirePermission("portfolio.manage"))],
)
async def create_cross_link(
    body: CrossLinkCreate,
    user_id: CurrentUserId,
    service: PortfolioService = Depends(_get_service),
) -> CrossLinkResponse:
    link = await service.create_cross_link(body, user_id)
    return CrossLinkResponse.model_validate(link)


@router.get(
    "/cross-links/",
    response_model=list[CrossLinkResponse],
    summary="List cross-links touching a schedule",
    dependencies=[Depends(RequirePermission("portfolio.read"))],
)
async def list_cross_links(
    user_id: CurrentUserId,
    schedule_id: uuid.UUID = Query(...),
    service: PortfolioService = Depends(_get_service),
) -> list[CrossLinkResponse]:
    rows = await service.list_cross_links(schedule_id, user_id)
    # The register prints both ends of every dependency, and an end can live in
    # another schedule entirely, so the names are joined here once for the page
    # rather than left to the client to chase one id at a time.
    schedules, activities = await service.name_cross_link_endpoints(rows)
    return [
        CrossLinkResponse.model_validate(r).model_copy(
            update={
                "predecessor_schedule_name": schedules.get(r.predecessor_schedule_id),
                "predecessor_activity_name": activities.get(r.predecessor_activity_id),
                "successor_schedule_name": schedules.get(r.successor_schedule_id),
                "successor_activity_name": activities.get(r.successor_activity_id),
            }
        )
        for r in rows
    ]


@router.delete(
    "/cross-links/{link_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a cross-link",
    dependencies=[Depends(RequirePermission("portfolio.manage"))],
)
async def delete_cross_link(
    link_id: uuid.UUID,
    user_id: CurrentUserId,
    service: PortfolioService = Depends(_get_service),
) -> Response:
    await service.delete_cross_link(link_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/nodes/{node_id}/cpm/",
    response_model=PortfolioCpmResponse,
    summary="Portfolio (schedule-of-schedules) CPM across a node subtree",
    dependencies=[Depends(RequirePermission("portfolio.read"))],
)
async def node_cpm(
    node_id: uuid.UUID,
    user_id: CurrentUserId,
    service: PortfolioService = Depends(_get_service),
) -> PortfolioCpmResponse:
    payload = await service.compute_node_cpm(node_id, user_id)
    return PortfolioCpmResponse.model_validate(payload)
