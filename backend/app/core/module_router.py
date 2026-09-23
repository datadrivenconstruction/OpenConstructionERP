# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module management API - list, enable, disable modules at runtime.

Provides RESTful endpoints for the frontend Modules page to interact
with the :class:`~app.core.module_loader.ModuleLoader`.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.module_loader import module_loader
from app.dependencies import RequirePermission, get_current_user_payload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/modules", tags=["Module Management"])


@router.get("/", dependencies=[Depends(get_current_user_payload)])
async def list_all_modules() -> list[dict[str, Any]]:
    """List all discovered modules with enabled/disabled status.

    Signed-in callers only, like ``/api/system/modules``, which returns the
    same list. The sidebar asks for it once the user is authenticated, and no
    screen before sign-in needs the catalogue.
    """
    return module_loader.list_modules()


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
async def enable_module(module_name: str, request: Request) -> dict[str, Any]:
    """Enable a module (admin only)."""
    if module_name not in module_loader._manifests:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Module '{module_name}' not found.",
        )

    try:
        result = await module_loader.enable_module(module_name, request.app)
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.post(
    "/{module_name}/disable",
    dependencies=[Depends(RequirePermission("system.modules.disable"))],
)
async def disable_module(module_name: str, request: Request) -> dict[str, Any]:
    """Disable a module (admin only). Fails if other enabled modules depend on it."""
    if module_name not in module_loader._manifests:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Module '{module_name}' not found.",
        )

    try:
        result = await module_loader.disable_module(module_name, request.app)
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


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
