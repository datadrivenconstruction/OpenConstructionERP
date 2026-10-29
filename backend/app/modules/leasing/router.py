# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Leasing API routes (auto-mounted at /api/v1/leasing).

Endpoints (RequirePermission + per-project access check on every object route):
    GET    /?project_id=                       leases of a project
    POST   /                                   create a draft lease
    GET    /export-profiles                    export profiles available
    GET    /rent-roll?project_id=&as_of=       live leases with current and annual rent
    GET    /arrears?project_id=&as_of=         overdue rent read from finance
    GET    /export?project_id=&format=         leases in an export profile (json, csv, pack profiles)
    POST   /schedule/run                       raise receivable drafts for due rent
    GET    /{id}                               lease with events and documents
    PATCH  /{id}                               edit (terms only while draft)
    DELETE /{id}                               delete a draft
    POST   /{id}/activate                      draft -> active, builds the schedule
    POST   /{id}/terminate                     notice or end
    POST   /{id}/renew                         follow-on draft lease
    POST   /{id}/review                        record an index review rate
    GET    /{id}/schedule                      rent schedule
    POST   /{id}/schedule                      regenerate the schedule (idempotent)
    GET    /{id}/validate                      run the leasing rule set
    POST   /{id}/documents                     link a project document
    DELETE /{id}/documents/{document_id}       unlink it
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.leasing.schemas import (
    ActivateRequest,
    ArrearsResponse,
    DocumentLinkRequest,
    EventResponse,
    LeaseCreate,
    LeaseDetailResponse,
    LeaseDocument,
    LeaseListResponse,
    LeaseResponse,
    LeaseUpdate,
    RenewRequest,
    RentRollResponse,
    ReviewRequest,
    ScheduleLineResponse,
    ScheduleResponse,
    ScheduleRunRequest,
    ScheduleRunResponse,
    TerminateRequest,
    ValidationResponse,
)
from app.modules.leasing.service import LeasingService, export_profiles

router = APIRouter(tags=["leasing"])


def _uid(user_id: str | None) -> str | None:
    return str(user_id) if user_id else None


def _schedule(lease, lines) -> ScheduleResponse:
    total = sum((Decimal(x.amount) + Decimal(x.tax_amount or 0) for x in lines), Decimal("0"))
    return ScheduleResponse(
        lease_id=lease.id,
        currency=lease.currency,
        total=format(total, "f"),
        items=[ScheduleLineResponse.model_validate(x) for x in lines],
    )


@router.get("/", response_model=LeaseListResponse)
async def list_leases(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    status: str | None = Query(default=None, pattern="^(draft|active|notice|ended)$"),
    unit_ref: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("leasing.read")),
) -> LeaseListResponse:
    """Leases of one project."""
    await verify_project_access(project_id, user_id or "", session)
    rows = await LeasingService(session).repo.list_leases(
        [project_id], status=status, unit_ref=unit_ref, limit=limit, offset=offset
    )
    return LeaseListResponse(items=[LeaseResponse.model_validate(r) for r in rows], total=len(rows))


@router.post("/", response_model=LeaseResponse, status_code=201)
async def create_lease(
    body: LeaseCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("leasing.create")),
) -> LeaseResponse:
    """Create a draft lease; the leasing rules must pass."""
    await verify_project_access(body.project_id, user_id or "", session)
    return LeaseResponse.model_validate(await LeasingService(session).create(body, _uid(user_id)))


@router.get("/export-profiles")
async def list_export_profiles(
    _perm: None = Depends(RequirePermission("leasing.read")),
) -> dict[str, list[str]]:
    """Export profiles available: the generic ones and any a pack registered."""
    return {"profiles": export_profiles()}


@router.get("/rent-roll", response_model=RentRollResponse)
async def rent_roll(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    as_of: date | None = Query(default=None),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("leasing.read")),
) -> RentRollResponse:
    """Live leases with their current and annual rent."""
    await verify_project_access(project_id, user_id or "", session)
    service = LeasingService(session)
    leases = await service.repo.list_leases([project_id], limit=10_000)
    return RentRollResponse(**await service.rent_roll(leases, as_of or date.today()))


@router.get("/arrears", response_model=ArrearsResponse)
async def arrears(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    as_of: date | None = Query(default=None),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("leasing.read")),
) -> ArrearsResponse:
    """Overdue rent, read from finance invoices and payments."""
    await verify_project_access(project_id, user_id or "", session)
    service = LeasingService(session)
    leases = await service.repo.list_leases([project_id], limit=10_000)
    return ArrearsResponse(**await service.arrears(leases, as_of or date.today()))


@router.get("/export", response_model=None)
async def export_leases(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    format: str = Query(default="json", min_length=1, max_length=40),  # noqa: A002 - public query name
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("leasing.read")),
) -> Response:
    """Leases of a project in an export profile."""
    await verify_project_access(project_id, user_id or "", session)
    service = LeasingService(session)
    leases = await service.repo.list_leases([project_id], limit=10_000)
    body, media_type, ext = service.export(leases, format)
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="leases.{ext}"'},
    )


@router.post("/schedule/run", response_model=ScheduleRunResponse)
async def run_schedule(
    body: ScheduleRunRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("leasing.bill")),
) -> ScheduleRunResponse:
    """Raise a receivable draft in finance for each due, uninvoiced rent line."""
    await verify_project_access(body.project_id, user_id or "", session)
    service = LeasingService(session)
    if body.lease_id is not None:
        lease = await service.get(body.lease_id)
        if lease.project_id != body.project_id:
            raise HTTPException(status_code=404, detail="Lease not found")
        leases = [lease]
    else:
        leases = await service.repo.list_leases([body.project_id], limit=10_000)
    return ScheduleRunResponse(**await service.run_schedule(leases, body.as_of or date.today(), _uid(user_id)))


