# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Module management API - list, enable, disable modules at runtime.

Provides RESTful endpoints for the frontend Modules page to interact
with the :class:`~app.core.module_loader.ModuleLoader`.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core import solution_packages as sp
from app.core.module_loader import module_loader
from app.dependencies import RequirePermission, get_current_user_payload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/modules", tags=["Module Management"])


def _gate_key(module_name: str) -> str:
    return module_name.removeprefix("oe_")


def _tenant_id(payload: dict[str, Any]) -> str | None:
    sub = payload.get("tenant_id") or payload.get("sub")
    return str(sub) if sub else None


async def _load_tenant_metadata(tenant_id: str | None) -> dict[str, Any] | None:
    if not tenant_id:
        return None
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        return (await session.execute(select(User.metadata_).where(User.id == uuid.UUID(tenant_id)))).scalar()


async def _save_tenant_metadata(tenant_id: str, metadata: dict[str, Any]) -> None:
    from sqlalchemy import update

    from app.core import module_guard
    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(update(User).where(User.id == uuid.UUID(tenant_id)).values(metadata_=metadata))
        await session.commit()
    module_guard.invalidate_all()


async def _sync_package_state(payload: dict[str, Any], module_name: str, enabled: bool) -> None:
    """Mirror a Modules-page switch into the solution-package state the route guard reads."""
    tenant_id = _tenant_id(payload)
    metadata = await _load_tenant_metadata(tenant_id)
    key = _gate_key(module_name)
    if not tenant_id or not metadata or key not in sp.gateable_modules():
        return
    if enabled:
        metadata, changed = sp.unblock(dict(metadata), [key])
    else:
        if not sp.read_state(metadata)["modules"]:
            return
        metadata, _ = sp.set_module(dict(metadata), key, False, force=True)
        changed = [key]
    if changed:
        await _save_tenant_metadata(tenant_id, metadata)


def apply_gate(modules: list[dict[str, Any]], metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Report a module the caller's packages hide as disabled, with the reason."""
    out = []
    for mod in modules:
        blocked = sp.is_blocked(metadata, _gate_key(str(mod.get("name", ""))))
        out.append({**mod, "enabled": bool(mod.get("enabled")) and not blocked, "blocked_by_package": blocked})
    return out


@router.get("/")
async def list_all_modules(
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
) -> list[dict[str, Any]]:
    """List all discovered modules with enabled/disabled status.

    Signed-in callers only, like ``/api/system/modules``, which returns the
    same list. The sidebar asks for it once the user is authenticated, and no
    screen before sign-in needs the catalogue.
    """
    metadata = await _load_tenant_metadata(_tenant_id(payload))
    return apply_gate(module_loader.list_modules(), metadata)


@router.get("/{module_name}", dependencies=[Depends(get_current_user_payload)])
async def get_module_detail(module_name: str) -> dict[str, Any]:
    """Get detailed info about a module."""
    try:
        return module_loader.get_module_info(module_name)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Module '{module_name}' not found.",
        )


# ``system.modules.enable`` and ``.disable`` are registered at Role.ADMIN by
# ``register_core_permissions``. These two routes used to ask for the bare
# literal ``"admin"``, which nobody registers: ``RequirePermission`` returns
# False for an unknown key, and admin short-circuits above that check, so the
# routes behaved as admin-only and no test could tell. What it cost was the
# admin permission matrix - ``set_min_role("admin", ...)`` raises KeyError, so
# unlike every other enable/disable-shaped permission these two could never be
# delegated to a manager. Ask for the key that exists.
@router.post(
    "/{module_name}/enable",
    dependencies=[Depends(RequirePermission("system.modules.enable"))],
)
async def enable_module(
    module_name: str,
    request: Request,
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
) -> dict[str, Any]:
    """Enable a module (admin only)."""
    if module_name not in module_loader._manifests:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Module '{module_name}' not found.",
        )

    try:
        result = await module_loader.enable_module(module_name, request.app)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    # A ZIP-installed module gets its missing tables on enable (additive only).
    from app.core import module_package

    if module_package.read_marker(module_package.runtime_modules_dir() / module_name.removeprefix("oe_")):
        result["tables"] = await module_package.create_missing_tables(module_name)
    await _sync_package_state(payload, module_name, True)
    return result


@router.post(
    "/{module_name}/disable",
    dependencies=[Depends(RequirePermission("system.modules.disable"))],
)
async def disable_module(
    module_name: str,
    request: Request,
    payload: Annotated[dict[str, Any], Depends(get_current_user_payload)],
) -> dict[str, Any]:
    """Disable a module (admin only). Fails if other enabled modules depend on it."""
    if module_name not in module_loader._manifests:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Module '{module_name}' not found.",
        )

    try:
        result = await module_loader.disable_module(module_name, request.app)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    await _sync_package_state(payload, module_name, False)
    return result


@router.get("/dependency-tree/{module_name}", dependencies=[Depends(get_current_user_payload)])
async def get_dependency_tree(module_name: str) -> dict[str, Any]:
    """Show which modules depend on this module."""
    try:
        return module_loader.get_dependency_tree(module_name)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Module '{module_name}' not found.",
        )
