# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dataflow service: per-project counts, data paths per module and the platform map.

Callers check project access first (``verify_project_access``); this layer adds
the per-path read-permission mask, the market-profile filter and the cache.
Raw numbers are cached per (project, module); masking runs after the cache, so
one user's permissions never leak into another user's response.
"""

from __future__ import annotations

import importlib
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_paths import DataPath, Importance, Latest, Sum
from app.modules.dataflow import live
from app.modules.dataflow.graph import Graph, module_dir
from app.modules.dataflow.phases import PHASES, phase_of
from app.modules.dataflow.registry import REGISTRY, CounterSpec
from app.modules.dataflow.schemas import (
    EdgeOut,
    EntityOut,
    HealthItem,
    Live,
    MapModule,
    ModuleCounts,
    ModulePaths,
    ObjectCount,
    ParamOut,
    PathOut,
    PlatformMap,
    ProjectCounts,
    StaleOut,
)

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60.0
counts_cache = live.TTLCache(max_entries=512, ttl_seconds=CACHE_TTL_SECONDS)

Reader = Callable[[str], bool]
"""``reader(module_name)`` -> may the caller read that module's records."""


def clear_cache() -> None:
    """Drop all cached results (tests, admin tools)."""
    counts_cache.clear()
    live.path_cache.clear()


# ── Project data map counters ──────────────────────────────────────────────


def _load(path: str) -> Any:
    module_path, _, cls = path.partition(":")
    return getattr(importlib.import_module(module_path), cls)


def _count_stmt(spec: CounterSpec, project_id: uuid.UUID) -> Any:
    model = _load(spec.model)
    if spec.via_model:
        parent = _load(spec.via_model)
        return (
            select(func.count())
            .select_from(model)
            .join(parent, getattr(model, spec.via_fk or "") == parent.id)
            .where(parent.project_id == project_id)
        )
    return select(func.count()).select_from(model).where(getattr(model, spec.fk) == project_id)


def _module_disabled(module: str) -> bool:
    try:
        from app.core.module_loader import module_loader

        return f"oe_{module}" in getattr(module_loader, "_disabled", ())
    except Exception:
        return False


async def _count_module(
    session: AsyncSession,
    module: str,
    specs: list[CounterSpec],
    project_id: uuid.UUID,
) -> ModuleCounts:
    if _module_disabled(module):
        return ModuleCounts(module=module, installed=False, reason="disabled")
    objects: list[ObjectCount] = []
    try:
        # Savepoint: a missing table must not poison the shared transaction.
        async with session.begin_nested():
            for spec in specs:
                value = (await session.execute(_count_stmt(spec, project_id))).scalar_one()
                objects.append(ObjectCount(object=spec.object, count=int(value)))
    except (ImportError, AttributeError):
        return ModuleCounts(module=module, installed=False, reason="not_available")
    except Exception as exc:
        logger.warning("dataflow: counters for %s unavailable: %s", module, type(exc).__name__)
        return ModuleCounts(module=module, installed=False, reason="query_failed")
    return ModuleCounts(module=module, installed=True, objects=objects)


async def get_project_counts(
    session: AsyncSession,
    project_id: uuid.UUID,
    tenant_key: str = "",
) -> ProjectCounts:
    """Return counts per module for a project. The caller must check access first."""
    key = ("counts", tenant_key, project_id)
    hit = counts_cache.get(key, ttl=CACHE_TTL_SECONDS)
    if hit is not None:
        return hit
    modules = [await _count_module(session, m, specs, project_id) for m, specs in REGISTRY.items()]
    result = ProjectCounts(project_id=project_id, generated_at=datetime.now(UTC), modules=modules)
    counts_cache.put(key, result)
    return result


# ── Data paths per module ──────────────────────────────────────────────────


def _measure_name(measure: Any) -> tuple[str, str | None]:
    if isinstance(measure, Sum):
        return "sum", measure.field
    if isinstance(measure, Latest):
        return "latest", measure.field
    return "count", None


def _route(template: str, project_id: uuid.UUID | None) -> str:
    if not template:
        return ""
    return template.replace("{project}", str(project_id) if project_id else "")


