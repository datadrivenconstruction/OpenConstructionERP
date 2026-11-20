# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The focused-module side of the data paths window.

* ``module_rules``: validation rules that guard what a module takes in (rules
  whose class lives in the module's package);
* ``module_chips``: the live numbers on one module's card, fetched per module so
  a failing source hides only its own chip;
* ``recent_changes``: the audit log of the module and the modules downstream of
  it, mapped to modules through their ORM classes and filtered to the project;
* ``coverage``: declared, derived from the code, or nothing, per module.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_paths import Entity
from app.modules.dataflow import live
from app.modules.dataflow.graph import UBIQUITOUS, Graph, ModelInfo, module_dir

logger = logging.getLogger(__name__)

MAX_RULES = 12
MAX_CHANGES = 40
AUDIT_SCAN = 400


def module_rules(module: str) -> list[dict[str, str]]:
    """Validation rules defined in the module's own package, sorted by id."""
    from app.core.validation.engine import rule_registry

    prefix = f"app.modules.{module_dir(module)}"
    out = []
    for rule in getattr(rule_registry, "_rules", {}).values():
        owner = type(rule).__module__
        if owner == prefix or owner.startswith(prefix + "."):
            severity = getattr(rule, "severity", "")
            out.append(
                {
                    "rule_id": str(rule.rule_id),
                    "name": str(getattr(rule, "name", "") or rule.rule_id),
                    "severity": str(getattr(severity, "value", severity) or ""),
                }
            )
    return sorted(out, key=lambda r: r["rule_id"])[:MAX_RULES]


async def module_chips(
    session: AsyncSession, graph: Graph, module: str, project_id: uuid.UUID | None
) -> list[dict[str, Any]]:
    """Headline count plus status chips for one module; every number is measured on its own."""
    decl = graph.declaration(module)
    if decl is None or project_id is None:
        return []
    await live.prepare(session)
    chips: list[dict[str, Any]] = []
    if decl.entities:
        head = decl.entities[0]
        data = await live.measure_entity(session, graph, module, head, project_id)
        if data.get("state") == "ok" and isinstance(data.get("count"), int):
            chips.append({"id": "head", "label": head.label, "count": data["count"], "tone": "neutral"})
    for idx, chip in enumerate(decl.chips):
        data = await live.measure_entity(session, graph, module, Entity(chip.model, where=chip.where), project_id)
        count = data.get("count")
        if data.get("state") == "ok" and isinstance(count, int) and count > 0:
            chips.append({"id": f"chip:{idx}", "label": chip.label, "count": count, "tone": chip.tone})
    return chips


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def audit_index(graph: Graph) -> dict[str, ModelInfo]:
    """``entity_type`` as services write it -> mapped class: class name, table name and table name minus prefixes."""
    out: dict[str, ModelInfo] = {}
    for module, infos in graph.models.items():
        prefix = module_dir(module)
        for info in infos:
            table = getattr(getattr(info.cls, "__table__", None), "name", "") or ""
            bare = table[3:] if table.startswith("oe_") else table
            keys = {_snake(info.name), bare}
            if bare.startswith(prefix + "_"):
                keys.add(bare[len(prefix) + 1 :])
            for key in keys:
                out.setdefault(key, info)
    return out


async def recent_changes(
    session: AsyncSession,
    graph: Graph,
    modules: list[str],
    project_id: uuid.UUID,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Who changed what, when, in ``modules`` inside the project during the last ``days``.

    Only entries whose record is proven to belong to the project are returned: the
    record's ``project_id`` is checked, or the entry's own ``details.project_id``.
    """
    from app.core.audit import AuditEntry

    index = audit_index(graph)
    wanted = set(modules)
    types = [k for k, info in index.items() if info.module in wanted]
    if not types:
        return []
    since = datetime.now(UTC) - timedelta(days=days)
    try:
        async with session.begin_nested():
            rows = (
                (
                    await session.execute(
                        select(AuditEntry)
                        .where(AuditEntry.entity_type.in_(types), AuditEntry.created_at >= since)
                        .order_by(AuditEntry.created_at.desc())
                        .limit(AUDIT_SCAN)
                    )
                )
                .scalars()
                .all()
            )
    except Exception as exc:
        logger.info("dataflow: audit log unavailable: %s", type(exc).__name__)
        return []
    in_project = await _ids_in_project(session, index, rows, project_id)
    names = await _user_names(session, {r.user_id for r in rows if r.user_id})
    out: list[dict[str, Any]] = []
    for row in rows:
        info = index[row.entity_type]
        details = row.details if isinstance(row.details, dict) else {}
        tagged = str(details.get("project_id", "")) == str(project_id)
        if not tagged and (row.entity_id or "") not in in_project.get(info.cls, set()):
            continue
        out.append(
            {
                "module": info.module,
                "entity": info.name,
                "entity_id": row.entity_id,
                "action": row.action,
                "at": row.created_at.isoformat() if row.created_at else None,
                "user": names.get(row.user_id, "") if row.user_id else "",
            }
        )
        if len(out) >= MAX_CHANGES:
            break
    return out


async def _ids_in_project(
    session: AsyncSession, index: dict[str, ModelInfo], rows: list[Any], project_id: uuid.UUID
) -> dict[Any, set[str]]:
    by_cls: dict[Any, set[str]] = {}
    for row in rows:
        info = index[row.entity_type]
        if row.entity_id and info.has_project_id():
            by_cls.setdefault(info.cls, set()).add(row.entity_id)
    out: dict[Any, set[str]] = {}
    for cls, ids in by_cls.items():
        valid = []
        for raw in ids:
            try:
                valid.append(uuid.UUID(raw))
            except ValueError:
                continue
        if not valid:
            continue
        try:
            async with session.begin_nested():
                found = (
                    await session.execute(select(cls.id).where(cls.id.in_(valid), cls.project_id == project_id))
                ).scalars()
                out[cls] = {str(x) for x in found}
        except Exception:
            logger.debug("dataflow: project check failed for %s", cls.__name__, exc_info=True)
    return out


async def _user_names(session: AsyncSession, ids: set[Any]) -> dict[Any, str]:
    if not ids:
        return {}
    try:
        from app.modules.users.models import User

        async with session.begin_nested():
            rows = (await session.execute(select(User.id, User.full_name).where(User.id.in_(list(ids))))).all()
    except Exception:
        return {}
    return {uid: name or "" for uid, name in rows}


def coverage(graph: Graph) -> dict[str, str]:
    """``declared`` (hand declaration), ``derived`` (links found in FKs, events or dependencies) or ``none``."""
    linked: set[str] = set()
    for edge in graph.edges:
        if edge.kind != "declared":
            linked.add(edge.source)
            linked.add(edge.target)
    out: dict[str, str] = {}
    for name in graph.manifests:
        if graph.declaration(name) is not None:
            out[name] = "declared"
        elif name in linked or name in UBIQUITOUS:
            out[name] = "derived"
        else:
            out[name] = "none"
    return out


__all__ = ["audit_index", "coverage", "module_chips", "module_rules", "recent_changes"]
