# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Budget ledger endpoints, mounted on the cost model router.

GET    /projects/{project_id}/budget-ledger/                        transfers, modifications, effect per line, audit
POST   /projects/{project_id}/budget-ledger/transfers/              new draft transfer        (costmodel.write)
PUT    /projects/{project_id}/budget-ledger/transfers/{id}/         change a draft            (costmodel.write)
DELETE /projects/{project_id}/budget-ledger/transfers/{id}/         remove a draft            (costmodel.write)
POST   /projects/{project_id}/budget-ledger/transfers/{id}/submit/  submit                    (costmodel.write)
POST   /projects/{project_id}/budget-ledger/transfers/{id}/approve|reject/    decide          (costmodel.manage)
The same set exists under .../modifications/.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Response, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.costmodel.budget_ledger_schemas import (
    BudgetLedger,
    DecisionIn,
    ModificationIn,
    ModificationOut,
    TransferIn,
    TransferOut,
)
from app.modules.costmodel.budget_ledger_service import BudgetLedgerService

router = APIRouter(tags=["costmodel"])
_BASE = "/projects/{project_id}/budget-ledger"
_READ = [Depends(RequirePermission("costmodel.read"))]
_WRITE = [Depends(RequirePermission("costmodel.write"))]
_MANAGE = [Depends(RequirePermission("costmodel.manage"))]


def _locale() -> str:
    from app.core.i18n import get_locale

    return get_locale()


async def _svc(project_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> BudgetLedgerService:
    await verify_project_access(project_id, user_id, session)
    return BudgetLedgerService(session)


@router.get(f"{_BASE}/", response_model=BudgetLedger, dependencies=_READ)
async def get_budget_ledger(project_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> BudgetLedger:
    """Every transfer and modification with its status, what approved ones did to each line, and the audit trail."""
    return await (await _svc(project_id, user_id, session)).ledger(project_id)


@router.post(f"{_BASE}/transfers/", response_model=TransferOut, status_code=201, dependencies=_WRITE)
async def create_transfer(
    project_id: uuid.UUID, body: TransferIn, user_id: CurrentUserId, session: SessionDep
) -> TransferOut:
    """Draft a transfer: signed legs on two or more cost lines that add up to zero."""
    svc = await _svc(project_id, user_id, session)
    return await svc.create_transfer(project_id, body, str(user_id), _locale())


@router.put(f"{_BASE}/transfers/{{entry_id}}/", response_model=TransferOut, dependencies=_WRITE)
async def update_transfer(
    project_id: uuid.UUID, entry_id: uuid.UUID, body: TransferIn, user_id: CurrentUserId, session: SessionDep
) -> TransferOut:
    svc = await _svc(project_id, user_id, session)
    return await svc.update_transfer(project_id, entry_id, body, str(user_id), _locale())


@router.delete(f"{_BASE}/transfers/{{entry_id}}/", status_code=204, dependencies=_WRITE)
async def delete_transfer(
    project_id: uuid.UUID, entry_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep
) -> Response:
    svc = await _svc(project_id, user_id, session)
    await svc.delete_transfer(project_id, entry_id, str(user_id), _locale())
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(f"{_BASE}/transfers/{{entry_id}}/submit/", response_model=TransferOut, dependencies=_WRITE)
async def submit_transfer(
    project_id: uuid.UUID, entry_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep
) -> TransferOut:
    svc = await _svc(project_id, user_id, session)
    return await svc.transfer_step(project_id, entry_id, "submit", str(user_id), "", _locale())


@router.post(f"{_BASE}/transfers/{{entry_id}}/{{decision}}/", response_model=TransferOut, dependencies=_MANAGE)
async def decide_transfer(
    project_id: uuid.UUID,
    entry_id: uuid.UUID,
    decision: Literal["approve", "reject"],
    body: DecisionIn,
    user_id: CurrentUserId,
    session: SessionDep,
) -> TransferOut:
    """Approving moves the budget between the lines; rejecting needs a reason."""
    svc = await _svc(project_id, user_id, session)
    return await svc.transfer_step(project_id, entry_id, decision, str(user_id), body.note, _locale())


@router.post(f"{_BASE}/modifications/", response_model=ModificationOut, status_code=201, dependencies=_WRITE)
async def create_modification(
    project_id: uuid.UUID, body: ModificationIn, user_id: CurrentUserId, session: SessionDep
) -> ModificationOut:
    """Draft an owner-approved budget change on one cost line (positive adds budget, negative takes it off)."""
    svc = await _svc(project_id, user_id, session)
    return await svc.create_modification(project_id, body, str(user_id), _locale())


@router.put(f"{_BASE}/modifications/{{entry_id}}/", response_model=ModificationOut, dependencies=_WRITE)
async def update_modification(
    project_id: uuid.UUID, entry_id: uuid.UUID, body: ModificationIn, user_id: CurrentUserId, session: SessionDep
) -> ModificationOut:
    svc = await _svc(project_id, user_id, session)
    return await svc.update_modification(project_id, entry_id, body, str(user_id), _locale())


@router.delete(f"{_BASE}/modifications/{{entry_id}}/", status_code=204, dependencies=_WRITE)
async def delete_modification(
    project_id: uuid.UUID, entry_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep
) -> Response:
    svc = await _svc(project_id, user_id, session)
    await svc.delete_modification(project_id, entry_id, str(user_id), _locale())
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(f"{_BASE}/modifications/{{entry_id}}/submit/", response_model=ModificationOut, dependencies=_WRITE)
async def submit_modification(
    project_id: uuid.UUID, entry_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep
) -> ModificationOut:
    svc = await _svc(project_id, user_id, session)
    return await svc.modification_step(project_id, entry_id, "submit", str(user_id), "", _locale())


@router.post(f"{_BASE}/modifications/{{entry_id}}/{{decision}}/", response_model=ModificationOut, dependencies=_MANAGE)
async def decide_modification(
    project_id: uuid.UUID,
    entry_id: uuid.UUID,
    decision: Literal["approve", "reject"],
    body: DecisionIn,
    user_id: CurrentUserId,
    session: SessionDep,
) -> ModificationOut:
    """Approving adds the amount to the line revised budget; rejecting needs a reason."""
    svc = await _svc(project_id, user_id, session)
    return await svc.modification_step(project_id, entry_id, decision, str(user_id), body.note, _locale())
