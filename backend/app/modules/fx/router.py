# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Currency / FX API routes.

Endpoints:
    GET    /status/                      -- Feed status: source, freshness, reachability
    GET    /rates/                       -- Rate map for a base currency, on a date
    POST   /convert/                     -- Convert an amount (market or PPP, any date)
    POST   /revalue/                     -- Split a movement into scope effect and rate effect
    POST   /refresh/                     -- Pull the live feed into the register
    GET    /rate-sets/                   -- Stored rate sets, newest first
    POST   /rate-sets/                   -- Record a hand-entered rate set
    GET    /rate-sets/{id}/              -- One rate set with every quote
    POST   /rate-sets/{id}/lock/         -- Lock or unlock a rate set
    DELETE /rate-sets/{id}/              -- Delete an unlocked rate set
    GET    /policies/{project_id}/       -- A project's currency policy
    PUT    /policies/{project_id}/       -- Create or update it
    DELETE /policies/{project_id}/       -- Remove it
    GET    /policies/{project_id}/validation/ -- Traffic light over the project's FX setup
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.core.i18n import get_locale
from app.core.validation.engine import ValidationReport
from app.core.validation.messages import translate
from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.fx.repository import RateSetLockedError
from app.modules.fx.schemas import (
    ConvertRequest,
    ConvertResponse,
    FxPolicyRequest,
    FxPolicyResponse,
    FxRatesResponse,
    FxStatusResponse,
    FxValidationFinding,
    FxValidationResponse,
    RateSetCreateRequest,
    RateSetDetail,
    RateSetListResponse,
    RateSetLockRequest,
    RefreshResponse,
    RevaluationRequest,
    RevaluationResponse,
)
from app.modules.fx.service import (
    FxService,
    RateSetUnavailableError,
    UnknownCurrencyError,
    as_revaluation_lines,
)

router = APIRouter(tags=["fx"])
logger = logging.getLogger(__name__)


def _get_fx_service(session: SessionDep) -> FxService:
    return FxService(session)


def _unknown_currency(exc: UnknownCurrencyError) -> HTTPException:
    """422 for a currency the active rates cannot price."""
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Unknown currency: {exc}",
    )


def _rate_set_unavailable(exc: RateSetUnavailableError) -> HTTPException:
    """404 for a pinned or named rate set that does not resolve.

    Deliberately not a silent fallback to today's rates: a pin exists precisely
    so the figure cannot move without someone deciding it should.
    """
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _rate_set_locked(exc: RateSetLockedError) -> HTTPException:
    """409 for a write against a locked set."""
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/status/", response_model=FxStatusResponse)
async def fx_status(
    _user_id: CurrentUserId,
    service: FxService = Depends(_get_fx_service),
    _perm: None = Depends(RequirePermission("fx.read")),
) -> FxStatusResponse:
    """Report FX feed status: rate source, freshness, register size and reachability.

    Makes one best-effort probe of the ECB feed for ``network_ok``; a failure is
    reported, never raised.
    """
    return FxStatusResponse(**await service.status())


@router.get("/rates/", response_model=FxRatesResponse)
async def fx_rates(
    _user_id: CurrentUserId,
    service: FxService = Depends(_get_fx_service),
    base: str = Query(default="EUR", min_length=3, max_length=3, description="Base currency (ISO 4217)."),
    on_date: date | None = Query(default=None, description="Return the rates that applied on this date."),
    rate_set_id: uuid.UUID | None = Query(default=None, description="Quote one named rate set instead."),
    _perm: None = Depends(RequirePermission("fx.read")),
) -> FxRatesResponse:
    """Return the rate map for a base currency (units of each currency per 1 base).

    Rates resolve from the register first, then the legacy latest-rate cache,
    then the bundled seed; the response says which. Non-EUR bases are rebased
    from the EUR-based feed.
    """
    try:
        data = await service.get_rates(base, on_date=on_date, rate_set_id=rate_set_id)
    except UnknownCurrencyError as exc:
        raise _unknown_currency(exc) from exc
    except RateSetUnavailableError as exc:
        raise _rate_set_unavailable(exc) from exc
    return FxRatesResponse(**data)


@router.post("/convert/", response_model=ConvertResponse)
async def fx_convert(
    body: ConvertRequest,
    _user_id: CurrentUserId,
    service: FxService = Depends(_get_fx_service),
    _perm: None = Depends(RequirePermission("fx.read")),
) -> ConvertResponse:
    """Convert an amount between two currencies, optionally as at a past date.

    ``mode=market`` uses published reference rates (default); ``mode=ppp`` uses
    World Bank purchasing-power-parity factors and may return
    ``available=false`` when a factor is missing, which is a 200 response, not
    an error. Passing ``project_id`` applies that project's FX policy, so a
    pinned project reprices at its pinned set rather than at today's rates.
    """
    try:
        data = await service.convert(
            body.amount,
            body.from_currency,
            body.to_currency,
            mode=body.mode,
            on_date=body.on_date,
            project_id=body.project_id,
            rate_set_id=body.rate_set_id,
        )
    except UnknownCurrencyError as exc:
        raise _unknown_currency(exc) from exc
    except RateSetUnavailableError as exc:
        raise _rate_set_unavailable(exc) from exc
    return ConvertResponse(**data)


