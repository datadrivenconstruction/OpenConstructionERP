"""‌⁠‍CRM API routes.

Mounted at ``/api/v1/crm/``. Every mutating endpoint is gated through
``RequirePermission``. List endpoints fall back to the generic ``crm.read``
gate.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
)
from app.modules.crm.schemas import (
    AccountCreate,
    AccountResponse,
    AccountUpdate,
    ActivityCreate,
    ActivityResponse,
    ActivityUpdate,
    CrmDashboardResponse,
    ForecastResponse,
    KanbanBoardResponse,
    KanbanColumnResponse,
    LeadConvertRequest,
    LeadCreate,
    LeadQualifyRequest,
    LeadResponse,
    LeadUpdate,
    OpportunityCreate,
    OpportunityLoseRequest,
    OpportunityMoveStageRequest,
    OpportunityResponse,
    OpportunityUpdate,
    OpportunityWinRequest,
    PipelineMetricsResponse,
    PipelineStageCreate,
    PipelineStageResponse,
    PipelineStageUpdate,
    StageHistoryResponse,
    WinLossAnalyticsResponse,
    WinLossReasonCreate,
    WinLossReasonResponse,
    WinLossReasonUpdate,
)
from app.modules.crm.service import (
    CrmService,
    compute_average_sales_cycle,
    compute_lost_reasons_breakdown,
    compute_pipeline_metrics,
    compute_win_rate,
    redact_lead_pii,
)

router = APIRouter()


def _get_service(session: SessionDep) -> CrmService:
    return CrmService(session)


def _lead_to_response(
    lead: Any,
    *,
    viewer_id: str | None,
    viewer_role: str | None,
) -> LeadResponse:
    """‌⁠‍Build a ``LeadResponse`` with PII redacted for non-owner viewers.

    R7 audit: ``LeadResponse.model_validate(lead)`` used to echo raw
    contact_email / contact_phone to every VIEWER. Only the assigned rep,
    managers and admins should see full PII; everyone else gets
    ``j***@example.com`` / ``+49…567``. The lead row itself is unchanged —
    redaction happens at the response boundary only.
    """
    email, phone = redact_lead_pii(
        lead,
        viewer_id=viewer_id,
        viewer_role=viewer_role,
    )
    payload = LeadResponse.model_validate(lead)
    # Pydantic v2 frozen=False default — we mutate the validated copy in
    # place so the redaction can't be lost via a downstream .model_dump().
    payload.contact_email = email
    payload.contact_phone = phone
    return payload


# ── Accounts ─────────────────────────────────────────────────────────────


@router.get("/accounts/", response_model=list[AccountResponse])
async def list_accounts(
    industry: str | None = Query(default=None),
    owner_user_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> list[AccountResponse]:
    items, _ = await service.account_repo.list_all(
        offset=offset,
        limit=limit,
        industry=industry,
        owner_user_id=owner_user_id,
        status=status_filter,
    )
    return [AccountResponse.model_validate(a) for a in items]


@router.post("/accounts/", response_model=AccountResponse, status_code=201)
async def create_account(
    data: AccountCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("crm.create")),
    service: CrmService = Depends(_get_service),
) -> AccountResponse:
    account = await service.create_account(data, user_id=user_id)
    return AccountResponse.model_validate(account)


# NOTE: static sub-paths (``/accounts/tree``) MUST be declared before the
# parameterised ``/accounts/{account_id}`` route — Starlette matches routes
# in registration order, so a later ``/accounts/tree`` would otherwise be
# captured by ``{account_id}`` and 422 on UUID coercion of the literal
# "tree".
@router.get("/accounts/tree")
async def account_tree(
    root_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> list[dict]:
    """‌⁠‍Full account hierarchy (owner / GC / sub) as a nested tree."""
    return await service.account_tree(root_id=root_id)


@router.get("/accounts/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> AccountResponse:
    account = await service.get_account(account_id)
    return AccountResponse.model_validate(account)


@router.patch("/accounts/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: uuid.UUID,
    data: AccountUpdate,
    _perm: None = Depends(RequirePermission("crm.update")),
    service: CrmService = Depends(_get_service),
) -> AccountResponse:
    account = await service.update_account(account_id, data)
    return AccountResponse.model_validate(account)


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(
    account_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("crm.delete")),
    service: CrmService = Depends(_get_service),
) -> None:
    await service.delete_account(account_id)


# ── Leads ────────────────────────────────────────────────────────────────


@router.get("/leads/", response_model=list[LeadResponse])
async def list_leads(
    payload: CurrentUserPayload,
    status_filter: str | None = Query(default=None, alias="status"),
    assigned_to: uuid.UUID | None = Query(default=None),
    source: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> list[LeadResponse]:
    items, _ = await service.lead_repo.list_all(
        offset=offset, limit=limit, status=status_filter, assigned_to=assigned_to, source=source
    )
    viewer_id = payload.get("sub")
    viewer_role = payload.get("role")
    return [_lead_to_response(li, viewer_id=viewer_id, viewer_role=viewer_role) for li in items]


@router.post("/leads/", response_model=LeadResponse, status_code=201)
async def create_lead(
    data: LeadCreate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("crm.create")),
    service: CrmService = Depends(_get_service),
) -> LeadResponse:
    lead = await service.create_lead(data, user_id=user_id)
    return _lead_to_response(
        lead,
        viewer_id=user_id,
        viewer_role=payload.get("role"),
    )


@router.get("/leads/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: uuid.UUID,
    payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> LeadResponse:
    lead = await service.get_lead(lead_id)
    return _lead_to_response(
        lead,
        viewer_id=payload.get("sub"),
        viewer_role=payload.get("role"),
    )


@router.patch("/leads/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: uuid.UUID,
    data: LeadUpdate,
    payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("crm.update")),
    service: CrmService = Depends(_get_service),
) -> LeadResponse:
    lead = await service.update_lead(lead_id, data)
    return _lead_to_response(
        lead,
        viewer_id=payload.get("sub"),
        viewer_role=payload.get("role"),
    )


@router.delete("/leads/{lead_id}", status_code=204)
async def delete_lead(
    lead_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("crm.delete")),
    service: CrmService = Depends(_get_service),
) -> None:
    await service.delete_lead(lead_id)


@router.post("/leads/{lead_id}/forget")
async def forget_lead(
    lead_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("crm.forget")),
    service: CrmService = Depends(_get_service),
) -> dict:
    """GDPR Art. 17 right-to-be-forgotten.

    Scrubs all PII from the lead row + every linked activity, audit-logs
    the actor, but preserves the lead's row + status so referential
    integrity stays intact. ADMIN-only.
    """
    return await service.forget_lead(lead_id, user_id=user_id)


@router.post("/leads/{lead_id}/qualify", response_model=LeadResponse)
async def qualify_lead(
    lead_id: uuid.UUID,
    data: LeadQualifyRequest,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("crm.qualify_lead")),
    service: CrmService = Depends(_get_service),
) -> LeadResponse:
    lead = await service.qualify_lead(lead_id, data.qualification_notes, user_id=user_id)
    return _lead_to_response(
        lead,
        viewer_id=user_id,
        viewer_role=payload.get("role"),
    )


@router.post("/leads/{lead_id}/disqualify", response_model=LeadResponse)
async def disqualify_lead(
    lead_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("crm.qualify_lead")),
    service: CrmService = Depends(_get_service),
) -> LeadResponse:
    lead = await service.disqualify_lead(lead_id, user_id=user_id)
    return _lead_to_response(
        lead,
        viewer_id=user_id,
        viewer_role=payload.get("role"),
    )


@router.post("/leads/{lead_id}/convert", response_model=OpportunityResponse, status_code=201)
async def convert_lead(
    lead_id: uuid.UUID,
    data: LeadConvertRequest,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("crm.convert_lead")),
    service: CrmService = Depends(_get_service),
) -> OpportunityResponse:
    _, opp = await service.convert_lead(lead_id, data, user_id=user_id)
    return OpportunityResponse.model_validate(opp)


# ── Opportunities ────────────────────────────────────────────────────────


@router.get("/opportunities/", response_model=list[OpportunityResponse])
async def list_opportunities(
    owner_user_id: uuid.UUID | None = Query(default=None),
    stage_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    account_id: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> list[OpportunityResponse]:
    items, _ = await service.opportunity_repo.list_all(
        offset=offset,
        limit=limit,
        owner_user_id=owner_user_id,
        stage_id=stage_id,
        status=status_filter,
        account_id=account_id,
    )
    return [OpportunityResponse.model_validate(o) for o in items]


@router.post("/opportunities/", response_model=OpportunityResponse, status_code=201)
async def create_opportunity(
    data: OpportunityCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("crm.create")),
    service: CrmService = Depends(_get_service),
) -> OpportunityResponse:
    opp = await service.create_opportunity(data, user_id=user_id)
    return OpportunityResponse.model_validate(opp)


@router.get("/opportunities/{opportunity_id}", response_model=OpportunityResponse)
async def get_opportunity(
    opportunity_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> OpportunityResponse:
    return OpportunityResponse.model_validate(await service.get_opportunity(opportunity_id))


@router.patch("/opportunities/{opportunity_id}", response_model=OpportunityResponse)
async def update_opportunity(
    opportunity_id: uuid.UUID,
    data: OpportunityUpdate,
    _perm: None = Depends(RequirePermission("crm.update")),
    service: CrmService = Depends(_get_service),
) -> OpportunityResponse:
    opp = await service.update_opportunity(opportunity_id, data)
    return OpportunityResponse.model_validate(opp)


@router.delete("/opportunities/{opportunity_id}", status_code=204)
async def delete_opportunity(
    opportunity_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("crm.delete")),
    service: CrmService = Depends(_get_service),
) -> None:
    await service.delete_opportunity(opportunity_id)


@router.post(
    "/opportunities/{opportunity_id}/move-stage",
    response_model=OpportunityResponse,
)
async def move_stage(
    opportunity_id: uuid.UUID,
    data: OpportunityMoveStageRequest,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("crm.move_stage")),
    service: CrmService = Depends(_get_service),
) -> OpportunityResponse:
    opp = await service.transition_opportunity_stage(
        opportunity_id,
        data.to_stage_id,
        user_id=user_id,
        override_probability_percent=data.override_probability_percent,
    )
    return OpportunityResponse.model_validate(opp)


@router.post("/opportunities/{opportunity_id}/win", response_model=OpportunityResponse)
async def win_opportunity(
    opportunity_id: uuid.UUID,
    data: OpportunityWinRequest,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("crm.win_opportunity")),
    service: CrmService = Depends(_get_service),
) -> OpportunityResponse:
    opp = await service.win_opportunity(
        opportunity_id,
        user_id=user_id,
        won_at=data.won_at,
        win_reason_code=data.win_reason_code,
    )
    return OpportunityResponse.model_validate(opp)


@router.post("/opportunities/{opportunity_id}/lose", response_model=OpportunityResponse)
async def lose_opportunity(
    opportunity_id: uuid.UUID,
    data: OpportunityLoseRequest,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("crm.lose_opportunity")),
    service: CrmService = Depends(_get_service),
) -> OpportunityResponse:
    opp = await service.lose_opportunity(
        opportunity_id,
        data.lost_reason_code,
        user_id=user_id,
        lost_at=data.lost_at,
    )
    return OpportunityResponse.model_validate(opp)


@router.get(
    "/opportunities/{opportunity_id}/history",
    response_model=list[StageHistoryResponse],
)
async def opportunity_history(
    opportunity_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> list[StageHistoryResponse]:
    items = await service.history_repo.list_for_opportunity(opportunity_id)
    return [StageHistoryResponse.model_validate(i) for i in items]


# ── Pipeline stages ──────────────────────────────────────────────────────


@router.get("/pipeline-stages/", response_model=list[PipelineStageResponse])
async def list_stages(
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> list[PipelineStageResponse]:
    items = await service.stage_repo.list_all()
    return [PipelineStageResponse.model_validate(s) for s in items]


@router.post("/pipeline-stages/", response_model=PipelineStageResponse, status_code=201)
async def create_stage(
    data: PipelineStageCreate,
    _perm: None = Depends(RequirePermission("crm.create")),
    service: CrmService = Depends(_get_service),
) -> PipelineStageResponse:
    stage = await service.create_stage(data)
    return PipelineStageResponse.model_validate(stage)


@router.patch("/pipeline-stages/{stage_id}", response_model=PipelineStageResponse)
async def update_stage(
    stage_id: uuid.UUID,
    data: PipelineStageUpdate,
    _perm: None = Depends(RequirePermission("crm.update")),
    service: CrmService = Depends(_get_service),
) -> PipelineStageResponse:
    stage = await service.update_stage(stage_id, data)
    return PipelineStageResponse.model_validate(stage)


@router.delete("/pipeline-stages/{stage_id}", status_code=204)
async def delete_stage(
    stage_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("crm.delete")),
    service: CrmService = Depends(_get_service),
) -> None:
    await service.delete_stage(stage_id)


# ── Activities ───────────────────────────────────────────────────────────


@router.get("/activities/", response_model=list[ActivityResponse])
async def list_activities(
    owner_user_id: uuid.UUID | None = Query(default=None),
    opportunity_id: uuid.UUID | None = Query(default=None),
    account_id: uuid.UUID | None = Query(default=None),
    lead_id: uuid.UUID | None = Query(default=None),
    kind: str | None = Query(default=None),
    due_before: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> list[ActivityResponse]:
    items, _ = await service.activity_repo.list_all(
        offset=offset,
        limit=limit,
        owner_user_id=owner_user_id,
        opportunity_id=opportunity_id,
        account_id=account_id,
        lead_id=lead_id,
        kind=kind,
        due_before=due_before,
    )
    return [ActivityResponse.model_validate(a) for a in items]


@router.post("/activities/", response_model=ActivityResponse, status_code=201)
async def create_activity(
    data: ActivityCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("crm.create")),
    service: CrmService = Depends(_get_service),
) -> ActivityResponse:
    activity = await service.create_activity(data, user_id=user_id)
    return ActivityResponse.model_validate(activity)


# NOTE: declared before ``/activities/{activity_id}`` so the literal
# "timeline" is not captured by the UUID path param (route order matters).
@router.get("/activities/timeline")
async def activity_timeline(
    account_id: uuid.UUID | None = Query(default=None),
    opportunity_id: uuid.UUID | None = Query(default=None),
    lead_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> list[dict]:
    """‌⁠‍Unified chronological feed (activities + stage history)."""
    return await service.activity_timeline(
        account_id=account_id,
        opportunity_id=opportunity_id,
        lead_id=lead_id,
        limit=limit,
    )


@router.get("/activities/{activity_id}", response_model=ActivityResponse)
async def get_activity(
    activity_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> ActivityResponse:
    return ActivityResponse.model_validate(await service.get_activity(activity_id))


@router.patch("/activities/{activity_id}", response_model=ActivityResponse)
async def update_activity(
    activity_id: uuid.UUID,
    data: ActivityUpdate,
    _perm: None = Depends(RequirePermission("crm.update")),
    service: CrmService = Depends(_get_service),
) -> ActivityResponse:
    return ActivityResponse.model_validate(await service.update_activity(activity_id, data))


@router.delete("/activities/{activity_id}", status_code=204)
async def delete_activity(
    activity_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("crm.delete")),
    service: CrmService = Depends(_get_service),
) -> None:
    await service.delete_activity(activity_id)


# ── Forecasts ────────────────────────────────────────────────────────────


@router.get("/forecasts/{period}", response_model=ForecastResponse)
async def get_forecast(
    period: str,
    owner_user_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> ForecastResponse:
    forecast = await service.get_forecast(period, owner_user_id)
    return ForecastResponse.model_validate(forecast)


@router.post("/forecasts/compute", response_model=ForecastResponse)
async def compute_forecast_endpoint(
    period: str = Query(...),
    owner_user_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("crm.compute_forecast")),
    service: CrmService = Depends(_get_service),
) -> ForecastResponse:
    forecast = await service.compute_and_store_forecast(period, owner_user_id)
    return ForecastResponse.model_validate(forecast)


# ── Win/loss reasons ─────────────────────────────────────────────────────


@router.get("/win-loss-reasons/", response_model=list[WinLossReasonResponse])
async def list_reasons(
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> list[WinLossReasonResponse]:
    items = await service.reason_repo.list_all()
    return [WinLossReasonResponse.model_validate(r) for r in items]


@router.post("/win-loss-reasons/", response_model=WinLossReasonResponse, status_code=201)
async def create_reason(
    data: WinLossReasonCreate,
    _perm: None = Depends(RequirePermission("crm.create")),
    service: CrmService = Depends(_get_service),
) -> WinLossReasonResponse:
    reason = await service.create_reason(data)
    return WinLossReasonResponse.model_validate(reason)


@router.patch("/win-loss-reasons/{reason_id}", response_model=WinLossReasonResponse)
async def update_reason(
    reason_id: uuid.UUID,
    data: WinLossReasonUpdate,
    _perm: None = Depends(RequirePermission("crm.update")),
    service: CrmService = Depends(_get_service),
) -> WinLossReasonResponse:
    reason = await service.update_reason(reason_id, data)
    return WinLossReasonResponse.model_validate(reason)


@router.delete("/win-loss-reasons/{reason_id}", status_code=204)
async def delete_reason(
    reason_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("crm.delete")),
    service: CrmService = Depends(_get_service),
) -> None:
    await service.delete_reason(reason_id)


# ── Pipeline kanban + metrics + dashboards ───────────────────────────────


@router.get("/pipeline/kanban", response_model=KanbanBoardResponse)
async def pipeline_kanban(
    owner_user_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> KanbanBoardResponse:
    stages = await service.stage_repo.list_all()
    opps_tuple = await service.opportunity_repo.list_all(limit=10000, owner_user_id=owner_user_id, status="open")
    opps = opps_tuple[0]
    by_stage: dict[uuid.UUID, list[Any]] = {s.id: [] for s in stages}
    for o in opps:
        by_stage.setdefault(o.stage_id, []).append(o)

    columns = [
        KanbanColumnResponse(
            stage_id=s.id,
            code=s.code,
            name=s.name,
            display_order=s.display_order,
            color=s.color,
            opportunities=[OpportunityResponse.model_validate(o) for o in by_stage.get(s.id, [])],
        )
        for s in stages
    ]
    return KanbanBoardResponse(columns=columns)


@router.get("/pipeline/metrics", response_model=PipelineMetricsResponse)
async def pipeline_metrics(
    period_start: str | None = Query(default=None),
    period_end: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> PipelineMetricsResponse:
    opps_tuple = await service.opportunity_repo.list_all(limit=10000)
    metrics = compute_pipeline_metrics(opps_tuple[0])
    return PipelineMetricsResponse(
        open_count=metrics["open_count"],
        weighted_value=metrics["weighted_value"],
        total_value=metrics["total_value"],
        by_stage=metrics["by_stage"],
        win_rate_30d=metrics["win_rate_30d"],
    )


@router.get("/analytics/win-loss", response_model=WinLossAnalyticsResponse)
async def win_loss_analytics(
    period_start: str | None = Query(default=None),
    period_end: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> WinLossAnalyticsResponse:
    opps_tuple = await service.opportunity_repo.list_all(limit=10000)
    opps = opps_tuple[0]

    won_value = Decimal(0)
    lost_value = Decimal(0)
    won_count = 0
    lost_count = 0
    abandoned_count = 0
    for o in opps:
        if o.status == "won":
            won_count += 1
            won_value += Decimal(o.estimated_value or 0)
        elif o.status == "lost":
            lost_count += 1
            lost_value += Decimal(o.estimated_value or 0)
        elif o.status == "abandoned":
            abandoned_count += 1

    return WinLossAnalyticsResponse(
        period_start=period_start,
        period_end=period_end,
        won_count=won_count,
        lost_count=lost_count,
        abandoned_count=abandoned_count,
        win_rate=compute_win_rate(opps, period_start, period_end),
        average_sales_cycle_days=compute_average_sales_cycle(opps),
        lost_reasons_breakdown=compute_lost_reasons_breakdown(opps, period_start, period_end),
        won_value=won_value,
        lost_value=lost_value,
    )


@router.get("/dashboard", response_model=CrmDashboardResponse)
async def crm_dashboard(
    owner_user_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> CrmDashboardResponse:
    opps_tuple = await service.opportunity_repo.list_all(limit=10000, owner_user_id=owner_user_id)
    metrics = compute_pipeline_metrics(opps_tuple[0])

    leads_tuple = await service.lead_repo.list_all(limit=10000)
    open_leads = [
        li
        for li in leads_tuple[0]
        if li.status in ("new", "qualifying", "qualified")
        and (owner_user_id is None or li.assigned_to == owner_user_id)
    ]

    from datetime import datetime as _dt
    from datetime import timedelta as _td

    horizon = (_dt.now().date() + _td(days=7)).isoformat()
    activities_tuple = await service.activity_repo.list_all(
        limit=10000, owner_user_id=owner_user_id, due_before=horizon
    )
    due_soon = sum(1 for a in activities_tuple[0] if a.completed_at is None)

    return CrmDashboardResponse(
        open_opportunities=metrics["open_count"],
        weighted_value=metrics["weighted_value"],
        pipeline_value=metrics["total_value"],
        leads_open=len(open_leads),
        activities_due_soon=due_soon,
        win_rate_30d=metrics["win_rate_30d"],
        by_stage=metrics["by_stage"],
    )


# ── Account hierarchy ────────────────────────────────────────────────────


@router.put("/accounts/{account_id}/parent")
async def set_account_parent(
    account_id: uuid.UUID,
    payload: dict,
    _perm: None = Depends(RequirePermission("crm.update")),
    service: CrmService = Depends(_get_service),
) -> dict:
    """Set / clear an account's parent. Detects cycles."""
    raw = payload.get("parent_account_id")
    parent_id: uuid.UUID | None = None
    if raw is not None:
        try:
            parent_id = uuid.UUID(str(raw))
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid parent_account_id: {exc}",
            ) from exc
    account = await service.set_account_parent(account_id, parent_id)
    return {
        "id": str(account.id),
        "parent_account_id": (str(account.parent_account_id) if account.parent_account_id else None),
        "role": account.role,
    }


