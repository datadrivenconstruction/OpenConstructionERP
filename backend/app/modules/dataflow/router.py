# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dataflow API.

Endpoints:
    GET /projects/{project_id}/counts/   - object counts per module for a project
    GET /projects/{project_id}/parties/  - people, companies and organisations on the project
    GET /paths/{module}/?project_id=     - one module's data paths with live numbers
    GET /map/?project_id=                - every visible module and its data flows
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.active_markets import ActiveMarkets
from app.core.market_scope import is_visible
from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.dataflow import service
from app.modules.dataflow.graph import Graph, graph_holder, module_dir
from app.modules.dataflow.parties import collect_parties
from app.modules.dataflow.schemas import ModulePaths, PlatformMap, ProjectCounts, ProjectParties

router = APIRouter(tags=["dataflow"])


async def _tenant_key(session: SessionDep, project_id: uuid.UUID) -> str:
    from app.modules.projects.models import Project

    project = await session.get(Project, project_id)
    return str(getattr(project, "owner_id", "") or "")


async def _currency(session: SessionDep, project_id: uuid.UUID | None) -> str:
    if project_id is None:
        return ""
    from app.modules.projects.models import Project

    project = await session.get(Project, project_id)
    return str(getattr(project, "currency", "") or "")


def make_reader(payload: dict[str, Any]) -> Callable[[str], bool]:
    """``reader(module)``: may this caller read the module's records (its ``<dir>.read``)."""
    from app.core.demo_read_only import DEMO_READ_GRANTS, demo_read_only_enabled
    from app.core.permissions import permission_registry

    role = str(payload.get("role", ""))
    granted = set(payload.get("permissions", []) or [])

    def reader(module: str) -> bool:
        if role == "admin":
            return True
        perm = f"{module_dir(module)}.read"
        if not permission_registry.has(perm):
            return True
        if perm in granted or permission_registry.role_has_permission(role, perm):
            return True
        return perm in DEMO_READ_GRANTS and demo_read_only_enabled()

    return reader


def make_visible(graph: Graph, markets: list[str]) -> Callable[[str], bool]:
    """``visible(module)``: the module serves one of the company's markets (pack modules hide otherwise)."""

    def visible(module: str) -> bool:
        manifest = graph.manifests.get(module)
        if manifest is None:
            return False
        return is_visible(getattr(manifest, "markets", ["*"]), markets)

    return visible


@router.get("/projects/{project_id}/counts/", response_model=ProjectCounts)
async def project_counts(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("dataflow.read")),
) -> ProjectCounts:
    """Count query per registered object type; 404 for projects the caller cannot see."""
    await verify_project_access(project_id, user_id, session)
    return await service.get_project_counts(session, project_id, await _tenant_key(session, project_id))


@router.get("/paths/{module}/", response_model=ModulePaths)
async def module_paths(
    module: str,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    markets: ActiveMarkets,
    project_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("dataflow.read")),
) -> ModulePaths:
    """Where the module's data comes from and goes to, with live numbers for the project."""
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    graph = graph_holder.get()
    visible = make_visible(graph, markets)
    if module not in graph.manifests or not visible(module):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")
    result = await service.module_paths(session, graph, module, project_id, make_reader(payload), visible)
    result.currency = await _currency(session, project_id)
    return result


@router.get("/map/", response_model=PlatformMap)
async def platform_map(
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    markets: ActiveMarkets,
    project_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("dataflow.read")),
) -> PlatformMap:
    """Whole-platform map: modules, declared and derived links, live counts for the project."""
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    graph = graph_holder.get()
    result = await service.platform_map(session, graph, project_id, make_reader(payload), make_visible(graph, markets))
    result.currency = await _currency(session, project_id)
    return result


@router.get("/projects/{project_id}/parties/", response_model=ProjectParties)
async def project_parties(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("dataflow.read")),
) -> ProjectParties:
    """Parties on the project, in three zones; role placeholders when there are none yet."""
    await verify_project_access(project_id, user_id, session)
    graph = graph_holder.get()
    reader = make_reader(payload)
    sources = frozenset(n for n in graph.loaded if reader(n))
    parties = await collect_parties(session, project_id, graph.manifests, sources)
    return ProjectParties(project_id=project_id, parties=parties)
