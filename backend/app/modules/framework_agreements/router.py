# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Framework agreements API, mounted at /api/v1/framework-agreements."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field

from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    accessible_project_ids,
    verify_project_access,
)
from app.modules.contracts.models import Contract
from app.modules.framework_agreements.packs import pack_profile
from app.modules.framework_agreements.schemas import (
    AdjustmentIn,
    AdjustmentOut,
    AgreementCreate,
    AgreementDetail,
    AgreementListResponse,
    AgreementUpdate,
    BreakdownResponse,
    ImportItemsRequest,
    MeasurementIn,
    OrderCreate,
    OrderDetail,
    OrderIssueRequest,
    OrderListResponse,
    OrderQuote,
    OrderQuoteRequest,
    OrderStatusRequest,
    Page,
    RateItemOut,
    RateItemUpdate,
    RatePeriodIn,
    RatePeriodOut,
)
from app.modules.framework_agreements.service import FrameworkService

router = APIRouter(tags=["framework_agreements"])


def _service(session: SessionDep) -> FrameworkService:
    return FrameworkService(session)


async def _agreement(svc: FrameworkService, agreement_id: uuid.UUID, user_id: str) -> Contract:
    """The agreement, once the caller is proven to reach the project it lives in."""
    row = await svc.agreement(agreement_id)
    await verify_project_access(row.project_id, user_id, svc.session)
    return row


async def _order(svc: FrameworkService, order_id: uuid.UUID, user_id: str) -> tuple[Contract, Contract]:
    """A call-off order and its agreement; access follows the agreement's project, as for every order."""
    order, row = await svc.order(order_id)
    await verify_project_access(row.project_id, user_id, svc.session)
    return order, row


def _page[T](rows: list[T]) -> Page[T]:
    return Page(items=rows, total=len(rows), offset=0, limit=len(rows))


def _can_override(payload: dict[str, Any]) -> bool:
    """Whether the caller holds ``framework.override_cap`` (admin, token or live registry)."""
    role = str(payload.get("role") or "")
    if role == "admin" or "framework.override_cap" in (payload.get("permissions") or []):
        return True
    from app.core.permissions import permission_registry

    return bool(permission_registry.role_has_permission(role, "framework.override_cap"))


class StatusIn(BaseModel):
    status: str = Field(..., pattern="^(active|closed)$")


class ExtraIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str = Field(default="", max_length=5000)
    amount: Decimal = Field(default=Decimal("0"), ge=0)


# ── Agreements ──────────────────────────────────────────────────────────────


@router.get("/", response_model=AgreementListResponse)
async def list_agreements(
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("framework.read")),
    svc: FrameworkService = Depends(_service),
) -> AgreementListResponse:
    ids: set[uuid.UUID] | None = None
    if project_id is not None:
        await verify_project_access(project_id, user_id, svc.session)
    else:
        ids = await accessible_project_ids(svc.session, user_id, live_only=True)
    rows = await svc.list_agreements(ids, project_id)
    return AgreementListResponse(items=rows, total=len(rows))


@router.get("/pack-profile")
async def get_pack_profile(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    client_kind: str = Query(default="classic", pattern="^(classic|sector)$"),
    _perm: None = Depends(RequirePermission("framework.read")),
) -> dict[str, Any]:
    """The pack fields, term hint and templates a new agreement in this project gets."""
    await verify_project_access(project_id, user_id, session)
    from app.modules.projects.models import Project

    project = await session.get(Project, project_id)
    return {
        **pack_profile(getattr(project, "country_code", None), client_kind),
        "currency": getattr(project, "currency", "") or "",
    }


@router.post("/", response_model=AgreementDetail, status_code=201)
async def create_agreement(
    data: AgreementCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.create")),
    svc: FrameworkService = Depends(_service),
) -> AgreementDetail:
    row = await svc.create_agreement(data, user_id)
    return AgreementDetail(**await svc.detail(row))


@router.get("/orders/{order_id}", response_model=OrderDetail)
async def get_order(
    order_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.read")),
    svc: FrameworkService = Depends(_service),
) -> OrderDetail:
    order, row = await _order(svc, order_id, user_id)
    return OrderDetail(**await svc.order_detail(order, row))


