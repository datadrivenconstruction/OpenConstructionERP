"""Spec book to register routes: start an import, review proposals, confirm.

POST /spec-imports/                      - start parsing a Document (background job)
GET  /spec-imports/{id}/                 - status and progress
GET  /spec-imports/{id}/proposals/       - proposals, grouped by section on the client
POST /spec-imports/{id}/confirm/         - create draft submittals for the ticked ones
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.submittals.models import SpecImport
from app.modules.submittals.spec_service import SpecImportService

spec_router = APIRouter(prefix="/spec-imports")


class SpecImportCreate(BaseModel):
    project_id: uuid.UUID
    document_id: uuid.UUID
    # Run OCR when the book has no text layer (slower, needs the optional engine).
    use_ocr: bool = False


class SpecImportConfirm(BaseModel):
    accept_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5000)
    reject_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5000)
    edits: dict[str, dict[str, Any]] = Field(default_factory=dict)


def _status(row: SpecImport) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "document_id": str(row.document_id),
        "status": row.status,
        "section_count": row.section_count,
        "pages_total": row.pages_total,
        "pages_done": row.pages_done,
        "error_code": row.error_code,
    }


async def _run(import_id: uuid.UUID, use_ocr: bool) -> None:
    from app.database import async_session_factory  # noqa: PLC0415

    async with async_session_factory() as session:
        await SpecImportService(session).run(import_id, use_ocr)


@spec_router.post("/", status_code=201, dependencies=[Depends(RequirePermission("submittals.import"))])
async def start_spec_import(
    data: SpecImportCreate,
    background_tasks: BackgroundTasks,
    session: SessionDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    """Start reading a specification book. Poll the import; nothing reaches the register yet."""
    await verify_project_access(data.project_id, user_id, session)
    row = await SpecImportService(session).create(data.project_id, data.document_id, user_id)
    await session.commit()
    background_tasks.add_task(_run, row.id, data.use_ocr)
    return _status(row)


@spec_router.get("/{import_id}/", dependencies=[Depends(RequirePermission("submittals.read"))])
async def get_spec_import(import_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    row = await SpecImportService(session).get(import_id)
    await verify_project_access(row.project_id, user_id, session)
    return _status(row)


@spec_router.get("/{import_id}/proposals/", dependencies=[Depends(RequirePermission("submittals.read"))])
async def spec_import_proposals(
    import_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    include_hidden: bool = Query(default=False),
) -> dict[str, Any]:
    svc = SpecImportService(session)
    row = await svc.get(import_id)
    await verify_project_access(row.project_id, user_id, session)
    return await svc.proposals(import_id, include_hidden=include_hidden)


@spec_router.post("/{import_id}/confirm/", dependencies=[Depends(RequirePermission("submittals.import"))])
async def confirm_spec_import(
    import_id: uuid.UUID,
    data: SpecImportConfirm,
    session: SessionDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    svc = SpecImportService(session)
    row = await svc.get(import_id)
    await verify_project_access(row.project_id, user_id, session)
    return await svc.confirm(import_id, data.accept_ids, data.edits, data.reject_ids, user_id)
