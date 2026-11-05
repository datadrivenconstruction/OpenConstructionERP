# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Capital plan API, mounted by the module loader at ``/api/v1/capital_plan``.

``capital_plan.read`` (viewer and up) gates reads; ``capital_plan.write`` (manager and up)
gates every change. The funding suggestion is a read-only POST: it returns a proposal and
changes nothing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.capital_plan.schemas import (
    ApplyStatuses,
    AutofundResponse,
    CloneRequest,
    CompareResponse,
    EnvelopeListResponse,
    EnvelopeResponse,
    EnvelopesReplace,
    ImportResponse,
    ItemCreate,
    ItemListResponse,
    ItemPatch,
    ItemResponse,
    PlanCreate,
    PlanListResponse,
    PlanPatch,
    PlanResponse,
    ScenarioCreate,
    ScenarioListResponse,
    ScenarioPatch,
    ScenarioResponse,
    SummaryResponse,
)
from app.modules.capital_plan.service import CapitalPlanService

router = APIRouter(tags=["capital_plan"])

_READ = [Depends(RequirePermission("capital_plan.read"))]
_WRITE = [Depends(RequirePermission("capital_plan.write"))]
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _service(session: SessionDep) -> CapitalPlanService:
    return CapitalPlanService(session)


Svc = Depends(_service)


# ── Plans ──────────────────────────────────────────────────────────────────


@router.get("/plans/", response_model=PlanListResponse, dependencies=_READ, summary="List capital plans")
async def list_plans(
    node_id: uuid.UUID | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    service: CapitalPlanService = Svc,
) -> PlanListResponse:
    rows, total = await service.list_plans(node_id, offset=offset, limit=limit)
    return PlanListResponse(
        items=[PlanResponse.model_validate(p) for p in rows], total=total, offset=offset, limit=limit
    )


@router.post(
    "/plans/",
    response_model=PlanResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
    summary="Create a capital plan with its baseline scenario",
)
async def create_plan(body: PlanCreate, user_id: CurrentUserId, service: CapitalPlanService = Svc) -> PlanResponse:
    return PlanResponse.model_validate(await service.create_plan(body, user_id))


@router.get("/plans/{plan_id}/", response_model=PlanResponse, dependencies=_READ)
async def get_plan(plan_id: uuid.UUID, service: CapitalPlanService = Svc) -> PlanResponse:
    return PlanResponse.model_validate(await service.get_plan(plan_id))


@router.patch("/plans/{plan_id}/", response_model=PlanResponse, dependencies=_WRITE)
async def patch_plan(plan_id: uuid.UUID, body: PlanPatch, service: CapitalPlanService = Svc) -> PlanResponse:
    return PlanResponse.model_validate(await service.patch_plan(plan_id, body))