@router.post("/orders/{order_id}/issue", response_model=OrderDetail)
async def issue_order(
    order_id: uuid.UUID,
    data: OrderIssueRequest,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("framework.issue_order")),
    svc: FrameworkService = Depends(_service),
) -> OrderDetail:
    order, row = await _order(svc, order_id, user_id)
    await svc.issue_order(order, row, data.override_reason, user_id, _can_override(payload))
    return OrderDetail(**await svc.order_detail(order, row))


@router.post("/orders/{order_id}/status", response_model=OrderDetail)
async def set_order_status(
    order_id: uuid.UUID,
    data: OrderStatusRequest,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.issue_order")),
    svc: FrameworkService = Depends(_service),
) -> OrderDetail:
    order, row = await _order(svc, order_id, user_id)
    await svc.set_order_status(order, data.status)
    return OrderDetail(**await svc.order_detail(order, row))


@router.post("/orders/{order_id}/measurements", response_model=OrderDetail)
async def record_measurements(
    order_id: uuid.UUID,
    data: MeasurementIn,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.issue_order")),
    svc: FrameworkService = Depends(_service),
) -> OrderDetail:
    order, row = await _order(svc, order_id, user_id)
    await svc.record_measurements(order, data.measurements)
    return OrderDetail(**await svc.order_detail(order, row))


@router.get("/orders/{order_id}/extras", response_model=Page[dict[str, Any]])
async def list_extras(
    order_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.read")),
    svc: FrameworkService = Depends(_service),
) -> Page[dict[str, Any]]:
    order, _row = await _order(svc, order_id, user_id)
    return _page([{**e, "amount": format(Decimal(e["amount"] or 0), "f")} for e in await svc.list_extras(order)])


@router.post("/orders/{order_id}/extras", status_code=201)
async def raise_extra(
    order_id: uuid.UUID,
    data: ExtraIn,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.issue_order")),
    svc: FrameworkService = Depends(_service),
) -> dict[str, Any]:
    order, _row = await _order(svc, order_id, user_id)
    vr = await svc.raise_extra(order, data.title, data.description, data.amount, user_id)
    return {"id": str(vr.id), "code": vr.code, "status": vr.status}


@router.get("/{agreement_id}", response_model=AgreementDetail)
async def get_agreement(
    agreement_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.read")),
    svc: FrameworkService = Depends(_service),
) -> AgreementDetail:
    return AgreementDetail(**await svc.detail(await _agreement(svc, agreement_id, user_id)))


@router.patch("/{agreement_id}", response_model=AgreementDetail)
async def update_agreement(
    agreement_id: uuid.UUID,
    data: AgreementUpdate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.edit_rates")),
    svc: FrameworkService = Depends(_service),
) -> AgreementDetail:
    row = await svc.update_agreement(await _agreement(svc, agreement_id, user_id), data)
    return AgreementDetail(**await svc.detail(row))


@router.post("/{agreement_id}/status", response_model=AgreementDetail)
async def set_agreement_status(
    agreement_id: uuid.UUID,
    data: StatusIn,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.accept_order")),
    svc: FrameworkService = Depends(_service),
) -> AgreementDetail:
    row = await svc.set_agreement_status(await _agreement(svc, agreement_id, user_id), data.status)
    return AgreementDetail(**await svc.detail(row))


@router.get("/{agreement_id}/items", response_model=Page[RateItemOut])
async def list_items(
    agreement_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.read")),
    svc: FrameworkService = Depends(_service),
) -> Page[RateItemOut]:
    return _page([RateItemOut(**i) for i in await svc.list_items(await _agreement(svc, agreement_id, user_id))])


@router.post("/{agreement_id}/items/import")
async def import_items(
    agreement_id: uuid.UUID,
    data: ImportItemsRequest,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.edit_rates")),
    svc: FrameworkService = Depends(_service),
) -> dict[str, int]:
    row = await _agreement(svc, agreement_id, user_id)
    return {"imported": await svc.import_items(row, data.items, data.replace)}


@router.patch("/{agreement_id}/items/{item_id}")
async def update_item(
    agreement_id: uuid.UUID,
    item_id: uuid.UUID,
    data: RateItemUpdate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.edit_rates")),
    svc: FrameworkService = Depends(_service),
) -> dict[str, Any]:
    out = await svc.update_item(await _agreement(svc, agreement_id, user_id), item_id, data)
    return {k: (str(v) if v is not None else None) for k, v in out.items()}


