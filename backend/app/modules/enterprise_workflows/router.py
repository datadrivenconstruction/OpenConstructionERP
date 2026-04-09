"""Enterprise Workflows API routes.

Endpoints:
    GET    /                         — List workflows
    POST   /                         — Create workflow (auth required)
    GET    /{id}                     — Get single workflow
    PATCH  /{id}                     — Update workflow (auth required)
    DELETE /{id}                     — Delete workflow (auth required)
    GET    /requests                 — List approval requests
    POST   /requests                 — Submit approval request (auth required)
    GET    /requests/{id}            — Get single approval request
    POST   /requests/{id}/approve    — Approve request (auth required)
    POST   /requests/{id}/reject     — Reject request (auth required)
"""

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, SessionDep
from app.modules.enterprise_workflows.schemas import (
    ApprovalDecision,
    ApprovalRequestCreate,
    ApprovalRequestListResponse,
    ApprovalRequestResponse,
    WorkflowCreate,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowUpdate,
)
from app.modules.enterprise_workflows.service import WorkflowService

router = APIRouter()


def _get_service(session: SessionDep) -> WorkflowService:
    return WorkflowService(session)


# ── Workflows ───────────────────────────────────────────────────────────────


@router.get("/", response_model=WorkflowListResponse)
async def list_workflows(
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    project_id: uuid.UUID | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: WorkflowService = Depends(_get_service),
) -> WorkflowListResponse:
    """List approval workflows with optional filters."""
    items, total = await service.list_workflows(
        project_id=project_id,
        entity_type=entity_type,
        is_active=is_active,
        offset=offset,
        limit=limit,
    )
    return WorkflowListResponse(
        items=[WorkflowResponse.model_validate(w) for w in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/", response_model=WorkflowResponse, status_code=201)
async def create_workflow(
    data: WorkflowCreate,
    user_id: CurrentUserId,
    service: WorkflowService = Depends(_get_service),
) -> WorkflowResponse:
    """Create a new approval workflow."""
    workflow = await service.create_workflow(data)
    return WorkflowResponse.model_validate(workflow)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: WorkflowService = Depends(_get_service),
) -> WorkflowResponse:
    """Get a single workflow by ID."""
    workflow = await service.get_workflow(workflow_id)
    return WorkflowResponse.model_validate(workflow)


@router.patch("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: uuid.UUID,
    data: WorkflowUpdate,
    user_id: CurrentUserId,
    service: WorkflowService = Depends(_get_service),
) -> WorkflowResponse:
    """Update a workflow."""
    workflow = await service.update_workflow(workflow_id, data)
    return WorkflowResponse.model_validate(workflow)


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow(
    workflow_id: uuid.UUID,
    user_id: CurrentUserId,
    service: WorkflowService = Depends(_get_service),
) -> None:
    """Delete a workflow and all its requests."""
    await service.delete_workflow(workflow_id)


# ── Approval Requests ──────────────────────────────────────────────────────


@router.get("/requests/", response_model=ApprovalRequestListResponse)
async def list_approval_requests(
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    workflow_id: uuid.UUID | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: WorkflowService = Depends(_get_service),
) -> ApprovalRequestListResponse:
    """List approval requests with optional filters."""
    items, total = await service.list_requests(
        workflow_id=workflow_id,
        entity_type=entity_type,
        request_status=status,
        offset=offset,
        limit=limit,
    )
    return ApprovalRequestListResponse(
        items=[ApprovalRequestResponse.model_validate(r) for r in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/requests/", response_model=ApprovalRequestResponse, status_code=201)
async def submit_approval_request(
    data: ApprovalRequestCreate,
    user_id: CurrentUserId,
    service: WorkflowService = Depends(_get_service),
) -> ApprovalRequestResponse:
    """Submit an entity for approval."""
    request = await service.submit_request(data, user_id=user_id)
    return ApprovalRequestResponse.model_validate(request)


@router.get("/requests/{request_id}", response_model=ApprovalRequestResponse)
async def get_approval_request(
    request_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: WorkflowService = Depends(_get_service),
) -> ApprovalRequestResponse:
    """Get a single approval request by ID."""
    request = await service.get_request(request_id)
    return ApprovalRequestResponse.model_validate(request)


@router.post("/requests/{request_id}/approve/", response_model=ApprovalRequestResponse)
async def approve_request(
    request_id: uuid.UUID,
    data: ApprovalDecision | None = None,
    user_id: CurrentUserId = "",  # type: ignore[assignment]
    service: WorkflowService = Depends(_get_service),
) -> ApprovalRequestResponse:
    """Approve an approval request."""
    notes = data.decision_notes if data else None
    request = await service.approve_request(request_id, user_id=user_id, decision_notes=notes)
    return ApprovalRequestResponse.model_validate(request)


@router.post("/requests/{request_id}/reject/", response_model=ApprovalRequestResponse)
async def reject_request(
    request_id: uuid.UUID,
    data: ApprovalDecision | None = None,
    user_id: CurrentUserId = "",  # type: ignore[assignment]
    service: WorkflowService = Depends(_get_service),
) -> ApprovalRequestResponse:
    """Reject an approval request."""
    notes = data.decision_notes if data else None
    request = await service.reject_request(request_id, user_id=user_id, decision_notes=notes)
    return ApprovalRequestResponse.model_validate(request)
