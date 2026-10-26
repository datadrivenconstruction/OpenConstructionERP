# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Progress sheet API: export, preview, apply.

Mounted into the schedule router under ``/api/v1/schedule``:

* ``GET  /schedules/{id}/progress-sheet``          - the XLSX for site staff
* ``POST /schedules/{id}/progress-sheet/preview``  - per-activity diff and validation
* ``POST /schedules/{id}/progress-sheet/apply``    - apply the confirmed rows

The preview writes nothing. Apply takes the digest the preview returned and
refuses a different file, so only what the user saw is applied.
"""

from __future__ import annotations

import io
import json
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from app.core.content_disposition import attachment_disposition
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.schedule.progress_sheet_schemas import SheetApplyResponse, SheetPreviewResponse
from app.modules.schedule.progress_sheet_service import ProgressSheetService, SheetFilters
from app.modules.schedule.tabular_import_router import _read_upload

progress_sheet_router = APIRouter(tags=["schedule"])

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DATE = r"^\d{4}-\d{2}-\d{2}$"


async def _verify(service: ProgressSheetService, session: SessionDep, schedule_id: uuid.UUID, user_id: str) -> None:
    schedule = await service.base.get_schedule(schedule_id)
    await verify_project_access(schedule.project_id, user_id, session)


@progress_sheet_router.get(
    "/schedules/{schedule_id}/progress-sheet",
    summary="Download the progress sheet for offline progress capture",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def export_progress_sheet(
    schedule_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    wbs: str | None = Query(default=None, max_length=50, description="WBS code prefix"),
    assignee_id: uuid.UUID | None = Query(default=None, description="Responsible person"),
    date_from: str | None = Query(default=None, pattern=_DATE),
    date_to: str | None = Query(default=None, pattern=_DATE),
    include_completed: bool = Query(default=False),
    locale: str | None = Query(default=None, max_length=10, description="Language of the headers"),
) -> StreamingResponse:
    """One row per activity in scope; identity columns locked, editable columns validated."""
    service = ProgressSheetService(session)
    await _verify(service, session, schedule_id, user_id)
    data, filename, rows = await service.export(
        schedule_id,
        SheetFilters(
            wbs_prefix=wbs or None,
            assignee_id=assignee_id,
            date_from=date_from,
            date_to=date_to,
            include_completed=include_completed,
        ),
        locale=locale,
        user_id=user_id,
    )
    return StreamingResponse(
        io.BytesIO(data),
        media_type=_XLSX,
        headers={"Content-Disposition": attachment_disposition(filename), "X-Row-Count": str(rows)},
    )


@progress_sheet_router.post(
    "/schedules/{schedule_id}/progress-sheet/preview",
    response_model=SheetPreviewResponse,
    summary="Read a filled progress sheet and show what it would change",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def preview_progress_sheet(
    schedule_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    status_date: str | None = Form(default=None, pattern=_DATE),
    locale: str | None = Form(default=None, max_length=10),
) -> SheetPreviewResponse:
    service = ProgressSheetService(session)
    await _verify(service, session, schedule_id, user_id)
    data, filename = await _read_upload(file)
    result = await service.preview(schedule_id, data, filename, status_date=status_date, locale=locale)
    return SheetPreviewResponse(**result)


def _row_numbers(raw: str) -> list[int]:
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "row_numbers_invalid", "message": "row_numbers must be a JSON list of integers"},
        ) from exc
    if not isinstance(value, list) or not all(isinstance(v, int) and not isinstance(v, bool) for v in value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "row_numbers_invalid", "message": "row_numbers must be a JSON list of integers"},
        )
    return value


@progress_sheet_router.post(
    "/schedules/{schedule_id}/progress-sheet/apply",
    response_model=SheetApplyResponse,
    summary="Apply the confirmed rows of a previewed progress sheet",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def apply_progress_sheet(
    schedule_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    expected_sha256: str = Form(..., min_length=64, max_length=64),
    status_date: str = Form(..., pattern=_DATE),
    row_numbers: str = Form(..., description="JSON list of the sheet row numbers to apply"),
    locale: str | None = Form(default=None, max_length=10),
) -> SheetApplyResponse:
    """Record an approved progress update per row, set progress at the status date, advance the data date."""
    service = ProgressSheetService(session)
    await _verify(service, session, schedule_id, user_id)
    data, filename = await _read_upload(file)
    result = await service.apply(
        schedule_id,
        data,
        filename,
        expected_sha256=expected_sha256,
        status_date=status_date,
        row_numbers=_row_numbers(row_numbers),
        user_id=user_id,
        locale=locale,
    )
    return SheetApplyResponse(**result)
