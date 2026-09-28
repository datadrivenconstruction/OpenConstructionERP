# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""API routes for activity codes, UDFs and saved layouts (T2.3).

Mounted onto the schedule module's main router (``/api/v1/schedule``). Every
handler resolves the owning project and calls ``verify_project_access`` (404 on
deny, existence-oracle safe) before touching anything; permissions reuse
``schedule.read`` (VIEWER) / ``schedule.update`` (EDITOR) / ``schedule.delete``.
The grouped grid endpoint ships separately.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.saved_views.errors import RegistrationError, ScopeDenied, WhitelistError
from app.modules.schedule.codes_grouped import resolve_grouped_layout
from app.modules.schedule.codes_models import CodeDictionary, ScheduleLayout, ScheduleUdf
from app.modules.schedule.codes_schemas import (
    ActivityCodesSet,
    ActivityUdfValuesSet,
    BulkAssignRequest,
    BulkAssignResponse,
    CodeAssignmentResponse,
    CodeDictionaryCreate,
    CodeDictionaryPatch,
    CodeDictionaryResponse,
    CodeValueCreate,
    CodeValuePatch,
    CodeValueResponse,
    GroupedRequest,
    GroupedResponse,
    ImportLibraryRequest,
    LayoutCreate,
    LayoutPatch,
    LayoutResponse,
    LayoutSpec,
    UdfCreate,
    UdfPatch,
    UdfResponse,
    UdfValueResponse,
)
from app.modules.schedule.codes_service import ConflictError, ScheduleCodesService, udf_value_readback
from app.modules.schedule.models import Schedule

codes_router = APIRouter(tags=["schedule"])


def _svc(session: SessionDep) -> ScheduleCodesService:
    return ScheduleCodesService(session)


def _as_uuid(value: object) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _not_found(detail: str = "Not found") -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


async def _project_id_for_schedule(schedule_id: uuid.UUID, session: SessionDep) -> uuid.UUID:
    row = await session.execute(select_schedule_project(schedule_id))
    project_id = row.scalar_one_or_none()
    if project_id is None:
        raise _not_found("Schedule not found")
    return project_id


def select_schedule_project(schedule_id: uuid.UUID):
    from sqlalchemy import select

    return select(Schedule.project_id).where(Schedule.id == schedule_id)


# ── code dictionaries ─────────────────────────────────────────────────────────


@codes_router.get("/projects/{project_id}/code-dictionaries/", response_model=list[CodeDictionaryResponse])
async def list_code_dictionaries(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.read")),
) -> list[CodeDictionaryResponse]:
    await verify_project_access(project_id, user_id, session)
    svc = _svc(session)
    return [CodeDictionaryResponse.model_validate(d) for d in await svc.list_dictionaries(project_id)]


