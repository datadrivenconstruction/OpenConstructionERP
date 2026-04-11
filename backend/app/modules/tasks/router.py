"""Tasks API routes.

Endpoints:
    GET    /                    - List tasks for a project
    POST   /                    - Create task
    GET    /my-tasks             - List tasks for the current user
    GET    /export               - Export tasks as Excel file
    GET    /template             - Download import template Excel file
    POST   /import/file          - Import tasks from Excel/CSV file
    GET    /{task_id}            - Get single task
    PATCH  /{task_id}            - Update task
    DELETE /{task_id}            - Delete task
    POST   /{task_id}/complete   - Mark task as completed
    PATCH  /{task_id}/bim-links  - Replace linked BIM element ids
"""

from __future__ import annotations

import csv
import io
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from app.core.bulk_ops import BulkAssignRequest, BulkDeleteRequest, BulkStatusRequest
from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.tasks.schemas import (
    TaskBimLinkRequest,
    TaskCompleteRequest,
    TaskCreate,
    TaskResponse,
    TaskStatsResponse,
    TaskUpdate,
)
from app.modules.tasks.service import TaskService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> TaskService:
    return TaskService(session)


def _compute_checklist_progress(checklist: list | None) -> float:
    """Return completion percentage (0.0 - 100.0) for a checklist."""
    if not checklist:
        return 0.0
    total = len(checklist)
    done = sum(1 for c in checklist if isinstance(c, dict) and c.get("completed"))
    return round(done / total * 100, 1) if total > 0 else 0.0


def _compute_is_overdue(item: object) -> bool:
    """Determine if a task is overdue based on due_date and status."""
    status = getattr(item, "status", "")
    if status == "completed":
        return False
    due_date = getattr(item, "due_date", None)
    if not due_date:
        return False
    try:
        today_str = datetime.now(UTC).strftime("%Y-%m-%d")
        return str(due_date) < today_str
    except (ValueError, TypeError):
        return False


def _to_response(item: object) -> TaskResponse:
    checklist = item.checklist or []  # type: ignore[attr-defined]
    return TaskResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        task_type=item.task_type,  # type: ignore[attr-defined]
        title=item.title,  # type: ignore[attr-defined]
        description=item.description,  # type: ignore[attr-defined]
        checklist=checklist,
        checklist_progress=_compute_checklist_progress(checklist),
        responsible_id=str(item.responsible_id) if item.responsible_id else None,  # type: ignore[attr-defined]
        persons_involved=item.persons_involved or [],  # type: ignore[attr-defined]
        due_date=item.due_date,  # type: ignore[attr-defined]
        milestone_id=item.milestone_id,  # type: ignore[attr-defined]
        meeting_id=item.meeting_id,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        priority=item.priority,  # type: ignore[attr-defined]
        result=item.result,  # type: ignore[attr-defined]
        is_private=item.is_private,  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        bim_element_ids=[
            str(x) for x in (getattr(item, "bim_element_ids", None) or [])
        ],
        metadata=getattr(item, "metadata_", {}),
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
        is_overdue=_compute_is_overdue(item),
    )