@router.delete("/plans/{plan_id}/", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_plan(plan_id: uuid.UUID, service: CapitalPlanService = Svc) -> Response:
    await service.delete_plan(plan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Envelopes ──────────────────────────────────────────────────────────────


@router.get("/plans/{plan_id}/envelopes/", response_model=EnvelopeListResponse, dependencies=_READ)
async def list_envelopes(
    plan_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=1000),
    service: CapitalPlanService = Svc,
) -> EnvelopeListResponse:
    rows, total = await service.list_envelopes(plan_id, offset=offset, limit=limit)
    return EnvelopeListResponse(
        items=[EnvelopeResponse.model_validate(e) for e in rows], total=total, offset=offset, limit=limit
    )


@router.put(
    "/plans/{plan_id}/envelopes/",
    response_model=list[EnvelopeResponse],
    dependencies=_WRITE,
    summary="Replace all envelopes of a plan",
)
async def replace_envelopes(
    plan_id: uuid.UUID, body: EnvelopesReplace, service: CapitalPlanService = Svc
) -> list[EnvelopeResponse]:
    return [EnvelopeResponse.model_validate(e) for e in await service.replace_envelopes(plan_id, body)]


# ── Scenarios ──────────────────────────────────────────────────────────────


@router.get("/plans/{plan_id}/scenarios/", response_model=ScenarioListResponse, dependencies=_READ)
async def list_scenarios(
    plan_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    service: CapitalPlanService = Svc,
) -> ScenarioListResponse:
    rows, total = await service.list_scenarios(plan_id, offset=offset, limit=limit)
    return ScenarioListResponse(
        items=[ScenarioResponse.model_validate(s) for s in rows], total=total, offset=offset, limit=limit
    )


@router.post(
    "/plans/{plan_id}/scenarios/",
    response_model=ScenarioResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def create_scenario(
    plan_id: uuid.UUID, body: ScenarioCreate, service: CapitalPlanService = Svc
) -> ScenarioResponse:
    return ScenarioResponse.model_validate(await service.create_scenario(plan_id, body))


@router.patch("/plans/{plan_id}/scenarios/{scenario_id}/", response_model=ScenarioResponse, dependencies=_WRITE)
async def patch_scenario(
    plan_id: uuid.UUID, scenario_id: uuid.UUID, body: ScenarioPatch, service: CapitalPlanService = Svc
) -> ScenarioResponse:
    return ScenarioResponse.model_validate(await service.patch_scenario(plan_id, scenario_id, body))


@router.delete("/plans/{plan_id}/scenarios/{scenario_id}/", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_scenario(plan_id: uuid.UUID, scenario_id: uuid.UUID, service: CapitalPlanService = Svc) -> Response:
    await service.delete_scenario(plan_id, scenario_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/plans/{plan_id}/scenarios/{scenario_id}/clone/",
    response_model=ScenarioResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
    summary="Copy a scenario and its items (what-if never mutates the source)",
)
async def clone_scenario(
    plan_id: uuid.UUID, scenario_id: uuid.UUID, body: CloneRequest | None = None, service: CapitalPlanService = Svc
) -> ScenarioResponse:
    clone = await service.clone_scenario(plan_id, scenario_id, body.name if body else None)
    return ScenarioResponse.model_validate(clone)


# ── Items ──────────────────────────────────────────────────────────────────


@router.get("/scenarios/{scenario_id}/items/", response_model=ItemListResponse, dependencies=_READ)
async def list_items(
    scenario_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
    service: CapitalPlanService = Svc,
) -> ItemListResponse:
    rows, total = await service.list_items(scenario_id, offset=offset, limit=limit)
    return ItemListResponse(
        items=[ItemResponse.model_validate(i) for i in rows], total=total, offset=offset, limit=limit
    )


@router.post(
    "/scenarios/{scenario_id}/items/",
    response_model=ItemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def create_item(
    scenario_id: uuid.UUID, body: ItemCreate, user_id: CurrentUserId, service: CapitalPlanService = Svc
) -> ItemResponse:
    return ItemResponse.model_validate(await service.create_item(scenario_id, body, user_id))


@router.patch(
    "/scenarios/{scenario_id}/items/",
    response_model=list[ItemResponse],
    dependencies=_WRITE,
    summary="Apply item statuses in bulk (accepting a funding suggestion)",
)
async def apply_statuses(
    scenario_id: uuid.UUID, body: ApplyStatuses, service: CapitalPlanService = Svc
) -> list[ItemResponse]:
    return [ItemResponse.model_validate(i) for i in await service.apply_statuses(scenario_id, body)]


@router.patch("/items/{item_id}/", response_model=ItemResponse, dependencies=_WRITE)
async def patch_item(
    item_id: uuid.UUID, body: ItemPatch, user_id: CurrentUserId, service: CapitalPlanService = Svc
) -> ItemResponse:
    return ItemResponse.model_validate(await service.patch_item(item_id, body, user_id))


@router.delete("/items/{item_id}/", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_item(item_id: uuid.UUID, service: CapitalPlanService = Svc) -> Response:
    await service.delete_item(item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/plans/{plan_id}/import-projects/",
    response_model=ImportResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
    summary="Create items from the projects under the plan's node",
)
async def import_projects(
    plan_id: uuid.UUID,
    scenario_id: uuid.UUID,
    user_id: CurrentUserId,
    service: CapitalPlanService = Svc,
) -> ImportResponse:
    created, skipped = await service.import_projects(plan_id, scenario_id, user_id)
    return ImportResponse(created=[ItemResponse.model_validate(i) for i in created], skipped=skipped)


# ── Analysis ───────────────────────────────────────────────────────────────


@router.get("/scenarios/{scenario_id}/summary/", response_model=SummaryResponse, dependencies=_READ)
async def get_summary(scenario_id: uuid.UUID, service: CapitalPlanService = Svc) -> SummaryResponse:
    return SummaryResponse.model_validate(await service.summary(scenario_id))


@router.post(
    "/scenarios/{scenario_id}/autofund/",
    response_model=AutofundResponse,
    dependencies=_READ,
    summary="Suggest which items to fund; changes nothing",
)
async def autofund(scenario_id: uuid.UUID, service: CapitalPlanService = Svc) -> AutofundResponse:
    return AutofundResponse.model_validate(await service.autofund(scenario_id))


@router.get("/plans/{plan_id}/compare/", response_model=CompareResponse, dependencies=_READ)
async def compare(plan_id: uuid.UUID, a: uuid.UUID, b: uuid.UUID, service: CapitalPlanService = Svc) -> CompareResponse:
    return CompareResponse.model_validate(await service.compare(plan_id, a, b))


@router.get("/scenarios/{scenario_id}/export/", dependencies=_READ, summary="Scenario as a workbook")
async def export_scenario(
    scenario_id: uuid.UUID,
    format: str = Query(default="xlsx", pattern="^xlsx$"),  # noqa: A002 - the query parameter every export takes
    service: CapitalPlanService = Svc,
) -> Response:
    from app.core.content_disposition import attachment_disposition
    from app.core.i18n import get_locale

    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        content=await service.export_xlsx(scenario_id, get_locale()),
        media_type=_XLSX,
        headers={"Content-Disposition": attachment_disposition(f"capital_plan_{stamp}.{format}")},
    )