# ── BANT scoring ─────────────────────────────────────────────────────────


@router.post("/opportunities/{opportunity_id}/score")
async def score_opportunity(
    opportunity_id: uuid.UUID,
    payload: dict,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("crm.update")),
    service: CrmService = Depends(_get_service),
) -> dict:
    """Compute and persist a BANT score for an opportunity.

    Body:
        budget: int (0..100)
        authority: int (0..100)
        need: int (0..100)
        timeline: int (0..100)
        weights: optional dict[str,int] — override the 30/25/25/20 default.
    """
    try:
        budget = int(payload.get("budget", 0))
        authority = int(payload.get("authority", 0))
        need = int(payload.get("need", 0))
        timeline = int(payload.get("timeline", 0))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid score input: {exc}",
        ) from exc
    weights = payload.get("weights")
    if weights is not None and not isinstance(weights, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="weights must be a dict",
        )
    return await service.score_opportunity(
        opportunity_id,
        budget=budget,
        authority=authority,
        need=need,
        timeline=timeline,
        weights=weights,
        user_id=user_id,
    )


# ── Stage-weighted pipeline forecast ─────────────────────────────────────


@router.get("/pipeline/stage-forecast")
async def stage_weighted_forecast(
    owner_user_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("crm.read")),
    service: CrmService = Depends(_get_service),
) -> dict:
    """Pipeline value grouped by stage with weighted forecast totals."""
    result = await service.stage_weighted_forecast(owner_user_id=owner_user_id)
    return {
        "by_stage": {
            sid: {**{k: (str(v) if hasattr(v, "as_tuple") else v) for k, v in bucket.items()}}
            for sid, bucket in result["by_stage"].items()
        },
        "grand_total": str(result["grand_total"]),
        "grand_weighted": str(result["grand_weighted"]),
    }
