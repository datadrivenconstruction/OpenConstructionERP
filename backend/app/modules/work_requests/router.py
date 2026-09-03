# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Work Requests API (mounted at ``/api/v1/work-requests/``).

    GET    /departments?include_inactive=   - every department (seeded on first read)
    POST   /departments                     - add one (manage)
    PATCH  /departments/{key}               - edit one, whole arrays (manage)
    POST   /departments/{key}/request-types              - add a type (manage)
    PATCH  /departments/{key}/request-types/{type_key}   - edit / retire one (manage)
    DELETE /departments/{key}/request-types/{type_key}   - only if unused (manage)
    PUT    /departments/{key}/request-types/order        - {keys: [...]} (manage)
    GET    /requests?...                    - the register, newest first
    POST   /requests                        - raise one (reference minted here)
    GET    /requests/export?format=csv|xlsx - the same register as a file
    POST   /requests/bulk                   - one patch over many, per-item rails
    GET    /requests/{id}                   - one, by id OR by reference
    PATCH  /requests/{id}                   - edit / status / stage
    POST   /requests/{id}/stage             - move on the department board
    POST   /requests/{id}/checklist         - tick / untick one item
    POST   /requests/{id}/checklist/items       - add an item to THIS request
    PATCH  /requests/{id}/checklist/items/{key} - re-word / re-require one
    DELETE /requests/{id}/checklist/items/{key} - remove added / hide inherited
    PUT    /requests/{id}/checklist/order       - {keys: [...]}
    POST   /requests/{id}/checklist/reset       - back to the type's list
    POST   /requests/{id}/duplicate         - copy it into a new draft
    POST   /requests/{id}/assign            - who is on it
    POST   /requests/{id}/needs-info        - ball back to the requester
    POST   /requests/{id}/answer            - ball back to the department
    POST   /requests/{id}/handoff           - a child request in another department
    GET|POST /requests/{id}/hours, DELETE /requests/{id}/hours/{log_id}
    GET|POST /requests/{id}/comments
    POST   /requests/{id}/attachments, GET /requests/{id}/attachments/{filename}
    GET    /requests/{id}/activity
    GET    /planner?department=&from=&to=   - the headcount grid
    PUT    /planner/capacity?department=    - people available per day (manage)
    PUT    /planner/{request_id}            - people on a request per day
    GET    /summary?project_id=             - per-department header counts
    GET    /my-queue                        - what is mine
    POST   /deadline-sweep                  - due-tomorrow / overdue bells, once a day

