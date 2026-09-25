# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment clock API routes.

Mounted at ``/api/v1/payment-clock/``.

    GET    /regimes/                          - the statutory regime catalogue
    POST   /regimes/reload                    - reload the catalogue from source

    GET    /applications/                     - clocks on one project
    POST   /applications/                     - open a clock over an application
    GET    /applications/{id}                 - one clock, computed in full
    PATCH  /applications/{id}                 - change what was recorded
    DELETE /applications/{id}                 - delete a clock
    POST   /applications/{id}/recompute       - recompute the statutory dates

    GET    /applications/{id}/notices         - notices served
    POST   /applications/{id}/notices         - record a notice that was served
    DELETE /notices/{notice_id}               - delete a notice recorded in error

    GET    /events/                           - the breach register
    POST   /events/refresh                    - bring the register up to today

Reads never write. The register is brought level by the routes that change a
clock and by ``/events/refresh``; a GET that filed or deleted breaches would
let a reader rewrite the record by picking an ``as_of`` date.

``/regimes/`` and ``/events/`` are declared before ``/applications/{id}`` only
in the sense that they sit on different path roots, so no ordering trap
applies; ``/notices/{notice_id}`` is on its own root for the same reason.

Every project-scoped route calls ``verify_project_access`` before it reads or
writes. The permission dependency answers "may this role do this at all" and
the project check answers "on this project", and neither substitutes for the
other.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.payment_clock.models import (
    PaymentRegime,
    StatutoryPaymentApplication,
)
from app.modules.payment_clock.schemas import (
    ApplicationClock,
    ApplicationCreate,
    ApplicationResponse,
    ApplicationUpdate,
    ClockFinding,
    EventResponse,
    NoticeCreate,
    NoticeResponse,
    NotifiedSum,
    RecomputeRequest,
    RegimeResponse,
)
from app.modules.payment_clock.service import (
    build_schedule,
    clock_snapshot,
    create_application,
    create_notice,
    delete_application,
    delete_notice,
    ensure_regimes,
    get_application,
    get_notice,
    get_regime,
    get_regime_by_code,
    list_applications,
    list_events,
    list_notices,
    list_regimes,
    notified_sum,
    recompute_schedule,
    regime_summary,
    sync_clock_register,
    sync_project_register,
    update_application,
)
from app.modules.payment_clock.validators import evaluate_clock

router = APIRouter(tags=["payment-clock"])


def _regime_response(regime: PaymentRegime) -> RegimeResponse:
    payload = RegimeResponse.model_validate(regime)
    payload.interest_description = regime_summary(regime)
    return payload


def _application_response(
    application: StatutoryPaymentApplication,
    regime: PaymentRegime | None = None,
) -> ApplicationResponse:
    payload = ApplicationResponse.model_validate(application)
    if regime is not None:
        payload.regime_code = regime.code
        payload.jurisdiction = regime.jurisdiction
    return payload


def _findings(results: list) -> list[ClockFinding]:
    return [
        ClockFinding(
            key=f"payment_clock.validation.{result.rule_id}",
            rule_id=result.rule_id,
            severity=str(result.severity),
            message=result.message,
            suggestion=result.suggestion or "",
            details=dict(result.details or {}),
        )
        for result in results
    ]


async def _load_application(
    session: SessionDep,
    application_id: uuid.UUID,
    user_id: str,
) -> tuple[StatutoryPaymentApplication, PaymentRegime]:
    """One application plus its regime, after checking access to its project."""
    application = await get_application(session, application_id=application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment application not found")
    await verify_project_access(application.project_id, user_id, session)
    regime = await get_regime(session, regime_id=application.regime_id)
    if regime is None:
        # A RESTRICT foreign key makes this unreachable through the API. It is
        # still checked rather than assumed, because the alternative is a 500
        # from an attribute on None in the middle of a statutory calculation.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The statutory regime this application was computed under is missing.",
        )
    return application, regime


# ── Regimes ──────────────────────────────────────────────────────────────────


@router.get(
    "/regimes/",
    response_model=list[RegimeResponse],
    dependencies=[Depends(RequirePermission("payment_clock.read"))],
)
async def get_regimes(
    session: SessionDep,
    country_code: str = Query("", max_length=2),
) -> list[RegimeResponse]:
    """The statutory regime catalogue, seeded on first read."""
    await ensure_regimes(session)
    return [_regime_response(regime) for regime in await list_regimes(session, country_code=country_code)]


