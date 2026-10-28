# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Labor rate API routes.

Endpoints:
    POST   /compute                        - build an all-in rate (and optional crew blend)
    POST   /templates/                     - create a rate template
    GET    /templates/                     - list the caller's templates
    GET    /templates/{template_id}        - get a template
    PATCH  /templates/{template_id}        - update a template
    DELETE /templates/{template_id}        - delete a template (409 while referenced)
    POST   /templates/{template_id}/publish - publish the all-in rate as a labor cost item
    POST   /crews/                         - create or replace a crew's members
    GET    /crews/{crew_id}                - get a crew with its blended rate
    DELETE /crews/{crew_id}                - delete a crew
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep
from app.modules.costs.schemas import CostItemResponse
from app.modules.labor_rates.models import LaborRateTemplate
from app.modules.labor_rates.schemas import (
    ComputeRequest,
    CrewResponse,
    CrewSaveRequest,
    PublishTemplateRequest,
    RateBreakdown,
    TemplateCreate,
    TemplateResponse,
    TemplateUpdate,
)
from app.modules.labor_rates.service import (
    LaborRateService,
    LaborRateTemplateInUseError,
    LaborRateTemplateNotFoundError,
    describe_template_references,
)

router = APIRouter(tags=["labor_rates"])


def _get_service(session: SessionDep) -> LaborRateService:
    return LaborRateService(session)


def _uuid_or_none(user_id: str) -> uuid.UUID | None:
    """Parse a user id string to a UUID, or ``None`` when it is not one."""
    try:
        return uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return None


def _scope_owner_id(user_id: str, payload: dict | None) -> uuid.UUID | None:
    """Resolve the owner scope for collection endpoints.

    Admins get ``None`` (an unscoped, platform-wide view); everyone else is
    pinned to their own id so collections never leak another tenant's rows.
    """
    if payload and payload.get("role") == "admin":
        return None
    return _uuid_or_none(user_id)


async def _load_owned_template(
    service: LaborRateService,
    template_id: uuid.UUID,
    user_id: str,
    payload: dict | None,
) -> LaborRateTemplate:
    """Load a template and verify ownership.

    Returns 404 (not 403) on a missing template or an ownership mismatch so
    callers cannot enumerate valid ids by probing for 403s. Admins bypass the
    ownership check via the role claim.
    """
    template = await service.get_template(template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if payload and payload.get("role") == "admin":
        return template
    if template.owner_id is None or str(template.owner_id) != str(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return template


# ── Compute ──────────────────────────────────────────────────────────────────


@router.post(
    "/compute",
    response_model=RateBreakdown,
    dependencies=[Depends(RequirePermission("labor_rates.read"))],
)
async def compute_rate(
    data: ComputeRequest,
    _user_id: CurrentUserId,
) -> RateBreakdown:
    """Build the all-in rate breakdown (and optional crew blend) for a request."""
    return LaborRateService.compute(data)


# ── Templates ────────────────────────────────────────────────────────────────


@router.post(
    "/templates/",
    response_model=TemplateResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("labor_rates.create"))],
)
async def create_template(
    data: TemplateCreate,
    user_id: CurrentUserId,
    service: LaborRateService = Depends(_get_service),
) -> TemplateResponse:
    """Create a labor rate template with its on-cost components."""
    template = await service.create_template(data, owner_id=_uuid_or_none(user_id))
    return service.to_template_response(template)


@router.get(
    "/templates/",
    response_model=list[TemplateResponse],
    dependencies=[Depends(RequirePermission("labor_rates.read"))],
)
async def list_templates(
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: LaborRateService = Depends(_get_service),
) -> list[TemplateResponse]:
    """List the caller's labor rate templates (admins see all)."""
    templates = await service.list_templates(owner_id=_scope_owner_id(user_id, payload))
    return [service.to_template_response(t) for t in templates]


@router.get(
    "/templates/{template_id}",
    response_model=TemplateResponse,
    dependencies=[Depends(RequirePermission("labor_rates.read"))],
)
async def get_template(
    template_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: LaborRateService = Depends(_get_service),
) -> TemplateResponse:
    """Get a single labor rate template with its components."""
    template = await _load_owned_template(service, template_id, user_id, payload)
    return service.to_template_response(template)


