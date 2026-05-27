# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File References API routes.

Mounted by the module loader at ``/api/v1/file-references/``.

ISO 19650 surface
-----------------
    POST /validate-name/                    Validate a single filename.
    POST /scan-project/?project_id=         Sweep a whole project.
    GET  /violations/?project_id=           Paginated violation list.
    POST /violations/{id}/acknowledge/      Mark one violation read.

Cross-entity references surface
-------------------------------
    GET    /?kind=&file_id=                 References on a file.
    GET    /by-target/?target_type=&target_id=
                                            Files referencing an entity.
    POST   /                                Create a link (idempotent).
    DELETE /{id}/                           Delete a link.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.file_references.schemas import (
    ALLOWED_FILE_KINDS,
    ALLOWED_TARGET_TYPES,
    FileReferenceCreate,
    FileReferenceListResponse,
    FileReferenceResponse,
    Iso19650Result,
    Iso19650ValidateRequest,
    NamingViolationListResponse,
    NamingViolationResponse,
    ProjectScanResponse,
)
from app.modules.file_references.service import (
    acknowledge_violation,
    create_reference,
    delete_reference,
    list_files_for_target,
    list_references_for_file,
    list_violations,
    scan_project,
    validate_iso19650_name,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _coerce_user_uuid(user_id: str) -> uuid.UUID | None:
    """Coerce the JWT subject. Returns ``None`` for non-UUID subjects
    so service-account-driven scans don't crash on attribution."""
    try:
        return uuid.UUID(user_id)
    except (ValueError, TypeError):
        return None


def _validate_kind(kind: str) -> None:
    if kind not in ALLOWED_FILE_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown file_kind: {kind!r}",
        )


def _validate_target_type(t: str) -> None:
    if t not in ALLOWED_TARGET_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown target_type: {t!r}",
        )


# ── ISO 19650 ──────────────────────────────────────────────────────────


@router.post(
    "/validate-name/",
    response_model=Iso19650Result,
)
async def validate_name(
    payload: Iso19650ValidateRequest,
    _: None = Depends(RequirePermission("file_references.read")),
) -> Iso19650Result:
    """Validate a single filename. Stateless — no project access check."""
    if payload.rule_set != "iso19650":
        # Future rule sets land here. The validator currently only
        # implements ISO 19650; "none" trivially passes.
        return Iso19650Result(
            filename=payload.filename,
            rule_set=payload.rule_set,
            is_valid=True,
            violation_codes=[],
            parts=validate_iso19650_name(payload.filename).parts,
        )
    return validate_iso19650_name(payload.filename)


@router.post(
    "/scan-project/",
    response_model=ProjectScanResponse,
)
async def scan_project_route(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: Annotated[uuid.UUID, Query(...)],
    rule_set: Annotated[str, Query(pattern=r"^(iso19650|none)$")] = "iso19650",
    _: None = Depends(RequirePermission("file_references.write")),
) -> ProjectScanResponse:
    """Sweep every file in the project and upsert violation rows."""
    await verify_project_access(project_id, user_id, session)
    return await scan_project(session, project_id, rule_set=rule_set)


@router.get(
    "/violations/",
    response_model=NamingViolationListResponse,
)
async def list_violations_route(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: Annotated[uuid.UUID, Query(...)],
    include_acknowledged: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    _: None = Depends(RequirePermission("file_references.read")),
) -> NamingViolationListResponse:
    """Paginated list of un-acknowledged naming violations."""
    await verify_project_access(project_id, user_id, session)
    items, total = await list_violations(
        session,
        project_id,
        include_acknowledged=include_acknowledged,
        limit=limit,
        offset=offset,
    )
    return NamingViolationListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/violations/{violation_id}/acknowledge/",
    response_model=NamingViolationResponse,
)
async def acknowledge_violation_route(
    violation_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("file_references.write")),
) -> NamingViolationResponse:
    """Mark a violation as acknowledged so it disappears from the banner."""
    actor = _coerce_user_uuid(user_id)
    result = await acknowledge_violation(session, violation_id, actor)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Violation not found")
    # IDOR guard — verify project access against the row we just loaded.
    await verify_project_access(result.project_id, user_id, session)
    return result


# ── Cross-entity references ──────────────────────────────────────────


@router.get(
    "/",
    response_model=FileReferenceListResponse,
)
async def list_for_file_route(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: Annotated[uuid.UUID, Query(...)],
    kind: Annotated[str, Query(...)],
    file_id: Annotated[str, Query(..., min_length=1, max_length=255)],
    _: None = Depends(RequirePermission("file_references.read")),
) -> FileReferenceListResponse:
    """Entities that reference a single file (the "Referenced in N" chip)."""
    _validate_kind(kind)
    await verify_project_access(project_id, user_id, session)
    items, total = await list_references_for_file(session, file_kind=kind, file_id=file_id)
    return FileReferenceListResponse(items=items, total=total)


@router.get(
    "/by-target/",
    response_model=FileReferenceListResponse,
)
async def list_for_target_route(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: Annotated[uuid.UUID, Query(...)],
    target_type: Annotated[str, Query(...)],
    target_id: Annotated[str, Query(..., min_length=1, max_length=255)],
    _: None = Depends(RequirePermission("file_references.read")),
) -> FileReferenceListResponse:
    """Files that reference a given entity (e.g. files attached to an RFI)."""
    _validate_target_type(target_type)
    await verify_project_access(project_id, user_id, session)
    items, total = await list_files_for_target(session, target_type=target_type, target_id=target_id)
    return FileReferenceListResponse(items=items, total=total)


@router.post(
    "/",
    response_model=FileReferenceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_reference_route(
    payload: FileReferenceCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("file_references.write")),
) -> FileReferenceResponse:
    """Link a file to an entity (idempotent: re-linking returns the row)."""
    await verify_project_access(payload.project_id, user_id, session)
    actor = _coerce_user_uuid(user_id)
    try:
        return await create_reference(session, payload, actor)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.delete(
    "/{reference_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_reference_route(
    reference_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: Annotated[uuid.UUID, Query(...)],
    _: None = Depends(RequirePermission("file_references.write")),
) -> None:
    """Drop a single reference link."""
    await verify_project_access(project_id, user_id, session)
    ok = await delete_reference(session, reference_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reference not found")
    return
