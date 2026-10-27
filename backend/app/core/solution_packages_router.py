# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HTTP surface for solution packages: list, install, switch single modules, seed a demo.

State is tenant-scoped. The tenant is the signed-in owner today (see
``tenant_scope``), so every call reads and writes the caller's own metadata.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core import solution_packages as sp
from app.core.module_guard import invalidate_user
from app.dependencies import CurrentUserId
from app.modules.users.router import _get_service
from app.modules.users.service import UserService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/solution-packages", tags=["Solution packages"])


class InstallRequest(BaseModel):
    """Packages to add, plus the optional modules the user ticked."""

    package_ids: list[str] = Field(min_length=1, max_length=20)
    optional: list[str] = Field(default_factory=list, max_length=200)


class ModuleToggle(BaseModel):
    """Switch one module on or off."""

    enabled: bool
    force: bool = False


def _state_payload(metadata: dict[str, Any]) -> dict[str, Any]:
    state = sp.read_state(metadata)
    return {
        "installed": state["installed"],
        "optional": state["optional"],
        "modules": state["modules"],
        "packaged": bool(state["modules"]),
    }


@router.get("/")
async def list_solution_packages(
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> dict[str, Any]:
    """All packages, every gateable module with its dependencies, and the tenant's state."""
    user = await service.get_user(uuid.UUID(user_id))
    graph = sp.module_dependencies()
    gateable = sorted(sp.gateable_modules() & sp.known_modules())
    return {
        "packages": sp.list_packages(),
        "modules": [
            {"key": m, "depends": [d for d in graph.get(m, ()) if d in sp.gateable_modules()]} for m in gateable
        ],
        "state": _state_payload(user.metadata_ or {}),
    }


@router.post("/install/")
async def install_solution_packages(
    data: InstallRequest,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> dict[str, Any]:
    """Install packages for the tenant. Idempotent; a later install only adds modules."""
    user = await service.get_user(uuid.UUID(user_id))
    try:
        metadata, added = sp.install(dict(user.metadata_ or {}), data.package_ids, data.optional)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await service.update_profile(uuid.UUID(user_id), metadata_=metadata)
    invalidate_user(user_id)
    state = _state_payload(metadata)
    return {
        **state,
        "added": added,
        "enabled_modules": sorted(k for k, v in state["modules"].items() if v),
        "demos": [sp.SOLUTION_PACKAGES[p].demo_id for p in added if sp.SOLUTION_PACKAGES[p].demo_id],
    }


@router.put("/modules/{module}/")
async def toggle_module(
    module: str,
    data: ModuleToggle,
    user_id: CurrentUserId,
    service: UserService = Depends(_get_service),
) -> dict[str, Any]:
    """Switch one module. Turning one off that others need is a 409 unless ``force``."""
    user = await service.get_user(uuid.UUID(user_id))
    try:
        metadata, affected = sp.set_module(dict(user.metadata_ or {}), module, data.enabled, force=data.force)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not data.enabled and affected and not data.force:
        raise HTTPException(status_code=409, detail={"code": "module_has_dependents", "dependents": affected})
    await service.update_profile(uuid.UUID(user_id), metadata_=metadata)
    invalidate_user(user_id)
    return {**_state_payload(metadata), "affected": affected}


@router.post("/{package_id}/demo/")
async def seed_package_demo(package_id: str, user_id: CurrentUserId) -> dict[str, Any]:
    """Seed this package's demo project only. Re-running returns the existing one."""
    pkg = sp.get_package(package_id)
    if pkg is None:
        raise HTTPException(status_code=404, detail="unknown package")
    if not pkg.demo_id:
        return {"package_id": package_id, "demo_id": None}
    from app.database import async_session_factory

    async with async_session_factory() as session:
        if pkg.demo_id == sp.SUPPLY_CHAIN_DEMO_ID:
            from app.core.solution_package_demos import seed_rebar_cage_demo

            result = await seed_rebar_cage_demo(session, owner_id=user_id)
        else:
            from app.core.demo_projects import install_demo_project

            result = await install_demo_project(session, pkg.demo_id)
        await session.commit()
    return {"package_id": package_id, "demo_id": pkg.demo_id, **result}