@router.get("/{agreement_id}/periods", response_model=Page[RatePeriodOut])
async def list_periods(
    agreement_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.read")),
    svc: FrameworkService = Depends(_service),
) -> Page[RatePeriodOut]:
    return _page([RatePeriodOut(**p) for p in await svc.list_periods(await _agreement(svc, agreement_id, user_id))])


@router.post("/{agreement_id}/periods", response_model=RatePeriodOut, status_code=201)
async def add_period(
    agreement_id: uuid.UUID,
    data: RatePeriodIn,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.edit_rates")),
    svc: FrameworkService = Depends(_service),
) -> RatePeriodOut:
    period = await svc.add_period(await _agreement(svc, agreement_id, user_id), data)
    return RatePeriodOut.model_validate(period)


@router.put("/{agreement_id}/periods/{period_id}", response_model=RatePeriodOut)
async def update_period(
    agreement_id: uuid.UUID,
    period_id: uuid.UUID,
    data: RatePeriodIn,
    user_id: CurrentUserId,
    activate: bool = Query(default=False),
    _perm: None = Depends(RequirePermission("framework.edit_rates")),
    svc: FrameworkService = Depends(_service),
) -> RatePeriodOut:
    period = await svc.update_period(await _agreement(svc, agreement_id, user_id), period_id, data, activate)
    return RatePeriodOut.model_validate(period)


@router.get("/{agreement_id}/adjustments", response_model=Page[AdjustmentOut])
async def list_adjustments(
    agreement_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.read")),
    svc: FrameworkService = Depends(_service),
) -> Page[AdjustmentOut]:
    rows = await svc.list_adjustments(await _agreement(svc, agreement_id, user_id))
    return _page([AdjustmentOut.model_validate(r) for r in rows])


@router.post("/{agreement_id}/adjustments", response_model=AdjustmentOut, status_code=201)
async def add_adjustment(
    agreement_id: uuid.UUID,
    data: AdjustmentIn,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.edit_rates")),
    svc: FrameworkService = Depends(_service),
) -> AdjustmentOut:
    adj = await svc.add_adjustment(await _agreement(svc, agreement_id, user_id), data)
    return AdjustmentOut.model_validate(adj)


@router.delete("/{agreement_id}/adjustments/{adjustment_id}", status_code=204)
async def delete_adjustment(
    agreement_id: uuid.UUID,
    adjustment_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.edit_rates")),
    svc: FrameworkService = Depends(_service),
) -> None:
    await svc.delete_adjustment(await _agreement(svc, agreement_id, user_id), adjustment_id)


@router.post("/{agreement_id}/quote", response_model=OrderQuote)
async def quote_order(
    agreement_id: uuid.UUID,
    data: OrderQuoteRequest,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.read")),
    svc: FrameworkService = Depends(_service),
) -> OrderQuote:
    return OrderQuote(**await svc.quote(await _agreement(svc, agreement_id, user_id), data))


@router.get("/{agreement_id}/orders", response_model=OrderListResponse)
async def list_orders(
    agreement_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("framework.read")),
    svc: FrameworkService = Depends(_service),
) -> OrderListResponse:
    rows = await svc.list_orders(await _agreement(svc, agreement_id, user_id))
    return OrderListResponse(items=rows, total=len(rows))


@router.post("/{agreement_id}/orders", response_model=OrderDetail, status_code=201)
async def create_order(
    agreement_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    data: OrderCreate = Body(...),
    _perm: None = Depends(RequirePermission("framework.issue_order")),
    svc: FrameworkService = Depends(_service),
) -> OrderDetail:
    row = await _agreement(svc, agreement_id, user_id)
    order = await svc.create_order(row, data, user_id, _can_override(payload))
    return OrderDetail(**await svc.order_detail(order, row))


@router.get("/{agreement_id}/breakdown", response_model=BreakdownResponse)
async def breakdown(
    agreement_id: uuid.UUID,
    user_id: CurrentUserId,
    by: str = Query(default="site", pattern="^(site|item|month)$"),
    _perm: None = Depends(RequirePermission("framework.read")),
    svc: FrameworkService = Depends(_service),
) -> BreakdownResponse:
    rows = await svc.breakdown(await _agreement(svc, agreement_id, user_id), by)
    return BreakdownResponse(by=by, rows=rows)