@router.get("/", response_model=list[TaskResponse])
async def list_tasks(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    type_filter: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    priority: str | None = Query(default=None),
    responsible_id: str | None = Query(default=None),
    meeting_id: str | None = Query(default=None),
    bim_element_id: str | None = Query(
        default=None,
        description=(
            "Filter tasks to those whose bim_element_ids JSON array contains "
            "this element id (used by the BIM viewer to show linked defects)."
        ),
    ),
    search: str | None = Query(
        default=None,
        max_length=200,
        description="Free-text search across title, description, and result fields.",
    ),
    service: TaskService = Depends(_get_service),
) -> list[TaskResponse]:
    """List tasks for a project with optional filters.

    Private tasks are only visible to their creator. When ``bim_element_id``
    is supplied, the result is filtered to tasks whose ``bim_element_ids``
    list includes that element id. All other filters still apply on top.
    """
    if bim_element_id:
        # JSON-contains filter — delegated to the service for dialect handling.
        tasks_with_bim = await service.get_tasks_for_bim_element(
            bim_element_id,
            project_id=project_id,
            current_user_id=user_id,
        )
        # Apply the remaining lightweight filters in memory. The element
        # filter is typically very selective (O(handful)) so this is fine.
        if type_filter is not None:
            tasks_with_bim = [t for t in tasks_with_bim if t.task_type == type_filter]
        if status_filter is not None:
            tasks_with_bim = [t for t in tasks_with_bim if t.status == status_filter]
        if priority is not None:
            tasks_with_bim = [t for t in tasks_with_bim if t.priority == priority]
        if responsible_id is not None:
            tasks_with_bim = [
                t
                for t in tasks_with_bim
                if str(t.responsible_id or "") == responsible_id
            ]
        if meeting_id is not None:
            tasks_with_bim = [t for t in tasks_with_bim if t.meeting_id == meeting_id]
        if search and search.strip():
            needle = search.strip().lower()
            tasks_with_bim = [
                t
                for t in tasks_with_bim
                if needle in (t.title or "").lower()
                or needle in (t.description or "").lower()
                or needle in (t.result or "").lower()
            ]
        return [_to_response(t) for t in tasks_with_bim[offset : offset + limit]]

    tasks, _ = await service.list_tasks(
        project_id,
        current_user_id=user_id,
        offset=offset,
        limit=limit,
        task_type=type_filter,
        status_filter=status_filter,
        priority=priority,
        responsible_id=responsible_id,
        meeting_id=meeting_id,
        search=search,
    )
    return [_to_response(t) for t in tasks]


@router.get("/my-tasks/", response_model=list[TaskResponse])
async def my_tasks(
    user_id: CurrentUserId,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    service: TaskService = Depends(_get_service),
) -> list[TaskResponse]:
    """List tasks assigned to the current user across all projects."""
    tasks, _ = await service.list_my_tasks(
        user_id,
        offset=offset,
        limit=limit,
        status_filter=status_filter,
    )
    return [_to_response(t) for t in tasks]


@router.post("/", response_model=TaskResponse, status_code=201)
async def create_task(
    data: TaskCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("tasks.create")),
    service: TaskService = Depends(_get_service),
) -> TaskResponse:
    """Create a new task."""
    task = await service.create_task(data, user_id=user_id)
    return _to_response(task)


@router.get("/stats/", response_model=TaskStatsResponse)
async def task_stats(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: TaskService = Depends(_get_service),
) -> TaskStatsResponse:
    """Return summary statistics for tasks in a project.

    Includes total, breakdown by status/type/priority, overdue count,
    and average checklist progress.
    """
    return await service.get_stats(project_id, current_user_id=user_id)


# ── Export tasks as Excel ────────────────────────────────────────────────────


