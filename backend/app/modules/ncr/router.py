# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""NCR API routes.

Endpoints:
    GET    /                           - List NCRs for a project
    POST   /                           - Create NCR
    GET    /{ncr_id}                   - Get single NCR
    PATCH  /{ncr_id}                   - Update NCR
    DELETE /{ncr_id}                   - Delete NCR
    POST   /{ncr_id}/create-variation  - Create change order from NCR
    POST   /{ncr_id}/close             - Close NCR
"""

import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.ncr.schemas import (
    NCRCreate,
    NCRListResponse,
    NCRResponse,
    NCRUpdate,
)
from app.modules.ncr.service import NCRService

router = APIRouter(tags=["ncr"])
logger = logging.getLogger(__name__)

# Matches a free-text cost_impact like "BRL 12000", "USD 1,250.50" or "12000".
# Group 1 = optional leading 3-letter ISO code; group 2 = the numeric amount.
_COST_IMPACT_RE = re.compile(r"^\s*([A-Za-z]{3})?\s*([\d.,]+)\s*$")


def _parse_cost_impact(raw: str | None) -> tuple[str, str | None]:
    """Best-effort split of an NCR's free-text ``cost_impact`` into amount + ISO currency.

    The NCR ``cost_impact`` column is free text (e.g. ``"BRL 12000"``) - amount and
    currency jammed into one string. ``ChangeOrder.cost_impact`` is a numeric MoneyType
    whose ``_to_decimal`` coercion returns 0 for any non-numeric input, so passing the
    raw string silently zeroes the escalated change order's cost.

    This returns ``(numeric_amount_str, currency_or_none)``:
      * a leading 3-letter ISO code (if present) is stripped out and returned separately;
      * thousands separators (``,``) are removed so the numeric part survives coercion;
      * if the string cannot be parsed, the amount falls back to ``"0"`` and currency to
        ``None`` (the caller then uses the project currency).
    """
    if not raw:
        return "0", None
    match = _COST_IMPACT_RE.match(raw)
    if not match:
        # Ambiguous / unparseable free text: keep amount safe and defer currency to project.
        return "0", None
    code, amount = match.groups()
    # Strip thousands separators so "12,000" -> "12000" instead of truncating to 12.
    amount = amount.replace(",", "")
    currency = code.upper() if code else None
    return amount or "0", currency


def _get_service(session: SessionDep) -> NCRService:
    return NCRService(session)


def _to_response(item: object) -> NCRResponse:
    return NCRResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        ncr_number=item.ncr_number,  # type: ignore[attr-defined]
        title=item.title,  # type: ignore[attr-defined]
        description=item.description,  # type: ignore[attr-defined]
        ncr_type=item.ncr_type,  # type: ignore[attr-defined]
        severity=item.severity,  # type: ignore[attr-defined]
        root_cause=item.root_cause,  # type: ignore[attr-defined]
        root_cause_category=item.root_cause_category,  # type: ignore[attr-defined]
        corrective_action=item.corrective_action,  # type: ignore[attr-defined]
        preventive_action=item.preventive_action,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        cost_impact=item.cost_impact,  # type: ignore[attr-defined]
        schedule_impact_days=item.schedule_impact_days,  # type: ignore[attr-defined]
        location_description=item.location_description,  # type: ignore[attr-defined]
        location_lat=item.location_lat,  # type: ignore[attr-defined]
        location_lon=item.location_lon,  # type: ignore[attr-defined]
        location_accuracy_m=item.location_accuracy_m,  # type: ignore[attr-defined]
        linked_inspection_id=item.linked_inspection_id,  # type: ignore[attr-defined]
        change_order_id=item.change_order_id,  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


@router.get("/", response_model=NCRListResponse)
async def list_ncrs(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    type_filter: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
    service: NCRService = Depends(_get_service),
) -> NCRListResponse:
    """List non-conformance reports for a project, with the size of the set.

    The service has always returned the count and this route has always
    dropped it, so a quality register that only ever grows presented its
    first page as the whole of itself.
    """
    await verify_project_access(project_id, user_id, session)
    ncrs, total = await service.list_ncrs(
        project_id,
        offset=offset,
        limit=limit,
        ncr_type=type_filter,
        status_filter=status_filter,
        severity=severity,
    )
    return NCRListResponse(
        items=[_to_response(n) for n in ncrs],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/", response_model=NCRResponse, status_code=201)
async def create_ncr(
    data: NCRCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("ncr.create")),
    service: NCRService = Depends(_get_service),
) -> NCRResponse:
    """Create a new non-conformance report."""
    await verify_project_access(data.project_id, user_id, session)
    ncr = await service.create_ncr(data, user_id=user_id)
    return _to_response(ncr)


@router.get("/{ncr_id}", response_model=NCRResponse)
async def get_ncr(
    ncr_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: NCRService = Depends(_get_service),
) -> NCRResponse:
    """Get a single non-conformance report."""
    ncr = await service.get_ncr(ncr_id)
    await verify_project_access(ncr.project_id, str(user_id), session)
    return _to_response(ncr)


@router.patch("/{ncr_id}", response_model=NCRResponse)
async def update_ncr(
    ncr_id: uuid.UUID,
    data: NCRUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("ncr.update")),
    service: NCRService = Depends(_get_service),
) -> NCRResponse:
    """Update a non-conformance report."""
    existing = await service.get_ncr(ncr_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    ncr = await service.update_ncr(ncr_id, data)
    return _to_response(ncr)


@router.delete("/{ncr_id}", status_code=204)
async def delete_ncr(
    ncr_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("ncr.delete")),
    service: NCRService = Depends(_get_service),
) -> None:
    """Delete a non-conformance report."""
    existing = await service.get_ncr(ncr_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_ncr(ncr_id)


@router.post("/{ncr_id}/create-variation/", status_code=201)
async def create_variation_from_ncr(
    ncr_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("ncr.update")),
    service: NCRService = Depends(_get_service),
) -> dict:
    """Create a change order/variation pre-filled from an NCR with cost impact.

    The NCR must have a non-empty cost_impact value and must not be void.
    Pre-fills the change order with the NCR title, description, and cost impact.
    Repeating the call returns the change order already linked to the NCR
    instead of creating another one.
    """
    ncr = await service.get_ncr(ncr_id)
    # IDOR guard: ncr.update is a global role; without this any holder could
    # escalate an NCR in a project they cannot access into a change order.
    await verify_project_access(ncr.project_id, str(user_id), session)

    if not ncr.cost_impact:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="NCR has no cost impact - cannot create a variation.",
        )

    # A void NCR was raised in error. It is frozen like a closed one, and unlike
    # a closed one (whose cost is often recovered after the fix is verified) it
    # has no cost to recover, so it does not become a change order.
    if ncr.status == "void":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A void NCR was raised in error and has no cost to recover, so no change order is created from it.",
        )

    # Lazy import changeorders module
    try:
        from sqlalchemy import select

        from app.modules.changeorders.models import ChangeOrder
        from app.modules.changeorders.repository import ChangeOrderRepository
        from app.modules.projects.models import Project

        repo = ChangeOrderRepository(session)

        # One NCR, one change order. Every call used to mint another change
        # order carrying the same cost and re-point the NCR at the newest,
        # leaving the earlier ones in the project's change order register with
        # metadata that still names this NCR, so a double click or a retry
        # counted the cost twice. The RFI handoff already works this way: when
        # the linked change order still exists it is returned unchanged, and a
        # link whose change order was deleted falls through and mints afresh.
        if ncr.change_order_id:
            try:
                existing_order_id = uuid.UUID(str(ncr.change_order_id))
            except (ValueError, TypeError):
                existing_order_id = None
            existing_order = await repo.get_by_id(existing_order_id) if existing_order_id is not None else None
            if existing_order is not None:
                logger.info("NCR %s already linked to change order %s - returning it", ncr_id, existing_order.code)
                return {
                    "change_order_id": str(existing_order.id),
                    "code": existing_order.code,
                    "ncr_id": str(ncr_id),
                    "title": existing_order.title,
                }

        count = await repo.count_for_project(ncr.project_id)
        code = f"CO-{count + 1:03d}"

        # Money-correctness fix: ncr.cost_impact is free text like "BRL 12000".
        # Passing it raw to ChangeOrder.cost_impact (a numeric MoneyType) coerces
        # to Decimal('0'), silently dropping the cost, and the ChangeOrder.currency
        # column was left blank - so the rollup treated the lost amount as base
        # currency. Split a clean numeric amount + any leading ISO code here.
        amount, parsed_currency = _parse_cost_impact(ncr.cost_impact)

        # Guard the escalated amount exactly as ChangeOrderCreate does: an
        # absurd-magnitude NCR cost (e.g. a fat-fingered 16-digit value) would
        # otherwise be stored raw on the numeric ChangeOrder and poison the
        # approved-CO rollup / overflow the column. Reuse the CO money validator.
        from app.modules.changeorders.schemas import _validate_decimal

        try:
            _validate_decimal(amount, "cost_impact")
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="NCR cost impact is outside the supported range.",
            ) from exc

        # Prefer the currency parsed from the NCR's own cost_impact; otherwise fall
        # back to the project's real currency. NEVER hardcode "EUR" - load the
        # project's currency, and leave blank ("") if the project has none set.
        project_currency = await session.scalar(select(Project.currency).where(Project.id == ncr.project_id))
        currency = parsed_currency or (project_currency or "")

        description_parts = [
            f"Variation from NCR {ncr.ncr_number}: {ncr.title}",
            "",
            "Description:",
            ncr.description,
        ]
        if ncr.corrective_action:
            description_parts.extend(["", "Corrective Action:", ncr.corrective_action])
        if ncr.root_cause:
            description_parts.extend(["", "Root Cause:", ncr.root_cause])

        order = ChangeOrder(
            project_id=ncr.project_id,
            code=code,
            title=f"Variation: {ncr.title}",
            description="\n".join(description_parts),
            reason_category="non_conformance",
            # Numeric-only amount so the MoneyType coercion no longer rounds to 0.
            cost_impact=amount,
            # Set the real currency (parsed ISO code, else project currency) instead
            # of leaving ChangeOrder.currency at its blank default.
            currency=currency,
            schedule_impact_days=ncr.schedule_impact_days or 0,
            metadata_={
                "source": "ncr",
                "ncr_id": str(ncr_id),
                "ncr_number": ncr.ncr_number,
                # Preserve the original free-text value for traceability/audit.
                "ncr_cost_impact_raw": ncr.cost_impact,
            },
        )
        session.add(order)
        await session.flush()

        # Link the change order back to the NCR
        ncr.change_order_id = str(order.id)
        await session.flush()

        logger.info(
            "Created change order %s from NCR %s",
            code,
            ncr_id,
        )
        return {
            "change_order_id": str(order.id),
            "code": code,
            "ncr_id": str(ncr_id),
            "title": order.title,
        }
    except HTTPException:
        # Let our own 4xx (e.g. the cost-range guard above) propagate instead of
        # being masked as a 500 by the broad handler below.
        raise
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Change orders module is not available.",
        )
    except Exception as exc:
        logger.exception("Failed to create variation from NCR %s: %s", ncr_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create change order from NCR.",
        )


@router.post("/{ncr_id}/close/", response_model=NCRResponse)
async def close_ncr(
    ncr_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("ncr.update")),
    service: NCRService = Depends(_get_service),
) -> NCRResponse:
    """Close an NCR after verification."""
    # IDOR guard: verify the caller can access the NCR's project before
    # mutating it (ncr.update is a global role, not project-scoped).
    ncr = await service.get_ncr(ncr_id)
    await verify_project_access(ncr.project_id, str(user_id), session)
    ncr = await service.close_ncr(ncr_id)
    return _to_response(ncr)
