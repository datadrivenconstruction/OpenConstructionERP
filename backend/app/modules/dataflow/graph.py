# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The data path graph: hand declarations plus links derived from the code.

Derived links come from three places no one has to maintain by hand:

* ``depends`` / ``optional_depends`` in each manifest (module level),
* foreign keys in ``Base.metadata`` between tables of different modules,
* event bus subscriptions (``<publisher>.<entity>.<verb>`` -> handler module).

Declarations decide what a user sees first; derived links the declarations do
not mention are "technical links", shown collapsed. The graph is pure (no
database) and rebuilt only when the set of loaded modules changes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path as FsPath
from typing import Any

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

from app.core.data_paths import DataPath, DataPaths, Importance

logger = logging.getLogger(__name__)

# Every module references users and projects; drawing those edges hides the real flow.
UBIQUITOUS = frozenset({"oe_users", "oe_projects", "oe_teams", "oe_dataflow"})

MODULES_DIR = FsPath(__file__).resolve().parent.parent


def module_dir(name: str) -> str:
    """``oe_boq`` -> ``boq``."""
    return name[3:] if name.startswith("oe_") else name


@dataclass(frozen=True)
class ModelInfo:
    """One mapped class and the module that owns it."""

    module: str
    cls: Any

    @property
    def name(self) -> str:
        return self.cls.__name__

    def attr_keys(self) -> set[str]:
        return {a.key for a in self.cls.__mapper__.column_attrs}

    def has_project_id(self) -> bool:
        return "project_id" in self.attr_keys()


@dataclass(frozen=True)
class Ref:
    """A resolved ``Model.field[.json_key]`` reference."""

    model: ModelInfo
    attr: str
    json_key: str | None = None

    @property
    def is_json(self) -> bool:
        col = self.model.cls.__mapper__.column_attrs[self.attr].columns[0]
        return isinstance(col.type, JSON | JSONB) or "JSON" in type(col.type).__name__.upper()


@dataclass
class Edge:
    """One link between two modules."""

    source: str
    target: str
    kind: str  # declared | depends | fk | event
    details: list[str] = field(default_factory=list)
    importance: str = Importance.SUPPORTING.value
    label: str = ""

    def key(self) -> tuple[str, str, str]:
        return (self.source, self.target, self.kind)


def _owner_by_module_path(manifests: dict[str, Any], packages: dict[str, str]) -> dict[str, str]:
    """Python package prefix -> owning module name."""
    owners = {f"app.modules.{module_dir(name)}": name for name in manifests}
    owners.update(packages)
    return owners


def index_models(manifests: dict[str, Any], packages: dict[str, str] | None = None) -> dict[str, list[ModelInfo]]:
    """Mapped classes per owning module, from the SQLAlchemy registry."""
    from app.database import Base

    owners = _owner_by_module_path(manifests, packages or {})
    out: dict[str, list[ModelInfo]] = {}
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        mod_path = cls.__module__
        owner = next(
            (name for prefix, name in owners.items() if mod_path == prefix or mod_path.startswith(prefix + ".")),
            None,
        )
        if owner is not None:
            out.setdefault(owner, []).append(ModelInfo(owner, cls))
    return out


def resolve_ref(ref: str, candidates: tuple[str, ...], models: dict[str, list[ModelInfo]]) -> Ref | str:
    """Resolve ``[oe_x.]Model.field[.key]`` against the candidate modules; a string is the error."""
    parts = ref.split(".")
    if parts and parts[0].startswith("oe_"):
        candidates = (parts[0],)
        parts = parts[1:]
    if len(parts) < 2:
        return f"{ref!r} is not Model.field"
    model_name, attr, *rest = parts
    info = next((m for c in candidates for m in models.get(c, []) if m.name == model_name), None)
    if info is None:
        return f"{ref!r}: no model {model_name} in {', '.join(candidates)}"
    if attr not in info.attr_keys():
        return f"{ref!r}: {model_name} has no field {attr}"
    resolved = Ref(info, attr, ".".join(rest) or None)
    if rest and not resolved.is_json:
        return f"{ref!r}: {model_name}.{attr} is not a JSON column, so {'.'.join(rest)} cannot be a key"
    return resolved


