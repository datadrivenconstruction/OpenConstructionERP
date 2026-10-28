# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Condition API routes (auto-mounted at /api/v1/condition).

Endpoints (RequirePermission + per-project access check on every one):
    GET    /scales?project_id=                 shipped, pack and project scales
    POST   /scales?project_id=                 define a project scale
    DELETE /scales/{key}?project_id=           remove an unused project scale
    POST   /suggest-rating                     rating proposal from severity/extent/intensity
    GET    /assessments?project_id=            ratings (filter by inspection, asset, area)
    POST   /assessments                        record a rating
    PATCH  /assessments/{id}                   edit a rating
    DELETE /assessments/{id}                   remove a rating
    GET    /actions?project_id=                maintenance actions
    POST   /actions                            plan an action by hand (approved)
    PATCH  /actions/{id}                       edit; approve / reject needs condition.approve
    DELETE /actions/{id}                       remove an action
    POST   /plan/derive?project_id=            propose actions from the latest ratings
    GET    /plan?project_id=                   multi-year plan in year buckets
    GET    /plan/export?project_id=            the plan as CSV
    POST   /plan/apply-to-assets?project_id=   write annual cost + rating into the asset register
    GET    /validate?project_id=               run the condition rule set
"""

from __future__ import annotations

import csv
import io
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.condition.schemas import (
    ActionCreate,
    ActionListResponse,
    ActionResponse,
    ActionUpdate,
    ApplyToAssetsResponse,
    AssessmentCreate,
    AssessmentListResponse,
    AssessmentResponse,
    AssessmentUpdate,
    DeriveRequest,
    DeriveResponse,
    RatingSuggestionRequest,
    RatingSuggestionResponse,
    ScaleCreate,
    ScaleListResponse,
    ScaleResponse,
)
from app.modules.condition.service import DEFAULT_HORIZON_YEARS, ConditionService

router = APIRouter(tags=["condition"])


def _service(session: SessionDep) -> ConditionService:
    return ConditionService(session)


def _uid(user_id: str | None) -> str | None:
    return str(user_id) if user_id else None


# ── Scales ───────────────────────────────────────────────────────────────────


@router.get("/scales", response_model=ScaleListResponse)
async def list_scales(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("condition.read")),
    service: ConditionService = Depends(_service),
) -> ScaleListResponse:
    """Every scale usable in this project."""
    await verify_project_access(project_id, user_id or "", service.session)
    items = [ScaleResponse(**s) for s in await service.list_scales(project_id)]
    return ScaleListResponse(items=items, total=len(items), limit=len(items))


@router.post("/scales", response_model=ScaleResponse, status_code=201)
async def create_scale(
    body: ScaleCreate,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("condition.update")),
    service: ConditionService = Depends(_service),
) -> ScaleResponse:
    """Define a scale for this project."""
    await verify_project_access(project_id, user_id or "", service.session)
    return ScaleResponse(**await service.create_scale(project_id, body, _uid(user_id)))


@router.delete("/scales/{key}", status_code=204)
async def delete_scale(
    key: str,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("condition.delete")),
    service: ConditionService = Depends(_service),
) -> None:
    """Remove a project scale no assessment uses."""
    await verify_project_access(project_id, user_id or "", service.session)
    await service.delete_scale(project_id, key)


@router.post("/suggest-rating", response_model=RatingSuggestionResponse)
async def suggest_rating(
    body: RatingSuggestionRequest,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("condition.read")),
    service: ConditionService = Depends(_service),
) -> RatingSuggestionResponse:
    """Propose a rating from a defect record (the inspector decides)."""
    if body.project_id is not None:
        await verify_project_access(body.project_id, user_id or "", service.session)
    rating, confidence, level = await service.suggest(
        body.project_id,
        body.scale_key,
        severity=body.severity,
        extent_pct=body.extent_pct,
        intensity=body.intensity,
    )
    return RatingSuggestionResponse(rating=rating, confidence=confidence, level=level)


# ── Assessments ──────────────────────────────────────────────────────────────


@router.get("/assessments", response_model=AssessmentListResponse)
async def list_assessments(
    project_id: uuid.UUID = Query(...),
    inspection_id: str | None = Query(default=None, max_length=36),
    asset_ref: str | None = Query(default=None, max_length=100),
    area: str | None = Query(default=None, max_length=255),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("condition.read")),
    service: ConditionService = Depends(_service),
) -> AssessmentListResponse:
    """Ratings of a project, newest first."""
    await verify_project_access(project_id, user_id or "", service.session)
    rows = await service.repo.list_assessments(project_id, inspection_id=inspection_id, asset_ref=asset_ref, area=area)
    items = [AssessmentResponse.model_validate(r) for r in rows]
    return AssessmentListResponse(items=items, total=len(items), limit=len(items))


@router.post("/assessments", response_model=AssessmentResponse, status_code=201)
async def create_assessment(
    body: AssessmentCreate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("condition.create")),
    service: ConditionService = Depends(_service),
) -> AssessmentResponse:
    """Record a condition rating."""
    await verify_project_access(body.project_id, user_id or "", service.session)
    row = await service.create_assessment(body, _uid(user_id))
    return AssessmentResponse.model_validate(row)


@router.patch("/assessments/{assessment_id}", response_model=AssessmentResponse)
async def update_assessment(
    assessment_id: uuid.UUID,
    body: AssessmentUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("condition.update")),
    service: ConditionService = Depends(_service),
) -> AssessmentResponse:
    """Edit a rating (only the fields sent change)."""
    row = await service.get_assessment(assessment_id)
    await verify_project_access(row.project_id, user_id or "", service.session)
    return AssessmentResponse.model_validate(await service.update_assessment(row, body))


@router.delete("/assessments/{assessment_id}", status_code=204)
async def delete_assessment(
    assessment_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("condition.delete")),
    service: ConditionService = Depends(_service),
) -> None:
    """Remove a rating; derived actions keep their figures and lose the link."""
    row = await service.get_assessment(assessment_id)
    await verify_project_access(row.project_id, user_id or "", service.session)
    await service.delete_assessment(row)


# ── Actions ──────────────────────────────────────────────────────────────────


@router.get("/actions", response_model=ActionListResponse)
async def list_actions(
    project_id: uuid.UUID = Query(...),
    action_status: str | None = Query(default=None, alias="status", pattern=r"^(proposed|approved|done|rejected)$"),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("condition.read")),
    service: ConditionService = Depends(_service),
) -> ActionListResponse:
    """Maintenance actions of a project, by first year and priority."""
    await verify_project_access(project_id, user_id or "", service.session)
    rows = await service.repo.list_actions(project_id, statuses=[action_status] if action_status else None)
    items = [ActionResponse.model_validate(r) for r in rows]
    return ActionListResponse(items=items, total=len(items), limit=len(items))


@router.post("/actions", response_model=ActionResponse, status_code=201)
async def create_action(
    body: ActionCreate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("condition.create")),
    service: ConditionService = Depends(_service),
) -> ActionResponse:
    """Plan an action by hand."""
    await verify_project_access(body.project_id, user_id or "", service.session)
    return ActionResponse.model_validate(await service.create_action(body, _uid(user_id)))


@router.patch("/actions/{action_id}", response_model=ActionResponse)
async def update_action(
    action_id: uuid.UUID,
    body: ActionUpdate,
    payload: CurrentUserPayload,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("condition.update")),
    service: ConditionService = Depends(_service),
) -> ActionResponse:
    """Edit an action; approving or rejecting a proposal is a manager decision."""
    row = await service.get_action(action_id)
    await verify_project_access(row.project_id, user_id or "", service.session)
    if body.status is not None and body.status != row.status and body.status in ("approved", "rejected"):
        await RequirePermission("condition.approve")(payload)
    return ActionResponse.model_validate(await service.update_action(row, body, _uid(user_id)))


@router.delete("/actions/{action_id}", status_code=204)
async def delete_action(
    action_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("condition.delete")),
    service: ConditionService = Depends(_service),
) -> None:
    """Remove an action."""
    row = await service.get_action(action_id)
    await verify_project_access(row.project_id, user_id or "", service.session)
    await service.delete_action(row)


# ── Plan ─────────────────────────────────────────────────────────────────────


@router.post("/plan/derive", response_model=DeriveResponse)
async def derive_plan(
    body: DeriveRequest,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("condition.create")),
    service: ConditionService = Depends(_service),
) -> DeriveResponse:
    """Propose maintenance actions from the latest rating of each asset."""
    await verify_project_access(project_id, user_id or "", service.session)
    result = await service.derive(project_id, body.base_year, _uid(user_id))
    return DeriveResponse(
        created=result["created"],
        skipped=result["skipped"],
        actions=[ActionResponse.model_validate(a) for a in result["actions"]],
    )


async def _plan(
    service: ConditionService,
    project_id: uuid.UUID,
    start_year: int | None,
    horizon_years: int,
    inflation_rate: Decimal | None,
    index_series_id: uuid.UUID | None,
    discount_rate: Decimal | None,
    include_proposed: bool,
    area: str | None,
    asset_ref: str | None,
) -> dict:
    return await service.plan(
        project_id,
        start_year=start_year,
        horizon_years=horizon_years,
        inflation_rate=inflation_rate,
        index_series_id=index_series_id,
        discount_rate=discount_rate,
        include_proposed=include_proposed,
        area=area,
        asset_ref=asset_ref,
    )


@router.get("/plan")
async def get_plan(
    project_id: uuid.UUID = Query(...),
    start_year: int | None = Query(default=None, ge=1900, le=2300),
    horizon_years: int = Query(default=DEFAULT_HORIZON_YEARS, ge=1, le=100),
    inflation_rate: Decimal | None = Query(default=None, ge=-0.5, le=1),
    index_series_id: uuid.UUID | None = Query(default=None),
    discount_rate: Decimal | None = Query(default=None, ge=0, le=1),
    include_proposed: bool = Query(default=False),
    area: str | None = Query(default=None, max_length=255),
    asset_ref: str | None = Query(default=None, max_length=100),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("condition.read")),
    service: ConditionService = Depends(_service),
) -> dict:
    """The maintenance plan in year buckets (money as decimal strings)."""
    await verify_project_access(project_id, user_id or "", service.session)
    return await _plan(
        service,
        project_id,
        start_year,
        horizon_years,
        inflation_rate,
        index_series_id,
        discount_rate,
        include_proposed,
        area,
        asset_ref,
    )


@router.get("/plan/export")
async def export_plan(
    project_id: uuid.UUID = Query(...),
    start_year: int | None = Query(default=None, ge=1900, le=2300),
    horizon_years: int = Query(default=DEFAULT_HORIZON_YEARS, ge=1, le=100),
    inflation_rate: Decimal | None = Query(default=None, ge=-0.5, le=1),
    index_series_id: uuid.UUID | None = Query(default=None),
    discount_rate: Decimal | None = Query(default=None, ge=0, le=1),
    include_proposed: bool = Query(default=False),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("condition.read")),
    service: ConditionService = Depends(_service),
) -> Response:
    """The plan as CSV, one row per action occurrence."""
    await verify_project_access(project_id, user_id or "", service.session)
    plan = await _plan(
        service,
        project_id,
        start_year,
        horizon_years,
        inflation_rate,
        index_series_id,
        discount_rate,
        include_proposed,
        None,
        None,
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "year",
            "element",
            "asset_ref",
            "area",
            "action",
            "description",
            "status",
            "priority",
            "quantity",
            "unit",
            "unit_cost",
            "currency",
            "cost",
            "cost_inflated",
        ]
    )
    for bucket in plan["years"]:
        for item in bucket["items"]:
            writer.writerow(
                [
                    bucket["year"],
                    item.get("element_name") or "",
                    item.get("asset_ref") or "",
                    item.get("area") or "",
                    item.get("action_type") or "",
                    item.get("description") or "",
                    item.get("status") or "",
                    item.get("priority") or "",
                    item.get("quantity") if item.get("quantity") is not None else "",
                    item.get("unit") or "",
                    item.get("unit_cost") if item.get("unit_cost") is not None else "",
                    item.get("currency") or "",
                    item.get("cost"),
                    item.get("cost_inflated"),
                ]
            )
    return Response(
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=maintenance_plan_{project_id}.csv"},
    )


@router.post("/plan/apply-to-assets", response_model=ApplyToAssetsResponse)
async def apply_plan_to_assets(
    project_id: uuid.UUID = Query(...),
    horizon_years: int = Query(default=DEFAULT_HORIZON_YEARS, ge=1, le=100),
    inflation_rate: Decimal | None = Query(default=None, ge=-0.5, le=1),
    index_series_id: uuid.UUID | None = Query(default=None),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("condition.approve")),
    service: ConditionService = Depends(_service),
) -> ApplyToAssetsResponse:
    """Write each asset's latest rating and annual plan cost into the asset register."""
    await verify_project_access(project_id, user_id or "", service.session)
    plan = await _plan(
        service, project_id, None, horizon_years, inflation_rate, index_series_id, None, False, None, None
    )
    return ApplyToAssetsResponse(**await service.apply_to_assets(project_id, plan))