Every request-level route checks project access the way every other
module does (``verify_project_access``: 404 for both missing and
forbidden), and the service refuses anyone who is neither the requester,
the department nor a manager.
"""

from __future__ import annotations

import io
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse

from app.core.storage import module_uploads_dir
from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    accessible_project_ids,
    verify_project_access,
)
from app.modules.work_requests import service
from app.modules.work_requests.models import WorkRequest
from app.modules.work_requests.permissions import register_work_requests_permissions
from app.modules.work_requests.schemas import (
    AnswerBody,
    AssignBody,
    BulkBody,
    ChecklistItemAdd,
    ChecklistItemPatch,
    ChecklistOrder,
    ChecklistTick,
    CommentBody,
    DepartmentCreate,
    DepartmentPatch,
    DuplicateBody,
    HandoffBody,
    HoursBody,
    NeedsInfoBody,
    PlannerAllocBody,
    RequestCreate,
    RequestPatch,
    RequestTypeCreate,
    RequestTypeOrder,
    RequestTypePatch,
    StageMove,
    WorkRequestListResponse,
)

logger = logging.getLogger(__name__)

# The module loader imports router/models/hooks/events - never
# permissions.py - and the registry fails closed on unknown permission
# names, so an unregistered module is silently admin-only. An explicit
# CALL cannot be "unused": no import-sort autofix will ever remove it.
register_work_requests_permissions()

router = APIRouter(tags=["work_requests"])

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
ATTACHMENTS_DIR = module_uploads_dir("work_requests", "attachments")
_INLINE = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".txt": "text/plain",
}


def _can_manage(payload: dict) -> bool:
    """Admin, or a role the live registry grants ``work_requests.manage``."""
    if not isinstance(payload, dict):
        return False
    if payload.get("role") == "admin":
        return True
    if "work_requests.manage" in (payload.get("permissions") or []):
        return True
    from app.core.permissions import permission_registry

    return permission_registry.role_has_permission(payload.get("role", ""), "work_requests.manage")


def _raise_for(exc: service.WorkRequestError) -> HTTPException:
    if isinstance(exc, service.NotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, service.NotPermitted):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, service.TransitionError):
        return HTTPException(status.HTTP_409_CONFLICT, {"error": str(exc), "allowed": exc.allowed})
    if isinstance(exc, service.ConflictError):
        return HTTPException(status.HTTP_409_CONFLICT, {"error": str(exc), "allowed": []})
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


async def _request_or_404(session, user_id: str, id_or_reference: str) -> WorkRequest:
    try:
        req = await service.request_or_error(session, id_or_reference)
    except service.NotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work request not found") from None
    await verify_project_access(req.project_id, user_id, session)
    return req


@router.get("/")
async def module_info() -> dict[str, str]:
    """Health-style ping so operators can confirm the module mounted."""
    return {"module": "oe_work_requests", "status": "active"}


def _page(rows: list[dict], limit: int, offset: int) -> WorkRequestListResponse:
    """Wrap rows the service returns whole. ``total`` is the full set, so a
    caller holding a window can tell that it is holding a window."""
    start = max(0, offset)
    return WorkRequestListResponse(
        items=rows[start : start + max(1, limit)], total=len(rows), limit=limit, offset=start
    )


# ── Departments ──────────────────────────────────────────────────────────


@router.get("/departments")
async def list_departments(
    session: SessionDep,
    user_id: CurrentUserId,
    include_inactive: bool = False,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _perm: None = Depends(RequirePermission("work_requests.read")),
) -> WorkRequestListResponse:
    """Every department. Request types come back in ``position`` order and
    RETIRED ones are left out - a raise form must only ever offer what is
    current. The manage screen asks for ``include_inactive=true``."""
    await service.ensure_seeded(session)
    await session.commit()  # persist first-run seeds
    return _page(
        [
            service.department_payload(d, include_inactive=include_inactive)
            for d in await service.list_departments(session)
        ],
        limit,
        offset,
    )


@router.post("/departments", status_code=status.HTTP_201_CREATED)
async def create_department(
    payload: DepartmentCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("work_requests.manage")),
) -> dict:
    await service.ensure_seeded(session)
    try:
        row = await service.create_department(session, payload.model_dump())
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return service.department_payload(row, include_inactive=True)


@router.patch("/departments/{key}")
async def update_department(
    key: str,
    payload: DepartmentPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("work_requests.manage")),
) -> dict:
    try:
        dept = await service.department_or_error(session, key)
        row = await service.update_department(session, dept, payload.model_dump(exclude_unset=True))
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return service.department_payload(row, include_inactive=True)


# ── The department's request-type catalogue (manage) ─────────────────────


async def _dept_or_404(session, key: str):
    try:
        return await service.department_or_error(session, key)
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None


@router.post("/departments/{key}/request-types", status_code=status.HTTP_201_CREATED)
async def create_request_type(
    key: str,
    payload: RequestTypeCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("work_requests.manage")),
) -> dict:
    """Add a type without waiting on a release. Omit ``key`` and it is
    slugged from the label (``"Safety PLC"`` → ``safety_plc``)."""
    dept = await _dept_or_404(session, key)
    try:
        spec = await service.create_request_type(session, dept, payload.model_dump(exclude_unset=True))
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return {"request_type": spec, "department": service.department_payload(dept, include_inactive=True)}


@router.patch("/departments/{key}/request-types/{type_key}")
async def update_request_type(
    key: str,
    type_key: str,
    payload: RequestTypePatch,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("work_requests.manage")),
) -> dict:
    """Edit or RETIRE one (``active: false``). The type's key never
    changes - the requests already raised against it carry it."""
    dept = await _dept_or_404(session, key)
    changes = payload.model_dump(exclude_unset=True)
    for key in ("fields", "checklist"):
        if changes.get(key) is not None:
            changes[key] = [dict(f) for f in changes[key]]
    try:
        spec = await service.update_request_type(session, dept, type_key, changes)
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return {"request_type": spec, "department": service.department_payload(dept, include_inactive=True)}


@router.delete("/departments/{key}/request-types/{type_key}")
async def delete_request_type(
    key: str,
    type_key: str,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("work_requests.manage")),
) -> dict:
    """Delete a type nothing has been raised against. One that IS in use
    is a 409 naming the count - retire it instead."""
    dept = await _dept_or_404(session, key)
    try:
        await service.delete_request_type(session, dept, type_key)
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return {"department": service.department_payload(dept, include_inactive=True)}


@router.put("/departments/{key}/request-types/order")
async def order_request_types(
    key: str,
    payload: RequestTypeOrder,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("work_requests.manage")),
) -> dict:
    """``{keys: [...]}`` - the order the raise form offers them in."""
    dept = await _dept_or_404(session, key)
    try:
        types = await service.reorder_request_types(session, dept, payload.keys)
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return {"request_types": types, "department": service.department_payload(dept, include_inactive=True)}


# ── Requests ─────────────────────────────────────────────────────────────


@router.get("/requests")
async def list_requests(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = None,
    department: str | None = Query(default=None, max_length=40),
    request_type: str | None = Query(default=None, max_length=60),
    request_types: str | None = Query(default=None, max_length=200),
    request_status: str | None = Query(default=None, alias="status", max_length=200),
    stage: str | None = Query(default=None, max_length=60),
    assignee_id: str | None = Query(default=None, max_length=36),
    raised_by: str | None = Query(default=None, max_length=36),
    q: str | None = Query(default=None, max_length=200),
    include_closed: bool = False,
    is_template: bool = False,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _perm: None = Depends(RequirePermission("work_requests.read")),
) -> WorkRequestListResponse:
    """The register. Without ``project_id`` it is scoped to the jobs the
    caller can see - never every job in the deployment.

    ``request_type=scada`` matches every request that asks for SCADA among
    its types, not only the ones where it is the first; ``request_types=``
    takes a comma-separated list and means ANY of them.

    ``is_template=true`` lists the templates INSTEAD of the register -
    a template is never a live request and never appears here otherwise.
    """
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
        allowed = None
    else:
        allowed = await accessible_project_ids(session, user_id)
    filters: dict[str, Any] = {
        "project_id": project_id,
        "department": department,
        "request_type": request_type,
        "request_types": request_types,
        "status": request_status,
        "stage": stage,
        "assignee_id": assignee_id,
        "raised_by": raised_by,
        "q": q,
        "include_closed": include_closed,
        "is_template": is_template,
    }
    try:
        rows = await service.list_requests(session, project_ids=allowed, limit=limit, offset=offset, **filters)
        # The same filters, without the window: what the caller is holding
        # part of. Counted after the page so a filter error is raised once.
        total = await service.count_requests(session, project_ids=allowed, **filters)
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    return WorkRequestListResponse(items=await service.payloads(session, rows), total=total, limit=limit, offset=offset)


@router.post("/requests", status_code=status.HTTP_201_CREATED)
async def create_request(
    payload: RequestCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("work_requests.create")),
) -> dict:
    await verify_project_access(payload.project_id, user_id, session)
    try:
        req = await service.create_request(
            session,
            project_id=payload.project_id,
            department=payload.department,
            request_type=payload.request_type,
            request_types=payload.request_types,
            title=payload.title,
            description=payload.description,
            cost_centres=payload.cost_centres,
            estimated_hours=payload.estimated_hours,
            quoted_hours=payload.quoted_hours,
            info_required_by=payload.info_required_by,
            due_date=payload.due_date,
            priority=payload.priority,
            links=[link.model_dump() for link in payload.links],
            fields=payload.fields,
            assignee_ids=payload.assignee_ids,
            responsible_user_id=payload.responsible_user_id,
            depends_on_ids=payload.depends_on_ids,
            parent_id=payload.parent_id,
            draft=payload.draft,
            user_id=str(user_id),
        )
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return await service.payload(session, req)


# ── Export and bulk ──────────────────────────────────────────────────────
# Registered BEFORE ``/requests/{request_id}``: a path parameter would
# otherwise swallow ``/requests/export`` and answer "not found".


@router.get("/requests/export")
async def export_requests(
    session: SessionDep,
    user_id: CurrentUserId,
    export_format: str = Query(default="csv", alias="format", max_length=8),
    project_id: uuid.UUID | None = None,
    department: str | None = Query(default=None, max_length=40),
    request_type: str | None = Query(default=None, max_length=60),
    request_types: str | None = Query(default=None, max_length=200),
    request_status: str | None = Query(default=None, alias="status", max_length=200),
    stage: str | None = Query(default=None, max_length=60),
    assignee_id: str | None = Query(default=None, max_length=36),
    raised_by: str | None = Query(default=None, max_length=36),
    q: str | None = Query(default=None, max_length=200),
    include_closed: bool = False,
    is_template: bool = False,
    _perm: None = Depends(RequirePermission("work_requests.read")),
):
    """The register as a file, on exactly the filters ``GET /requests``
    takes - what somebody exports is what they were looking at.

    ``format=xlsx`` needs a spreadsheet library; without one the response
    is the CSV and ``X-Export-Note`` says so, rather than this module
    growing a dependency behind an operator's back.
    """
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
        allowed = None
    else:
        allowed = await accessible_project_ids(session, user_id)
    try:
        out = await service.export_requests(
            session,
            fmt=export_format,
            department=department,
            project_ids=allowed,
            project_id=project_id,
            request_type=request_type,
            request_types=request_types,
            status=request_status,
            stage=stage,
            assignee_id=assignee_id,
            raised_by=raised_by,
            q=q,
            include_closed=include_closed,
            is_template=is_template,
        )
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    headers = {
        "Content-Disposition": f'attachment; filename="{out["filename"]}"',
        "X-Export-Rows": str(out["rows"]),
        "X-Content-Type-Options": "nosniff",
    }
    if out["note"]:
        headers["X-Export-Note"] = out["note"]
    return StreamingResponse(io.BytesIO(out["content"]), media_type=out["media_type"], headers=headers)


@router.post("/requests/bulk")
async def bulk_update(
    payload: BulkBody,
    session: SessionDep,
    user_id: CurrentUserId,
    caller: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("work_requests.update")),
) -> dict:
    """One patch over many requests. NEVER all-or-nothing: each request
    goes through the same rails a single PATCH does, and the ones that
    refuse come back in ``refused`` with the reason while the rest land.
    """
    allowed = await accessible_project_ids(session, user_id)
    try:
        out = await service.bulk_update(
            session,
            ids=payload.ids,
            patch=payload.patch.model_dump(exclude_unset=True),
            user_id=str(user_id),
            can_manage=_can_manage(caller),
            project_ids=allowed,
        )
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return out


@router.get("/requests/{request_id}")
async def get_request(
    request_id: str,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("work_requests.read")),
) -> dict:
    """One request - by id, or by its reference (``WR-WKS-000012``)."""
    req = await _request_or_404(session, user_id, request_id)
    return await service.payload(session, req)


@router.patch("/requests/{request_id}")
async def update_request(
    request_id: str,
    payload: RequestPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    caller: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("work_requests.update")),
) -> dict:
    req = await _request_or_404(session, user_id, request_id)
    changes = payload.model_dump(exclude_unset=True)
    for key in ("links",):
        if key in changes and changes[key] is not None:
            changes[key] = [dict(link) for link in changes[key]]
    try:
        await service.update_request(session, req, changes, user_id=str(user_id), can_manage=_can_manage(caller))
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return await service.payload(session, req)


@router.post("/requests/{request_id}/stage")
async def move_stage(
    request_id: str,
    payload: StageMove,
    session: SessionDep,
    user_id: CurrentUserId,
    caller: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("work_requests.update")),
) -> dict:
    req = await _request_or_404(session, user_id, request_id)
    try:
        await service.move_stage(
            session, req, payload.stage, note=payload.note, user_id=str(user_id), can_manage=_can_manage(caller)
        )
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return await service.payload(session, req)


@router.post("/requests/{request_id}/checklist")
async def tick_checklist(
    request_id: str,
    payload: ChecklistTick,
    session: SessionDep,
    user_id: CurrentUserId,
    caller: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("work_requests.update")),
) -> dict:
    """Tick or untick one checklist item. Department side, like a stage
    move - the people doing the work say it is done, not the requester."""
    req = await _request_or_404(session, user_id, request_id)
    try:
        await service.set_checklist_item(
            session, req, payload.key, payload.done, user_id=str(user_id), can_manage=_can_manage(caller)
        )
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return await service.payload(session, req)


@router.post("/requests/{request_id}/checklist/items", status_code=status.HTTP_201_CREATED)
async def add_checklist_item(
    request_id: str,
    payload: ChecklistItemAdd,
    session: SessionDep,
    user_id: CurrentUserId,
    caller: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("work_requests.update")),
) -> dict:
    """Add a one-off item to THIS request's checklist. The department
    LEAD or a manager - the shape of the list is not a fitter's call, and
    the type every other job uses is left alone."""
    req = await _request_or_404(session, user_id, request_id)
    try:
        await service.add_checklist_item(
            session,
            req,
            label=payload.label,
            required=payload.required,
            after_key=payload.after_key,
            user_id=str(user_id),
            can_manage=_can_manage(caller),
        )
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return await service.payload(session, req)


@router.patch("/requests/{request_id}/checklist/items/{item_key}")
async def update_checklist_item(
    request_id: str,
    item_key: str,
    payload: ChecklistItemPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    caller: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("work_requests.update")),
) -> dict:
    """Re-word an item or change whether it gates completion, on THIS
    request. An inherited item is OVERRIDDEN, never rewritten on the
    type."""
    req = await _request_or_404(session, user_id, request_id)
    changes = payload.model_dump(exclude_unset=True)
    try:
        await service.update_checklist_item(
            session,
            req,
            item_key,
            label=changes.get("label"),
            required=changes.get("required"),
            user_id=str(user_id),
            can_manage=_can_manage(caller),
        )
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return await service.payload(session, req)


@router.delete("/requests/{request_id}/checklist/items/{item_key}")
async def delete_checklist_item(
    request_id: str,
    item_key: str,
    session: SessionDep,
    user_id: CurrentUserId,
    caller: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("work_requests.update")),
) -> dict:
    """Remove a request-added item; HIDE an inherited one so a later
    change of request type can bring it back. A ticked item is a 409."""
    req = await _request_or_404(session, user_id, request_id)
    try:
        await service.remove_checklist_item(
            session, req, item_key, user_id=str(user_id), can_manage=_can_manage(caller)
        )
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return await service.payload(session, req)


@router.put("/requests/{request_id}/checklist/order")
async def order_checklist(
    request_id: str,
    payload: ChecklistOrder,
    session: SessionDep,
    user_id: CurrentUserId,
    caller: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("work_requests.update")),
) -> dict:
    """``{keys: [...]}``. Keys left out keep their relative order, at the
    end - a partial drag never silently drops half the list."""
    req = await _request_or_404(session, user_id, request_id)
    try:
        await service.reorder_checklist(
            session, req, payload.keys, user_id=str(user_id), can_manage=_can_manage(caller)
        )
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return await service.payload(session, req)


@router.post("/requests/{request_id}/checklist/reset")
async def reset_checklist(
    request_id: str,
    session: SessionDep,
    user_id: CurrentUserId,
    caller: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("work_requests.update")),
) -> dict:
    """Drop every override on this request and go back to what its
    request types declare. Ticks on items that still exist are kept."""
    req = await _request_or_404(session, user_id, request_id)
    try:
        await service.reset_checklist(session, req, user_id=str(user_id), can_manage=_can_manage(caller))
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return await service.payload(session, req)


@router.post("/requests/{request_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_request(
    request_id: str,
    payload: DuplicateBody,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("work_requests.create")),
) -> dict:
    """Copy a request - or a template - into a NEW draft. Create-level on
    purpose: anyone who could raise it can start from one that exists."""
    req = await _request_or_404(session, user_id, request_id)
    if payload.project_id is not None:
        await verify_project_access(payload.project_id, user_id, session)
    try:
        copy = await service.duplicate_request(
            session, req, title=payload.title, project_id=payload.project_id, user_id=str(user_id)
        )
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return await service.payload(session, copy)


@router.post("/requests/{request_id}/assign")
async def assign(
    request_id: str,
    payload: AssignBody,
    session: SessionDep,
    user_id: CurrentUserId,
    caller: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("work_requests.update")),
) -> dict:
    req = await _request_or_404(session, user_id, request_id)
    try:
        await service.assign(
            session,
            req,
            assignee_ids=payload.assignee_ids,
            responsible_user_id=payload.responsible_user_id,
            user_id=str(user_id),
            can_manage=_can_manage(caller),
        )
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return await service.payload(session, req)


@router.post("/requests/{request_id}/needs-info")
async def needs_info(
    request_id: str,
    payload: NeedsInfoBody,
    session: SessionDep,
    user_id: CurrentUserId,
    caller: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("work_requests.update")),
) -> dict:
    req = await _request_or_404(session, user_id, request_id)
    try:
        await service.needs_info(session, req, payload.question, user_id=str(user_id), can_manage=_can_manage(caller))
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return await service.payload(session, req)


@router.post("/requests/{request_id}/answer")
async def answer(
    request_id: str,
    payload: AnswerBody,
    session: SessionDep,
    user_id: CurrentUserId,
    caller: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("work_requests.create")),
) -> dict:
    """Answer an open question. Create-level on purpose: the requester
    who could raise it can answer for it."""
    req = await _request_or_404(session, user_id, request_id)
    try:
        await service.answer(session, req, payload.answer, user_id=str(user_id), can_manage=_can_manage(caller))
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return await service.payload(session, req)


@router.post("/requests/{request_id}/handoff", status_code=status.HTTP_201_CREATED)
async def handoff(
    request_id: str,
    payload: HandoffBody,
    session: SessionDep,
    user_id: CurrentUserId,
    caller: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("work_requests.create")),
) -> dict:
    req = await _request_or_404(session, user_id, request_id)
    try:
        child = await service.handoff(
            session,
            req,
            department=payload.department,
            request_type=payload.request_type,
            request_types=payload.request_types,
            title=payload.title,
            description=payload.description,
            due_date=payload.due_date,
            info_required_by=payload.info_required_by,
            copy_links=payload.copy_links,
            user_id=str(user_id),
            can_manage=_can_manage(caller),
        )
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return await service.payload(session, child)


# ── Hours ────────────────────────────────────────────────────────────────


@router.get("/requests/{request_id}/hours")
async def list_hours(
    request_id: str,
    session: SessionDep,
    user_id: CurrentUserId,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _perm: None = Depends(RequirePermission("work_requests.read")),
) -> WorkRequestListResponse:
    req = await _request_or_404(session, user_id, request_id)
    return _page(await service.list_hours(session, req), limit, offset)


@router.post("/requests/{request_id}/hours", status_code=status.HTTP_201_CREATED)
async def log_hours(
    request_id: str,
    payload: HoursBody,
    session: SessionDep,
    user_id: CurrentUserId,
    caller: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("work_requests.update")),
) -> dict:
    req = await _request_or_404(session, user_id, request_id)
    try:
        row = await service.log_hours(
            session,
            req,
            day=payload.date,
            hours=payload.hours,
            note=payload.note,
            for_user_id=payload.user_id,
            user_id=str(user_id),
            can_manage=_can_manage(caller),
        )
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return {
        "id": str(row.id),
        "user_id": row.user_id,
        "user_name": row.user_name,
        "date": row.day,
        "hours": row.hours,
        "note": row.note,
        "request": await service.payload(session, req),
    }


@router.delete("/requests/{request_id}/hours/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hours(
    request_id: str,
    log_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    caller: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("work_requests.update")),
) -> None:
    req = await _request_or_404(session, user_id, request_id)
    try:
        await service.delete_hours(session, req, log_id, user_id=str(user_id), can_manage=_can_manage(caller))
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()


# ── Comments, activity, attachments ──────────────────────────────────────


@router.get("/requests/{request_id}/comments")
async def list_comments(
    request_id: str,
    session: SessionDep,
    user_id: CurrentUserId,
    include_system: bool = False,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _perm: None = Depends(RequirePermission("work_requests.read")),
) -> WorkRequestListResponse:
    req = await _request_or_404(session, user_id, request_id)
    return _page(await service.list_comments(session, req, include_system=include_system), limit, offset)


@router.post("/requests/{request_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(
    request_id: str,
    payload: CommentBody,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("work_requests.create")),
) -> dict:
    req = await _request_or_404(session, user_id, request_id)
    try:
        row = await service.add_comment(
            session, req, body=payload.body, mention_ids=payload.mention_ids, user_id=str(user_id)
        )
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return service.comment_payload(row)


@router.get("/requests/{request_id}/activity")
async def activity(
    request_id: str,
    session: SessionDep,
    user_id: CurrentUserId,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _perm: None = Depends(RequirePermission("work_requests.read")),
) -> WorkRequestListResponse:
    req = await _request_or_404(session, user_id, request_id)
    return _page(await service.activity(session, req), limit, offset)


def _safe_filename(raw: str | None) -> str:
    name = (raw or "file").replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = re.sub(r"[^\w.\- ()]", "_", name)[:120].strip(" .")
    return name or "file"


@router.post("/requests/{request_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    request_id: str,
    session: SessionDep,
    user_id: CurrentUserId,
    caller: CurrentUserPayload,
    file: UploadFile = File(...),
    _perm: None = Depends(RequirePermission("work_requests.update")),
) -> dict:
    """Attach a drawing, a request form, a test sheet. The on-disk name is
    the sanitised client name (numbered on collision, never overwritten)
    under this request's own folder in the app data dir."""
    req = await _request_or_404(session, user_id, request_id)
    dept = await service.department_or_error(session, req.department)
    if not service.may_update(req, dept, str(user_id), _can_manage(caller)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Only the requester, the {dept.name} team or a manager attach to {req.reference}",
        )
    raw = await file.read()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty")
    if len(raw) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"{MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB cap per file"
        )
    safe = _safe_filename(file.filename)
    folder = ATTACHMENTS_DIR / str(req.id)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / safe
        n = 1
        while dest.exists():
            stem, dot, ext = safe.rpartition(".")
            dest = folder / (f"{stem}-{n}.{ext}" if dot and stem else f"{safe}-{n}")
            n += 1
        dest.write_bytes(raw)
    except OSError as exc:  # pragma: no cover - storage failure
        logger.exception("Unable to save work request attachment")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Unable to save attachment") from exc
    entry = service.record_attachment(
        req,
        filename=dest.name,
        size=len(raw),
        mime=(file.content_type or "application/octet-stream")[:120],
        user_id=str(user_id),
        user_name=await service._user_name(session, str(user_id)),
    )
    await service._log(session, req, user_id=str(user_id), what="Attached", detail=dest.name)
    await session.commit()
    return {"attachment": entry, "request": await service.payload(session, req)}


