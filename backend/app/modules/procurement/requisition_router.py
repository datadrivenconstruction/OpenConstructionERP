# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Material requisition API routes, mounted under ``/requisitions``.

Endpoints:
    GET    /requisitions/                 - List a project's requisitions
    POST   /requisitions/                 - Create a draft requisition
    GET    /requisitions/{id}             - Get one requisition with its lines
    PATCH  /requisitions/{id}             - Edit a draft
    POST   /requisitions/{id}/submit      - Submit (stays ``submitted``, never auto-approved)
    POST   /requisitions/{id}/withdraw    - Take a submitted or rejected requisition back to draft
    POST   /requisitions/{id}/cancel      - Cancel
    POST   /requisitions/{id}/approve     - Approve (``procurement.approve_requisition``, not the submitter)
    POST   /requisitions/{id}/reject      - Reject with a required comment (same gate)
    GET    /requisitions/{id}/validate    - Run the ``procurement_requisition`` rules
    POST   /requisitions/convert-to-po    - Approved requisitions of a project -> one draft purchase order
    GET    /requisitions/trace/position/{boq_position_id}  - Requisitions and orders behind a BOQ position
    GET    /requisitions/trace/purchase-order/{po_id}      - Requisitions and BOQ sources behind an order
    GET    /requisitions/schedule-activities               - Activities a line can take its needed-by date from
    GET    /requisitions/settings          - The project's order owner and default approvers
    PUT    /requisitions/settings          - Change them (``procurement.manage_settings``)
    GET    /requisitions/feed              - Replayable change feed of a project's requisitions (cursor)
    POST   /requisitions/{id}/external-orders - Reconcile an order an external purchasing system placed

Every handler resolves the project from the trusted row (or the request body on
create) and checks the caller's access to it, the same gate the purchase order
endpoints use. This router is included into the procurement router before its
``/{po_id}`` routes so ``requisitions`` is never parsed as an order id.
"""

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.procurement.models import MaterialRequisition
from app.modules.procurement.requisition_feed import DEFAULT_SETTLE_SECONDS, MAX_SETTLE_SECONDS, page_feed
from app.modules.procurement.requisition_service import (
    RequisitionWorkflowService,
    build_response_context,
    requisition_to_response,
)
from app.modules.procurement.schemas import (
    ExternalOrderReport,
    PositionTraceResponse,
    POTraceResponse,
    ProcurementSettingsResponse,
    ProcurementSettingsUpdate,
    RequisitionApprove,
    RequisitionCancel,
    RequisitionConvert,
    RequisitionConvertResponse,
    RequisitionCreate,
    RequisitionFeedPage,
    RequisitionListResponse,
    RequisitionReject,
    RequisitionResponse,
    RequisitionUpdate,
    RequisitionValidationResponse,
    ScheduleActivityOptionPage,
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


async def _respond(service: RequisitionWorkflowService, req: MaterialRequisition) -> RequisitionResponse:
    """One requisition with its vendor name, order number and converted order lines."""
    return requisition_to_response(req, await build_response_context(service.session, [req]))


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
    context = await build_response_context(session, rows)
    return RequisitionListResponse(
        items=[requisition_to_response(r, context) for r in rows],
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
    """Create a draft requisition, optionally with lines raised from the BOQ.

    With ``client_request_id`` a repeated create answers with the requisition
    the first one made instead of raising a second one.
    """
    await verify_project_access(data.project_id, str(user_id), session)
    req = await service.create(data, user_id=str(user_id))
    return await _respond(service, req)


@router.get(
    "/settings",
    response_model=ProcurementSettingsResponse,
    dependencies=[Depends(RequirePermission("procurement.read"))],
)
async def get_requisition_settings(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: RequisitionWorkflowService = Depends(_get_service),
) -> ProcurementSettingsResponse:
    """Where the project's orders are placed, and who approves its requisitions by default."""
    await verify_project_access(project_id, str(user_id), session)
    return await service.settings_response(project_id)


@router.put(
    "/settings",
    response_model=ProcurementSettingsResponse,
    dependencies=[Depends(RequirePermission("procurement.manage_settings"))],
)
async def update_requisition_settings(
    data: ProcurementSettingsUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: RequisitionWorkflowService = Depends(_get_service),
) -> ProcurementSettingsResponse:
    """Change the project's order owner or default approvers. Existing requisitions keep theirs."""
    await verify_project_access(project_id, str(user_id), session)
    return await service.update_settings(project_id, data, user_id=str(user_id))


