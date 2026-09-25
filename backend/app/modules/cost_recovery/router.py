# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost recovery API routes (auto-mounted at /api/v1/cost-recovery).

Records and rolls up back-charges for a project. Every route is project-scoped:
the caller must hold the module capability (read or write) and pass
:func:`verify_project_access` for the project, which 404s on both "missing" and
"denied" so it never leaks project existence.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    accessible_project_ids,
    verify_project_access,
)
from app.modules.cost_recovery.back_charge import quantize_money
from app.modules.cost_recovery.models import BackCharge, BackChargeApportionment
from app.modules.cost_recovery.recovery_analytics import CohortRecovery, RecoveryPerformance
from app.modules.cost_recovery.schemas import (
    ApportionedShareOut,
    ApportionmentRequest,
    BackChargeApportionmentOut,
    BackChargeCreate,
    BackChargeOut,
    BackChargeUpdate,
    CohortRecoveryOut,
    CurrencyRecoveryOut,
    CurrencyRecoveryPerfOut,
    PartyRecoveryOut,
    PendingBackChargeOut,
    PendingBackChargesOut,
    RecoveryLedgerOut,
    RecoveryPerformanceOut,
)
from app.modules.cost_recovery.service import (
    InvalidBackChargeLink,
    InvalidSubjectLink,
    apportion_back_charge,
    build_portfolio_recovery_performance,
    build_recovery_ledger,
    build_recovery_performance,
    create_back_charge,
    get_back_charge,
    list_apportionment,
    list_back_charges,
    pending_backcharges,
    to_back_charge_item,
    update_back_charge,
)

router = APIRouter(tags=["Cost Recovery"])


def _serialize(back_charge: BackCharge) -> BackChargeOut:
    """Render a stored back-charge with its derived amounts as money strings."""
    item = to_back_charge_item(back_charge)
    meta = back_charge.metadata_ if isinstance(back_charge.metadata_, dict) else {}
    return BackChargeOut(
        id=str(back_charge.id),
        project_id=str(back_charge.project_id),
        source_ref=back_charge.source_ref or "",
        responsible_party=back_charge.responsible_party or "",
        description=back_charge.description or "",
        basis=back_charge.basis or "",
        gross_amount=str(item.gross_amount),
        chargeable_pct=str(back_charge.chargeable_pct if back_charge.chargeable_pct is not None else "0"),
        chargeable_amount=str(item.chargeable_amount),
        currency=back_charge.currency or "",
        status=back_charge.status or "",
        recovered_amount=str(item.recovered_amount),
        outstanding=str(item.outstanding),
        is_open=item.is_open,
        agreed_at=back_charge.agreed_at,
        recovered_at=back_charge.recovered_at,
        traceability_band=str(meta.get("traceability_band", "") or ""),
        subcontractor_id=str(back_charge.subcontractor_id) if back_charge.subcontractor_id else None,
        contact_id=str(back_charge.contact_id) if back_charge.contact_id else None,
        ncr_id=str(back_charge.ncr_id) if back_charge.ncr_id else None,
        punch_item_id=str(back_charge.punch_item_id) if back_charge.punch_item_id else None,
    )


