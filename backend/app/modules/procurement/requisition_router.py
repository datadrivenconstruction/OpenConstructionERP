# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Material requisition API routes, mounted under ``/requisitions``.

Endpoints:
    GET    /requisitions/                 - List a project's requisitions
    POST   /requisitions/                 - Create a draft requisition
    GET    /requisitions/{id}             - Get one requisition with its lines
    PATCH  /requisitions/{id}             - Edit a draft
    POST   /requisitions/{id}/submit      - Submit (stays ``submitted``, never auto-approved)
    POST   /requisitions/{id}/withdraw    - Take a submitted requisition back to draft
    POST   /requisitions/{id}/cancel      - Cancel
    GET    /requisitions/{id}/validate    - Run the ``procurement_requisition`` rules

Every handler resolves the project from the trusted row (or the request body on
create) and checks the caller's access to it, the same gate the purchase order
endpoints use. This router is included into the procurement router before its
``/{po_id}`` routes so ``requisitions`` is never parsed as an order id.
"""

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.procurement.models import MaterialRequisition
from app.modules.procurement.requisition_service import (
    RequisitionWorkflowService,
    requisition_to_response,
)
from app.modules.procurement.schemas import (
    RequisitionCancel,
    RequisitionCreate,
    RequisitionListResponse,
    RequisitionResponse,
    RequisitionUpdate,
    RequisitionValidationResponse,
)
from app.modules.procurement.service import ProcurementService

router = APIRouter(tags=["procurement"])


def _get_service(session: SessionDep) -> RequisitionWorkflowService:
    return RequisitionWorkflowService(session)


async def _load_guarded(
    service: RequisitionWorkflowService,
    requisition_id: uuid.UUID,
    user_id: str,
) -> MaterialRequisition:
    req = await service.get_requisition(requisition_id)
    await verify_project_access(req.project_id, str(user_id), service.session)
    return req


@router.get(
    "/",
    response_model=RequisitionListResponse,
    dependencies=[Depends(RequirePermission("procurement.read"))],
)
async def list_requisitions(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: RequisitionWorkflowService = Depends(_get_service),
) -> RequisitionListResponse:
    """List a project's requisitions, newest first."""
    await verify_project_access(project_id, str(user_id), session)
    rows, total = await service.list_requisitions(project_id, req_status=status, offset=offset, limit=limit)
    return RequisitionListResponse(
        items=[requisition_to_response(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/",
    response_model=RequisitionResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("procurement.create"))],
)
async def create_requisition(
    data: RequisitionCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RequisitionWorkflowService = Depends(_get_service),
) -> RequisitionResponse:
    """Create a draft requisition, optionally with lines raised from the BOQ."""
    await verify_project_access(data.project_id, str(user_id), session)
    req = await service.create(data, user_id=str(user_id))
    return requisition_to_response(req)


@router.get(
    "/{requisition_id}",
    response_model=RequisitionResponse,
    dependencies=[Depends(RequirePermission("procurement.read"))],
)
async def get_requisition(
    requisition_id: uuid.UUID,
    user_id: CurrentUserId,
    service: RequisitionWorkflowService = Depends(_get_service),
) -> RequisitionResponse:
    """Get one requisition with its lines, sources and progress."""
    req = await _load_guarded(service, requisition_id, user_id)
    return requisition_to_response(req)


@router.patch(
    "/{requisition_id}",
    response_model=RequisitionResponse,
    dependencies=[Depends(RequirePermission("procurement.update"))],
)
async def update_requisition(
    requisition_id: uuid.UUID,
    data: RequisitionUpdate,
    user_id: CurrentUserId,
    service: RequisitionWorkflowService = Depends(_get_service),
) -> RequisitionResponse:
    """Edit a draft requisition (409 once it has been submitted)."""
    await _load_guarded(service, requisition_id, user_id)
    req = await service.update(requisition_id, data, user_id=str(user_id))
    return requisition_to_response(req)


@router.post(
    "/{requisition_id}/submit",
    response_model=RequisitionResponse,
    dependencies=[Depends(RequirePermission("procurement.create"))],
)
async def submit_requisition(
    requisition_id: uuid.UUID,
    user_id: CurrentUserId,
    service: RequisitionWorkflowService = Depends(_get_service),
) -> RequisitionResponse:
    """Submit a draft. It stays ``submitted``; nothing here approves it."""
    await _load_guarded(service, requisition_id, user_id)
    req = await service.submit(requisition_id, user_id=str(user_id))
    return requisition_to_response(req)


@router.post(
    "/{requisition_id}/withdraw",
    response_model=RequisitionResponse,
    dependencies=[Depends(RequirePermission("procurement.update"))],
)
async def withdraw_requisition(
    requisition_id: uuid.UUID,
    user_id: CurrentUserId,
    service: RequisitionWorkflowService = Depends(_get_service),
) -> RequisitionResponse:
    """Take a submitted requisition back to draft."""
    await _load_guarded(service, requisition_id, user_id)
    req = await service.withdraw(requisition_id, user_id=str(user_id))
    return requisition_to_response(req)


@router.post(
    "/{requisition_id}/cancel",
    response_model=RequisitionResponse,
    dependencies=[Depends(RequirePermission("procurement.update"))],
)
async def cancel_requisition(
    requisition_id: uuid.UUID,
    user_id: CurrentUserId,
    data: RequisitionCancel | None = None,
    service: RequisitionWorkflowService = Depends(_get_service),
) -> RequisitionResponse:
    """Cancel a requisition. The row and its history are kept."""
    await _load_guarded(service, requisition_id, user_id)
    req = await service.cancel(requisition_id, user_id=str(user_id), reason=data.reason if data else None)
    return requisition_to_response(req)


@router.get(
    "/{requisition_id}/validate",
    response_model=RequisitionValidationResponse,
    dependencies=[Depends(RequirePermission("procurement.read"))],
)
async def validate_requisition(
    requisition_id: uuid.UUID,
    user_id: CurrentUserId,
    service: RequisitionWorkflowService = Depends(_get_service),
) -> RequisitionValidationResponse:
    """Run the requisition rules without changing anything."""
    req = await _load_guarded(service, requisition_id, user_id)
    report = await service.validate(req)
    return RequisitionValidationResponse(**ProcurementService._po_report_to_dict(report))
