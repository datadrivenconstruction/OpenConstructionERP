# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Admin API of the processes center, mounted at ``/api/v1/processes``."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.processes import ProcessError, process_registry
from app.dependencies import RequireRole, get_current_user_payload

router = APIRouter(
    prefix="/api/v1/processes",
    tags=["Processes"],
    dependencies=[Depends(RequireRole("admin"))],
)


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


def _http(exc: ProcessError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/")
async def list_processes() -> dict[str, Any]:
    """Every registered process with live status, plus totals."""
    await process_registry.reconcile()
    return process_registry.describe_all()


@router.get("/recommendations")
async def recommendations(modules: str = Query("", max_length=4000)) -> dict[str, Any]:
    """Processes the given comma-separated modules need, with a RAM estimate."""
    module_ids = [m.strip() for m in modules.split(",") if m.strip()]
    return process_registry.recommendations(module_ids)


@router.post("/preset")
async def apply_preset(body: PresetIn, payload: dict[str, Any] = Depends(get_current_user_payload)) -> dict[str, Any]:
    """Switch to a preset: minimal, recommended or all."""
    try:
        await process_registry.apply_preset(body.preset, updated_by=_actor(payload))
    except ProcessError as exc:
        raise _http(exc) from exc
    return process_registry.describe_all()


@router.post("/first-run")
async def first_run(body: FirstRunIn, payload: dict[str, Any] = Depends(get_current_user_payload)) -> dict[str, Any]:
    """Answer the first-run wizard with the modules this installation will use."""
    await process_registry.first_run(body.module_ids, body.start_now, updated_by=_actor(payload))
    return process_registry.describe_all()


@router.get("/{process_id}/logs")
async def process_logs(process_id: str, limit: int = Query(200, ge=1, le=200)) -> dict[str, Any]:
    """Last captured log lines of one process."""
    try:
        return {"lines": process_registry.logs(process_id, limit)}
    except ProcessError as exc:
        raise _http(exc) from exc


@router.post("/{process_id}/{action}")
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