@router.get("/{lease_id}", response_model=LeaseDetailResponse)
async def get_lease(
    lease_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("leasing.read")),
) -> LeaseDetailResponse:
    """A lease with its events and linked documents."""
    service = LeasingService(session)
    lease = await service.get(lease_id)
    await verify_project_access(lease.project_id, user_id or "", session)
    return LeaseDetailResponse(
        lease=LeaseResponse.model_validate(lease),
        events=[EventResponse.model_validate(e) for e in await service.repo.events(lease.id)],
        documents=[LeaseDocument(**d) for d in await service.documents(lease)],
    )


@router.patch("/{lease_id}", response_model=LeaseResponse)
async def update_lease(
    lease_id: uuid.UUID,
    body: LeaseUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("leasing.update")),
) -> LeaseResponse:
    """Edit a lease; money and dates only while it is a draft."""
    service = LeasingService(session)
    lease = await service.get(lease_id)
    await verify_project_access(lease.project_id, user_id or "", session)
    return LeaseResponse.model_validate(await service.update(lease, body, _uid(user_id)))


@router.delete("/{lease_id}", status_code=204, response_model=None)
async def delete_lease(
    lease_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("leasing.delete")),
) -> Response:
    """Delete a draft lease."""
    service = LeasingService(session)
    lease = await service.get(lease_id)
    await verify_project_access(lease.project_id, user_id or "", session)
    await service.delete(lease)
    return Response(status_code=204)


@router.post("/{lease_id}/activate", response_model=LeaseResponse)
async def activate_lease(
    lease_id: uuid.UUID,
    session: SessionDep,
    body: ActivateRequest | None = None,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("leasing.manage")),
) -> LeaseResponse:
    """Activate a draft: the rules must pass, then the schedule is built."""
    service = LeasingService(session)
    lease = await service.get(lease_id)
    await verify_project_access(lease.project_id, user_id or "", session)
    on = body.on if body else None
    return LeaseResponse.model_validate(await service.activate(lease, on, _uid(user_id)))


@router.post("/{lease_id}/terminate", response_model=LeaseResponse)
async def terminate_lease(
    lease_id: uuid.UUID,
    body: TerminateRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("leasing.manage")),
) -> LeaseResponse:
    """Give notice to a future date or end the lease now; uninvoiced rent past it is dropped."""
    service = LeasingService(session)
    lease = await service.get(lease_id)
    await verify_project_access(lease.project_id, user_id or "", session)
    return LeaseResponse.model_validate(await service.terminate(lease, body, _uid(user_id)))


@router.post("/{lease_id}/renew", response_model=LeaseResponse, status_code=201)
async def renew_lease(
    lease_id: uuid.UUID,
    body: RenewRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("leasing.manage")),
) -> LeaseResponse:
    """Create the follow-on draft lease starting the day after this one ends."""
    service = LeasingService(session)
    lease = await service.get(lease_id)
    await verify_project_access(lease.project_id, user_id or "", session)
    return LeaseResponse.model_validate(await service.renew(lease, body, _uid(user_id)))


@router.post("/{lease_id}/review", response_model=LeaseResponse)
async def review_lease(
    lease_id: uuid.UUID,
    body: ReviewRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("leasing.manage")),
) -> LeaseResponse:
    """Record the rate of an index review; the schedule follows."""
    service = LeasingService(session)
    lease = await service.get(lease_id)
    await verify_project_access(lease.project_id, user_id or "", session)
    return LeaseResponse.model_validate(await service.review(lease, body, _uid(user_id)))


@router.get("/{lease_id}/schedule", response_model=ScheduleResponse)
async def get_schedule(
    lease_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("leasing.read")),
) -> ScheduleResponse:
    """The stored rent schedule."""
    service = LeasingService(session)
    lease = await service.get(lease_id)
    await verify_project_access(lease.project_id, user_id or "", session)
    return _schedule(lease, await service.repo.lines(lease.id))


@router.post("/{lease_id}/schedule", response_model=ScheduleResponse)
async def regenerate_schedule(
    lease_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("leasing.update")),
) -> ScheduleResponse:
    """Rebuild the schedule from the lease; invoiced lines stay as they are."""
    service = LeasingService(session)
    lease = await service.get(lease_id)
    await verify_project_access(lease.project_id, user_id or "", session)
    return _schedule(lease, await service.generate_schedule(lease))


@router.get("/{lease_id}/validate", response_model=ValidationResponse)
async def validate_lease(
    lease_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("leasing.read")),
) -> ValidationResponse:
    """Run the leasing rule set over one lease."""
    service = LeasingService(session)
    lease = await service.get(lease_id)
    await verify_project_access(lease.project_id, user_id or "", session)
    return ValidationResponse(**await service.validate(lease))


@router.post("/{lease_id}/documents", response_model=LeaseResponse)
async def link_document(
    lease_id: uuid.UUID,
    body: DocumentLinkRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("leasing.update")),
) -> LeaseResponse:
    """Attach a document of the same project."""
    service = LeasingService(session)
    lease = await service.get(lease_id)
    await verify_project_access(lease.project_id, user_id or "", session)
    return LeaseResponse.model_validate(await service.link_document(lease, body.document_id, _uid(user_id)))


@router.delete("/{lease_id}/documents/{document_id}", response_model=LeaseResponse)
async def unlink_document(
    lease_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("leasing.update")),
) -> LeaseResponse:
    """Detach a document."""
    service = LeasingService(session)
    lease = await service.get(lease_id)
    await verify_project_access(lease.project_id, user_id or "", session)
    return LeaseResponse.model_validate(await service.unlink_document(lease, document_id, _uid(user_id)))