@cache
def _module_source(dir_name: str) -> str:
    root = MODULES_DIR / dir_name
    if not root.is_dir():
        return ""
    return "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in root.rglob("*.py"))


@cache
def _all_sources() -> str:
    files = (p for p in MODULES_DIR.rglob("*.py") if "tests" not in p.parts)
    return "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in files)


def json_key_known(module: str, key: str) -> bool:
    """A JSON key is real when module code writes or reads it as a literal (owner first, then any module)."""
    first = key.split(".")[0]
    pattern = re.compile(rf"[\"']{re.escape(first)}[\"']")
    return bool(pattern.search(_module_source(module_dir(module))) or pattern.search(_all_sources()))


def declaration_problems(
    name: str, decl: DataPaths, models: dict[str, list[ModelInfo]], known_modules: set[str]
) -> list[str]:
    """Every field reference in one declaration that does not resolve; empty = sound."""
    problems = [f"{name}: {gap}" for gap in decl.gaps()]

    def check(ref: str, candidates: tuple[str, ...], *, allow_concept: bool = False) -> None:
        if allow_concept and ":" in ref:
            mod = ref.split(":", 1)[0]
            if mod not in known_modules:
                problems.append(f"{name}: {ref!r} names unknown module {mod}")
            return
        got = resolve_ref(ref, candidates, models)
        if isinstance(got, str):
            problems.append(f"{name}: {got}")
        elif got.json_key and not json_key_known(got.model.module, got.json_key):
            problems.append(f"{name}: {ref!r}: key {got.json_key!r} never appears in {got.model.module}")

    for ent in decl.entities:
        check(f"{ent.model}.id", (name,))
        _check_measure(name, ent.model, ent.measure, ent.where, (name,), check)
    for _direction, path in decl.paths():
        if path.module not in known_modules:
            problems.append(f"{name}: path to unknown module {path.module}")
            continue
        both = (path.module, name)
        check(f"{path.entity}.id", (path.module, name))
        check(path.via, both)
        _check_measure(name, path.entity, path.measure, path.where, (path.module, name), check)
    for param in decl.parameters:
        check(param.field, (name,))
        for target in param.drives:
            check(target, (name, *known_modules), allow_concept=True)
    for rule in decl.stale:
        check(rule.source, (name,))
        check(rule.copy, (name,))
    return problems


def _check_measure(name: str, entity: str, measure: Any, where: tuple, candidates: tuple[str, ...], check: Any) -> None:
    measured = getattr(measure, "field", None)
    if measured:
        check(f"{entity}.{measured}", candidates)
    for cond in where:
        check(f"{entity}.{cond.field}", candidates)


@dataclass
class Graph:
    """Modules, declarations and edges, built once per set of loaded modules."""

    manifests: dict[str, Any]
    loaded: frozenset[str]
    models: dict[str, list[ModelInfo]]
    edges: list[Edge]

    def declaration(self, name: str) -> DataPaths | None:
        manifest = self.manifests.get(name)
        return getattr(manifest, "data_paths", None) if manifest is not None else None

    def neighbours(self, name: str, hops: int = 1) -> set[str]:
        seen = {name}
        frontier = {name}
        for _ in range(max(0, hops)):
            nxt: set[str] = set()
            for e in self.edges:
                if e.source in frontier and e.target not in seen:
                    nxt.add(e.target)
                if e.target in frontier and e.source not in seen:
                    nxt.add(e.source)
            seen |= nxt
            frontier = nxt
        return seen


def _add(edges: dict[tuple[str, str, str], Edge], edge: Edge, detail: str | None = None) -> None:
    if edge.source == edge.target or edge.source in UBIQUITOUS or edge.target in UBIQUITOUS:
        return
    existing = edges.setdefault(edge.key(), edge)
    if detail and detail not in existing.details and len(existing.details) < 6:
        existing.details.append(detail)


