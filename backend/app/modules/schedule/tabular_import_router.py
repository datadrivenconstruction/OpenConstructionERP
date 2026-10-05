# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Endpoints of the spreadsheet (Excel / CSV) schedule import.

Mounted into the schedule module's main router, so these share the
``/api/v1/schedule`` prefix, next to the XER and MSP XML imports:

* ``POST /schedule/import/spreadsheet/preview/``  - read the file, report the
  mapping, the issues and the parsed schedule; writes nothing;
* ``POST /schedule/import/spreadsheet/commit/``   - re-read the same file (its
  SHA-256 must match the preview) and create a schedule or replace a draft;
* ``GET  /schedule/import/spreadsheet/template/`` - an empty template with the
  headers in one of the importer's languages, as .xlsx or .csv.

Client visibility is a decision, not a column: the preview returns the rows
the sheet marks for the client in ``client_visible_suggested``, and the commit
makes visible exactly the refs sent back in ``client_visible_refs``. A sheet
"yes" that nobody confirmed stays hidden.

Uploads are spooled to disk in chunks and capped at
:data:`~app.modules.schedule.tabular_import.MAX_FILE_BYTES`; parsing runs in a
worker thread.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.core.content_disposition import attachment_disposition
from app.core.upload_streaming import stream_upload_to_temp
from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.schedule.tabular_import import MAX_FILE_BYTES, DateOrder
from app.modules.schedule.tabular_import_service import (
    ScheduleTabularImportService,
    render_template,
    template_language,
)

tabular_import_router = APIRouter(tags=["schedule"])


class TabularPreviewResponse(BaseModel):
    """What the importer read from the file; nothing was written."""

    sha256: str
    filename: str
    file_format: str | None = None
    encoding: str | None = None
    delimiter: str | None = None
    sheet: str | None = None
    header_row: int | None = None
    columns: list[dict[str, Any]] = Field(default_factory=list)
    mapping: dict[str, int] = Field(default_factory=dict)
    date_order: str | None = None
    date_order_source: str | None = None
    outline_source: str | None = None
    row_count: int = 0
    activity_count: int = 0
    relationship_count: int = 0
    has_errors: bool = False
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[dict[str, Any]] = Field(default_factory=list)
    client_visible_suggested: list[str] = Field(
        default_factory=list,
        description=(
            "Refs of the activities the sheet marks as visible to the client. A suggestion only: "
            "every activity in `document` is hidden until the commit lists it in `client_visible_refs`"
        ),
    )
    document: dict[str, Any] | None = None
    duplicate_of: list[uuid.UUID] = Field(
        default_factory=list,
        description="Schedules of the project already imported from these exact bytes",
    )


class TabularCommitResponse(BaseModel):
    """The schedule the import wrote and what CPM and validation found on it."""

    schedule_id: uuid.UUID
    schedule_name: str
    replaced: bool
    activity_count: int
    relationship_count: int
    critical_count: int
    project_duration_days: int
    validation: dict[str, Any]
    warnings: list[dict[str, Any]] = Field(default_factory=list)


def _service(session: SessionDep) -> ScheduleTabularImportService:
    return ScheduleTabularImportService(session)


def _column_mapping(raw: str | None) -> dict[str, Any] | None:
    """The ``column_mapping`` form field: a JSON object of column index to field ("" unmaps)."""
    if raw is None or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "column_mapping_invalid", "message": "column_mapping is not valid JSON"},
        ) from exc
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "column_mapping_invalid", "message": "column_mapping must be an object"},
        )
    # Entry by entry checks (unknown field, index outside the header, two
    # columns on one field) are the parser's, reported as issues.
    return data


def _client_visible_refs(raw: str | None) -> list[str]:
    """The ``client_visible_refs`` form field: a JSON list of activity refs the person confirmed."""
    if raw is None or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "client_visible_refs_invalid", "message": "client_visible_refs is not valid JSON"},
        ) from exc
    if not isinstance(data, list) or not all(isinstance(ref, (str, int)) and not isinstance(ref, bool) for ref in data):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "client_visible_refs_invalid", "message": "client_visible_refs must be a list of refs"},
        )
    return [str(ref) for ref in data]


