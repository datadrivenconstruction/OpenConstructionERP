# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dataflow API.

Endpoints:
    GET /projects/{project_id}/counts/   - object counts per module for a project
    GET /projects/{project_id}/parties/  - people, companies and organisations on the project
    GET /paths/{module}/?project_id=     - one module's data paths with live numbers
    GET /map/?project_id=                - every visible module and its data flows
    GET /focus/{module}/                 - roles, external sources, guarding rules, traces
    GET /chips/{module}/?project_id=     - live numbers on one module's card
    GET /changes/{module}/?project_id=   - audit log of the module and its downstream
    GET /traces/                         - every data trace the caller can see
    GET /coverage/                       - declared / derived / none per module
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
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
from app.modules.dataflow import focus, service
from app.modules.dataflow.graph import Graph, graph_holder, module_dir
from app.modules.dataflow.parties import collect_parties
from app.modules.dataflow.schemas import (
    ChangeOut,
    ChipOut,
    CoverageOut,
    DutyOut,
    ExternalOut,
    ModuleChanges,
    ModuleChips,
    ModuleFocus,
    ModulePaths,
    PlatformMap,
    ProjectCounts,
    ProjectParties,
    RuleOut,
    TraceList,
    TraceOut,
    TraceStepOut,
)
from app.modules.dataflow.traces import Trace, all_visible, traces_through

MAX_DOWNSTREAM = 12

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


def _visible_module(graph: Graph, markets: list[str], module: str) -> Callable[[str], bool]:
    visible = make_visible(graph, markets)
    if module not in graph.manifests or not visible(module):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")
    return visible


def _trace_out(trace: Trace, at: list[int] | None = None) -> TraceOut:
    return TraceOut(
        id=trace.id,
        label=trace.label,
        summary=trace.summary,
        steps=[TraceStepOut(module=s.module, label=s.label, via=s.via) for s in trace.steps],
        at=at or [],
    )


@router.get("/focus/{module}/", response_model=ModuleFocus)
async def module_focus(
    module: str,
    markets: ActiveMarkets,
    _perm: None = Depends(RequirePermission("dataflow.read")),
) -> ModuleFocus:
    """Who works here, what enters from outside, which rules guard it and which traces pass through."""
    graph = graph_holder.get()
    visible = _visible_module(graph, markets, module)
    decl = graph.declaration(module)
    shown = {n for n in graph.manifests if visible(n)}
    return ModuleFocus(
        module=module,
        declared=decl is not None,
        why=decl.why if decl else "",
        roles=list(decl.roles) if decl else [],
        duties=[DutyOut(role=d.role, label=d.label) for d in decl.duties] if decl else [],
        external=[ExternalOut(kind=e.kind, label=e.label, role=e.role) for e in decl.external] if decl else [],
        rules=[RuleOut(**r) for r in focus.module_rules(module)],
        traces=[_trace_out(t, at) for t, at in traces_through(module, shown)],
    )


@router.get("/chips/{module}/", response_model=ModuleChips)
async def module_chips(
    module: str,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    markets: ActiveMarkets,
    project_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("dataflow.read")),
) -> ModuleChips:
    """Headline count and status chips of one module; no read access to the module means no chips."""
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    graph = graph_holder.get()
    _visible_module(graph, markets, module)
    chips: list[dict] = []
    if module in graph.loaded and make_reader(payload)(module):
        chips = await focus.module_chips(session, graph, module, project_id)
    return ModuleChips(module=module, chips=[ChipOut(**c) for c in chips], generated_at=datetime.now(UTC))


@router.get("/changes/{module}/", response_model=ModuleChanges)
async def module_changes(
    module: str,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    markets: ActiveMarkets,
    project_id: uuid.UUID = Query(...),
    downstream: str = Query(default="", max_length=2000, description="Comma-separated downstream modules"),
    days: int = Query(default=30, ge=1, le=90),
    _perm: None = Depends(RequirePermission("dataflow.read")),
) -> ModuleChanges:
    """What changed here and downstream (who, when, what), only in modules the caller may read."""
    await verify_project_access(project_id, user_id, session)
    graph = graph_holder.get()
    visible = _visible_module(graph, markets, module)
    reader = make_reader(payload)
    wanted = [module, *[m for m in downstream.split(",") if m and m != module][:MAX_DOWNSTREAM]]
    allowed = [m for m in wanted if m in graph.manifests and visible(m) and reader(m)]
    rows = await focus.recent_changes(session, graph, allowed, project_id, days)
    return ModuleChanges(module=module, days=days, changes=[ChangeOut(**r) for r in rows])


@router.get("/traces/", response_model=TraceList)
async def list_traces(
    markets: ActiveMarkets,
    _perm: None = Depends(RequirePermission("dataflow.read")),
) -> TraceList:
    """Every data trace whose modules serve the caller's markets."""
    graph = graph_holder.get()
    visible = make_visible(graph, markets)
    shown = {n for n in graph.manifests if visible(n)}
    return TraceList(traces=[_trace_out(t) for t in all_visible(graph, shown)])


@router.get("/coverage/", response_model=CoverageOut)
async def module_coverage(
    markets: ActiveMarkets,
    _perm: None = Depends(RequirePermission("dataflow.read")),
) -> CoverageOut:
    """How each visible module's data paths are known: declared by hand, derived from code, or not at all."""
    graph = graph_holder.get()
    visible = make_visible(graph, markets)
    cov = {k: v for k, v in focus.coverage(graph).items() if visible(k)}
    tally = {kind: sum(1 for v in cov.values() if v == kind) for kind in ("declared", "derived", "none")}
    return CoverageOut(**tally, modules=cov)