@router.get("/export/")
async def export_tasks(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: TaskService = Depends(_get_service),
) -> StreamingResponse:
    """Export tasks for a project as Excel file."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    tasks, _ = await service.list_tasks(
        project_id, current_user_id=user_id, offset=0, limit=10000
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Tasks"

    headers = [
        "Title",
        "Type",
        "Status",
        "Priority",
        "Assignee",
        "Due Date",
        "Created",
        "Checklist Progress",
    ]
    for i, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=i, value=h)
        cell.font = Font(bold=True)

    for row_idx, task in enumerate(tasks, 2):
        ws.cell(row=row_idx, column=1, value=task.title)  # type: ignore[attr-defined]
        ws.cell(row=row_idx, column=2, value=task.task_type)  # type: ignore[attr-defined]
        ws.cell(row=row_idx, column=3, value=task.status)  # type: ignore[attr-defined]
        ws.cell(row=row_idx, column=4, value=task.priority)  # type: ignore[attr-defined]
        ws.cell(
            row=row_idx,
            column=5,
            value=str(task.responsible_id) if task.responsible_id else "",  # type: ignore[attr-defined]
        )
        ws.cell(row=row_idx, column=6, value=task.due_date)  # type: ignore[attr-defined]
        ws.cell(
            row=row_idx,
            column=7,
            value=str(task.created_at) if task.created_at else "",  # type: ignore[attr-defined]
        )
        # Checklist progress
        checklist = task.checklist or []  # type: ignore[attr-defined]
        total = len(checklist)
        done = sum(1 for c in checklist if isinstance(c, dict) and c.get("completed"))
        ws.cell(
            row=row_idx,
            column=8,
            value=f"{done}/{total}" if total > 0 else "",
        )

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="tasks_export.xlsx"'},
    )


# ── Import template ─────────────────────────────────────────────────────────


@router.get("/template/")
async def download_task_template() -> StreamingResponse:
    """Download an Excel template for task import."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Tasks"

    headers = ["Title", "Type", "Status", "Priority", "Due Date", "Description"]
    header_font = Font(bold=True)
    header_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")

    for i, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=i, value=h)
        cell.font = header_font
        cell.fill = header_fill

    # Example row
    ws.cell(row=2, column=1, value="Review structural drawings for Level 5")
    ws.cell(row=2, column=2, value="task")
    ws.cell(row=2, column=3, value="open")
    ws.cell(row=2, column=4, value="high")
    ws.cell(row=2, column=5, value="2026-06-15")
    ws.cell(row=2, column=6, value="Check all beam dimensions against the spec")

    # Add a note sheet with valid values
    notes = wb.create_sheet("Valid Values")
    notes.cell(row=1, column=1, value="Type values:").font = Font(bold=True)
    for i, v in enumerate(["task", "topic", "information", "decision", "personal"], 2):
        notes.cell(row=i, column=1, value=v)
    notes.cell(row=1, column=3, value="Status values:").font = Font(bold=True)
    for i, v in enumerate(["draft", "open", "in_progress", "completed"], 2):
        notes.cell(row=i, column=3, value=v)
    notes.cell(row=1, column=5, value="Priority values:").font = Font(bold=True)
    for i, v in enumerate(["low", "normal", "high", "urgent"], 2):
        notes.cell(row=i, column=5, value=v)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="tasks_import_template.xlsx"'},
    )


# ── Import tasks from file ──────────────────────────────────────────────────

_TASK_COLUMN_MAP: dict[str, str] = {
    "title": "title",
    "name": "title",
    "task name": "title",
    "task": "title",
    "titel": "title",
    "aufgabe": "title",
    "type": "task_type",
    "task type": "task_type",
    "typ": "task_type",
    "status": "status",
    "priority": "priority",
    "priorität": "priority",
    "due date": "due_date",
    "due": "due_date",
    "fällig": "due_date",
    "deadline": "due_date",
    "description": "description",
    "beschreibung": "description",
    "details": "description",
}

