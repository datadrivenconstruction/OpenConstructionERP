# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid outcome ledger API, mounted at /api/v1/win-loss."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.win_loss.schemas import (
    BidOutcomeCreate,
    BidOutcomeResponse,
    BidOutcomeUpdate,
    LedgerSummary,
)
from app.modules.win_loss.service import WinLossService

router = APIRouter(tags=["win_loss"])


def _service(session: SessionDep) -> WinLossService:
    return WinLossService(session)


@router.get("/summary", response_model=LedgerSummary)
async def summary(
    currency: str | None = Query(default=None, max_length=10),
    _perm: None = Depends(RequirePermission("win_loss.read")),
    svc: WinLossService = Depends(_service),
) -> LedgerSummary:
    return await svc.summary(currency)


@router.get("/", response_model=list[BidOutcomeResponse])
async def list_entries(
    outcome: str | None = Query(default=None, max_length=20),
    client: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=500, ge=1, le=5000),
    _perm: None = Depends(RequirePermission("win_loss.read")),
    svc: WinLossService = Depends(_service),
) -> list[BidOutcomeResponse]:
    rows = await svc.repo.list_all(outcome=outcome, client=client, limit=limit)
    return [await svc.to_response(r) for r in rows]


@router.post("/", response_model=BidOutcomeResponse, status_code=201)
async def create_entry(
    data: BidOutcomeCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("win_loss.create")),
    svc: WinLossService = Depends(_service),
) -> BidOutcomeResponse:
    if data.project_id is not None:
        await verify_project_access(data.project_id, user_id, session)
    entry = await svc.create(data, user_id)
    return await svc.to_response(entry, with_warnings=True)


@router.get("/{entry_id}", response_model=BidOutcomeResponse)
async def get_entry(
    entry_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("win_loss.read")),
    svc: WinLossService = Depends(_service),
) -> BidOutcomeResponse:
    return await svc.to_response(await svc.get(entry_id), with_warnings=True)


@router.patch("/{entry_id}", response_model=BidOutcomeResponse)
async def update_entry(
    entry_id: uuid.UUID,
    data: BidOutcomeUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("win_loss.update")),
    svc: WinLossService = Depends(_service),
) -> BidOutcomeResponse:
    if data.project_id is not None:
        await verify_project_access(data.project_id, user_id, session)
    entry = await svc.update(entry_id, data)
    return await svc.to_response(entry, with_warnings=True)


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(
    entry_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("win_loss.delete")),
    svc: WinLossService = Depends(_service),
) -> None:
    await svc.delete(entry_id)