@codes_router.post(
    "/projects/{project_id}/code-dictionaries/",
    response_model=CodeDictionaryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_code_dictionary(
    project_id: uuid.UUID,
    data: CodeDictionaryCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.update")),
) -> CodeDictionaryResponse:
    await verify_project_access(project_id, user_id, session)
    svc = _svc(session)
    try:
        d = await svc.create_dictionary(project_id, data)
    except ConflictError as exc:
        raise _conflict(str(exc)) from exc
    return CodeDictionaryResponse.model_validate(d)


@codes_router.get("/code-dictionaries/library/", response_model=list[CodeDictionaryResponse])
async def list_library_dictionaries(
    session: SessionDep,
    user_id: CurrentUserId,  # noqa: ARG001 - authentication only; libraries are workspace templates
    _perm: None = Depends(RequirePermission("schedule.read")),
) -> list[CodeDictionaryResponse]:
    svc = _svc(session)
    return [CodeDictionaryResponse.model_validate(d) for d in await svc.list_library_dictionaries()]


async def _require_writable_dictionary(
    dict_id: uuid.UUID, svc: ScheduleCodesService, user_id: CurrentUserId, session: SessionDep
) -> CodeDictionary:
    d = await svc.get_dictionary(dict_id)
    if d is None or d.project_id is None:
        # A library template (project_id is None) is not editable through the project API in v1.
        raise _not_found("Code dictionary not found")
    await verify_project_access(d.project_id, user_id, session)
    return d


@codes_router.patch("/code-dictionaries/{dict_id}", response_model=CodeDictionaryResponse)
async def patch_code_dictionary(
    dict_id: uuid.UUID,
    data: CodeDictionaryPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.update")),
) -> CodeDictionaryResponse:
    svc = _svc(session)
    d = await _require_writable_dictionary(dict_id, svc, user_id, session)
    try:
        d = await svc.patch_dictionary(d, data)
    except ConflictError as exc:
        raise _conflict(str(exc)) from exc
    return CodeDictionaryResponse.model_validate(d)


@codes_router.delete("/code-dictionaries/{dict_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_code_dictionary(
    dict_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.delete")),
) -> None:
    svc = _svc(session)
    d = await _require_writable_dictionary(dict_id, svc, user_id, session)
    await svc.delete_dictionary(d)


@codes_router.post(
    "/projects/{project_id}/code-dictionaries/import-library",
    response_model=CodeDictionaryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_library_dictionary(
    project_id: uuid.UUID,
    data: ImportLibraryRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.update")),
) -> CodeDictionaryResponse:
    await verify_project_access(project_id, user_id, session)
    svc = _svc(session)
    library = await svc.get_dictionary(data.library_dictionary_id)
    if library is None or not library.is_library:
        raise _not_found("Library dictionary not found")
    try:
        d = await svc.import_library(library, project_id)
    except ConflictError as exc:
        raise _conflict(str(exc)) from exc
    return CodeDictionaryResponse.model_validate(d)


# ── code values ───────────────────────────────────────────────────────────────


@codes_router.get("/code-dictionaries/{dict_id}/values/", response_model=list[CodeValueResponse])
async def list_code_values(
    dict_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.read")),
) -> list[CodeValueResponse]:
    svc = _svc(session)
    d = await svc.get_dictionary(dict_id)
    if d is None or d.project_id is None:
        raise _not_found("Code dictionary not found")
    await verify_project_access(d.project_id, user_id, session)
    return [CodeValueResponse.model_validate(v) for v in await svc.list_values(dict_id)]


@codes_router.post(
    "/code-dictionaries/{dict_id}/values/",
    response_model=CodeValueResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_code_value(
    dict_id: uuid.UUID,
    data: CodeValueCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.update")),
) -> CodeValueResponse:
    svc = _svc(session)
    d = await _require_writable_dictionary(dict_id, svc, user_id, session)
    try:
        v = await svc.add_value(d, data)
    except ConflictError as exc:
        raise _conflict(str(exc)) from exc
    except ValueError as exc:
        raise _unprocessable(str(exc)) from exc
    return CodeValueResponse.model_validate(v)


async def _require_writable_value(
    value_id: uuid.UUID, svc: ScheduleCodesService, user_id: CurrentUserId, session: SessionDep
):
    v = await svc.get_value(value_id)
    if v is None:
        raise _not_found("Code value not found")
    d = await svc.get_dictionary(v.dictionary_id)
    if d is None or d.project_id is None:
        raise _not_found("Code value not found")
    await verify_project_access(d.project_id, user_id, session)
    return v


@codes_router.patch("/code-values/{value_id}", response_model=CodeValueResponse)
async def patch_code_value(
    value_id: uuid.UUID,
    data: CodeValuePatch,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.update")),
) -> CodeValueResponse:
    svc = _svc(session)
    v = await _require_writable_value(value_id, svc, user_id, session)
    try:
        v = await svc.patch_value(v, data)
    except ConflictError as exc:
        raise _conflict(str(exc)) from exc
    return CodeValueResponse.model_validate(v)


@codes_router.delete("/code-values/{value_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_code_value(
    value_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.delete")),
) -> None:
    svc = _svc(session)
    v = await _require_writable_value(value_id, svc, user_id, session)
    await svc.delete_value(v)


# ── per-activity code assignments ──────────────────────────────────────────────


def _code_pairs_to_response(pairs) -> list[CodeAssignmentResponse]:
    out: list[CodeAssignmentResponse] = []
    for a, v in pairs:
        out.append(
            CodeAssignmentResponse(
                dictionary_id=a.dictionary_id,
                value_id=a.value_id,
                code=v.code if v is not None else "",
                label=v.label if v is not None else "",
            )
        )
    return out


@codes_router.get("/activities/{activity_id}/codes/", response_model=list[CodeAssignmentResponse])
async def list_activity_codes(
    activity_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.read")),
) -> list[CodeAssignmentResponse]:
    svc = _svc(session)
    project_id = await svc.project_id_for_activity(activity_id)
    if project_id is None:
        raise _not_found("Activity not found")
    await verify_project_access(project_id, user_id, session)
    return _code_pairs_to_response(await svc.list_activity_code_pairs(activity_id))


@codes_router.put("/activities/{activity_id}/codes/", response_model=list[CodeAssignmentResponse])
async def set_activity_codes(
    activity_id: uuid.UUID,
    data: ActivityCodesSet,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.update")),
) -> list[CodeAssignmentResponse]:
    svc = _svc(session)
    project_id = await svc.project_id_for_activity(activity_id)
    if project_id is None:
        raise _not_found("Activity not found")
    await verify_project_access(project_id, user_id, session)
    try:
        pairs = await svc.set_activity_codes(activity_id, project_id, data.assignments)
    except ValueError as exc:
        raise _unprocessable(str(exc)) from exc
    return _code_pairs_to_response(pairs)


@codes_router.post("/schedules/{schedule_id}/codes/bulk-assign/", response_model=BulkAssignResponse)
async def bulk_assign_code(
    schedule_id: uuid.UUID,
    data: BulkAssignRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.update")),
) -> BulkAssignResponse:
    svc = _svc(session)
    project_id = await _project_id_for_schedule(schedule_id, session)
    await verify_project_access(project_id, user_id, session)
    d = await svc.get_dictionary(data.dictionary_id)
    if d is None or d.project_id != project_id:
        raise _not_found("Code dictionary not found")
    try:
        n = await svc.bulk_assign(d, data.value_id, data.activity_ids)
    except ValueError as exc:
        raise _unprocessable(str(exc)) from exc
    return BulkAssignResponse(assigned=n)


# ── user-defined fields ─────────────────────────────────────────────────────────


@codes_router.get("/projects/{project_id}/udfs/", response_model=list[UdfResponse])
async def list_udfs(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.read")),
) -> list[UdfResponse]:
    await verify_project_access(project_id, user_id, session)
    svc = _svc(session)
    return [UdfResponse.model_validate(u) for u in await svc.list_udfs(project_id)]


@codes_router.post("/projects/{project_id}/udfs/", response_model=UdfResponse, status_code=status.HTTP_201_CREATED)
async def create_udf(
    project_id: uuid.UUID,
    data: UdfCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.update")),
) -> UdfResponse:
    await verify_project_access(project_id, user_id, session)
    svc = _svc(session)
    try:
        u = await svc.create_udf(project_id, data)
    except ConflictError as exc:
        raise _conflict(str(exc)) from exc
    return UdfResponse.model_validate(u)


async def _require_writable_udf(
    udf_id: uuid.UUID, svc: ScheduleCodesService, user_id: CurrentUserId, session: SessionDep
) -> ScheduleUdf:
    u = await svc.get_udf(udf_id)
    if u is None:
        raise _not_found("UDF not found")
    await verify_project_access(u.project_id, user_id, session)
    return u


@codes_router.patch("/udfs/{udf_id}", response_model=UdfResponse)
async def patch_udf(
    udf_id: uuid.UUID,
    data: UdfPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.update")),
) -> UdfResponse:
    svc = _svc(session)
    u = await _require_writable_udf(udf_id, svc, user_id, session)
    u = await svc.patch_udf(u, data)
    return UdfResponse.model_validate(u)


@codes_router.delete("/udfs/{udf_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_udf(
    udf_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.delete")),
) -> None:
    svc = _svc(session)
    u = await _require_writable_udf(udf_id, svc, user_id, session)
    await svc.delete_udf(u)


def _udf_pairs_to_response(pairs) -> list[UdfValueResponse]:
    out: list[UdfValueResponse] = []
    for val_row, udf in pairs:
        value = udf_value_readback(udf.value_type, val_row)
        if isinstance(value, Decimal):
            value = float(value)
        out.append(UdfValueResponse(udf_id=udf.id, value_type=udf.value_type, value=value))
    return out


@codes_router.get("/activities/{activity_id}/udf-values/", response_model=list[UdfValueResponse])
async def list_activity_udf_values(
    activity_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.read")),
) -> list[UdfValueResponse]:
    svc = _svc(session)
    project_id = await svc.project_id_for_activity(activity_id)
    if project_id is None:
        raise _not_found("Activity not found")
    await verify_project_access(project_id, user_id, session)
    return _udf_pairs_to_response(await svc.list_activity_udf_pairs(activity_id))


@codes_router.put("/activities/{activity_id}/udf-values/", response_model=list[UdfValueResponse])
async def set_activity_udf_values(
    activity_id: uuid.UUID,
    data: ActivityUdfValuesSet,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.update")),
) -> list[UdfValueResponse]:
    svc = _svc(session)
    project_id = await svc.project_id_for_activity(activity_id)
    if project_id is None:
        raise _not_found("Activity not found")
    await verify_project_access(project_id, user_id, session)
    try:
        pairs = await svc.set_activity_udf_values(activity_id, project_id, data.values)
    except ValueError as exc:
        raise _unprocessable(str(exc)) from exc
    return _udf_pairs_to_response(pairs)


# ── saved layouts ───────────────────────────────────────────────────────────────


@codes_router.get("/schedules/{schedule_id}/layouts/", response_model=list[LayoutResponse])
async def list_layouts(
    schedule_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.read")),
) -> list[LayoutResponse]:
    svc = _svc(session)
    project_id = await _project_id_for_schedule(schedule_id, session)
    await verify_project_access(project_id, user_id, session)
    layouts = await svc.list_layouts(_as_uuid(user_id), schedule_id, project_id)
    return [LayoutResponse.model_validate(layout) for layout in layouts]


@codes_router.post(
    "/schedules/{schedule_id}/layouts/", response_model=LayoutResponse, status_code=status.HTTP_201_CREATED
)
async def create_layout(
    schedule_id: uuid.UUID,
    data: LayoutCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.update")),
) -> LayoutResponse:
    svc = _svc(session)
    project_id = await _project_id_for_schedule(schedule_id, session)
    await verify_project_access(project_id, user_id, session)
    try:
        layout = await svc.create_layout(_as_uuid(user_id), schedule_id, project_id, data)
    except ConflictError as exc:
        raise _conflict(str(exc)) from exc
    except (WhitelistError, ScopeDenied, RegistrationError) as exc:
        raise _unprocessable(f"Invalid layout filter: {exc}") from exc
    return LayoutResponse.model_validate(layout)


async def _require_owned_layout(
    layout_id: uuid.UUID, svc: ScheduleCodesService, user_id: CurrentUserId, session: SessionDep
) -> ScheduleLayout:
    layout = await svc.get_layout(layout_id)
    # Owner-only for writes; 404 (not 403) cross-owner for existence-oracle safety.
    if layout is None or str(layout.owner_id) != str(user_id):
        raise _not_found("Layout not found")
    if layout.project_id is not None:
        await verify_project_access(layout.project_id, user_id, session)
    return layout


@codes_router.patch("/layouts/{layout_id}", response_model=LayoutResponse)
async def patch_layout(
    layout_id: uuid.UUID,
    data: LayoutPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.update")),
) -> LayoutResponse:
    svc = _svc(session)
    layout = await _require_owned_layout(layout_id, svc, user_id, session)
    try:
        layout = await svc.patch_layout(layout, data)
    except ConflictError as exc:
        raise _conflict(str(exc)) from exc
    except (WhitelistError, ScopeDenied, RegistrationError) as exc:
        raise _unprocessable(f"Invalid layout filter: {exc}") from exc
    return LayoutResponse.model_validate(layout)


@codes_router.delete("/layouts/{layout_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_layout(
    layout_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.delete")),
) -> None:
    svc = _svc(session)
    layout = await _require_owned_layout(layout_id, svc, user_id, session)
    await svc.delete_layout(layout)


# ── grouped grid (the 20k-activity workhorse) ─────────────────────────────────


@codes_router.post("/schedules/{schedule_id}/activities/grouped/", response_model=GroupedResponse)
async def grouped_activities(
    schedule_id: uuid.UUID,
    data: GroupedRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("schedule.read")),
) -> GroupedResponse:
    """Resolve a layout into a grouped, filtered, paged activity grid.

    Read-only; POST because the layout spec is a structured body. The spec comes
    from an inline body or a saved (and visible) layout; an empty spec returns a
    flat first page.
    """
    svc = _svc(session)
    project_id = await _project_id_for_schedule(schedule_id, session)
    await verify_project_access(project_id, user_id, session)

    if data.spec is not None:
        spec = data.spec
    elif data.layout_id is not None:
        layout = await svc.get_layout(data.layout_id)
        if layout is None or layout.schedule_id != schedule_id:
            raise _not_found("Layout not found")
        visible = (
            str(layout.owner_id) == str(user_id)
            or layout.share_scope == "workspace"
            or (layout.share_scope == "project" and layout.project_id == project_id)
        )
        if not visible:
            raise _not_found("Layout not found")
        spec = LayoutSpec.model_validate(layout.spec)
    else:
        spec = LayoutSpec()

    try:
        result = await resolve_grouped_layout(
            session,
            schedule_id,
            project_id,
            spec,
            page=data.page,
            page_size=data.page_size,
            expanded_groups=data.expanded_groups,
        )
    except (WhitelistError, ScopeDenied, RegistrationError) as exc:
        raise _unprocessable(f"Invalid layout: {exc}") from exc
    return GroupedResponse.model_validate(result)
