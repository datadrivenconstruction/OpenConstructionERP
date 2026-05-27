# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File search API routes.

Endpoints (mounted under ``/api/v1/file-search/`` by the module loader):

    POST   /index/                       Index a single file by id/kind.
    GET    /?project_id=&q=              Search the index (content/filename).
    POST   /reindex/?project_id=         Re-OCR every file in a project.
    DELETE /{file_id}/?kind=             Remove a file from the index.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.file_search.schemas import (
    IndexFileRequest,
    IndexFileResponse,
    ReindexResponse,
    SearchResponse,
)
from app.modules.file_search.service import (
    delete_index_for_file,
    index_file,
    reindex_project,
    search_content,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/index/",
    response_model=IndexFileResponse,
    status_code=status.HTTP_200_OK,
)
async def index_single_file(
    body: IndexFileRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("file_search.index")),
) -> IndexFileResponse:
    """Trigger indexing for one file.

    Caller passes the canonical (kind, file_id, project_id). We resolve
    the on-disk path internally — clients never need to know storage
    layout.
    """
    await verify_project_access(body.project_id, user_id, session)

    row = await index_file(session, body.project_id, body.file_kind, body.file_id)
    return IndexFileResponse(
        file_kind=row.file_kind,
        file_id=row.file_id,
        indexed=True,
        ocr_engine=row.ocr_engine or "none",
        page_count=row.page_count,
        chars_extracted=len(row.content_text or ""),
    )


@router.get(
    "/",
    response_model=SearchResponse,
)
async def search_files(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    q: str = Query("", min_length=0, max_length=512),
    kind: str | None = Query(None),
    mode: Literal["content", "filename"] = Query("content"),
    limit: int = Query(50, ge=1, le=200),
    _: None = Depends(RequirePermission("file_search.read")),
) -> SearchResponse:
    """Run a content or filename search.

    Returns an empty result list (not 400) when ``q`` is empty so the
    debounced UI doesn't have to special-case the initial keystroke.
    """
    await verify_project_access(project_id, user_id, session)

    if not q.strip():
        return SearchResponse(project_id=project_id, q=q, mode=mode, total=0, hits=[])

    hits = await search_content(
        session,
        project_id,
        q,
        kind=kind,
        mode=mode,
        limit=limit,
    )
    return SearchResponse(
        project_id=project_id,
        q=q,
        mode=mode,
        total=len(hits),
        hits=hits,
    )


@router.post(
    "/reindex/",
    response_model=ReindexResponse,
)
async def reindex_all(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    _: None = Depends(RequirePermission("file_search.index")),
) -> ReindexResponse:
    """Re-OCR every file in the project."""
    await verify_project_access(project_id, user_id, session)

    started = datetime.now(UTC)
    indexed, skipped, errors = await reindex_project(session, project_id)
    return ReindexResponse(
        project_id=project_id,
        started_at=started,
        queued=indexed + skipped + errors,
        indexed=indexed,
        skipped=skipped,
        errors=errors,
    )


@router.delete(
    "/{file_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_index(
    file_id: str,
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    kind: str | None = Query(None),
    _: None = Depends(RequirePermission("file_search.index")),
) -> None:
    """Remove a file from the index.

    Idempotent: removing a file that isn't indexed returns 204 with no
    body and ``rowcount = 0`` — callers don't need to check existence
    first.
    """
    await verify_project_access(project_id, user_id, session)
    deleted = await delete_index_for_file(session, project_id, file_id, kind)
    if deleted == 0:
        # Still 204 — the desired post-condition (no rows) holds.
        logger.debug(
            "remove_index: no rows for project=%s file=%s kind=%s",
            project_id,
            file_id,
            kind,
        )
    return