def _declared_edges(name: str, decl: DataPaths, edges: dict) -> None:
    for direction, path in decl.paths():
        source, target = (path.module, name) if direction == "in" else (name, path.module)
        edge = _edge_for(source, target, path)
        _add(edges, edge, path.via)
        current = edges.get(edge.key())
        if current is not None and _rank(path.importance) < _rank(current.importance):
            current.importance = path.importance.value


def _edge_for(source: str, target: str, path: DataPath) -> Edge:
    return Edge(source, target, "declared", importance=path.importance.value, label=path.label)


def _rank(importance: Importance | str) -> int:
    return {"critical": 0, "high": 1, "supporting": 2}.get(str(importance), 2)


def _fk_edges(models: dict[str, list[ModelInfo]], edges: dict) -> None:
    table_owner = {
        m.cls.__table__.name: m.module for mods in models.values() for m in mods if hasattr(m.cls, "__table__")
    }
    for mods in models.values():
        for info in mods:
            table = getattr(info.cls, "__table__", None)
            if table is None:
                continue
            for fk in table.foreign_keys:
                owner = table_owner.get(fk.column.table.name)
                if owner and owner != info.module:
                    _add(edges, Edge(owner, info.module, "fk"), f"{info.name}.{fk.parent.name}")


def _event_edges(manifests: dict[str, Any], owners: dict[str, str], edges: dict) -> None:
    from app.core.events import event_bus

    by_dir = {module_dir(n): n for n in manifests}
    for event_name, handlers in getattr(event_bus, "_handlers", {}).items():
        head = event_name.split(".", 1)[0]
        publisher = by_dir.get(head) or by_dir.get(head + "s") or by_dir.get(head.rstrip("s"))
        if publisher is None:
            continue
        for handler in handlers:
            mod_path = getattr(handler, "__module__", "") or ""
            subscriber = next(
                (n for p, n in owners.items() if mod_path == p or mod_path.startswith(p + ".")),
                None,
            )
            if subscriber:
                _add(edges, Edge(publisher, subscriber, "event"), event_name)


def build_graph(
    manifests: dict[str, Any],
    loaded: frozenset[str],
    packages: dict[str, str] | None = None,
) -> Graph:
    """Build the graph from manifests, the ORM registry and the event bus."""
    models = index_models(manifests, packages)
    edges: dict[tuple[str, str, str], Edge] = {}
    for name, manifest in manifests.items():
        decl = getattr(manifest, "data_paths", None)
        if decl is not None:
            _declared_edges(name, decl, edges)
    for name, manifest in manifests.items():
        for dep in [*getattr(manifest, "depends", []), *getattr(manifest, "optional_depends", [])]:
            if dep in manifests:
                _add(edges, Edge(dep, name, "depends"), dep)
    _fk_edges(models, edges)
    try:
        _event_edges(manifests, _owner_by_module_path(manifests, packages or {}), edges)
    except Exception:
        logger.debug("dataflow: event bus not readable for derivation", exc_info=True)
    return Graph(manifests=manifests, loaded=loaded, models=models, edges=list(edges.values()))


class GraphHolder:
    """Caches the graph for the current set of loaded modules (rebuilt when it changes)."""

    def __init__(self) -> None:
        self._key: frozenset[str] | None = None
        self._graph: Graph | None = None

    def get(self) -> Graph:
        from app.core.module_loader import module_loader

        manifests = dict(module_loader._manifests)
        loaded = frozenset(n for n in module_loader.loaded_modules if module_loader.is_enabled(n))
        if self._graph is None or self._key != loaded:
            packages = {
                getattr(m.package, "__name__", ""): n
                for n, m in module_loader.loaded_modules.items()
                if getattr(m.package, "__name__", "")
            }
            self._graph = build_graph(manifests, loaded, packages)
            self._key = loaded
        return self._graph

    def reset(self) -> None:
        self._key = None
        self._graph = None


graph_holder = GraphHolder()