_VALID_TASK_TYPES = {"task", "topic", "information", "decision", "personal"}
_VALID_STATUSES = {"draft", "open", "in_progress", "completed"}
_VALID_PRIORITIES = {"low", "normal", "high", "urgent"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _match_task_column(header: str) -> str | None:
    """Match a header string to a canonical task column name."""
    return _TASK_COLUMN_MAP.get(header.strip().lower().replace("_", " "))


def _parse_task_rows_from_csv(content: bytes) -> list[dict[str, Any]]:
    """Parse CSV content into a list of row dicts."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    raw_headers = next(reader, None)
    if not raw_headers:
        raise ValueError("No headers found")

    column_map: dict[int, str] = {}
    for idx, hdr in enumerate(raw_headers):
        canonical = _match_task_column(hdr)
        if canonical:
            column_map[idx] = canonical

    rows: list[dict[str, Any]] = []
    for raw_row in reader:
        row: dict[str, Any] = {}
        for idx, val in enumerate(raw_row):
            canonical = column_map.get(idx)
            if canonical and val is not None and str(val).strip():
                row[canonical] = str(val).strip()
        if row:
            rows.append(row)
    return rows


def _parse_task_rows_from_excel(content: bytes) -> list[dict[str, Any]]:
    """Parse Excel (.xlsx) content into a list of row dicts."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        raise ValueError("No active sheet found")

    rows_iter = ws.iter_rows(values_only=True)
    raw_headers = next(rows_iter, None)
    if not raw_headers:
        wb.close()
        raise ValueError("No headers found")

    column_map: dict[int, str] = {}
    for idx, hdr in enumerate(raw_headers):
        if hdr is not None:
            canonical = _match_task_column(str(hdr))
            if canonical:
                column_map[idx] = canonical

    rows: list[dict[str, Any]] = []
    for raw_row in rows_iter:
        row: dict[str, Any] = {}
        for idx, val in enumerate(raw_row):
            canonical = column_map.get(idx)
            if canonical and val is not None and str(val).strip():
                row[canonical] = str(val).strip()
        if row:
            rows.append(row)

    wb.close()
    return rows


@router.post("/import/file/")
async def import_tasks_file(
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    file: UploadFile = File(..., description="Excel (.xlsx) or CSV (.csv) file"),
    _perm: None = Depends(RequirePermission("tasks.create")),
    service: TaskService = Depends(_get_service),
) -> dict[str, Any]:
    """Import tasks from an Excel or CSV file upload.

    Expected columns (flexible auto-detection):
    - **Title / Task Name** -- task title (required)
    - **Type / Task Type** -- task type (task, topic, information, decision, personal)
    - **Status** -- status (draft, open, in_progress, completed)
    - **Priority** -- priority (low, normal, high, urgent)
    - **Due Date / Deadline** -- due date in YYYY-MM-DD format
    - **Description / Details** -- task description

    Returns:
        Summary with counts of imported, skipped, and error details per row.
    """
    filename = (file.filename or "").lower()
    if not filename.endswith((".xlsx", ".csv", ".xls")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Please upload an Excel (.xlsx) or CSV (.csv) file.",
        )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large. Maximum size is 10 MB.",
        )

    try:
        if filename.endswith(".xlsx") or filename.endswith(".xls"):
            rows = _parse_task_rows_from_excel(content)
        else:
            rows = _parse_task_rows_from_csv(content)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse file: {exc}",
        )
    except Exception as exc:
        logger.exception("Unexpected error parsing task import file: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to parse file. Please check the format and try again.",
        )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No data rows found in file. Check that the first row contains column headers.",
        )

    imported_count = 0
    skipped = 0
    errors: list[dict[str, Any]] = []

    for row_idx, row in enumerate(rows, start=2):
        try:
            title = str(row.get("title", "")).strip()
            if not title:
                skipped += 1
                continue

            task_type = str(row.get("task_type", "task")).strip().lower()
            if task_type not in _VALID_TASK_TYPES:
                task_type = "task"

            task_status = str(row.get("status", "open")).strip().lower()
            if task_status not in _VALID_STATUSES:
                task_status = "open"

            priority = str(row.get("priority", "normal")).strip().lower()
            if priority not in _VALID_PRIORITIES:
                priority = "normal"

            due_date = str(row.get("due_date", "")).strip() or None
            if due_date and not _DATE_RE.match(due_date):
                errors.append({
                    "row": row_idx,
                    "error": f"Invalid date format: {due_date} (expected YYYY-MM-DD)",
                    "data": {k: str(v)[:100] for k, v in row.items()},
                })
                continue

            description = str(row.get("description", "")).strip() or None

            create_data = TaskCreate(
                project_id=project_id,
                task_type=task_type,
                title=title,
                description=description,
                status=task_status,
                priority=priority,
                due_date=due_date,
            )
            await service.create_task(create_data, user_id=user_id)
            imported_count += 1
        except Exception as exc:
            errors.append({
                "row": row_idx,
                "error": str(exc)[:200],
                "data": {k: str(v)[:100] for k, v in row.items()},
            })

    return {
        "imported": imported_count,
        "skipped": skipped,
        "errors": errors,
        "total_rows": len(rows),
    }


# ── Bulk operations (must come BEFORE parametric /{task_id}) ───────────


async def _filter_owned_task_ids(
    session: SessionDep,
    user_id: str,
    task_ids: list[uuid.UUID],
) -> list[uuid.UUID]:
    """Return the subset of task_ids that belong to projects owned by user_id."""
    from sqlalchemy import select as _select

    from app.modules.projects.repository import ProjectRepository
    from app.modules.tasks.models import Task

    proj_repo = ProjectRepository(session)
    owned_projects, _ = await proj_repo.list_for_user(
        owner_id=user_id, offset=0, limit=10000, exclude_archived=False
    )
    owned_project_ids = {str(p.id) for p in owned_projects}

    rows = (await session.execute(
        _select(Task.id, Task.project_id).where(Task.id.in_(task_ids))
    )).all()
    return [r[0] for r in rows if str(r[1]) in owned_project_ids]


