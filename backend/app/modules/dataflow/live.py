# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Live numbers per declared path: one aggregate query each, cached briefly.

Every query is scoped to one project: through the entity's own ``project_id``
or one foreign-key hop to a parent that has it. An entity that can be scoped
neither way returns no number rather than a cross-tenant one. Paths marked
``scope="global"`` count shared reference data (cost catalogues, statutory
regimes) that has no project by design.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Float, Integer, Numeric, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_paths import Count, DataPath, Entity, Latest, Stale, Sum, Where
from app.modules.dataflow.graph import Graph, ModelInfo, Ref, resolve_ref

logger = logging.getLogger(__name__)

STATEMENT_TIMEOUT_MS = 500


class TTLCache:
    """Small in-process LRU with a TTL; no Redis, PostgreSQL stays the only dependency."""

    def __init__(self, max_entries: int = 512, ttl_seconds: float = 60.0) -> None:
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._entries: OrderedDict[tuple[Any, ...], tuple[float, Any]] = OrderedDict()

    def get(self, key: tuple[Any, ...], ttl: float | None = None) -> Any | None:
        hit = self._entries.get(key)
        if hit is None:
            return None
        if time.monotonic() - hit[0] >= (self.ttl_seconds if ttl is None else ttl):
            self._entries.pop(key, None)
            return None
        self._entries.move_to_end(key)
        return hit[1]

    def put(self, key: tuple[Any, ...], value: Any) -> None:
        self._entries[key] = (time.monotonic(), value)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def drop_module(self, module: str) -> None:
        """Invalidate every entry that involves ``module`` (keys carry the module names)."""
        for key in [k for k in self._entries if module in k]:
            self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()


path_cache = TTLCache()


def _project_scope(info: ModelInfo, graph: Graph, depth: int = 3) -> list[tuple[Any, Any]] | None:
    """Join chain (target, on-clause) up to ``depth`` FK hops to an ancestor with project_id."""
    by_table = {m.cls.__table__.name: m for mods in graph.models.values() for m in mods if hasattr(m.cls, "__table__")}

    def walk(current: ModelInfo, left: int, seen: set[Any]) -> list[tuple[Any, Any]] | None:
        table = getattr(current.cls, "__table__", None)
        if table is None or left == 0:
            return None
        fks = sorted(table.foreign_keys, key=lambda f: f.parent.name)
        parents = [(fk, by_table.get(fk.column.table.name)) for fk in fks]
        parents = [(fk, p) for fk, p in parents if p is not None and p.cls not in seen and p.module != "oe_users"]
        for fk, parent in parents:
            if parent.has_project_id():
                return [(parent.cls, current.cls.__table__.c[fk.parent.name] == parent.cls.__table__.c[fk.column.name])]
        for fk, parent in parents:
            rest = walk(parent, left - 1, seen | {parent.cls})
            if rest is not None:
                on = current.cls.__table__.c[fk.parent.name] == parent.cls.__table__.c[fk.column.name]
                return [(parent.cls, on), *rest]
        return None

    return walk(info, depth, {info.cls})


def _apply_where(stmt: Any, cls: Any, where: tuple[Where, ...]) -> Any:
    for cond in where:
        col = getattr(cls, cond.field)
        values = cond.value if isinstance(cond.value, tuple) else (cond.value,)
        if cond.op == "eq":
            stmt = stmt.where(col == cond.value)
        elif cond.op == "ne":
            stmt = stmt.where((col != cond.value) | col.is_(None))
        elif cond.op == "in":
            stmt = stmt.where(col.in_(values))
        elif cond.op == "not_in":
            stmt = stmt.where(col.notin_(values))
        elif cond.op == "not_null":
            stmt = stmt.where(col.isnot(None))
        elif cond.op == "is_null":
            stmt = stmt.where(col.is_(None))
    return stmt


def _link_condition(ref: Ref) -> Any:
    col = getattr(ref.model.cls, ref.attr)
    if ref.json_key:
        node = col
        for key in ref.json_key.split("."):
            node = node[key]
        return node.as_string().isnot(None)
    return col.isnot(None)


def _measure_expr(cls: Any, measure: Any) -> Any:
    if isinstance(measure, Sum):
        col = getattr(cls, measure.field)
        if isinstance(col.type, Numeric | Integer | Float):
            return func.sum(col)
        # Money is often stored as a decimal string; '' must not break the cast.
        return func.sum(cast(func.nullif(col, ""), Numeric))
    if isinstance(measure, Latest):
        return func.max(getattr(cls, measure.field))
    return None


