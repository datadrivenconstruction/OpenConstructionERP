# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rebar schedule API routes.

Mounted at ``/api/v1/rebar-schedule``.

    GET    /super-groups                     - the format's super-groups and rule set
    POST   /preview                          - parse and validate without storing
    POST   /imports?project_id=X             - import an ABS file
    GET    /imports?project_id=X             - list a project's imports
    GET    /imports/{import_id}              - one import
    DELETE /imports/{import_id}              - delete an import and its shapes
    GET    /imports/{import_id}/shapes       - the bending shapes of one import
    GET    /imports/{import_id}/cutting      - bars and weight per bar diameter
    GET    /imports/{import_id}/export       - write the shapes back out as .abs

Reads need ``rebar_schedule.read``, importing needs ``rebar_schedule.import``,
deleting needs ``rebar_schedule.delete``. Every project-scoped route also
verifies the caller may reach the project.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.rebar_schedule.abs_format import MAX_RECORD_LENGTH, SUPER_GROUP_KINDS, SUPER_GROUPS
from app.modules.rebar_schedule.schemas import (
    AbsPreviewRequest,
    AbsPreviewResponse,
    CuttingItem,
    RebarImportListResponse,
    RebarImportResponse,
    RebarImportResult,
    RebarShapeListResponse,
    RebarShapeResponse,
    SuperGroupInfo,
    SuperGroupsResponse,
)
from app.modules.rebar_schedule.service import RebarScheduleError, RebarScheduleService
from app.modules.rebar_schedule.validators import RULE_SET, RULES

router = APIRouter()

_READ = Depends(RequirePermission("rebar_schedule.read"))
_IMPORT = Depends(RequirePermission("rebar_schedule.import"))
_DELETE = Depends(RequirePermission("rebar_schedule.delete"))

#: The standard's compactness target is 1000 characters per shape. A bending
#: schedule of ten thousand shapes is already an outlier, so this cap is
#: generous while still keeping an accidental upload of the wrong file from
#: being parsed line by line.
MAX_UPLOAD_BYTES = 16 * 1024 * 1024


def _service(session: AsyncSession) -> RebarScheduleService:
    return RebarScheduleService(session)


# ── Format vocabulary (static lookup) ─────────────────────────────────────


@router.get("/super-groups", response_model=SuperGroupsResponse, include_in_schema=False, dependencies=[_READ])
@router.get("/super-groups/", response_model=SuperGroupsResponse, dependencies=[_READ])
async def list_super_groups() -> SuperGroupsResponse:
    """Return the super-groups the format defines and the rule set that checks them.

    ``kind`` is an i18n key rather than a label, so the frontend names each
    super-group in the reader's language instead of showing the German
    identifier the standard uses on the wire.
    """
    return SuperGroupsResponse(
        groups=[SuperGroupInfo(code=code, kind=SUPER_GROUP_KINDS[code]) for code in SUPER_GROUPS],
        rule_set=RULE_SET,
        rule_ids=[rule.rule_id for rule in RULES],
        max_record_length=MAX_RECORD_LENGTH,
    )


# ── Dry run ───────────────────────────────────────────────────────────────


@router.post("/preview", response_model=AbsPreviewResponse, include_in_schema=False, dependencies=[_READ])
@router.post("/preview/", response_model=AbsPreviewResponse, dependencies=[_READ])
async def preview(payload: AbsPreviewRequest, session: SessionDep) -> AbsPreviewResponse:
    """Parse and validate ABS content without storing anything.

    Lets an estimator see what a file says, and what is wrong with it, before
    deciding to take it into the project.
    """
    try:
        result = await _service(session).preview(payload.content, locale=payload.locale)
    except RebarScheduleError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return AbsPreviewResponse.model_validate(result)


# ── Imports ───────────────────────────────────────────────────────────────