@router.post(
    "/batch/delete/",
    status_code=200,
    dependencies=[Depends(RequirePermission("tasks.delete"))],
)
async def batch_delete_tasks(
    body: BulkDeleteRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> dict:
    """Delete multiple tasks in one request. Only project-owned tasks are deleted."""
    from app.core.bulk_ops import bulk_delete
    from app.modules.tasks.models import Task

    allowed = await _filter_owned_task_ids(session, user_id, body.ids)
    deleted = await bulk_delete(session, Task, allowed)
    logger.info(
        "Bulk delete tasks: requested=%d deleted=%d user=%s",
        len(body.ids), deleted, user_id,
    )
    return {"requested": len(body.ids), "deleted": deleted}


@router.patch(
    "/batch/status/",
    status_code=200,
    dependencies=[Depends(RequirePermission("tasks.update"))],
)
async def batch_update_task_status(
    body: BulkStatusRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> dict:
    """Bulk-update status on multiple tasks."""
    from app.core.bulk_ops import bulk_update_status
    from app.modules.tasks.models import Task

    allowed_statuses = {"draft", "open", "in_progress", "completed"}
    if body.status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Allowed: {sorted(allowed_statuses)}",
        )

    allowed_ids = await _filter_owned_task_ids(session, user_id, body.ids)
    updated = await bulk_update_status(
        session, Task, allowed_ids, body.status, allowed_statuses=allowed_statuses
    )
    logger.info(
        "Bulk update task status: requested=%d updated=%d new_status=%s user=%s",
        len(body.ids), updated, body.status, user_id,
    )
    return {"requested": len(body.ids), "updated": updated, "status": body.status}


@router.post(
    "/batch/assign/",
    status_code=200,
    dependencies=[Depends(RequirePermission("tasks.update"))],
)
async def batch_assign_tasks(
    body: BulkAssignRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> dict:
    """Bulk-assign multiple tasks to a single user."""
    from app.core.bulk_ops import bulk_update_fields
    from app.modules.tasks.models import Task

    allowed_ids = await _filter_owned_task_ids(session, user_id, body.ids)
    updated = await bulk_update_fields(
        session, Task, allowed_ids, {"responsible_id": body.assignee_id}
    )
    logger.info(
        "Bulk assign tasks: requested=%d updated=%d assignee=%s user=%s",
        len(body.ids), updated, body.assignee_id, user_id,
    )
    return {"requested": len(body.ids), "updated": updated, "assignee_id": body.assignee_id}


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: TaskService = Depends(_get_service),
) -> TaskResponse:
    """Get a single task. Private tasks are only visible to their creator."""
    task = await service.get_task(task_id, current_user_id=user_id)
    return _to_response(task)


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: uuid.UUID,
    data: TaskUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("tasks.update")),
    service: TaskService = Depends(_get_service),
) -> TaskResponse:
    """Update a task."""
    task = await service.update_task(task_id, data, current_user_id=user_id)
    return _to_response(task)


@router.delete("/{task_id}", status_code=204)
async def delete_task(
    task_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("tasks.delete")),
    service: TaskService = Depends(_get_service),
) -> None:
    """Delete a task."""
    await service.delete_task(task_id, current_user_id=user_id)


@router.post("/{task_id}/complete/", response_model=TaskResponse)
async def complete_task(
    task_id: uuid.UUID,
    body: TaskCompleteRequest | None = None,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("tasks.update")),
    service: TaskService = Depends(_get_service),
) -> TaskResponse:
    """Mark a task as completed with optional result text."""
    result = body.result if body else None
    task = await service.complete_task(task_id, result=result, current_user_id=user_id)
    return _to_response(task)


@router.patch("/{task_id}/bim-links", response_model=TaskResponse)
async def update_task_bim_links(
    task_id: uuid.UUID,
    body: TaskBimLinkRequest,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("tasks.update")),
    service: TaskService = Depends(_get_service),
) -> TaskResponse:
    """Replace the full set of BIM element ids linked to this task.

    Idempotent set semantics — the incoming ``bim_element_ids`` list
    fully overwrites the previously stored list. Sending an empty list
    clears all links.
    """
    task = await service.update_bim_links(
        task_id,
        body.bim_element_ids,
        current_user_id=user_id,
    )
    return _to_response(task)