def build_statement(
    graph: Graph,
    info: ModelInfo,
    project_id: uuid.UUID | None,
    measure: Any,
    where: tuple[Where, ...] = (),
    link: Ref | None = None,
    scope: str = "project",
) -> Any | None:
    """count(*), measure, max(updated_at) on ``info`` for one project; None when it cannot be scoped."""
    cls = info.cls
    cols = [func.count()]
    extra = _measure_expr(cls, measure)
    cols.append(extra if extra is not None else text("NULL"))
    cols.append(func.max(cls.updated_at) if "updated_at" in info.attr_keys() else text("NULL"))
    stmt = select(*cols).select_from(cls)
    if scope == "global":
        pass
    elif project_id is None:
        return None
    elif info.has_project_id():
        stmt = stmt.where(cls.project_id == project_id)
    else:
        chain = _project_scope(info, graph)
        if chain is None:
            return None
        for parent, condition in chain:
            stmt = stmt.join(parent, condition)
        stmt = stmt.where(chain[-1][0].project_id == project_id)
    if link is not None and link.model.cls is cls:
        stmt = stmt.where(_link_condition(link))
    return _apply_where(stmt, cls, where)


async def _set_timeout(session: AsyncSession) -> None:
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        await session.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))


def _num(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


async def run_measure(session: AsyncSession, stmt: Any) -> dict[str, Any]:
    """Execute one aggregate inside a savepoint; failure or timeout reads as ``unknown``."""
    try:
        async with session.begin_nested():
            row = (await session.execute(stmt)).one()
    except Exception as exc:
        logger.info("dataflow: path measure unavailable: %s", type(exc).__name__)
        return {"state": "unknown"}
    count, value, latest = row[0], row[1], row[2]
    return {"count": int(count or 0), "value": _num(value), "latest_at": _iso(latest), "state": "ok"}


def _parse_stamp(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def stale_count(
    session: AsyncSession, graph: Graph, module: str, rule: Stale, project_id: uuid.UUID
) -> int | None:
    """Source rows changed after the newest copy stamp in the project; None = cannot tell."""
    source = resolve_ref(rule.source, (module,), graph.models)
    copy = resolve_ref(rule.copy, (module,), graph.models)
    if isinstance(source, str) or isinstance(copy, str):
        return None
    copy_col = getattr(copy.model.cls, copy.attr)
    if copy.json_key:
        for key in copy.json_key.split("."):
            copy_col = copy_col[key]
        copy_col = copy_col.as_string()
    copy_stmt = build_statement(graph, copy.model, project_id, Count())
    if copy_stmt is None:
        return None
    stamp_stmt = copy_stmt.with_only_columns(func.max(copy_col))
    try:
        async with session.begin_nested():
            stamp = _parse_stamp((await session.execute(stamp_stmt)).scalar())
            if stamp is None:
                return 0
            src_stmt = build_statement(graph, source.model, project_id, Count())
            if src_stmt is None:
                return None
            src_col = getattr(source.model.cls, source.attr)
            src_stmt = src_stmt.with_only_columns(func.count()).where(src_col > stamp)
            return int((await session.execute(src_stmt)).scalar() or 0)
    except Exception as exc:
        logger.info("dataflow: stale rule unavailable: %s", type(exc).__name__)
        return None


def path_id(direction: str, path: DataPath) -> str:
    return f"{direction}:{path.module}:{path.entity}:{path.via}"


def entity_id(entity: Entity) -> str:
    return f"entity:{entity.model}"


async def measure_path(
    session: AsyncSession, graph: Graph, module: str, path: DataPath, project_id: uuid.UUID | None
) -> dict[str, Any]:
    """Live numbers for one declared path (no permission or install check here)."""
    info_ref = resolve_ref(f"{path.entity}.id", (path.module, module), graph.models)
    if isinstance(info_ref, str):
        return {"state": "broken", "reason": "model_missing"}
    link = resolve_ref(path.via, (path.module, module), graph.models)
    link_ref = None if isinstance(link, str) else link
    stmt = build_statement(graph, info_ref.model, project_id, path.measure, path.where, link_ref, path.scope)
    if stmt is None:
        return {"state": "ok" if project_id is None else "unknown"}
    return await run_measure(session, stmt)


async def measure_entity(
    session: AsyncSession, graph: Graph, module: str, entity: Entity, project_id: uuid.UUID | None
) -> dict[str, Any]:
    """Live numbers for one centre-card entity."""
    ref = resolve_ref(f"{entity.model}.id", (module,), graph.models)
    if isinstance(ref, str):
        return {"state": "broken", "reason": "model_missing"}
    stmt = build_statement(graph, ref.model, project_id, entity.measure, entity.where, scope=entity.scope)
    if stmt is None:
        return {"state": "ok" if project_id is None else "unknown"}
    return await run_measure(session, stmt)


async def prepare(session: AsyncSession) -> None:
    """Per-request setup: statement timeout on PostgreSQL."""
    try:
        await _set_timeout(session)
    except Exception:
        logger.debug("dataflow: statement_timeout not set", exc_info=True)


def is_recent(latest_at: str | None, days: int = 7) -> bool:
    stamp = _parse_stamp(latest_at)
    return stamp is not None and (datetime.now(UTC) - stamp).days < days
