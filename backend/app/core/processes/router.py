# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""API of the processes center, mounted at ``/api/v1/processes``.

Any signed-in user may read the list (non-admins get it without logs and error
details) and ask for a module's processes to warm up; every change is
admin-only.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.processes import ProcessError, process_registry
from app.dependencies import RequireRole, get_current_user_payload

router = APIRouter(
    prefix="/api/v1/processes",
    tags=["Processes"],
    dependencies=[Depends(get_current_user_payload)],
)
_ADMIN = [Depends(RequireRole("admin"))]


class PresetIn(BaseModel):
    """Body of ``POST /preset``."""

    preset: Literal["minimal", "recommended", "all"]


class FirstRunIn(BaseModel):
    """Body of ``POST /first-run``."""

    module_ids: list[str] = Field(default_factory=list, max_length=500)
    start_now: bool = True


def _actor(payload: dict[str, Any]) -> str | None:
    sub = payload.get("sub")
    return str(sub)[:100] if sub else None


def _is_admin(payload: dict[str, Any]) -> bool:
    from app.core.permissions import ROLE_HIERARCHY, _resolve_role

    role = _resolve_role(payload.get("role", ""))
    admin = _resolve_role("admin")
    return role is not None and admin is not None and ROLE_HIERARCHY.get(role, -1) >= ROLE_HIERARCHY.get(admin, 999)


def _redact(item: dict[str, Any]) -> dict[str, Any]:
    item = dict(item)
    item["log_tail"] = []
    if item.get("last_error"):
        item["last_error"] = {"message": None, "at": item["last_error"]["at"], "traceback_id": None}
    return item


def _listing(payload: dict[str, Any]) -> dict[str, Any]:
    body = process_registry.describe_all()
    if not _is_admin(payload):
        body["processes"] = [_redact(p) for p in body["processes"]]
        body["process_rss_mb"] = None
    return body


def _http(exc: ProcessError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/")
async def list_processes(payload: dict[str, Any] = Depends(get_current_user_payload)) -> dict[str, Any]:
    """Every registered process with live status, plus totals."""
    await process_registry.reconcile()
    return _listing(payload)


@router.post("/ensure")
async def ensure_module(module: str = Query(..., min_length=1, max_length=100)) -> dict[str, Any]:
    """Warm up the processes a module needs, in the background. Idempotent.

    Returns at once; poll the list for progress. Disabled processes are not
    started and come back under ``disabled``.
    """
    return process_registry.ensure_for_module(module)


@router.get("/recommendations")
async def recommendations(modules: str = Query("", max_length=4000)) -> dict[str, Any]:
    """Processes the given comma-separated modules need, with a RAM estimate."""
    module_ids = [m.strip() for m in modules.split(",") if m.strip()]
    return process_registry.recommendations(module_ids)


@router.post("/preset", dependencies=_ADMIN)
async def apply_preset(body: PresetIn, payload: dict[str, Any] = Depends(get_current_user_payload)) -> dict[str, Any]:
    """Switch to a preset: minimal, recommended or all."""
    try:
        await process_registry.apply_preset(body.preset, updated_by=_actor(payload))
    except ProcessError as exc:
        raise _http(exc) from exc
    return _listing(payload)


@router.post("/first-run", dependencies=_ADMIN)
async def first_run(body: FirstRunIn, payload: dict[str, Any] = Depends(get_current_user_payload)) -> dict[str, Any]:
    """Answer the first-run wizard with the modules this installation will use."""
    await process_registry.first_run(body.module_ids, body.start_now, updated_by=_actor(payload))
    return _listing(payload)


@router.get("/{process_id}/logs", dependencies=_ADMIN)
async def process_logs(process_id: str, limit: int = Query(200, ge=1, le=200)) -> dict[str, Any]:
    """Last captured log lines of one process."""
    try:
        return {"lines": process_registry.logs(process_id, limit)}
    except ProcessError as exc:
        raise _http(exc) from exc


@router.post("/{process_id}/{action}", dependencies=_ADMIN)
async def process_action(
    process_id: str,
    action: Literal["enable", "disable", "restart"],
    payload: dict[str, Any] = Depends(get_current_user_payload),
) -> dict[str, Any]:
    """Enable, disable or restart one process without restarting the platform."""
    try:
        if action == "enable":
            await process_registry.enable(process_id, updated_by=_actor(payload))
        elif action == "disable":
            await process_registry.disable(process_id, updated_by=_actor(payload))
        else:
            await process_registry.restart(process_id)
        return process_registry.describe(process_id)
    except ProcessError as exc:
        raise _http(exc) from exc