async def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    try:
        async with stream_upload_to_temp(file, max_bytes=MAX_FILE_BYTES) as upload:
            data = await asyncio.to_thread(upload.path.read_bytes)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "file_too_large",
                "message": f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB",
                "limit_mb": MAX_FILE_BYTES // (1024 * 1024),
            },
        ) from exc
    return data, file.filename or "schedule"


@tabular_import_router.post(
    "/schedule/import/spreadsheet/preview/",
    response_model=TabularPreviewResponse,
    summary="Preview a schedule spreadsheet (Excel or CSV) before importing it",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def preview_spreadsheet(
    _user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    column_mapping: str | None = Form(default=None),
    date_order: DateOrder | None = Form(default=None),
) -> TabularPreviewResponse:
    """Read the file against the project's working week and report what an
    import would create: column mapping with confidences, issues by sheet row,
    the parsed activities and links. Nothing is written."""
    data, filename = await _read_upload(file)
    result, duplicates = await _service(session).preview(
        project_id,
        _user_id,
        data,
        filename,
        column_mapping=_column_mapping(column_mapping),
        date_order=date_order,
    )
    return TabularPreviewResponse(**result.to_dict(), duplicate_of=duplicates)


@tabular_import_router.post(
    "/schedule/import/spreadsheet/commit/",
    response_model=TabularCommitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import a previewed schedule spreadsheet",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def commit_spreadsheet(
    _user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    expected_sha256: str = Form(..., min_length=64, max_length=64),
    target: Literal["new", "replace"] = Form(default="new"),
    schedule_id: uuid.UUID | None = Form(default=None),
    name: str | None = Form(default=None, max_length=255),
    column_mapping: str | None = Form(default=None),
    date_order: DateOrder | None = Form(default=None),
    allow_duplicate: bool = Form(default=False),
    client_visible_refs: str | None = Form(
        default=None,
        description=(
            "JSON list of activity refs the person confirmed as visible to the client. Only these "
            "become visible; the sheet's own column is a suggestion returned by the preview. "
            "Omitted or empty, every imported activity stays hidden"
        ),
    ),
) -> TabularCommitResponse:
    """Create a schedule from the file, or replace the contents of a draft
    schedule that has no baseline, progress or work orders. Runs CPM and the
    schedule quality checks afterwards; their findings name sheet rows.

    Client visibility comes from ``client_visible_refs`` alone, never from the
    sheet; a ref that names no activity of the file is refused with 422
    ``client_visible_unknown_ref``."""
    data, filename = await _read_upload(file)
    result = await _service(session).commit(
        project_id,
        _user_id,
        data,
        filename,
        expected_sha256=expected_sha256,
        target=target,
        schedule_id=schedule_id,
        name=name,
        column_mapping=_column_mapping(column_mapping),
        date_order=date_order,
        allow_duplicate=allow_duplicate,
        client_visible_refs=_client_visible_refs(client_visible_refs),
    )
    return TabularCommitResponse(
        schedule_id=result.schedule_id,
        schedule_name=result.schedule_name,
        replaced=result.replaced,
        activity_count=result.activity_count,
        relationship_count=result.relationship_count,
        critical_count=result.critical_count,
        project_duration_days=result.project_duration,
        validation=result.validation,
        warnings=result.warnings,
    )


@tabular_import_router.get(
    "/schedule/import/spreadsheet/template/",
    summary="Download the schedule spreadsheet import template",
    response_class=Response,
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def download_spreadsheet_template(
    _user_id: CurrentUserId,
    lang: str = Query(default="en", max_length=16),
    format: Literal["xlsx", "csv"] = Query(default="xlsx"),  # noqa: A002 - public query parameter name
) -> Response:
    """An empty template with the column headers in ``lang`` and four sample
    rows showing ids, outline, durations and the predecessor syntax."""
    language = template_language(lang)
    content, media_type, filename = await asyncio.to_thread(render_template, language, format)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": attachment_disposition(filename)},
    )
