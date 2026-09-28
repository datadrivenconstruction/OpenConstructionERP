# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HTTP routes for the saved-views module.

Auto-mounted by the module loader at ``/api/v1/saved-views`` (kebab) with a
legacy mirror at ``/api/v1/saved_views``. Every data endpoint takes a
``project_id`` so the scoper always has its pin; a run without a resolvable
project is a 422, never an unscoped query. Each typed engine error maps to a
fixed HTTP status: ``ScopeDenied`` -> 404 (no existence oracle), ``WhitelistError``
and ``BudgetError`` -> 422, ``DuplicateViewName`` -> 409.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.dependencies import (
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
)
from app.modules.saved_views.errors import (
    BudgetError,
    DuplicateViewName,
    ScopeDenied,
    WhitelistError,
)
from app.modules.saved_views.registry import entity_registry
from app.modules.saved_views.schemas import (
    CountResponse,
    RunRequest,
    RunResponse,
    RunStatsResponse,
    SavedViewCreate,
    SavedViewResponse,
    SavedViewUpdate,
    SavedViewValidationReport,
)
from app.modules.saved_views.scoper import ScopeContext
from app.modules.saved_views.service import SavedViewService

router = APIRouter(tags=["saved_views"])
logger = logging.getLogger(__name__)

#: Every engine error the CRUD paths translate rather than let escape as a 500.
_HANDLED = (ScopeDenied, WhitelistError, BudgetError, DuplicateViewName)


def _scope_ctx(payload: dict[str, Any], project_id: uuid.UUID | None) -> ScopeContext:
    """Assemble a :class:`ScopeContext` from the rehydrated payload and project."""
    return ScopeContext.from_payload(
        user_id=payload["sub"],
        payload=payload,
        project_id=project_id,
    )


def _raise_http(exc: Exception) -> None:
    """Translate an engine error into the correct HTTPException."""
    if isinstance(exc, ScopeDenied):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, DuplicateViewName):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(exc, WhitelistError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    if isinstance(exc, BudgetError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    raise exc


def _to_response(service: SavedViewService, view: Any) -> SavedViewResponse:
    """Render a stored row, annotated with whether it still binds.

    The staleness flags are a registry comparison, not a query, so annotating a
    whole list stays free.
    """
    response = SavedViewResponse.model_validate(view)
    is_stale, reasons = service.staleness(view)
    response.is_stale = is_stale
    response.stale_reasons = reasons
    return response


# ── CRUD ────────────────────────────────────────────────────────────────────


@router.post(
    "/",
    response_model=SavedViewResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("saved_views.create"))],
)
async def create_view(
    payload: SavedViewCreate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
) -> SavedViewResponse:
    """Create a saved view from a filter spec."""
    ctx = _scope_ctx(user_payload, payload.project_id)
    service = SavedViewService(session)
    try:
        view = await service.save_view(ctx, payload)
    except _HANDLED as exc:
        _raise_http(exc)
    return _to_response(service, view)


@router.get(
    "/",
    response_model=list[SavedViewResponse],
    dependencies=[Depends(RequirePermission("saved_views.read"))],
)
async def list_views(
    session: SessionDep,
    user_payload: CurrentUserPayload,
    entity_type: Annotated[str | None, Query()] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[SavedViewResponse]:
    """List the caller's own views plus views shared in the project."""
    ctx = _scope_ctx(user_payload, project_id)
    service = SavedViewService(session)
    views = await service.list_views(ctx, entity_type=entity_type, project_id=project_id)
    return [_to_response(service, v) for v in views]


@router.get(
    "/entities",
    dependencies=[Depends(RequirePermission("saved_views.read"))],
)
async def list_entities(_: CurrentUserPayload) -> dict[str, Any]:
    """List registered entity types and their whitelisted fields.

    Drives a data-driven frontend filter builder: the UI never hardcodes which
    columns it may filter on.
    """
    out: dict[str, Any] = {}
    for entity_type, entity in entity_registry.all().items():
        out[entity_type] = {
            "default_sort": list(entity.default_sort),
            "default_columns": list(entity.default_columns),
            "max_rows": entity.max_rows,
            "fields": [
                {
                    "name": fs.name,
                    "kind": fs.kind,
                    "filterable": fs.filterable,
                    "sortable": fs.sortable,
                    "selectable": fs.selectable,
                    "groupable": fs.groupable,
                    "enum_values": list(fs.enum_values) if fs.enum_values else None,
                }
                for fs in entity.fields.values()
            ],
        }
    return {"entities": out}


@router.get(
    "/{view_id}",
    response_model=SavedViewResponse,
    dependencies=[Depends(RequirePermission("saved_views.read"))],
)
async def get_view(
    view_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
) -> SavedViewResponse:
    """Fetch one saved-view definition the caller may see."""
    ctx = _scope_ctx(user_payload, project_id)
    service = SavedViewService(session)
    try:
        view = await service.get_view(view_id, ctx)
    except _HANDLED as exc:
        _raise_http(exc)
    return _to_response(service, view)


@router.patch(
    "/{view_id}",
    response_model=SavedViewResponse,
    dependencies=[Depends(RequirePermission("saved_views.update"))],
)
async def update_view(
    view_id: uuid.UUID,
    payload: SavedViewUpdate,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
) -> SavedViewResponse:
    """Update a saved view (owner or admin only)."""
    ctx = _scope_ctx(user_payload, project_id)
    service = SavedViewService(session)
    try:
        view = await service.update_view(view_id, ctx, payload)
    except _HANDLED as exc:
        _raise_http(exc)
    return _to_response(service, view)


@router.delete(
    "/{view_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("saved_views.delete"))],
)
async def delete_view(
    view_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
) -> None:
    """Delete a saved view (owner or admin only)."""
    ctx = _scope_ctx(user_payload, project_id)
    service = SavedViewService(session)
    try:
        await service.delete_view(view_id, ctx)
    except _HANDLED as exc:
        _raise_http(exc)


# ── Run / count / export ────────────────────────────────────────────────────


@router.post(
    "/{view_id}/run",
    response_model=RunResponse,
    dependencies=[Depends(RequirePermission("saved_views.read"))],
)
async def run_view(
    view_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    project_id: Annotated[uuid.UUID, Query()],
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1)] = None,
) -> RunResponse:
    """Run a stored saved view, returning a capped page of rows."""
    ctx = _scope_ctx(user_payload, project_id)
    service = SavedViewService(session)
    try:
        return await service.run_view(view_id, ctx, page=page, page_size=page_size)
    except _HANDLED as exc:
        _raise_http(exc)
        raise  # unreachable, keeps type checker happy