@router.get(
    "/projects/{project_id}/back-charges",
    response_model=list[BackChargeOut],
    dependencies=[Depends(RequirePermission("cost_recovery.read"))],
)
async def list_project_back_charges(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> list[BackChargeOut]:
    """List every back-charge recorded against a project."""
    await verify_project_access(project_id, user_id or "", session)
    rows = await list_back_charges(session, project_id)
    return [_serialize(row) for row in rows]


@router.post(
    "/projects/{project_id}/back-charges",
    response_model=BackChargeOut,
    dependencies=[Depends(RequirePermission("cost_recovery.write"))],
)
async def create_project_back_charge(
    project_id: uuid.UUID,
    payload: BackChargeCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> BackChargeOut:
    """Record a new back-charge for a project."""
    await verify_project_access(project_id, user_id or "", session)
    try:
        back_charge = await create_back_charge(session, project_id, payload, created_by=user_id)
    except InvalidSubjectLink as exc:
        raise HTTPException(status_code=404 if exc.not_found else 400, detail=exc.detail) from exc
    except InvalidBackChargeLink as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    return _serialize(back_charge)


@router.patch(
    "/projects/{project_id}/back-charges/{back_charge_id}",
    response_model=BackChargeOut,
    dependencies=[Depends(RequirePermission("cost_recovery.write"))],
)
async def update_project_back_charge(
    project_id: uuid.UUID,
    back_charge_id: uuid.UUID,
    payload: BackChargeUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> BackChargeOut:
    """Update a back-charge (amounts, responsible party, or commercial status)."""
    await verify_project_access(project_id, user_id or "", session)
    try:
        back_charge = await update_back_charge(session, project_id, back_charge_id, payload)
    except InvalidBackChargeLink as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    if back_charge is None:
        raise HTTPException(status_code=404, detail="Back-charge not found")
    return _serialize(back_charge)


@router.get(
    "/projects/{project_id}/pending-backcharges",
    response_model=PendingBackChargesOut,
    dependencies=[Depends(RequirePermission("cost_recovery.read"))],
)
async def get_pending_backcharges(
    project_id: uuid.UUID,
    subcontractor_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> PendingBackChargesOut:
    """Agreed back-charges this subcontractor still owes on the project."""
    await verify_project_access(project_id, user_id or "", session)
    pending = await pending_backcharges(session, subcontractor_id, project_id=project_id)
    return PendingBackChargesOut(
        subcontractor_id=str(pending.subcontractor_id),
        items=[
            PendingBackChargeOut(
                back_charge_id=str(p.back_charge_id),
                project_id=str(p.project_id),
                source_ref=p.source_ref,
                description=p.description,
                currency=p.currency,
                amount=str(p.amount),
                apportioned=p.apportioned,
            )
            for p in pending.items
        ],
        totals={cur: str(total) for cur, total in pending.totals.items()},
    )


@router.get(
    "/projects/{project_id}/recovery-ledger",
    response_model=RecoveryLedgerOut,
    dependencies=[Depends(RequirePermission("cost_recovery.read"))],
)
async def get_recovery_ledger(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> RecoveryLedgerOut:
    """Roll the project's back-charges into a per-party / per-currency ledger."""
    await verify_project_access(project_id, user_id or "", session)
    ledger = await build_recovery_ledger(session, project_id)
    return RecoveryLedgerOut(
        project_id=str(project_id),
        item_count=ledger.item_count,
        open_count=ledger.open_count,
        primary_currency=ledger.primary_currency,
        primary_outstanding=str(ledger.primary_outstanding),
        by_party=[
            PartyRecoveryOut(
                party=p.party,
                currency=p.currency,
                item_count=p.item_count,
                open_count=p.open_count,
                gross_total=str(p.gross_total),
                chargeable_total=str(p.chargeable_total),
                recovered_total=str(p.recovered_total),
                outstanding_total=str(p.outstanding_total),
            )
            for p in ledger.by_party
        ],
        by_currency=[
            CurrencyRecoveryOut(
                currency=c.currency,
                item_count=c.item_count,
                chargeable_total=str(c.chargeable_total),
                recovered_total=str(c.recovered_total),
                outstanding_total=str(c.outstanding_total),
            )
            for c in ledger.by_currency
        ],
    )


# --- Apportionment ----------------------------------------------------------


def _serialize_apportionment(
    back_charge: BackCharge,
    rows: list[BackChargeApportionment],
) -> BackChargeApportionmentOut:
    """Render a back-charge's apportionment with money / share as strings.

    ``share_total`` sums the persisted share amounts (one currency) and equals
    the back-charge's chargeable amount when an apportionment exists.
    """
    item = to_back_charge_item(back_charge)
    share_total = sum((r.share_amount for r in rows), start=Decimal("0"))
    return BackChargeApportionmentOut(
        back_charge_id=str(back_charge.id),
        project_id=str(back_charge.project_id),
        currency=back_charge.currency or "",
        chargeable_amount=str(item.chargeable_amount),
        share_total=str(quantize_money(share_total)),
        is_apportioned=bool(rows),
        shares=[
            ApportionedShareOut(
                id=str(r.id),
                back_charge_id=str(r.back_charge_id),
                project_id=str(r.project_id),
                party=r.party or "",
                basis=r.basis or "",
                share_pct=str(r.share_pct if r.share_pct is not None else "0"),
                share_amount=str(r.share_amount if r.share_amount is not None else "0"),
                currency=r.currency or "",
            )
            for r in rows
        ],
    )


@router.put(
    "/projects/{project_id}/back-charges/{back_charge_id}/apportionment",
    response_model=BackChargeApportionmentOut,
    dependencies=[Depends(RequirePermission("cost_recovery.write"))],
)
async def apportion_project_back_charge(
    project_id: uuid.UUID,
    back_charge_id: uuid.UUID,
    payload: ApportionmentRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> BackChargeApportionmentOut:
    """Split a back-charge's chargeable amount across parties and persist it.

    The shares must sum to 1.0 (a fraction each, 0.6 = 60%); an invalid set
    yields a 422. Re-running replaces any previous apportionment. The stored
    per-party amounts reconcile to the chargeable amount exactly.
    """
    await verify_project_access(project_id, user_id or "", session)
    try:
        rows = await apportion_back_charge(
            session,
            project_id,
            back_charge_id,
            payload.shares,
            created_by=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if rows is None:
        raise HTTPException(status_code=404, detail="Back-charge not found")
    back_charge = await get_back_charge(session, project_id, back_charge_id)
    if back_charge is None:  # pragma: no cover - apportion_back_charge already proved it exists
        raise HTTPException(status_code=404, detail="Back-charge not found")
    return _serialize_apportionment(back_charge, rows)


@router.get(
    "/projects/{project_id}/back-charges/{back_charge_id}/apportionment",
    response_model=BackChargeApportionmentOut,
    dependencies=[Depends(RequirePermission("cost_recovery.read"))],
)
async def get_project_back_charge_apportionment(
    project_id: uuid.UUID,
    back_charge_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> BackChargeApportionmentOut:
    """Read a back-charge's persisted apportionment (empty if none recorded)."""
    await verify_project_access(project_id, user_id or "", session)
    back_charge = await get_back_charge(session, project_id, back_charge_id)
    if back_charge is None:
        raise HTTPException(status_code=404, detail="Back-charge not found")
    rows = await list_apportionment(session, project_id, back_charge_id)
    return _serialize_apportionment(back_charge, rows)


# --- Recovery performance (recovered vs entitled, by traceability) -----------


def _rate_str(rate: Decimal | None) -> str | None:
    """Render a recovery rate (a fraction) as a string, preserving null."""
    return None if rate is None else str(rate)


def _performance_out(
    performance: RecoveryPerformance,
    *,
    project_id: str | None,
) -> RecoveryPerformanceOut:
    """Render a RecoveryPerformance with money as strings and rate nullable."""

    def cohort_out(c: CohortRecovery) -> CohortRecoveryOut:
        return CohortRecoveryOut(
            cohort=c.cohort,
            currency=c.currency,
            item_count=c.item_count,
            chargeable_total=str(c.chargeable_total),
            recovered_total=str(c.recovered_total),
            outstanding_total=str(c.outstanding_total),
            absorbed_total=str(c.absorbed_total),
            rate=_rate_str(c.rate),
        )

    return RecoveryPerformanceOut(
        project_id=project_id,
        item_count=performance.item_count,
        primary_currency=performance.primary_currency,
        primary_rate=_rate_str(performance.primary_rate),
        by_currency=[
            CurrencyRecoveryPerfOut(
                currency=c.currency,
                item_count=c.item_count,
                chargeable_total=str(c.chargeable_total),
                recovered_total=str(c.recovered_total),
                outstanding_total=str(c.outstanding_total),
                absorbed_total=str(c.absorbed_total),
                rate=_rate_str(c.rate),
                by_cohort=[cohort_out(x) for x in c.by_cohort],
                by_band=[cohort_out(x) for x in c.by_band],
            )
            for c in performance.by_currency
        ],
    )


@router.get(
    "/projects/{project_id}/recovery-performance",
    response_model=RecoveryPerformanceOut,
    dependencies=[Depends(RequirePermission("cost_recovery.read"))],
)
async def get_recovery_performance(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> RecoveryPerformanceOut:
    """A project's recovery rate, split by traceability cohort, per currency."""
    await verify_project_access(project_id, user_id or "", session)
    performance = await build_recovery_performance(session, project_id)
    return _performance_out(performance, project_id=str(project_id))


@router.get(
    "/recovery-performance",
    response_model=RecoveryPerformanceOut,
    dependencies=[Depends(RequirePermission("cost_recovery.read"))],
)
async def get_portfolio_recovery_performance(
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> RecoveryPerformanceOut:
    """Recovery performance across every project the caller may access.

    Non-admins are scoped to projects they own or are a team member of; an admin
    sees all. An empty accessible set yields an empty performance rather than an
    error - the safe default for a caller with no projects.
    """
    accessible = await accessible_project_ids(session, user_id)
    project_ids = await _resolve_project_ids(session, accessible)
    performance = await build_portfolio_recovery_performance(session, project_ids)
    return _performance_out(performance, project_id=None)


async def _resolve_project_ids(
    session: AsyncSession,
    accessible: set[uuid.UUID] | None,
) -> list[uuid.UUID]:
    """Turn the accessible-project sentinel into a concrete id list.

    ``accessible_project_ids`` returns ``None`` for an admin (meaning "do not
    filter" - every project). The portfolio rollup needs a concrete list, so an
    admin is expanded to all project ids; a non-admin uses their own set (which
    may be empty, yielding an empty performance).
    """
    if accessible is not None:
        return sorted(accessible)

    from app.modules.projects.models import Project

    rows = (await session.execute(select(Project.id))).scalars().all()
    return [r if isinstance(r, uuid.UUID) else uuid.UUID(str(r)) for r in rows]
