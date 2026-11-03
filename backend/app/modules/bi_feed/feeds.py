# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The feed allow-list, the single source of truth for file feeds and SQL views.

A feed is a flat, read-only table: a main model, optional joins for the project
id and currency, and an explicit list of ``(name, attr, kind)`` columns. Nothing
outside this list is ever exposed, and :func:`resolve` checks every attribute
against its model before a feed is listed.

Kinds: ``text``, ``uuid``, ``int``, ``bool``, ``date`` (ISO string as stored),
``datetime`` (UTC), ``decimal`` and ``money``. Both numeric kinds are exported as
exact ``NUMERIC(38,6)``; a ``money`` column needs a sibling currency column.
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Numeric, Select, Text, case, cast, select
from sqlalchemy.orm import class_mapper

KINDS = ("text", "uuid", "int", "bool", "date", "datetime", "decimal", "money")
NUMERIC_KINDS = ("decimal", "money")
CURRENCY_COLUMNS = ("currency", "currency_code")
DECIMAL_PRECISION = 38
DECIMAL_SCALE = 6
MAX_LIMIT = 50_000
MAX_UNPAGED_ROWS = 500_000
SQL_SCHEMA = "oe_bi"
SQL_ROLE = "oe_bi_reader"

# Column names that must never reach a feed. The catalogue test fails the build on a match.
DENY_COLUMN_RE = re.compile(r"hash|token|secret|password|email|api_key", re.IGNORECASE)
FEED_ID_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
# Only plain decimals are converted; anything else becomes NULL rather than failing the whole feed.
_NUMBER_RE = "^-?[0-9]+([.][0-9]+)?$"


@dataclass(frozen=True)
class ColumnSpec:
    """One exported column: output name, source attribute and kind.

    ``attr`` is an attribute of the main model, or ``alias.attr`` for a joined model.
    """

    name: str
    attr: str
    kind: str


@dataclass(frozen=True)
class JoinSpec:
    """A joined model: ``parent.left == alias.right`` (parent ``""`` is the main model)."""

    alias: str
    model: str
    left: str
    right: str = "id"
    parent: str = ""


@dataclass(frozen=True)
class FeedSpec:
    """Declarative description of a feed; ``model`` is ``"package.module:Class"``."""

    id: str
    title_key: str
    model: str
    columns: tuple[ColumnSpec, ...]
    project_col: str
    joins: tuple[JoinSpec, ...] = ()
    order_by: str = "id"
    updated_col: str = "updated_at"
    permission: str = ""


@dataclass(frozen=True)
class ResolvedColumn:
    """A column bound to a SQL expression."""

    name: str
    kind: str
    expr: Any


@dataclass(frozen=True)
class ResolvedFeed:
    """A feed whose models and attributes exist."""

    spec: FeedSpec
    entity: Any
    joined: dict[str, Any] = field(default_factory=dict)
    columns: tuple[ResolvedColumn, ...] = ()
    pk: Any = None
    project_expr: Any = None
    updated_expr: Any = None

    @property
    def id(self) -> str:
        return self.spec.id

    def query(self, *columns: Any) -> Select[Any]:
        """A select over the feed's tables with its joins, for the given columns."""
        stmt = select(*columns).select_from(self.entity)
        for j in self.spec.joins:
            parent = self.joined[j.parent] if j.parent else self.entity
            target = self.joined[j.alias]
            stmt = stmt.join(target, getattr(parent, j.left) == getattr(target, j.right))
        return stmt

    def select(self) -> Select[Any]:
        """The full flat select, one labelled expression per column."""
        return self.query(*[c.expr.label(c.name) for c in self.columns])


def _c(name: str, kind: str, attr: str | None = None) -> ColumnSpec:
    return ColumnSpec(name, attr or name, kind)


_STAMPS = (_c("created_at", "datetime"), _c("updated_at", "datetime"))

