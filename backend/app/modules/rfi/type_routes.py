# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request type catalogue routes, preset loading and register validation.

    GET    /types/?project_id=                      - The project's catalogue, with request counts
    POST   /types/                                  - Add a type (manager)
    PATCH  /types/{type_id}                         - Edit a type (manager)
    DELETE /types/{type_id}                         - Delete a type no request uses (manager)
    GET    /types/presets/                          - The shipped presets
    POST   /types/presets/{preset_code}/load/?project_id=  - Copy a preset into a project (manager)
    GET    /validation/?project_id=                 - Run the ``rfi`` rule set over the register

The module router includes :data:`type_router` before its own ``/{rfi_id}``
routes, so ``types`` and ``validation`` are never read as an RFI id.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.rfi.request_types import RequestTypeSpec, list_presets
from app.modules.rfi.schemas import (
    RequestTypeCatalogueResponse,
    RequestTypeCreate,
    RequestTypePresetListResponse,
    RequestTypePresetLoadResponse,
    RequestTypePresetResponse,
    RequestTypePresetType,
    RequestTypeResponse,
    RequestTypeUpdate,
    RFIValidationResponse,
    RFIValidationResult,
)
from app.modules.rfi.type_service import RequestTypeService, spec_from_row

type_router = APIRouter()


def _type_response(project_id: uuid.UUID, spec: RequestTypeSpec, count: int = 0) -> RequestTypeResponse:
    return RequestTypeResponse(
        id=spec.id,
        project_id=project_id,
        code=spec.code,
        name=spec.name_i18n.get("en") or spec.code,
        name_i18n=dict(spec.name_i18n),
        description_i18n=dict(spec.description_i18n),
        number_prefix=spec.number_prefix,
        number_digits=spec.number_digits,
        default_response_days=spec.default_response_days,
        response_days=spec.response_days,
        required_fields=list(spec.required_fields),
        default_route_id=spec.default_route_id,
        is_active=spec.is_active,
        is_builtin=spec.is_builtin,
        sort_order=spec.sort_order,
        preset_code=spec.preset_code,
        request_count=count,
    )


@type_router.get(
    "/types/",
    response_model=RequestTypeCatalogueResponse,
    dependencies=[Depends(RequirePermission("rfi.read"))],
)
async def list_request_types(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
) -> RequestTypeCatalogueResponse:
    """The project's request types, built-in RFI included while the project has no RFI row."""
    await verify_project_access(project_id, user_id, session)
    svc = RequestTypeService(session)
    counts = await svc.request_counts(project_id)
    items = [_type_response(project_id, spec, counts.get(spec.code, 0)) for spec in await svc.catalogue(project_id)]
    return RequestTypeCatalogueResponse(items=items, total=len(items))


@type_router.post(
    "/types/",
    response_model=RequestTypeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("rfi.types.manage"))],
)
async def create_request_type(
    data: RequestTypeCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> RequestTypeResponse:
    """Add a type to the project's catalogue. 409 when its code or prefix is taken."""
    await verify_project_access(data.project_id, user_id, session)
    row = await RequestTypeService(session).create_type(data)
    return _type_response(data.project_id, spec_from_row(row))


@type_router.get(
    "/types/presets/",
    response_model=RequestTypePresetListResponse,
    dependencies=[Depends(RequirePermission("rfi.read"))],
)
async def list_request_type_presets() -> RequestTypePresetListResponse:
    """The presets shipped with the platform."""
    items = [
        RequestTypePresetResponse(
            code=preset.code,
            name_i18n=dict(preset.name_i18n),
            description_i18n=dict(preset.description_i18n),
            types=[
                RequestTypePresetType(
                    code=t.code,
                    number_prefix=t.number_prefix,
                    number_digits=t.number_digits,
                    name_i18n=dict(t.name_i18n),
                    default_response_days=t.default_response_days,
                    required_fields=list(t.required_fields),
                )
                for t in preset.types
            ],
        )
        for preset in list_presets()
    ]
    return RequestTypePresetListResponse(items=items, total=len(items))


@type_router.post(
    "/types/presets/{preset_code}/load/",
    response_model=RequestTypePresetLoadResponse,
    dependencies=[Depends(RequirePermission("rfi.types.manage"))],
)
async def load_request_type_preset(
    preset_code: str,
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
) -> RequestTypePresetLoadResponse:
    """Copy a shipped preset into the project; types it already has are skipped, not overwritten."""
    await verify_project_access(project_id, user_id, session)
    created, skipped = await RequestTypeService(session).load_preset(project_id, preset_code)
    return RequestTypePresetLoadResponse(preset_code=preset_code, created=created, skipped=skipped)


@type_router.patch(
    "/types/{type_id}",
    response_model=RequestTypeResponse,
    dependencies=[Depends(RequirePermission("rfi.types.manage"))],
)
async def update_request_type(
    type_id: uuid.UUID,
    data: RequestTypeUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> RequestTypeResponse:
    """Edit a type. Code and prefix are fixed once requests carry them."""
    svc = RequestTypeService(session)
    row = await svc.get_row(type_id)
    await verify_project_access(row.project_id, user_id, session)
    row = await svc.update_type(row, data)
    counts = await svc.request_counts(row.project_id)
    return _type_response(row.project_id, spec_from_row(row), counts.get(row.code, 0))


@type_router.delete(
    "/types/{type_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(RequirePermission("rfi.types.manage"))],
)
async def delete_request_type(
    type_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> Response:
    """Delete a type no request uses; 409 when requests use it (retire it instead)."""
    svc = RequestTypeService(session)
    row = await svc.get_row(type_id)
    await verify_project_access(row.project_id, user_id, session)
    await svc.delete_type(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@type_router.get(
    "/validation/",
    response_model=RFIValidationResponse,
    dependencies=[Depends(RequirePermission("rfi.read"))],
)
async def validate_rfi_register(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
) -> RFIValidationResponse:
    """Traffic-light check of the register: required fields per type and catalogue consistency."""
    from app.modules.rfi.service import RFIService

    await verify_project_access(project_id, user_id, session)
    report = await RFIService(session).validate_register(project_id)
    return RFIValidationResponse(
        status=str(report.status),
        score=report.score,
        errors=len(report.errors),
        warnings=len(report.warnings),
        results=[
            RFIValidationResult(
                rule_id=r.rule_id,
                severity=str(r.severity),
                passed=r.passed,
                message=r.message,
                element_ref=r.element_ref,
                details=r.details,
            )
            for r in report.results
        ],
    )