@router.post(
    "/regimes/reload",
    response_model=dict,
    dependencies=[Depends(RequirePermission("payment_clock.manage"))],
)
async def reload_regimes(session: SessionDep) -> dict:
    """Reload the catalogue from the shipped statutory data.

    Rewrites the shipped regimes in place and leaves any locally added ones
    alone. Applications keep pointing at the same rows, so a correction to a
    statutory period reaches new calculations without disturbing the dates
    already recorded against a live application - those move only on an
    explicit recompute.
    """
    return await ensure_regimes(session, refresh=True)


# ── Applications ─────────────────────────────────────────────────────────────


@router.get(
    "/applications/",
    response_model=list[ApplicationResponse],
    dependencies=[Depends(RequirePermission("payment_clock.read"))],
)
async def get_applications(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    status_filter: str = Query("", alias="status", max_length=24),
    overdue_only: bool = Query(False),
    as_of: date | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ApplicationResponse]:
    """Payment clocks on one project."""
    await verify_project_access(project_id, user_id, session)
    rows = await list_applications(
        session,
        project_id=project_id,
        status=status_filter,
        overdue_as_of=(as_of or date.today()) if overdue_only else None,
        limit=limit,
        offset=offset,
    )
    regimes = {regime.id: regime for regime in await list_regimes(session)}
    return [_application_response(row, regimes.get(row.regime_id)) for row in rows]


@router.post(
    "/applications/",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("payment_clock.write"))],
)
async def open_clock(
    payload: ApplicationCreate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> ApplicationResponse:
    """Open a payment clock over an application and compute its dates."""
    await verify_project_access(payload.project_id, user_id, session)
    await ensure_regimes(session)
    regime = await get_regime_by_code(session, code=payload.regime_code)
    if regime is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown statutory regime {payload.regime_code!r}.",
        )
    application = await create_application(session, body=payload, regime=regime, created_by=str(user_id))
    await sync_clock_register(session, application=application, regime=regime)
    return _application_response(application, regime)


@router.get(
    "/applications/{application_id}",
    response_model=ApplicationClock,
    dependencies=[Depends(RequirePermission("payment_clock.read"))],
)
async def get_clock(
    application_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    as_of: date | None = Query(None),
) -> ApplicationClock:
    """One clock in full: dates, notices, findings, register and notified sum.

    A pure read. The findings are computed for ``as_of`` (today by default)
    and returned as they stand; the register is returned as it was filed and
    is not touched. Filing happens on the routes that change the clock and on
    ``POST /events/refresh``, so reading a clock as of some other date cannot
    delete a breach from the record.
    """
    application, regime = await _load_application(session, application_id, user_id)
    notices = await list_notices(session, application_id=application.id)
    reading_date = as_of or date.today()
    snapshot = clock_snapshot(application, regime, notices, as_of=reading_date)
    findings = await evaluate_clock(snapshot, application_id=str(application.id))
    events = await list_events(session, application_id=application.id)
    summary = notified_sum(application, regime, notices, as_of=reading_date)
    schedule = build_schedule(
        regime,
        application_date=application.application_date,
        period_end=application.period_end,
    )
    return ApplicationClock(
        application=_application_response(application, regime),
        notices=[NoticeResponse.model_validate(notice) for notice in notices],
        events=[EventResponse.model_validate(event) for event in events],
        findings=_findings(findings),
        notified_sum=NotifiedSum(**summary),
        # The derivation of the dates as the regime computes them today. Where
        # the stored dates were set by hand these are the dates that would have
        # applied, which is exactly the comparison a reader wants.
        derivation=schedule.derivation,
        interest_description=regime_summary(regime),
    )


