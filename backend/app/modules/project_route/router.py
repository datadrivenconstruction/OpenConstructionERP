# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠FastAPI router for the work-type route classifier.

Auto-mounted at ``/api/v1/project-route/``. Every project-scoped endpoint is
guarded by :func:`app.dependencies.verify_project_access` - the same guard the
credentials and compliance-docs modules use - so a caller cannot see or mutate
assessments on a project they lack access to, and a cross-project id surfaces as
404 (not 403) so the endpoint cannot be turned into an id-existence oracle.

``/classify`` is stateless (it needs no project) and only requires the read
permission: it runs the decision tree and returns the route without persisting.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import (
    CurrentUserId,
    LangDep,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.project_route import intl
from app.modules.project_route.schemas import (
    ROUTE_OPTIONS,
    STATUSES,
    WORK_TYPES,
    ClassifyRequest,
    ClassifyResult,
    RouteAssessmentCreate,
    RouteAssessmentResponse,
    RouteAssessmentUpdate,
)
from app.modules.project_route.service import RouteService

router = APIRouter(tags=["project_route"])


def _get_service(session: SessionDep) -> RouteService:
    return RouteService(session)


@router.get(
    "/meta",
    dependencies=[Depends(RequirePermission("project_route.read"))],
)
async def get_meta(lang: LangDep) -> dict:
    """Expose the validated vocabularies with localized labels for the UI.

    The frontend builds its work-type / route pickers from this payload so it
    never drifts from the server-side whitelists, and the labels come
    pre-translated for the requested locale (falling back to English).
    """
    return {
        "work_types": [{"code": w, "label": intl.describe_work_type(w, lang)} for w in WORK_TYPES],
        "route_options": [{"code": r, "label": intl.describe_route(r, lang)} for r in ROUTE_OPTIONS],
        "statuses": list(STATUSES),
    }


@router.get(
    "/work-types",
    dependencies=[Depends(RequirePermission("project_route.read"))],
)
async def get_work_types(lang: LangDep) -> list[dict]:
    """The classifiable work types with localized labels."""
    return [{"code": w, "label": intl.describe_work_type(w, lang)} for w in WORK_TYPES]


@router.get(
    "/route-options",
    dependencies=[Depends(RequirePermission("project_route.read"))],
)
async def get_route_options(lang: LangDep) -> list[dict]:
    """The possible delivery / permit routes with localized labels."""
    return [{"code": r, "label": intl.describe_route(r, lang)} for r in ROUTE_OPTIONS]


@router.post(
    "/classify",
    response_model=ClassifyResult,
    dependencies=[Depends(RequirePermission("project_route.read"))],
)
async def classify_route(
    data: ClassifyRequest,
    service: RouteService = Depends(_get_service),
) -> ClassifyResult:
    """Run the decision tree for a work type + criteria without persisting."""
    route, rationale, confidence = service.classify(data.work_type, data.criteria)
    return ClassifyResult(
        work_type=data.work_type,
        determined_route=route,
        rationale=rationale,
        confidence=confidence,
    )


@router.get(
    "/assessments",
    response_model=list[RouteAssessmentResponse],
    dependencies=[Depends(RequirePermission("project_route.read"))],
)
async def list_assessments(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    work_type: str | None = Query(default=None),
    service: RouteService = Depends(_get_service),
) -> list[RouteAssessmentResponse]:
    """List route assessments for a project, optionally filtered."""
    await verify_project_access(project_id, user_id, session)
    items = await service.list_assessments(
        project_id,
        status=status_filter,
        work_type=work_type,
    )
    return [RouteAssessmentResponse.model_validate(i) for i in items]


@router.post(
    "/assessments",
    response_model=RouteAssessmentResponse,
    status_code=201,
)
async def create_assessment(
    data: RouteAssessmentCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("project_route.create")),
    service: RouteService = Depends(_get_service),
) -> RouteAssessmentResponse:
    """Create (and auto-classify) a route assessment against a project."""
    await verify_project_access(data.project_id, user_id, session)
    assessment = await service.create_assessment(data, user_id=user_id)
    return RouteAssessmentResponse.model_validate(assessment)


@router.get(
    "/assessments/{assessment_id}",
    response_model=RouteAssessmentResponse,
    dependencies=[Depends(RequirePermission("project_route.read"))],
)
async def get_assessment(
    assessment_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: RouteService = Depends(_get_service),
) -> RouteAssessmentResponse:
    """Read a single route assessment."""
    assessment = await service.get_assessment(assessment_id)
    await verify_project_access(assessment.project_id, user_id, session)
    return RouteAssessmentResponse.model_validate(assessment)


@router.patch(
    "/assessments/{assessment_id}",
    response_model=RouteAssessmentResponse,
)
async def update_assessment(
    assessment_id: uuid.UUID,
    data: RouteAssessmentUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("project_route.update")),
    service: RouteService = Depends(_get_service),
) -> RouteAssessmentResponse:
    """Patch an assessment. Changing the inputs re-classifies and returns it to draft."""
    existing = await service.get_assessment(assessment_id)
    await verify_project_access(existing.project_id, user_id, session)
    assessment = await service.update_assessment(assessment_id, data, user_id=user_id)
    return RouteAssessmentResponse.model_validate(assessment)


@router.post(
    "/assessments/{assessment_id}/confirm",
    response_model=RouteAssessmentResponse,
)
async def confirm_assessment(
    assessment_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("project_route.update")),
    service: RouteService = Depends(_get_service),
) -> RouteAssessmentResponse:
    """Confirm the assessment's route - the gate the project proceeds under."""
    existing = await service.get_assessment(assessment_id)
    await verify_project_access(existing.project_id, user_id, session)
    assessment = await service.confirm_assessment(assessment_id, user_id=user_id)
    return RouteAssessmentResponse.model_validate(assessment)


@router.delete(
    "/assessments/{assessment_id}",
    status_code=204,
)
async def delete_assessment(
    assessment_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("project_route.delete")),
    service: RouteService = Depends(_get_service),
) -> None:
    """Delete a route assessment."""
    existing = await service.get_assessment(assessment_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_assessment(assessment_id)


__all__ = ["router"]
