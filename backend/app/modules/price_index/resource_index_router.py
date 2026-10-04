# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Resource-index method (Russia) API routes.

Included into the price-index router, so mounted under
``/api/v1/price-index/resource-index/``:

    GET    /indices/                    - list index values (filter by region/quarter)
    POST   /indices/                    - enter an index value             (price_index.manage)
    PATCH  /indices/{id}/               - change a value or its source     (price_index.manage)
    DELETE /indices/{id}/               - remove a value                   (price_index.manage)
    GET    /norms/                      - list NR/SP norms per work type
    POST   /norms/ ; PATCH / DELETE /norms/{id}/                           (price_index.manage)
    POST   /compute/                    - price explicit positions
    GET    /boqs/{boq_id}/settings/     - the person's choices for a BOQ   (project access)
    PUT    /boqs/{boq_id}/settings/     - store them             (project access + boq.update, 409 if locked)
    POST   /boqs/{boq_id}/compute/      - price a BOQ, read-only           (project access)

Every refusal of the computation is a 422 whose ``detail`` carries a ``code``
(``missing_index``, ``missing_overhead_norm``, ``missing_operator_wages``,
``invalid_index``, ``invalid_input``, ``vat_unresolved``,
``settings_incomplete``) and the facts the screen needs to say what to enter.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.boq.models import BOQ
from app.modules.price_index import resource_index_math as rim
from app.modules.price_index.resource_index_schemas import (
    LIST_LIMIT_MAX,
    BOQResourceIndexComputeRequest,
    BOQResourceIndexSettings,
    OverheadNormCreate,
    OverheadNormList,
    OverheadNormResponse,
    OverheadNormUpdate,
    ResourceIndexComputeRequest,
    ResourceIndexEstimateResponse,
    ResourceIndexValueCreate,
    ResourceIndexValueList,
    ResourceIndexValueResponse,
    ResourceIndexValueUpdate,
)
from app.modules.price_index.resource_index_service import (
    BOQLockedError,
    BOQNotFoundError,
    DuplicateEntryError,
    ResourceIndexService,
    SettingsIncompleteError,
    VatUnresolvedError,
)

router = APIRouter(prefix="/resource-index", tags=["price-index"])

_MANAGE = Depends(RequirePermission("price_index.manage"))
_BOQ_UPDATE = Depends(RequirePermission("boq.update"))


def _refusal(exc: Exception) -> HTTPException:
    """Turn a refusal of the computation into a 422 the screen can explain."""
    detail: dict[str, object] = {"message": str(exc)}
    if isinstance(exc, rim.MissingIndexError):
        detail.update(code=exc.code, groups=list(exc.groups), region_code=exc.region, quarter=exc.quarter)
    elif isinstance(exc, rim.MissingOverheadNormError):
        detail.update(code=exc.code, work_types=list(exc.work_types))
    elif isinstance(exc, rim.MissingOperatorWagesError):
        detail.update(code=exc.code, positions=list(exc.positions))
    elif isinstance(exc, rim.InvalidIndexError):
        detail.update(code=exc.code, group=exc.group)
    elif isinstance(exc, rim.ResourceIndexError):
        detail.update(code=exc.code)
    elif isinstance(exc, VatUnresolvedError):
        detail.update(code="vat_unresolved", on_date=exc.on_date.isoformat(), reason=exc.reason)
    elif isinstance(exc, SettingsIncompleteError):
        detail.update(code="settings_incomplete")
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


# ── Index values ─────────────────────────────────────────────────────────────


@router.get("/indices/", response_model=ResourceIndexValueList)
async def list_indices(
    session: SessionDep,
    _user_id: CurrentUserId,
    region_code: str | None = Query(default=None, max_length=64),
    quarter: str | None = Query(default=None, max_length=7),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=LIST_LIMIT_MAX, ge=1, le=LIST_LIMIT_MAX),
) -> ResourceIndexValueList:
    """One page of index values, newest quarter first within each region, with the total."""
    try:
        rows, total = await ResourceIndexService(session).list_indices(region_code, quarter, offset=offset, limit=limit)
    except rim.ResourceIndexInputError as exc:
        raise _refusal(exc) from exc
    return ResourceIndexValueList(
        items=[ResourceIndexValueResponse.model_validate(r) for r in rows], total=total, offset=offset, limit=limit
    )


@router.post(
    "/indices/",
    response_model=ResourceIndexValueResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_MANAGE],
)
async def create_index(
    data: ResourceIndexValueCreate, session: SessionDep, _user_id: CurrentUserId
) -> ResourceIndexValueResponse:
    """Enter one index from a quarterly letter."""
    try:
        row = await ResourceIndexService(session).create_index(data)
    except DuplicateEntryError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ResourceIndexValueResponse.model_validate(row)


@router.patch("/indices/{index_id}/", response_model=ResourceIndexValueResponse, dependencies=[_MANAGE])
async def update_index(
    index_id: uuid.UUID, data: ResourceIndexValueUpdate, session: SessionDep, _user_id: CurrentUserId
) -> ResourceIndexValueResponse:
    """Change an index value or its source."""
    row = await ResourceIndexService(session).update_index(index_id, data)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Index value not found")
    return ResourceIndexValueResponse.model_validate(row)