async def _raw_module(
    session: AsyncSession, graph: Graph, module: str, project_id: uuid.UUID | None
) -> dict[str, dict[str, Any]]:
    """Live numbers for every entity, path and stale rule of one module (cached, unmasked)."""
    key = ("paths", project_id, module)
    hit = live.path_cache.get(key)
    if hit is not None:
        return hit
    decl = graph.declaration(module)
    out: dict[str, dict[str, Any]] = {}
    if decl is None:
        return out
    await live.prepare(session)
    for ent in decl.entities:
        out[live.entity_id(ent)] = await live.measure_entity(session, graph, module, ent, project_id)
    for direction, path in decl.paths()[: decl.MAX_PATHS]:
        if path.module not in graph.loaded:
            out[live.path_id(direction, path)] = {"state": "not_installed"}
            continue
        out[live.path_id(direction, path)] = await live.measure_path(session, graph, module, path, project_id)
    if project_id is not None:
        for idx, rule in enumerate(decl.stale):
            out[f"stale:{idx}"] = {"count": await live.stale_count(session, graph, module, rule, project_id)}
    live.path_cache.put(key, out)
    return out


def _live(raw: dict[str, Any] | None, *, readable: bool, project_id: uuid.UUID | None) -> Live:
    if not readable:
        return Live(state="no_access")
    raw = raw or {}
    state = raw.get("state", "ok")
    data = Live(
        count=raw.get("count") if project_id is not None or raw.get("count") is not None else None,
        value=raw.get("value"),
        latest_at=raw.get("latest_at"),
        state=state,
        reason=raw.get("reason"),
    )
    data.active = live.is_recent(data.latest_at)
    return data


def _path_matches(target: str, path: DataPath) -> bool:
    if ":" in target:
        return target.split(":", 1)[0] == path.module
    parts = target.split(".")
    if parts[0].startswith("oe_"):
        return parts[0] == path.module and len(parts) > 1 and parts[1] == path.entity
    return parts[0] == path.entity


async def module_paths(
    session: AsyncSession,
    graph: Graph,
    module: str,
    project_id: uuid.UUID | None,
    reader: Reader,
    visible: Callable[[str], bool],
) -> ModulePaths:
    """The drawer payload: declared paths with live numbers, plus derived technical links."""
    decl = graph.declaration(module)
    raw = await _raw_module(session, graph, module, project_id) if decl is not None else {}
    own_readable = reader(module)
    result = ModulePaths(
        module=module,
        declared=decl is not None,
        installed=module in graph.loaded,
        why=decl.why if decl else "",
        roles=list(decl.roles) if decl else [],
        phase=phase_of(module, graph.manifests.get(module)),
        project_id=project_id,
        generated_at=datetime.now(UTC),
    )
    declared_pairs: set[tuple[str, str]] = set()
    if decl is not None:
        for ent in decl.entities:
            name, fld = _measure_name(ent.measure)
            result.entities.append(
                EntityOut(
                    id=live.entity_id(ent),
                    model=ent.model,
                    label=ent.label,
                    route=_route(ent.route, project_id),
                    measure=name if not fld else f"{name}:{fld}",
                    live=_live(raw.get(live.entity_id(ent)), readable=own_readable, project_id=project_id),
                )
            )
        for direction, path in decl.paths():
            if not visible(path.module):
                continue
            pid = live.path_id(direction, path)
            source, target = (path.module, module) if direction == "in" else (module, path.module)
            declared_pairs.add((source, target))
            name, fld = _measure_name(path.measure)
            live_item = _live(raw.get(pid), readable=reader(path.module) and own_readable, project_id=project_id)
            result.paths.append(
                PathOut(
                    id=pid,
                    direction=direction,
                    module=path.module,
                    entity=path.entity,
                    via=path.via,
                    label=path.label,
                    measure=name,
                    measure_field=fld,
                    route=_route(path.route, project_id),
                    importance=str(path.importance),
                    breaks=path.breaks,
                    edge=path.edge,
                    live=live_item,
                )
            )
        for param in decl.parameters:
            hits = [live.path_id(d, p) for d, p in decl.paths() if any(_path_matches(t, p) for t in param.drives)]
            result.parameters.append(
                ParamOut(field=param.field, label=param.label, drives=list(param.drives), drives_paths=hits)
            )
        for idx, rule in enumerate(decl.stale):
            target_path = next(
                (p for p in result.paths if p.entity in (rule.copy.split(".")[0], rule.source.split(".")[-2])),
                None,
            )
            count = (raw.get(f"stale:{idx}") or {}).get("count") if own_readable else None
            result.stale.append(
                StaleOut(
                    source=rule.source,
                    copy_field=rule.copy,
                    label=rule.label,
                    path_id=target_path.id if target_path else None,
                    count=count,
                )
            )
            if target_path is not None and count:
                target_path.live.state = "stale" if target_path.live.state == "ok" else target_path.live.state
                target_path.live.stale_count = count
    for edge in graph.edges:
        if module not in (edge.source, edge.target) or edge.kind == "declared":
            continue
        other = edge.target if edge.source == module else edge.source
        if not visible(other) or (edge.source, edge.target) in declared_pairs:
            continue
        result.technical.append(
            EdgeOut(
                source=edge.source,
                target=edge.target,
                kind=edge.kind,
                details=list(edge.details),
                state="ok" if other in graph.loaded else "not_installed",
            )
        )
    result.neighbours = sorted(n for n in graph.neighbours(module, 1) if n != module and visible(n))
    return result