@router.post(
    "/imports",
    response_model=RebarImportResult,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
    dependencies=[_IMPORT],
)
@router.post(
    "/imports/",
    response_model=RebarImportResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_IMPORT],
)
async def import_schedule(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    locale: str | None = Query(default=None, max_length=16),
    upload: UploadFile = File(...),
) -> RebarImportResult:
    """Import an ABS file into a project.

    The file is parsed, validated against the ``bvbs_abs`` rule set and stored
    with its findings. A file that fails validation is still stored, so each
    finding can be shown against the shape it came from; the import's
    ``validation_status`` says whether it is clean.

    Re-uploading bytes already imported into this project returns the existing
    import untouched, with ``duplicate`` set.
    """
    await verify_project_access(project_id, user_id, session)
    content = await upload.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {MAX_UPLOAD_BYTES} byte limit",
        )
    if not content.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="File is empty")
    try:
        result = await _service(session).import_file(
            project_id,
            upload.filename or "schedule.abs",
            content,
            created_by=user_id,
            locale=locale,
        )
    except RebarScheduleError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    await session.commit()
    return RebarImportResult(
        import_record=RebarImportResponse.model_validate(result["import_record"]),
        validation=result["validation"],
        duplicate=result["duplicate"],
    )


@router.get("/imports", response_model=RebarImportListResponse, include_in_schema=False, dependencies=[_READ])
@router.get("/imports/", response_model=RebarImportListResponse, dependencies=[_READ])
async def list_imports(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    validation_status: str | None = Query(default=None, max_length=16),
) -> RebarImportListResponse:
    """List a project's imported bending schedules, newest first."""
    await verify_project_access(project_id, user_id, session)
    rows, total = await _service(session).list_imports(
        project_id,
        offset=offset,
        limit=limit,
        validation_status=validation_status,
    )
    return RebarImportListResponse(
        items=[RebarImportResponse.model_validate(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/imports/{import_id}", response_model=RebarImportResponse, dependencies=[_READ])
async def get_import(import_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> RebarImportResponse:
    """Get one import."""
    service = _service(session)
    try:
        record = await service.get_import(import_id)
    except RebarScheduleError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await verify_project_access(record.project_id, user_id, session)
    return RebarImportResponse.model_validate(record)


@router.delete("/imports/{import_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_DELETE])
async def delete_import(import_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    """Delete an import and every shape that came in with it."""
    service = _service(session)
    try:
        record = await service.get_import(import_id)
    except RebarScheduleError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await verify_project_access(record.project_id, user_id, session)
    await service.delete_import(import_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Shapes ────────────────────────────────────────────────────────────────


@router.get("/imports/{import_id}/shapes", response_model=RebarShapeListResponse, dependencies=[_READ])
async def list_shapes(
    import_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    super_group: str | None = Query(default=None, max_length=4),
) -> RebarShapeListResponse:
    """List one import's bending shapes, in the order the file held them."""
    service = _service(session)
    try:
        record = await service.get_import(import_id)
    except RebarScheduleError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await verify_project_access(record.project_id, user_id, session)
    rows, total = await service.list_shapes(import_id, offset=offset, limit=limit, super_group=super_group)
    return RebarShapeListResponse(
        items=[RebarShapeResponse.model_validate(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/imports/{import_id}/cutting", response_model=list[CuttingItem], dependencies=[_READ])
async def cutting_summary(
    import_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> list[CuttingItem]:
    """Bars and steel weight per bar diameter, for ordering and cutting."""
    service = _service(session)
    try:
        record = await service.get_import(import_id)
    except RebarScheduleError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await verify_project_access(record.project_id, user_id, session)
    return await service.cutting_summary(import_id)


@router.get("/imports/{import_id}/export", dependencies=[_READ])
async def export_schedule(
    import_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    super_group: str | None = Query(default=None, max_length=4),
) -> Response:
    """Write an import's shapes back out as an ABS file.

    Without ``super_group`` the bytes are exactly the bytes that came in: each
    shape is written from the line it was parsed from, because the checksum
    covers those characters and a bending shop cannot tell a re-render from an
    edit.
    """
    service = _service(session)
    try:
        record = await service.get_import(import_id)
    except RebarScheduleError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await verify_project_access(record.project_id, user_id, session)
    payload = await service.export(import_id, super_group=super_group)
    name = record.filename if record.filename.lower().endswith(".abs") else f"{record.filename}.abs"
    return Response(
        content=payload,
        media_type="text/plain; charset=us-ascii",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