@router.post(
    "/run",
    response_model=RunResponse,
    dependencies=[Depends(RequirePermission("saved_views.read"))],
)
async def run_adhoc(
    payload: RunRequest,
    session: SessionDep,
    user_payload: CurrentUserPayload,
) -> RunResponse:
    """Run an inline spec without saving (preview-before-save)."""
    ctx = _scope_ctx(user_payload, payload.project_id)
    service = SavedViewService(session)
    try:
        return await service.run_adhoc(payload.entity_type, payload.spec, ctx)
    except _HANDLED as exc:
        _raise_http(exc)
        raise


@router.get(
    "/{view_id}/count",
    response_model=CountResponse,
    dependencies=[Depends(RequirePermission("saved_views.read"))],
)
async def count_view(
    view_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    project_id: Annotated[uuid.UUID, Query()],
) -> CountResponse:
    """Capped count for a reminder badge or dashboard tile."""
    ctx = _scope_ctx(user_payload, project_id)
    service = SavedViewService(session)
    try:
        return await service.count_for_reminder(view_id, ctx)
    except _HANDLED as exc:
        _raise_http(exc)
        raise


@router.get(
    "/{view_id}/validation",
    response_model=SavedViewValidationReport,
    dependencies=[Depends(RequirePermission("saved_views.read"))],
)
async def validate_view(
    view_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    locale: Annotated[str, Query(max_length=16)] = "",
) -> SavedViewValidationReport:
    """Check a stored view against the register as it is registered now.

    Answers "will this still work, and if not, what changed" without running
    the query, so a broken view can be repaired instead of being clicked and
    refused.
    """
    ctx = _scope_ctx(user_payload, project_id)
    service = SavedViewService(session)
    try:
        return await service.validate_view(view_id, ctx, locale=locale)
    except _HANDLED as exc:
        _raise_http(exc)
        raise


@router.get(
    "/{view_id}/runs",
    response_model=RunStatsResponse,
    dependencies=[Depends(RequirePermission("saved_views.read"))],
)
async def view_run_stats(
    view_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
) -> RunStatsResponse:
    """Aggregated run telemetry: how often a view runs, how slow, how truncated."""
    ctx = _scope_ctx(user_payload, project_id)
    service = SavedViewService(session)
    try:
        return await service.run_stats(view_id, ctx)
    except _HANDLED as exc:
        _raise_http(exc)
        raise


@router.get(
    "/{view_id}/export",
    dependencies=[Depends(RequirePermission("saved_views.export"))],
)
async def export_view(
    view_id: uuid.UUID,
    session: SessionDep,
    user_payload: CurrentUserPayload,
    project_id: Annotated[uuid.UUID, Query()],
    fmt: Annotated[str, Query()] = "csv",
) -> StreamingResponse:
    """Stream a capped CSV export of a saved view."""
    ctx = _scope_ctx(user_payload, project_id)
    service = SavedViewService(session)
    if fmt not in ("csv", "parquet"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="fmt must be 'csv' or 'parquet'",
        )

    async def _stream() -> Any:
        try:
            async for chunk in service.to_export(view_id, ctx, fmt):
                yield chunk
        except _HANDLED as exc:
            logger.warning("saved-view export refused: %s", exc)
            return

    media = "text/csv"
    filename = f"saved_view_{view_id}.csv"
    return StreamingResponse(
        _stream(),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