@router.post("/revalue/", response_model=RevaluationResponse)
async def fx_revalue(
    body: RevaluationRequest,
    _user_id: CurrentUserId,
    service: FxService = Depends(_get_fx_service),
    _perm: None = Depends(RequirePermission("fx.read")),
) -> RevaluationResponse:
    """Revalue figures between two rate dates and attribute the movement.

    Answers the question a cost report is actually asked: of the change in this
    number, how much is scope and how much is the exchange rate. Each line
    returns both, plus the interaction term, and the three sum exactly to the
    total.
    """
    try:
        data = await service.revalue(
            as_revaluation_lines([line.model_dump() for line in body.lines]),
            reporting_currency=body.reporting_currency,
            baseline_date=body.baseline_date,
            current_date=body.current_date,
            baseline_rate_set_id=body.baseline_rate_set_id,
            current_rate_set_id=body.current_rate_set_id,
            project_id=body.project_id,
        )
    except UnknownCurrencyError as exc:
        raise _unknown_currency(exc) from exc
    except RateSetUnavailableError as exc:
        raise _rate_set_unavailable(exc) from exc
    return RevaluationResponse(**data)


@router.post(
    "/refresh/",
    response_model=RefreshResponse,
    dependencies=[Depends(RequirePermission("fx.refresh"))],
)
async def fx_refresh(
    _user_id: CurrentUserId,
    service: FxService = Depends(_get_fx_service),
) -> RefreshResponse:
    """Fetch the live ECB feed now and store it as a rate set.

    On a network failure the register is seeded from the bundled fallback (only
    when it is still empty, so live rates are never overwritten) and the
    response records ``network_ok=false``; the endpoint never fails on a
    network error.
    """
    try:
        return RefreshResponse(**await service.refresh())
    except RateSetLockedError as exc:
        # A pinned set is kept as it was; the create and delete routes answer
        # the same refusal with a 409, and so does the refresh.
        day = exc.rate_date.isoformat() if exc.rate_date else ""
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=translate("errors.fx_rate_set_locked", locale=get_locale(), date=day),
        ) from exc


# ── Rate sets ────────────────────────────────────────────────────────────────


@router.get("/rate-sets/", response_model=RateSetListResponse)
async def list_rate_sets(
    _user_id: CurrentUserId,
    service: FxService = Depends(_get_fx_service),
    base: str | None = Query(default=None, min_length=3, max_length=3, description="Filter by base currency."),
    source: str | None = Query(default=None, max_length=30, description="Filter by provenance (ecb/seed/manual)."),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _perm: None = Depends(RequirePermission("fx.read")),
) -> RateSetListResponse:
    """List stored rate sets, newest first: the register's history."""
    return RateSetListResponse(
        **await service.list_rate_sets(base_currency=base, source=source, limit=limit, offset=offset)
    )


@router.post("/rate-sets/", response_model=RateSetDetail, status_code=status.HTTP_201_CREATED)
async def create_rate_set(
    body: RateSetCreateRequest,
    _user_id: CurrentUserId,
    service: FxService = Depends(_get_fx_service),
    _perm: None = Depends(RequirePermission("fx.manage")),
) -> RateSetDetail:
    """Record a hand-entered rate set: a contract rate, a bank quote, treasury.

    Re-recording the same base, date and source replaces the quotes rather than
    accumulating duplicates, so a corrected entry is a re-post. A locked set is
    refused with 409.
    """
    try:
        data = await service.record_rate_set(
            base_currency=body.base_currency,
            rate_date=body.rate_date,
            rates=body.rates,
            source=body.source,
            source_ref=body.source_ref,
            note=body.note,
            lock=body.lock,
        )
    except UnknownCurrencyError as exc:
        raise _unknown_currency(exc) from exc
    except RateSetLockedError as exc:
        raise _rate_set_locked(exc) from exc
    return RateSetDetail(**data)


@router.get("/rate-sets/{rate_set_id}/", response_model=RateSetDetail)
async def get_rate_set(
    rate_set_id: uuid.UUID,
    _user_id: CurrentUserId,
    service: FxService = Depends(_get_fx_service),
    _perm: None = Depends(RequirePermission("fx.read")),
) -> RateSetDetail:
    """Return one rate set with every quote it carries."""
    try:
        data = await service.get_rate_set(rate_set_id)
    except RateSetUnavailableError as exc:
        raise _rate_set_unavailable(exc) from exc
    return RateSetDetail(**data)