# ── Platform map ───────────────────────────────────────────────────────────


async def platform_map(
    session: AsyncSession,
    graph: Graph,
    project_id: uuid.UUID | None,
    reader: Reader,
    visible: Callable[[str], bool],
) -> PlatformMap:
    """Every visible module, every link; live counts on declared edges for the project."""
    modules: list[MapModule] = []
    edge_counts: dict[tuple[str, str], tuple[int | None, bool, str]] = {}
    health: list[HealthItem] = []
    health_pairs: set[tuple[str, str]] = set()
    for name, manifest in sorted(graph.manifests.items()):
        if not visible(name):
            continue
        decl = graph.declaration(name)
        item = MapModule(
            name=name,
            display_name=getattr(manifest, "display_name", name),
            category=getattr(manifest, "category", "core"),
            phase=phase_of(name, manifest),
            declared=decl is not None,
            installed=name in graph.loaded,
            why=decl.why if decl else "",
            roles=list(decl.roles) if decl else [],
        )
        if decl is not None and project_id is not None and item.installed and reader(name):
            raw = await _raw_module(session, graph, name, project_id)
            total = 0
            for ent in decl.entities:
                cnt = (raw.get(live.entity_id(ent)) or {}).get("count")
                if isinstance(cnt, int):
                    item.counts[ent.model] = cnt
                    total += cnt
            item.count = total
            for direction, path in decl.paths():
                pid = live.path_id(direction, path)
                data = raw.get(pid) or {}
                pair = (path.module, name) if direction == "in" else (name, path.module)
                cnt = data.get("count") if reader(path.module) else None
                prev_count, prev_active, _prev_state = edge_counts.get(pair, (None, False, "ok"))
                if isinstance(cnt, int):
                    cnt = cnt + (prev_count or 0)
                else:
                    cnt = prev_count
                edge_counts[pair] = (
                    cnt,
                    prev_active or live.is_recent(data.get("latest_at")),
                    data.get("state", "ok"),
                )
                if (
                    path.importance is Importance.CRITICAL
                    and cnt == 0
                    and total > 0
                    and visible(path.module)
                    and path.module in graph.loaded
                    and pair not in health_pairs
                ):
                    # Both ends may declare the same link; one gap is one line.
                    health_pairs.add(pair)
                    health.append(
                        HealthItem(
                            module=name,
                            path_id=pid,
                            source=path.module,
                            label=path.label,
                            importance=str(path.importance),
                            breaks=path.breaks,
                            missing=path.missing,
                            upstream=pair[0],
                            downstream=pair[1],
                        )
                    )
        modules.append(item)
    names = {m.name for m in modules}
    edges: list[EdgeOut] = []
    for edge in graph.edges:
        if edge.source not in names or edge.target not in names:
            continue
        cnt, active, state = edge_counts.get((edge.source, edge.target), (None, False, "ok"))
        edges.append(
            EdgeOut(
                source=edge.source,
                target=edge.target,
                kind=edge.kind,
                details=list(edge.details),
                importance=edge.importance,
                label=edge.label,
                count=cnt if edge.kind == "declared" else None,
                active=active if edge.kind == "declared" else False,
                state=state if edge.kind == "declared" else "ok",
            )
        )
    return PlatformMap(
        project_id=project_id,
        modules=modules,
        edges=edges,
        health=health,
        phases=list(PHASES),
        generated_at=datetime.now(UTC),
    )


def invalidate_for_event(event_name: str, graph: Graph | None = None) -> None:
    """Drop cached numbers touched by an event (``boq.position.updated`` -> oe_boq and its readers)."""
    head = event_name.split(".", 1)[0]
    publishers = {f"oe_{head}", f"oe_{head}s", f"oe_{head.rstrip('s')}"}
    affected = set(publishers)
    if graph is not None:
        for edge in graph.edges:
            if edge.kind == "declared" and (edge.source in publishers or edge.target in publishers):
                affected |= {edge.source, edge.target}
    for name in affected:
        live.path_cache.drop_module(name)


__all__ = [
    "CACHE_TTL_SECONDS",
    "clear_cache",
    "get_project_counts",
    "invalidate_for_event",
    "module_dir",
    "module_paths",
    "platform_map",
]
