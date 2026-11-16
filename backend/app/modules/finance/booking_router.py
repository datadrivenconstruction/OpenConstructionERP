# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Booking export routes (mounted under /api/v1/finance/booking-exports/).

POST /preview/       - Rows, counts and findings for a period; writes nothing
POST /               - Create an immutable batch file and stamp its invoices
GET  /               - Recent batches, newest first
GET  /{id}/file      - The file of a batch, exactly as created
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.active_markets import ActiveMarkets
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, accessible_project_ids
from app.modules.finance.booking_service import BookingService

booking_router = APIRouter(prefix="/booking-exports", tags=["finance-booking-exports"])


class BatchRequest(BaseModel):
    connector_config_id: uuid.UUID
    period_from: date
    period_to: date
    reexport: bool = False


class FindingOut(BaseModel):
    rule_id: str
    severity: str
    invoice: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class RowOut(BaseModel):
    invoice_number: str
    date: date | None
    amount: Decimal
    side: str
    account: str
    counter_account: str
    tax_key: str
    cost1: str
    cost2: str


class PreviewOut(BaseModel):
    invoices: int
    rows: int
    total: Decimal
    findings: list[FindingOut]
    blocked: bool
    sample: list[RowOut]


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: int
    connector_type: str
    period_from: date
    period_to: date
    reexport: bool
    invoice_count: int
    row_count: int
    total_amount: Decimal
    filename: str
    sha256: str
    created_at: datetime


def _service(session: SessionDep) -> BookingService:
    return BookingService(session)


Service = Annotated[BookingService, Depends(_service)]
Read = Depends(RequirePermission("finance.connector.read"))
Run = Depends(RequirePermission("finance.connector.sync"))


@booking_router.post("/preview/", response_model=PreviewOut, dependencies=[Run])
async def preview(
    data: BatchRequest, service: Service, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> PreviewOut:
    scope = await accessible_project_ids(session, user_id, live_only=True)
    _c, _s, plan = await service.plan(
        data.connector_config_id,
        data.period_from,
        data.period_to,
        reexport=data.reexport,
        project_ids=scope,
        markets=markets,
    )
    return PreviewOut(
        invoices=len(plan.included),
        rows=len(plan.rows),
        total=sum((r.amount for r in plan.rows), Decimal("0")),
        findings=[FindingOut(**f) for f in plan.findings],
        blocked=plan.blocked,
        sample=[RowOut(**{k: getattr(r, k) for k in RowOut.model_fields}) for r in plan.rows[:20]],
    )


@booking_router.post("/", response_model=BatchOut, status_code=201, dependencies=[Run])
async def create_batch(
    data: BatchRequest, service: Service, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> BatchOut:
    scope = await accessible_project_ids(session, user_id, live_only=True)
    batch = await service.create(
        data.connector_config_id,
        data.period_from,
        data.period_to,
        reexport=data.reexport,
        project_ids=scope,
        markets=markets,
        user_id=uuid.UUID(user_id),
    )
    return BatchOut.model_validate(batch)


@booking_router.get("/", response_model=list[BatchOut], dependencies=[Read])
async def list_batches(service: Service) -> list[BatchOut]:
    return [BatchOut.model_validate(b) for b in await service.list()]


@booking_router.get("/{batch_id}/file", dependencies=[Read])
async def batch_file(batch_id: uuid.UUID, service: Service) -> Response:
    batch, content = await service.file(batch_id)
    return Response(
        content=content,
        media_type=f"text/csv; charset={batch.encoding}",
        headers={"Content-Disposition": f'attachment; filename="{batch.filename}"'},
    )