@router.post("/rate-sets/{rate_set_id}/lock/", response_model=RateSetDetail)
async def lock_rate_set(
    rate_set_id: uuid.UUID,
    body: RateSetLockRequest,
    _user_id: CurrentUserId,
    service: FxService = Depends(_get_fx_service),
    _perm: None = Depends(RequirePermission("fx.manage")),
) -> RateSetDetail:
    """Lock or unlock a rate set.

    Locking is what makes a pin worth having: a locked set cannot be rewritten
    by a refresh, so an estimate priced against it reprices identically later.
    """
    try:
        data = await service.set_rate_set_lock(rate_set_id, locked=body.locked)
    except RateSetUnavailableError as exc:
        raise _rate_set_unavailable(exc) from exc
    return RateSetDetail(**data)


@router.delete("/rate-sets/{rate_set_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rate_set(
    rate_set_id: uuid.UUID,
    _user_id: CurrentUserId,
    service: FxService = Depends(_get_fx_service),
    _perm: None = Depends(RequirePermission("fx.manage")),
) -> Response:
    """Delete an unlocked rate set. A locked set is refused with 409."""
    try:
        await service.delete_rate_set(rate_set_id)
    except RateSetUnavailableError as exc:
        raise _rate_set_unavailable(exc) from exc
    except RateSetLockedError as exc:
        raise _rate_set_locked(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Project policy ───────────────────────────────────────────────────────────


@router.get("/policies/{project_id}/", response_model=FxPolicyResponse)
async def get_fx_policy(
    project_id: uuid.UUID,
    _user_id: CurrentUserId,
    service: FxService = Depends(_get_fx_service),
    _perm: None = Depends(RequirePermission("fx.read")),
) -> FxPolicyResponse:
    """Return a project's currency policy, or 404 when it has none configured."""
    data = await service.get_policy(project_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No FX policy is configured for project {project_id}",
        )
    return FxPolicyResponse(**data)


@router.put("/policies/{project_id}/", response_model=FxPolicyResponse)
async def put_fx_policy(
    project_id: uuid.UUID,
    body: FxPolicyRequest,
    _user_id: CurrentUserId,
    service: FxService = Depends(_get_fx_service),
    _perm: None = Depends(RequirePermission("fx.manage")),
) -> FxPolicyResponse:
    """Create or update a project's currency policy.

    A pinned policy is checked against the register before it is stored, so a
    pin can never point at a set that is not there.
    """
    try:
        data = await service.save_policy(
            project_id,
            estimating_currency=body.estimating_currency,
            procurement_currency=body.procurement_currency,
            reporting_currency=body.reporting_currency,
            rate_mode=body.rate_mode,
            pinned_rate_set_id=body.pinned_rate_set_id,
            max_rate_age_days=body.max_rate_age_days,
            note=body.note,
        )
    except UnknownCurrencyError as exc:
        raise _unknown_currency(exc) from exc
    except RateSetUnavailableError as exc:
        raise _rate_set_unavailable(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return FxPolicyResponse(**data)


@router.delete("/policies/{project_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fx_policy(
    project_id: uuid.UUID,
    _user_id: CurrentUserId,
    service: FxService = Depends(_get_fx_service),
    _perm: None = Depends(RequirePermission("fx.manage")),
) -> Response:
    """Remove a project's currency policy."""
    if not await service.delete_policy(project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No FX policy is configured for project {project_id}",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/policies/{project_id}/validation/", response_model=FxValidationResponse)
async def validate_fx_policy(
    project_id: uuid.UUID,
    _user_id: CurrentUserId,
    service: FxService = Depends(_get_fx_service),
    on_date: date | None = Query(default=None, description="Judge rate freshness as at this date."),
    _perm: None = Depends(RequirePermission("fx.read")),
) -> FxValidationResponse:
    """Run the ``fx`` rule set over a project's policy and its backing rates.

    Green means the project's three currencies are all priceable, the rates are
    within the age it tolerates, and a pin (if any) actually holds.
    """
    report = await service.validate_project(project_id, on_date=on_date)
    return _validation_payload(project_id, report)


def _validation_payload(project_id: uuid.UUID, report: ValidationReport) -> FxValidationResponse:
    """Turn a core :class:`ValidationReport` into the module's API shape."""

    def _finding(result: object) -> FxValidationFinding:
        return FxValidationFinding(
            rule_id=getattr(result, "rule_id", ""),
            rule_name=getattr(result, "rule_name", ""),
            severity=str(getattr(result, "severity", "")),
            category=str(getattr(result, "category", "")),
            message=getattr(result, "message", ""),
            element_ref=getattr(result, "element_ref", None),
            suggestion=getattr(result, "suggestion", None),
        )

    return FxValidationResponse(
        project_id=str(project_id),
        status=report.status.value,
        score=report.score,
        checked=len(report.results),
        errors=[_finding(row) for row in report.errors],
        warnings=[_finding(row) for row in report.warnings],
    )