@router.get("/requests/{request_id}/attachments/{filename}")
async def get_attachment(
    request_id: str,
    filename: str,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("work_requests.read")),
):
    """Serve one attachment. The filename is hostile until proven inside
    this request's own folder; unknown types download rather than render."""
    req = await _request_or_404(session, user_id, request_id)
    known = {a.get("filename") for a in (req.attachments or []) if isinstance(a, dict)}
    bare = Path(str(filename)).name
    if not bare or bare not in known:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    folder = (ATTACHMENTS_DIR / str(req.id)).resolve()
    path = (folder / bare).resolve()
    if path.parent != folder or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment missing from storage")
    media = _INLINE.get(path.suffix.lower())
    return FileResponse(
        path,
        media_type=media or "application/octet-stream",
        content_disposition_type="inline" if media else "attachment",
        filename=path.name,
        headers={"X-Content-Type-Options": "nosniff"},
    )


# ── Planner ──────────────────────────────────────────────────────────────


@router.get("/planner")
async def planner(
    session: SessionDep,
    user_id: CurrentUserId,
    department: str = Query(max_length=40),
    from_day: str | None = Query(default=None, alias="from", max_length=10),
    to_day: str | None = Query(default=None, alias="to", max_length=10),
    _perm: None = Depends(RequirePermission("work_requests.read")),
) -> dict:
    try:
        return await service.planner(session, department=department, from_day=from_day, to_day=to_day)
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None