FEEDS: dict[str, FeedSpec] = {
    "projects": FeedSpec(
        id="projects",
        permission="projects.read",
        title_key="bi_feed.feed.projects",
        model="app.modules.projects.models:Project",
        project_col="id",
        columns=(
            _c("id", "uuid"),
            _c("name", "text"),
            _c("status", "text"),
            _c("region", "text"),
            _c("country_code", "text"),
            _c("currency", "text"),
            *_STAMPS,
        ),
    ),
    "boq_positions": FeedSpec(
        id="boq_positions",
        permission="boq.read",
        title_key="bi_feed.feed.boq_positions",
        model="app.modules.boq.models:Position",
        project_col="boq.project_id",
        joins=(
            JoinSpec("boq", "app.modules.boq.models:BOQ", "boq_id"),
            JoinSpec("project", "app.modules.projects.models:Project", "project_id", parent="boq"),
        ),
        columns=(
            _c("id", "uuid"),
            _c("project_id", "uuid", "boq.project_id"),
            _c("boq_id", "uuid"),
            _c("boq_name", "text", "boq.name"),
            _c("ordinal", "text"),
            _c("description", "text"),
            _c("unit", "text"),
            _c("quantity", "decimal"),
            _c("unit_rate", "money"),
            _c("total", "money"),
            _c("currency", "text", "project.currency"),
            _c("source", "text"),
            _c("validation_status", "text"),
            *_STAMPS,
        ),
    ),
    "invoices": FeedSpec(
        id="invoices",
        permission="finance.read",
        title_key="bi_feed.feed.invoices",
        model="app.modules.finance.models:Invoice",
        project_col="project_id",
        columns=(
            _c("id", "uuid"),
            _c("project_id", "uuid"),
            _c("invoice_number", "text"),
            _c("direction", "text", "invoice_direction"),
            _c("invoice_date", "date"),
            _c("due_date", "date"),
            _c("status", "text"),
            _c("currency", "text", "currency_code"),
            _c("amount_subtotal", "money"),
            _c("tax_amount", "money"),
            _c("retention_amount", "money"),
            _c("amount_total", "money"),
            _c("purchase_order_id", "uuid"),
            _c("created_by", "uuid"),
            *_STAMPS,
        ),
    ),
    "purchase_orders": FeedSpec(
        id="purchase_orders",
        permission="procurement.read",
        title_key="bi_feed.feed.purchase_orders",
        model="app.modules.procurement.models:PurchaseOrder",
        project_col="project_id",
        columns=(
            _c("id", "uuid"),
            _c("project_id", "uuid"),
            _c("po_number", "text"),
            _c("po_type", "text"),
            _c("issue_date", "date"),
            _c("delivery_date", "date"),
            _c("status", "text"),
            _c("currency", "text", "currency_code"),
            _c("amount_subtotal", "money"),
            _c("tax_amount", "money"),
            _c("amount_total", "money"),
            _c("created_by", "uuid"),
            *_STAMPS,
        ),
    ),
    "schedule_activities": FeedSpec(
        id="schedule_activities",
        permission="schedule.read",
        title_key="bi_feed.feed.schedule_activities",
        model="app.modules.schedule.models:Activity",
        project_col="schedule.project_id",
        joins=(JoinSpec("schedule", "app.modules.schedule.models:Schedule", "schedule_id"),),
        columns=(
            _c("id", "uuid"),
            _c("project_id", "uuid", "schedule.project_id"),
            _c("schedule_id", "uuid"),
            _c("schedule_name", "text", "schedule.name"),
            _c("wbs_code", "text"),
            _c("name", "text"),
            _c("activity_type", "text"),
            _c("status", "text"),
            _c("start_date", "date"),
            _c("end_date", "date"),
            _c("duration_days", "int"),
            _c("progress_pct", "decimal"),
            *_STAMPS,
        ),
    ),
}


class FeedDefinitionError(ValueError):
    """A feed names a model or attribute that does not exist."""


def _model(path: str) -> Any:
    module, _, name = path.partition(":")
    return getattr(importlib.import_module(module), name)


def _attr(model: Any, name: str, feed_id: str) -> Any:
    if name not in class_mapper(model).column_attrs:
        raise FeedDefinitionError(f"feed {feed_id!r}: {model.__name__} has no column attribute {name!r}")
    return getattr(model, name)


def _numeric(expr: Any) -> Any:
    """Exact NUMERIC from a numeric column or a numeric string; NULL for text that is not a number."""
    text = cast(expr, Text)
    return case(
        (text.op("~")(_NUMBER_RE), cast(text, Numeric(DECIMAL_PRECISION, DECIMAL_SCALE))),
        else_=None,
    )


def resolve(spec: FeedSpec) -> ResolvedFeed:
    """Bind a spec to its models; raises :class:`FeedDefinitionError` on any bad reference."""
    entity = _model(spec.model)
    joined = {j.alias: _model(j.model) for j in spec.joins}

    def locate(ref: str) -> Any:
        alias, dot, name = ref.rpartition(".")
        if not dot:
            return _attr(entity, name, spec.id)
        if alias not in joined:
            raise FeedDefinitionError(f"feed {spec.id!r}: unknown join alias {alias!r}")
        return _attr(joined[alias], name, spec.id)

    for j in spec.joins:
        _attr(joined[j.parent] if j.parent else entity, j.left, spec.id)
        _attr(joined[j.alias], j.right, spec.id)
    if "id" not in {c.name for c in spec.columns}:
        raise FeedDefinitionError(f"feed {spec.id!r}: needs an id column for stable paging")
    columns = []
    for col in spec.columns:
        if col.kind not in KINDS:
            raise FeedDefinitionError(f"feed {spec.id!r}: column {col.name!r} has unknown kind {col.kind!r}")
        expr = locate(col.attr)
        columns.append(ResolvedColumn(col.name, col.kind, _numeric(expr) if col.kind in NUMERIC_KINDS else expr))
    return ResolvedFeed(
        spec=spec,
        entity=entity,
        joined=joined,
        columns=tuple(columns),
        pk=locate(spec.order_by),
        project_expr=locate(spec.project_col),
        updated_expr=locate(spec.updated_col),
    )


def build_catalogue() -> dict[str, ResolvedFeed]:
    """Every feed whose modules are installed.

    A feed whose module cannot be imported is left out; one that names a missing
    attribute raises, so a typo cannot ship.
    """
    catalogue: dict[str, ResolvedFeed] = {}
    for spec in FEEDS.values():
        try:
            catalogue[spec.id] = resolve(spec)
        except ImportError:
            continue
    return catalogue
