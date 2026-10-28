# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Allowances & contingency register API routes (auto-mounted at /api/v1/allowances).

A register of the money an estimate carries but has not yet measured - provisional
sums, prime-cost sums and design / construction contingencies - each with a held
amount and a running drawdown as scope firms up. The endpoints cover allowance and
drawdown CRUD plus a per-currency, per-type summary whose ``remaining`` figure the
estimate carries forward.

Endpoints:
    GET    /projects/{project_id}                     - list a project's allowances
    POST   /projects/{project_id}                     - create an allowance
    GET    /projects/{project_id}/summary             - the register roll-up
    GET    /items/{allowance_id}                       - get one allowance
    PATCH  /items/{allowance_id}                       - update an allowance
    DELETE /items/{allowance_id}                       - delete an allowance
    GET    /items/{allowance_id}/drawdowns             - list an allowance's drawdowns
    POST   /items/{allowance_id}/drawdowns             - record a drawdown
    DELETE /drawdowns/{drawdown_id}                    - delete a drawdown

Reads need ``allowances.read``; writes need ``allowances.write``. Every route is
project-scoped and IDOR-guarded via :func:`verify_project_access` (404 on both
missing and denied, so project existence never leaks). Mutating handlers commit
explicitly. Fixed prefixes (/projects, /items, /drawdowns) never collide, so no
path segment is ever mis-parsed as a UUID.
"""

import uuid

from fastapi import APIRouter, Depends, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.allowances.allowance_math import (
    RegisterSummary,
    is_overdrawn,
    remaining,
    total_drawn,
)
from app.modules.allowances.models import Allowance
from app.modules.allowances.schemas import (
    AllowanceCreate,
    AllowanceRegisterSummary,
    AllowanceResponse,
    AllowanceUpdate,
    CurrencyRollupOut,
    DrawdownCreate,
    DrawdownResponse,
    TypeRollupOut,
)
from app.modules.allowances.service import AllowanceService

router = APIRouter(tags=["Allowances"])


def _get_service(session: SessionDep) -> AllowanceService:
    return AllowanceService(session)


def _allowance_out(allowance: Allowance) -> AllowanceResponse:
    """Build an allowance response, deriving drawn / remaining / overdrawn.

    Reads ``allowance.drawdowns`` (loaded via the ``selectin`` relationship) and
    runs the pure engine so the register's headline figures are computed one way,
    in one place. ``remaining`` may be negative on an over-draw.
    """
    amounts = [d.amount for d in allowance.drawdowns]
    drawn = total_drawn(amounts)
    return AllowanceResponse(
        id=allowance.id,
        project_id=allowance.project_id,
        label=allowance.label,
        allowance_type=allowance.allowance_type,
        held_amount=allowance.held_amount,
        currency=allowance.currency,
        notes=allowance.notes,
        drawn=drawn,
        remaining=remaining(allowance.held_amount, amounts),
        overdrawn=is_overdrawn(allowance.held_amount, drawn),
        drawdown_count=len(amounts),
        created_by=allowance.created_by,
        created_at=allowance.created_at,
        updated_at=allowance.updated_at,
    )


def _summary_out(project_id: uuid.UUID, summary: RegisterSummary) -> AllowanceRegisterSummary:
    """Map the pure register roll-up onto its wire model (money as strings)."""
    return AllowanceRegisterSummary(
        project_id=project_id,
        by_currency=[
            CurrencyRollupOut(
                currency=row.currency,
                held=row.held,
                drawn=row.drawn,
                remaining=row.remaining,
                count=row.count,
                overdrawn=row.overdrawn,
                by_type=[
                    TypeRollupOut(
                        allowance_type=t.allowance_type,
                        held=t.held,
                        drawn=t.drawn,
                        remaining=t.remaining,
                        count=t.count,
                        overdrawn=t.overdrawn,
                    )
                    for t in row.by_type
                ],
            )
            for row in summary.by_currency
        ],
        primary_currency=summary.primary_currency,
        allowance_count=summary.allowance_count,
    )


# ── Allowances (project-scoped) ────────────────────────────────────────────


@router.get(
    "/projects/{project_id}",
    response_model=list[AllowanceResponse],
    dependencies=[Depends(RequirePermission("allowances.read"))],
)
async def list_allowances(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: AllowanceService = Depends(_get_service),
) -> list[AllowanceResponse]:
    """List a project's allowances, each with its derived drawn / remaining."""
    await verify_project_access(project_id, user_id, session)
    allowances = await service.list_allowances(project_id)
    return [_allowance_out(a) for a in allowances]