@router.get("/validate")
async def validate_condition(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("condition.read")),
    service: ConditionService = Depends(_service),
) -> dict:
    """Run the condition rule set over the project's ratings and plan."""
    from app.core.i18n import get_locale
    from app.core.validation.engine import validation_engine
    from app.modules.condition.validators import CONDITION_RULE_SET

    await verify_project_access(project_id, user_id or "", service.session)
    scales = {s["key"]: s for s in await service.list_scales(project_id)}
    assessments = await service.repo.list_assessments(project_id)
    actions = await service.repo.list_actions(project_id)
    data = {
        "scales": scales,
        "assessments": [
            {
                "id": str(a.id),
                "asset_ref": a.asset_ref,
                "element_name": a.element_name,
                "scale_key": a.scale_key,
                "rating": a.rating,
                "severity": a.severity,
                "extent_pct": a.extent_pct,
            }
            for a in assessments
        ],
        "actions": [
            {
                "id": str(x.id),
                "assessment_id": str(x.assessment_id) if x.assessment_id else None,
                "asset_ref": x.asset_ref,
                "element_name": x.element_name,
                "status": x.status,
                "first_year": x.first_year,
                "unit_cost": str(x.unit_cost) if x.unit_cost is not None else None,
            }
            for x in actions
        ],
    }
    report = await validation_engine.validate(
        data=data,
        rule_sets=[CONDITION_RULE_SET],
        target_type="condition",
        target_id=str(project_id),
        project_id=str(project_id),
        metadata={"locale": get_locale()},
    )
    failed = [r for r in report.results if not r.passed]
    return {
        "status": "errors" if report.errors else "warnings" if report.warnings else "passed",
        "checked": len(report.results),
        "results": [
            {
                "rule_id": r.rule_id,
                "severity": str(r.severity),
                "message": r.message,
                "element_ref": r.element_ref,
                "suggestion": r.suggestion,
            }
            for r in failed
        ],
    }