@router.put("/planner/capacity")
async def set_capacity(
    capacity: dict[str, float | None],
    session: SessionDep,
    user_id: CurrentUserId,
    department: str = Query(max_length=40),
    _perm: None = Depends(RequirePermission("work_requests.manage")),
) -> dict:
    """``{iso day: people available}``; null removes the override."""
    try:
        out = await service.set_capacity(session, department, capacity)
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return {"department": department, "capacity": out}


@router.put("/planner/{request_id}")
async def set_allocation(
    request_id: str,
    payload: PlannerAllocBody,
    session: SessionDep,
    user_id: CurrentUserId,
    caller: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("work_requests.update")),
) -> dict:
    req = await _request_or_404(session, user_id, request_id)
    try:
        out = await service.set_allocation(
            session, req, payload.alloc, user_id=str(user_id), can_manage=_can_manage(caller)
        )
    except service.WorkRequestError as exc:
        raise _raise_for(exc) from None
    await session.commit()
    return {"request_id": str(req.id), "alloc": out}


# ── Summary, queue, sweep ────────────────────────────────────────────────


@router.get("/summary")
async def summary(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = None,
    _perm: None = Depends(RequirePermission("work_requests.read")),
) -> dict:
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
        allowed = None
    else:
        allowed = await accessible_project_ids(session, user_id)
    out = await service.summary(session, project_ids=allowed, project_id=project_id)
    await session.commit()  # persist first-run seeds
    return out


@router.get("/my-queue")
async def my_queue(
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("work_requests.read")),
) -> dict:
    allowed = await accessible_project_ids(session, user_id)
    return await service.my_queue(session, user_id=str(user_id), project_ids=allowed)


@router.post("/deadline-sweep")
async def deadline_sweep(
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("work_requests.read")),
) -> dict:
    """Ring the bell for what has newly fallen due. A POST because it
    writes: each reason is remembered so it fires once per request per
    day, however often the workspace polls."""
    from app.modules.work_requests import notifying

    allowed = await accessible_project_ids(session, user_id)
    result = await notifying.sweep(session, project_ids=allowed)
    await session.commit()
    return result