@router.delete("/indices/{index_id}/", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_MANAGE])
async def delete_index(index_id: uuid.UUID, session: SessionDep, _user_id: CurrentUserId) -> None:
    """Remove an index value."""
    if not await ResourceIndexService(session).delete_index(index_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Index value not found")


# ── Norms ────────────────────────────────────────────────────────────────────


@router.get("/norms/", response_model=OverheadNormList)
async def list_norms(
    session: SessionDep,
    _user_id: CurrentUserId,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=LIST_LIMIT_MAX, ge=1, le=LIST_LIMIT_MAX),
) -> OverheadNormList:
    """One page of NR/SP norms per work type, with the total."""
    rows, total = await ResourceIndexService(session).list_norms(offset=offset, limit=limit)
    return OverheadNormList(
        items=[OverheadNormResponse.model_validate(r) for r in rows], total=total, offset=offset, limit=limit
    )


@router.post(
    "/norms/",
    response_model=OverheadNormResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_MANAGE],
)
async def create_norm(data: OverheadNormCreate, session: SessionDep, _user_id: CurrentUserId) -> OverheadNormResponse:
    """Enter the NR and SP percentages for a type of work."""
    try:
        row = await ResourceIndexService(session).create_norm(data)
    except DuplicateEntryError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return OverheadNormResponse.model_validate(row)


@router.patch("/norms/{norm_id}/", response_model=OverheadNormResponse, dependencies=[_MANAGE])
async def update_norm(
    norm_id: uuid.UUID, data: OverheadNormUpdate, session: SessionDep, _user_id: CurrentUserId
) -> OverheadNormResponse:
    """Change a norm."""
    row = await ResourceIndexService(session).update_norm(norm_id, data)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Norm not found")
    return OverheadNormResponse.model_validate(row)


@router.delete("/norms/{norm_id}/", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_MANAGE])
async def delete_norm(norm_id: uuid.UUID, session: SessionDep, _user_id: CurrentUserId) -> None:
    """Remove a norm."""
    if not await ResourceIndexService(session).delete_norm(norm_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Norm not found")


# ── Compute ──────────────────────────────────────────────────────────────────


@router.post("/compute/", response_model=ResourceIndexEstimateResponse)
async def compute(
    request: ResourceIndexComputeRequest, session: SessionDep, _user_id: CurrentUserId
) -> ResourceIndexEstimateResponse:
    """Price explicit positions with the stored indices, norms and VAT. Read-only."""
    try:
        return await ResourceIndexService(session).compute(request)
    except (rim.ResourceIndexError, VatUnresolvedError) as exc:
        raise _refusal(exc) from exc


async def _boq_with_access(boq_id: uuid.UUID, user_id: str, service: ResourceIndexService) -> BOQ:
    try:
        boq = await service.get_boq(boq_id)
    except BOQNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found") from exc
    # 404 for both a missing and a forbidden project, so a BOQ id never
    # confirms that someone else's estimate exists.
    await verify_project_access(boq.project_id, user_id, service.session)
    return boq


@router.get("/boqs/{boq_id}/settings/", response_model=BOQResourceIndexSettings)
async def get_settings(boq_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> BOQResourceIndexSettings:
    """The region, quarter and work types chosen for this BOQ."""
    service = ResourceIndexService(session)
    boq = await _boq_with_access(boq_id, user_id, service)
    return service.read_settings(boq)


@router.put("/boqs/{boq_id}/settings/", response_model=BOQResourceIndexSettings, dependencies=[_BOQ_UPDATE])
async def put_settings(
    boq_id: uuid.UUID, data: BOQResourceIndexSettings, session: SessionDep, user_id: CurrentUserId
) -> BOQResourceIndexSettings:
    """Store the region, quarter and work types for this BOQ. Positions are not touched.

    A locked BOQ is a 409, as for every other writer of a bill.
    """
    service = ResourceIndexService(session)
    boq = await _boq_with_access(boq_id, user_id, service)
    try:
        return await service.save_settings(boq, data, user_id)
    except BOQLockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=translate("errors.boq_locked", locale=get_locale()),
        ) from exc


@router.post("/boqs/{boq_id}/compute/", response_model=ResourceIndexEstimateResponse)
async def compute_boq(
    boq_id: uuid.UUID, request: BOQResourceIndexComputeRequest, session: SessionDep, user_id: CurrentUserId
) -> ResourceIndexEstimateResponse:
    """Price a BOQ by the resource-index method. Read-only: nothing on the BOQ changes."""
    service = ResourceIndexService(session)
    boq = await _boq_with_access(boq_id, user_id, service)
    try:
        return await service.compute_boq(boq, request)
    except (rim.ResourceIndexError, VatUnresolvedError, SettingsIncompleteError) as exc:
        raise _refusal(exc) from exc