@router.get(
    "/feed",
    response_model=RequisitionFeedPage,
    dependencies=[Depends(RequirePermission("procurement.read"))],
)
async def requisition_feed(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    after: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    settle_seconds: int = Query(default=DEFAULT_SETTLE_SECONDS, ge=0, le=MAX_SETTLE_SECONDS),
    requisition_id: uuid.UUID | None = Query(default=None),
) -> RequisitionFeedPage:
    """Every change to the project's requisitions after a cursor, oldest first.

    An integration keeps the last ``next_cursor`` and asks again with it as
    ``after``; replaying from an older cursor returns the same entries again,
    each with its id and the requisition's ``row_version`` to drop duplicates by.
    """
    await verify_project_access(project_id, str(user_id), session)
    return await page_feed(
        session,
        project_id,
        after=after,
        limit=limit,
        settle_seconds=settle_seconds,
        requisition_id=requisition_id,
    )


@router.post(
    "/convert-to-po",
    response_model=RequisitionConvertResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("procurement.create"))],
)
async def convert_requisitions_to_po(
    data: RequisitionConvert,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RequisitionWorkflowService = Depends(_get_service),
) -> RequisitionConvertResponse:
    """Turn approved requisitions of one project into one draft purchase order.

    The order still goes through its own approval before it is issued.
    """
    await verify_project_access(data.project_id, str(user_id), session)
    return await service.convert_to_purchase_order(data, user_id=str(user_id))


@router.get(
    "/schedule-activities",
    response_model=ScheduleActivityOptionPage,
    dependencies=[Depends(RequirePermission("procurement.read"))],
)
async def list_schedule_activities(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=1000),
    service: RequisitionWorkflowService = Depends(_get_service),
) -> ScheduleActivityOptionPage:
    """One page of the project's schedule activities, by start date, for proposing a line's needed-by date."""
    await verify_project_access(project_id, str(user_id), session)
    return await service.page_schedule_activities(project_id, offset=offset, limit=limit)


@router.get(
    "/trace/position/{boq_position_id}",
    response_model=PositionTraceResponse,
    dependencies=[Depends(RequirePermission("procurement.read"))],
)
async def trace_boq_position(
    boq_position_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: RequisitionWorkflowService = Depends(_get_service),
) -> PositionTraceResponse:
    """The requisitions raised from a BOQ position and the order lines they became."""
    await verify_project_access(project_id, str(user_id), session)
    return await service.trace_position(project_id, boq_position_id)


@router.get(
    "/trace/purchase-order/{po_id}",
    response_model=POTraceResponse,
    dependencies=[Depends(RequirePermission("procurement.read"))],
)
async def trace_purchase_order(
    po_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RequisitionWorkflowService = Depends(_get_service),
) -> POTraceResponse:
    """The requisitions a purchase order came from, with each line's BOQ sources."""
    po = await ProcurementService(session).get_po(po_id)
    await verify_project_access(po.project_id, str(user_id), session)
    return await service.trace_purchase_order(po)


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
    return await _respond(service, req)


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
    return await _respond(service, req)


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
    return await _respond(service, req)


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
    return await _respond(service, req)


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
    return await _respond(service, req)


@router.post(
    "/{requisition_id}/approve",
    response_model=RequisitionResponse,
    dependencies=[Depends(RequirePermission("procurement.approve_requisition"))],
)
async def approve_requisition(
    requisition_id: uuid.UUID,
    user_id: CurrentUserId,
    data: RequisitionApprove | None = None,
    service: RequisitionWorkflowService = Depends(_get_service),
) -> RequisitionResponse:
    """Approve a submitted requisition. The person who submitted it may not."""
    await _load_guarded(service, requisition_id, user_id)
    req = await service.approve(requisition_id, user_id=str(user_id), comment=data.comment if data else None)
    return await _respond(service, req)


@router.post(
    "/{requisition_id}/reject",
    response_model=RequisitionResponse,
    dependencies=[Depends(RequirePermission("procurement.approve_requisition"))],
)
async def reject_requisition(
    requisition_id: uuid.UUID,
    data: RequisitionReject,
    user_id: CurrentUserId,
    service: RequisitionWorkflowService = Depends(_get_service),
) -> RequisitionResponse:
    """Reject a submitted requisition with the reason the requester needs."""
    await _load_guarded(service, requisition_id, user_id)
    req = await service.reject(requisition_id, user_id=str(user_id), comment=data.comment)
    return await _respond(service, req)


@router.post(
    "/{requisition_id}/external-orders",
    response_model=RequisitionResponse,
    dependencies=[Depends(RequirePermission("procurement.update"))],
)
async def report_external_order(
    requisition_id: uuid.UUID,
    data: ExternalOrderReport,
    user_id: CurrentUserId,
    service: RequisitionWorkflowService = Depends(_get_service),
) -> RequisitionResponse:
    """Reconcile an order an external purchasing system placed against this requisition.

    No purchase order and no commitment is created. Repeating the same report
    changes nothing.
    """
    await _load_guarded(service, requisition_id, user_id)
    req = await service.report_external_order(requisition_id, data, user_id=str(user_id))
    return await _respond(service, req)


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