@router.post(
    "/projects/{project_id}",
    response_model=AllowanceResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("allowances.write"))],
)
async def create_allowance(
    project_id: uuid.UUID,
    data: AllowanceCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: AllowanceService = Depends(_get_service),
) -> AllowanceResponse:
    """Create an allowance in a project's register."""
    await verify_project_access(project_id, user_id, session)
    allowance = await service.create_allowance(project_id, data, user_id=user_id)
    resp = _allowance_out(allowance)
    await session.commit()
    return resp


@router.get(
    "/projects/{project_id}/summary",
    response_model=AllowanceRegisterSummary,
    dependencies=[Depends(RequirePermission("allowances.read"))],
)
async def get_register_summary(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: AllowanceService = Depends(_get_service),
) -> AllowanceRegisterSummary:
    """The project's allowances roll-up: held, drawn and remaining by currency and type."""
    await verify_project_access(project_id, user_id, session)
    summary = await service.build_register_summary(project_id)
    return _summary_out(project_id, summary)


# ── Allowance (by id) ──────────────────────────────────────────────────────


@router.get(
    "/items/{allowance_id}",
    response_model=AllowanceResponse,
    dependencies=[Depends(RequirePermission("allowances.read"))],
)
async def get_allowance(
    allowance_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: AllowanceService = Depends(_get_service),
) -> AllowanceResponse:
    """Get a single allowance with its derived figures."""
    allowance = await service.get_allowance(allowance_id)
    await verify_project_access(allowance.project_id, user_id, session)
    return _allowance_out(allowance)


@router.patch(
    "/items/{allowance_id}",
    response_model=AllowanceResponse,
    dependencies=[Depends(RequirePermission("allowances.write"))],
)
async def update_allowance(
    allowance_id: uuid.UUID,
    data: AllowanceUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: AllowanceService = Depends(_get_service),
) -> AllowanceResponse:
    """Update an allowance's label, type, held amount, currency or notes."""
    existing = await service.get_allowance(allowance_id)
    await verify_project_access(existing.project_id, user_id, session)
    allowance = await service.update_allowance(allowance_id, data)
    resp = _allowance_out(allowance)
    await session.commit()
    return resp


@router.delete(
    "/items/{allowance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("allowances.write"))],
)
async def delete_allowance(
    allowance_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: AllowanceService = Depends(_get_service),
) -> None:
    """Delete an allowance and its drawdowns."""
    existing = await service.get_allowance(allowance_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_allowance(allowance_id)
    await session.commit()


# ── Drawdowns ──────────────────────────────────────────────────────────────


@router.get(
    "/items/{allowance_id}/drawdowns",
    response_model=list[DrawdownResponse],
    dependencies=[Depends(RequirePermission("allowances.read"))],
)
async def list_drawdowns(
    allowance_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: AllowanceService = Depends(_get_service),
) -> list[DrawdownResponse]:
    """List the drawdowns recorded against an allowance, oldest first."""
    allowance = await service.get_allowance(allowance_id)
    await verify_project_access(allowance.project_id, user_id, session)
    drawdowns = await service.list_drawdowns(allowance_id)
    return [DrawdownResponse.model_validate(d) for d in drawdowns]


@router.post(
    "/items/{allowance_id}/drawdowns",
    response_model=DrawdownResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("allowances.write"))],
)
async def create_drawdown(
    allowance_id: uuid.UUID,
    data: DrawdownCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: AllowanceService = Depends(_get_service),
) -> DrawdownResponse:
    """Record an amount drawn against an allowance as scope firms up."""
    allowance = await service.get_allowance(allowance_id)
    await verify_project_access(allowance.project_id, user_id, session)
    drawdown = await service.add_drawdown(allowance_id, data, user_id=user_id)
    resp = DrawdownResponse.model_validate(drawdown)
    await session.commit()
    return resp


@router.delete(
    "/drawdowns/{drawdown_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("allowances.write"))],
)
async def delete_drawdown(
    drawdown_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: AllowanceService = Depends(_get_service),
) -> None:
    """Delete a single drawdown (the allowance's remaining rises back up)."""
    drawdown = await service.get_drawdown(drawdown_id)
    allowance = await service.get_allowance(drawdown.allowance_id)
    await verify_project_access(allowance.project_id, user_id, session)
    await service.delete_drawdown(drawdown_id)
    await session.commit()