@router.patch(
    "/applications/{application_id}",
    response_model=ApplicationResponse,
    dependencies=[Depends(RequirePermission("payment_clock.write"))],
)
async def amend_clock(
    application_id: uuid.UUID,
    payload: ApplicationUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> ApplicationResponse:
    """Change what was recorded. Statutory dates move only on a recompute."""
    application, regime = await _load_application(session, application_id, user_id)
    updated = await update_application(session, application=application, body=payload)
    await sync_clock_register(session, application=updated, regime=regime)
    return _application_response(updated, regime)


@router.delete(
    "/applications/{application_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("payment_clock.manage"))],
)
async def close_clock(
    application_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> None:
    """Delete a clock, its notices and its register entries."""
    application, _ = await _load_application(session, application_id, user_id)
    await delete_application(session, application=application)


@router.post(
    "/applications/{application_id}/recompute",
    response_model=ApplicationClock,
    dependencies=[Depends(RequirePermission("payment_clock.manage"))],
)
async def recompute_clock(
    application_id: uuid.UUID,
    payload: RecomputeRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> ApplicationClock:
    """Recompute the statutory dates from the regime.

    Refused on a row whose dates were set by hand unless ``force`` is given.
    Overwriting them is overwriting evidence, and the caller has to say that is
    what they mean.
    """
    application, regime = await _load_application(session, application_id, user_id)
    _, written = await recompute_schedule(
        session,
        application=application,
        regime=regime,
        force=payload.force,
        holidays=payload.holidays,
    )
    if not written:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "These statutory dates were set by hand. Send force=true to replace them with the dates "
                "the regime computes."
            ),
        )
    await sync_clock_register(session, application=application, regime=regime)
    return await get_clock(application_id, session, user_id, as_of=None)


# ── Notices ──────────────────────────────────────────────────────────────────


@router.get(
    "/applications/{application_id}/notices",
    response_model=list[NoticeResponse],
    dependencies=[Depends(RequirePermission("payment_clock.read"))],
)
async def get_notices(
    application_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> list[NoticeResponse]:
    """Notices served against one application."""
    application, _ = await _load_application(session, application_id, user_id)
    rows = await list_notices(session, application_id=application.id)
    return [NoticeResponse.model_validate(row) for row in rows]


@router.post(
    "/applications/{application_id}/notices",
    response_model=NoticeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("payment_clock.write"))],
)
async def serve_notice(
    application_id: uuid.UUID,
    payload: NoticeCreate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> NoticeResponse:
    """Record a notice that was served.

    Recorded whether or not it was valid. A notice served a day late is the
    single most important fact about the application it belongs to, and
    refusing to store it would delete the evidence the rules exist to report.
    """
    application, regime = await _load_application(session, application_id, user_id)
    notice = await create_notice(session, application=application, body=payload, created_by=str(user_id))
    await sync_clock_register(session, application=application, regime=regime)
    return NoticeResponse.model_validate(notice)


@router.delete(
    "/notices/{notice_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("payment_clock.manage"))],
)
async def remove_notice(
    notice_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> None:
    """Delete a notice recorded in error.

    MANAGER rather than EDITOR: deleting the record of a notice changes what
    the statute says happened, and it is the one action here that can turn a
    breach into a clean sheet.
    """
    notice = await get_notice(session, notice_id=notice_id)
    if notice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notice not found")
    application, regime = await _load_application(session, notice.application_id, user_id)
    await delete_notice(session, notice=notice)
    await sync_clock_register(session, application=application, regime=regime)


# ── Register ─────────────────────────────────────────────────────────────────


@router.get(
    "/events/",
    response_model=list[EventResponse],
    dependencies=[Depends(RequirePermission("payment_clock.read"))],
)
async def get_events(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    event_type: str = Query("", max_length=48),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[EventResponse]:
    """The breach register for one project.

    Read-only: every row here was written by a validation rule when a clock
    changed or when the register was refreshed. A deadline that passed since
    then is not on it until ``POST /events/refresh`` runs, so a quiet register
    is telling you about the last refresh, not about the payments.
    """
    await verify_project_access(project_id, user_id, session)
    rows = await list_events(
        session,
        project_id=project_id,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )
    return [EventResponse.model_validate(row) for row in rows]


@router.post(
    "/events/refresh",
    response_model=list[EventResponse],
    dependencies=[Depends(RequirePermission("payment_clock.write"))],
)
async def refresh_events(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
) -> list[EventResponse]:
    """Bring the breach register of one project up to today.

    The explicit write the reads no longer do: every clock on the project is
    evaluated as of today and its breaches are filed, and the register is
    returned as it now stands.
    """
    await verify_project_access(project_id, user_id, session)
    await sync_project_register(session, project_id=project_id)
    rows = await list_events(session, project_id=project_id, limit=1000)
    return [EventResponse.model_validate(row) for row in rows]


__all__ = ["router"]