@router.patch(
    "/templates/{template_id}",
    response_model=TemplateResponse,
    dependencies=[Depends(RequirePermission("labor_rates.update"))],
)
async def update_template(
    template_id: uuid.UUID,
    data: TemplateUpdate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: LaborRateService = Depends(_get_service),
) -> TemplateResponse:
    """Update a template; a provided ``components`` list replaces the old one."""
    template = await _load_owned_template(service, template_id, user_id, payload)
    updated = await service.update_template(template, data)
    return service.to_template_response(updated)


@router.delete(
    "/templates/{template_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("labor_rates.delete"))],
)
async def delete_template(
    template_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: LaborRateService = Depends(_get_service),
) -> None:
    """Delete a labor rate template and its components.

    Refuses with 409 while a published cost item or a priced assembly still
    references the template, naming the holders by count and kind. The refusal
    body carries a machine-readable ``references`` list so the client can say
    the same thing in the user's language. Nothing is cascaded and nothing is
    soft-deleted: the caller clears the holders and retries.
    """
    template = await _load_owned_template(service, template_id, user_id, payload)
    try:
        await service.delete_template(template)
    except LaborRateTemplateInUseError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "labor_rate_template_in_use",
                # Phrased so the sentence reads for one holder as well as many;
                # "1 published cost item still use this template" does not.
                "message": (
                    f"This rate template is referenced by {describe_template_references(exc.references)} "
                    "and cannot be deleted. Remove those records first, then delete the template."
                ),
                "references": [{"kind": kind, "count": count} for kind, count in exc.references.items()],
            },
        ) from exc


@router.post(
    "/templates/{template_id}/publish",
    response_model=CostItemResponse,
    dependencies=[
        Depends(RequirePermission("labor_rates.create")),
        Depends(RequirePermission("costs.create")),
    ],
)
async def publish_template(
    template_id: uuid.UUID,
    data: PublishTemplateRequest,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: LaborRateService = Depends(_get_service),
) -> CostItemResponse:
    """Publish a template's all-in rate as a reusable labor cost item.

    Loads the caller's template (404 on a missing or unowned id, never 403),
    computes its all-in rate exactly as the priced-assembly build does, and
    creates - or updates, when one already exists for the same template, region
    and catalog - a labour cost item carrying that rate so it becomes a pickable
    cost line in the same pickers assemblies and the BOQ already use. This is an
    idempotent upsert. Requires ``labor_rates.create`` (a module write) and
    ``costs.create`` (the output is a cost item).
    """
    template = await _load_owned_template(service, template_id, user_id, payload)
    try:
        item = await service.publish_template_as_cost_item(
            template.id,
            region=data.region,
            catalog=data.catalog_id,
            currency=data.currency,
            owner_id=user_id,
        )
    except LaborRateTemplateNotFoundError as exc:
        # Unreachable via this route (the load above proved existence), but keeps
        # the IDOR posture explicit for any future caller path.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found") from exc
    return CostItemResponse.model_validate(item)


# ── Crews ────────────────────────────────────────────────────────────────────


@router.post(
    "/crews/",
    response_model=CrewResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("labor_rates.create"))],
)
async def save_crew(
    data: CrewSaveRequest,
    user_id: CurrentUserId,
    service: LaborRateService = Depends(_get_service),
) -> CrewResponse:
    """Create or replace a crew's members and return its blended rate."""
    return await service.save_crew(data, owner_id=_uuid_or_none(user_id))


@router.get(
    "/crews/{crew_id}",
    response_model=CrewResponse,
    dependencies=[Depends(RequirePermission("labor_rates.read"))],
)
async def get_crew(
    crew_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: LaborRateService = Depends(_get_service),
) -> CrewResponse:
    """Get a saved crew with its members and blended rate."""
    return await service.get_crew(crew_id, owner_id=_scope_owner_id(user_id, payload))


@router.delete(
    "/crews/{crew_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("labor_rates.delete"))],
)
async def delete_crew(
    crew_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    service: LaborRateService = Depends(_get_service),
) -> None:
    """Delete a saved crew (all members sharing the crew id)."""
    await service.delete_crew(crew_id, owner_id=_scope_owner_id(user_id, payload))
