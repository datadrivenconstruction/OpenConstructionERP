# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Declarative, whitelisted KPI specs - the safe way to define a custom KPI.

The 35 built-in KPIs are Python functions registered through
``@register_kpi``. Community modules can add more the same way, but a
person running the platform cannot: they have no place to put Python.
This module is the answer for them, and the shape of the answer is the
whole point.

A custom KPI is **data**, never code. It names one entity, one
aggregation, one field and a list of filters, and every one of those four
is looked up in a table declared here. Nothing a caller writes is ever
concatenated into SQL or evaluated: a field name is a dictionary key, and
a miss is a rejection, not a fallback. Rejection happens when the
definition is created, so a KPI that survives ``POST /kpis`` is a KPI that
will compute rather than one that will quietly read zero forever.

Two structures describe the same whitelist and they are deliberately
independent:

* :data:`ENTITY_CATALOG` is pure data - entity name, source module, field
  names and their kinds. It needs no ORM import, so validating a spec
  works whether or not the source module is installed, and the catalog can
  be served to a UI that wants to offer the user a picker.
* ``_bind_*`` builds the actual SQLAlchemy expressions, importing the
  source module's models lazily so this consumer module keeps its
  contract of degrading rather than crashing when a module is absent.

:func:`check_catalog_binding_parity` asserts the two agree. A field that
exists in one and not the other is either an unreachable promise or an
undeclared column, and both are bugs the parity test catches.

Scoping is not optional here. A spec evaluation goes through the same
``allowed_project_ids`` narrowing as every built-in formula, so a custom
KPI can never read across a tenant boundary that a built-in one respects.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from datetime import date as _date
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import Integer, cast, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sql_dates import days_since
from app.core.sql_numeric import numeric_value
from app.modules.bi_dashboards.models import KPIDefinition

logger = logging.getLogger(__name__)


# ── Vocabulary ─────────────────────────────────────────────────────────

#: Field kinds. The kind decides which aggregations and which filter
#: operators a field accepts, so ``sum`` over a text column is refused by
#: the same table that refuses an unknown column.
KIND_NUMERIC = "numeric"
KIND_TEXT = "text"
KIND_UUID = "uuid"
KIND_BOOL = "bool"

#: Keys a caller may read out of a declared JSON column, as ``<column>.<key>``.
#:
#: This is the one name in a spec that is not already a key in a table here, so
#: it is the one place the whitelist has to describe a shape instead of listing
#: members. Bounded length and a conservative alphabet, matching what a
#: classification scheme actually uses: ``tipo``, ``din276``, ``cost_type``.
#: The key never reaches SQL as text - SQLAlchemy binds it as a parameter - so
#: this is about keeping the vocabulary sane rather than about injection.
JSON_KEY_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")

#: What one computed value is a value OF.
#:
#: ``project`` is what every stored value has always been and stays the
#: default. ``estimate`` narrows the same definition to a single bill, which
#: is the only honest reading for anything normalised: a project holding nine
#: separately quoted and separately contracted additions has nine areas, nine
#: durations and nine margins, and the average of them is not a rougher
#: version of the right answer, it is a number with no referent. Money and
#: contract value still roll up to the project, which is why this is a choice
#: per definition rather than a change of meaning for all of them.
SCOPE_PROJECT = "project"
SCOPE_ESTIMATE = "estimate"
KPI_SCOPES: tuple[str, ...] = (SCOPE_PROJECT, SCOPE_ESTIMATE)

#: Aggregations a custom KPI may ask for. Anything outside this tuple is
#: rejected by name.
AGGREGATIONS: tuple[str, ...] = (
    "count",
    "sum",
    "avg",
    "min",
    "max",
    "weighted_avg",
    "top_by",
)

#: Aggregations that need a numeric ``field``. ``count`` is the one that
#: must not carry one - counting a column and counting rows are different
#: questions and silently answering the second is how a KPI lies.
_FIELD_REQUIRED: frozenset[str] = frozenset({"sum", "avg", "min", "max", "weighted_avg", "top_by"})

#: Filter operators. ``in`` takes a list; ``is_null`` / ``not_null`` take
#: no value; the ordering operators are numeric-only.
FILTER_OPERATORS: tuple[str, ...] = (
    "eq",
    "ne",
    "lt",
    "lte",
    "gt",
    "gte",
    "in",
    "is_null",
    "not_null",
)

_ORDERING_OPERATORS: frozenset[str] = frozenset({"lt", "lte", "gt", "gte"})
_VALUELESS_OPERATORS: frozenset[str] = frozenset({"is_null", "not_null"})

#: A breakdown is a display artefact, not a data export. Capping it keeps
#: a dashboard tile from carrying ten thousand keys because somebody
#: grouped by description.
MAX_BREAKDOWN_GROUPS = 200

#: Longest ``in`` list a filter may carry.
MAX_IN_VALUES = 100

#: The breakdown key standing for "this group had no value".
#:
#: Every other key in a breakdown is a data value, so the absent one needs
#: a key a consumer can recognise rather than a word it has to guess at.
#: This used to be the text ``(unset)``, which is a value a column can
#: hold: rows with no value and rows spelling "(unset)" keyed the same,
#: and since both grouped paths assign into ``breakdown[key]``, the later
#: write overwrote the earlier and a group disappeared from the KPI.
#:
#: Reserved rather than impossible - a row whose group value is literally
#: this string collides the same way - and that is the trade taken
#: knowingly. An empty string collides with a genuine empty-string group,
#: which SQL keeps apart from NULL; a word collides with prose somebody
#: typed, and cannot be localised once it is a dict key, by which point it
#: is indistinguishable from a real value like ``m3``. A name a consumer
#: can test for is mapped to whatever label that consumer speaks.
#:
#: It also stands in for a label nobody can read. A key must keep the data
#: apart - an empty-string group is not a NULL one and SQL keeps them
#: apart - but a label answers "what is this row called", and a name that
#: is empty or all whitespace answers it the same way an absent one does.
#: A blank label is worse than a missing one, because it renders as
#: nothing at all and the row looks like a bug rather than like an
#: estimate somebody never named.
NULL_GROUP_KEY = "__null__"


class KPISpecError(ValueError):
    """A spec was rejected, and the exception says exactly where.

    ``path`` is a dotted path into the submitted spec (``spec.field``,
    ``spec.filters[1].op``) so a caller can highlight the offending input
    rather than re-reading the whole document. ``allowed`` carries the
    accepted vocabulary at that path when there is one.
    """

    def __init__(
        self,
        path: str,
        message: str,
        *,
        value: Any = None,
        allowed: list[str] | None = None,
    ) -> None:
        self.path = path
        self.value = value
        self.allowed = allowed
        detail = f"{path}: {message}"
        if allowed:
            detail = f"{detail} Allowed: {', '.join(allowed)}."
        super().__init__(detail)

    def as_dict(self) -> dict[str, Any]:
        """Render for an HTTP error body."""
        return {
            "error": "invalid_kpi_spec",
            "path": self.path,
            "value": None if self.value is None else str(self.value),
            "allowed": self.allowed or [],
            "message": str(self),
        }


# ── Catalog (pure data - no ORM import) ────────────────────────────────


@dataclass(frozen=True)
class CatalogEntity:
    """One documented entity a custom KPI may aggregate over."""

    name: str
    source_module: str
    description: str
    #: field name -> kind
    fields: dict[str, str]
    #: id field -> the field that names it.
    #:
    #: An id is what the database groups by and a name is what a person
    #: reads, and only the entity knows which of its fields is the second
    #: one for the first. Declaring the pair here means a spec that groups
    #: by an id gets the name without its author having to know that
    #: ``boq_name`` exists, and it is served in the catalog so the form
    #: offers the same answer the server would.
    display_name_for: dict[str, str] = field(default_factory=dict)
    #: JSON column -> the kind of the values under it.
    #:
    #: A field named ``<column>.<key>`` reads one key out of one of these,
    #: which is the only place a caller supplies a name this table does not
    #: already contain. That is a real widening of the contract, so it is
    #: narrow on purpose: the column must be declared here, the key must
    #: match :data:`JSON_KEY_RE`, and the value is read as text whatever it
    #: holds. The key reaches SQL as a bind parameter through SQLAlchemy's
    #: ``col[key].as_string()`` - the same construct ``costs/repository.py``
    #: already uses with a variable key - so nothing is concatenated.
    #:
    #: The alternative was a per-deployment whitelist of keys, which would
    #: keep the vocabulary closed. It is rejected because these columns hold
    #: classification schemes: ``din276``, ``masterformat``, ``nrm`` and
    #: whatever an estimator's own workbook calls its cost types. A catalog
    #: that had to know those in advance would have to be edited before a
    #: deployment could read its own data, which is the thing this feature
    #: exists to avoid.
    json_fields: dict[str, str] = field(default_factory=dict)
    #: Whether one row here belongs to exactly one estimate.
    #:
    #: Declared rather than inferred, because "has a reachable ``boq_id``" and
    #: "means one estimate" are not the same claim. A project row reaches
    #: every estimate under it and belongs to none of them, and the usage
    #: ledger records the project a rate was applied to and not the bill it
    #: landed in, so neither can answer a per-estimate question however the
    #: join is written. The binder holds the column; this says whether the
    #: entity has the property at all, and
    #: :func:`check_catalog_binding_parity` refuses a disagreement between
    #: the two - a promise here with no column there would be accepted at
    #: creation and unanswerable at compute time.
    narrows_to_estimate: bool = False

    def numeric_fields(self) -> list[str]:
        return sorted(n for n, k in self.fields.items() if k == KIND_NUMERIC)

    def kind_of(self, name: str) -> str | None:
        """The kind of a field name, plain or ``<json column>.<key>``.

        Returns ``None`` for a name this entity does not offer, so callers
        that used to index ``fields`` directly get a miss rather than a
        ``KeyError`` on a path that is syntactically fine.
        """
        if name in self.fields:
            return self.fields[name]
        column, _, key = name.partition(".")
        if key and column in self.json_fields and JSON_KEY_RE.fullmatch(key):
            return self.json_fields[column]
        return None

    def groupable_fields(self) -> list[str]:
        """Fields a breakdown may be keyed by.

        Numeric fields are excluded on purpose: grouping by a measure
        produces one bucket per distinct amount, which is never the
        question anybody meant to ask.

        JSON paths are not listed, because there is no finite list of them
        to give: the keys live in the data. They are offered separately, in
        :meth:`as_dict`, as the column names a path may be built on.
        """
        return sorted(n for n, k in self.fields.items() if k != KIND_NUMERIC)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_module": self.source_module,
            "description": self.description,
            "fields": [{"name": n, "kind": k} for n, k in sorted(self.fields.items())],
            "numeric_fields": self.numeric_fields(),
            "groupable_fields": self.groupable_fields(),
            "display_name_for": dict(self.display_name_for),
            # Served so a picker can offer "group by classification.<key>"
            # and prompt for the key, rather than a reader having to learn
            # from the documentation that the dotted form exists at all.
            "json_path_fields": [
                {"name": n, "kind": k, "example": f"{n}.<key>"} for n, k in sorted(self.json_fields.items())
            ],
            # Served so a picker can grey out estimate scope on an entity that
            # cannot carry it, rather than offering it and letting the create
            # call refuse afterwards.
            "narrows_to_estimate": self.narrows_to_estimate,
        }


ENTITY_CATALOG: dict[str, CatalogEntity] = {
    "boq_position": CatalogEntity(
        name="boq_position",
        source_module="oe_boq",
        description=(
            "One priced line of a Bill of Quantities. ``amount`` is the "
            "derived quantity x unit_rate; ``confidence`` is the 0..1 "
            "estimator confidence and may be unset, in which case the row "
            "is left out of averages instead of being read as zero. "
            "``boq_name`` is the parent document's name, so a breakdown "
            "per bid can be read by a person rather than by id. "
            "``risk_dispersion`` is the estimating standard deviation for "
            "the line as a fraction of its own amount, which is what a "
            "risk-adjusted margin needs and what confidence cannot give: "
            "read it with weighted_avg weighted by amount. ``currency`` is "
            "the ISO code the money on this line is denominated in. It is "
            "the owning project's, because neither the line nor the bill "
            "has one of its own, so a portfolio reading can group a sum of "
            "``amount`` by it or filter to a single code instead of adding "
            "several currencies together. ``price_basis`` "
            "is what the price stands on, one of invoice, quotation, "
            "price_list, contract_rate, norm, historic, judgement - "
            "deliberately separate from ``source``, which records how the "
            "row was entered and is ``manual`` on nearly every row of a "
            "typed bill."
        ),
        fields={
            "quantity": KIND_NUMERIC,
            "unit_rate": KIND_NUMERIC,
            "total": KIND_NUMERIC,
            "amount": KIND_NUMERIC,
            "confidence": KIND_NUMERIC,
            "risk_dispersion": KIND_NUMERIC,
            "currency": KIND_TEXT,
            "price_basis": KIND_TEXT,
            "boq_id": KIND_UUID,
            "boq_name": KIND_TEXT,
            "parent_id": KIND_UUID,
            "ordinal": KIND_TEXT,
            "description": KIND_TEXT,
            "unit": KIND_TEXT,
            "source": KIND_TEXT,
            "validation_status": KIND_TEXT,
            "node_type": KIND_TEXT,
        },
        display_name_for={"boq_id": "boq_name"},
        # The only place a position says what KIND of work it is. `source`
        # is the nearest declared field and answers a different question,
        # how the row was entered. That column defaults to `manual` and
        # every ordinary create path writes it literally - only the CAD and
        # AI import paths write anything else - so on a bill that was typed
        # or imported from a workbook, a breakdown by it looks like a cost
        # analysis and is a provenance report with one bar.
        json_fields={"classification": KIND_TEXT},
        narrows_to_estimate=True,
    ),
    "boq": CatalogEntity(
        name="boq",
        source_module="oe_boq",
        description=(
            "A Bill of Quantities header. Carries no measure of its own, "
            "so only ``count`` applies - use ``boq_position`` for money."
        ),
        fields={
            "name": KIND_TEXT,
            "status": KIND_TEXT,
            "estimate_type": KIND_TEXT,
            "is_locked": KIND_BOOL,
        },
        narrows_to_estimate=True,
    ),
    "project": CatalogEntity(
        name="project",
        source_module="oe_projects",
        description=(
            "One project. This is the only entity here with one row per "
            "building, which is what makes ``gross_floor_area`` measurable "
            "and why it is offered here rather than borrowed onto the "
            "estimate or the line: the same area read over four estimates "
            "sums to four buildings, and the number looks right. "
            "``gross_floor_area`` is m2 GFA, ``contract_value`` and "
            "``budget_estimate`` are money in ``currency``, and all three may "
            "be unset, in which case the row is left out of the reading "
            "rather than counted as zero."
        ),
        fields={
            "gross_floor_area": KIND_NUMERIC,
            "contract_value": KIND_NUMERIC,
            "budget_estimate": KIND_NUMERIC,
            "name": KIND_TEXT,
            "status": KIND_TEXT,
            "phase": KIND_TEXT,
            "project_code": KIND_TEXT,
            "project_type": KIND_TEXT,
            "country_code": KIND_TEXT,
            "currency": KIND_TEXT,
            "parent_project_id": KIND_UUID,
        },
        # One row per project, which is exactly what makes it useful and
        # exactly what stops it narrowing: an estimate does not have a
        # project's floor area, it has whatever part of the building it was
        # quoted for, and reading the project's number under an estimate's
        # label would answer a question nobody asked with a plausible figure.
        narrows_to_estimate=False,
    ),
    "boq_markup": CatalogEntity(
        name="boq_markup",
        source_module="oe_boq",
        description=(
            "One markup line on an estimate: overhead, profit, tax, "
            "contingency. ``percentage`` and ``fixed_amount`` are the rate as "
            "the estimator entered it, which is what answers what margin an "
            "estimate is carrying and how many estimates carry none. It is "
            "deliberately not the markup MONEY: what a line adds to a total "
            "depends on the compounding order, on whether it applies to the "
            "direct cost or cumulatively, and on whether a section-scoped "
            "line overrides a bill-wide one. That cascade is the BOQ "
            "service's, and a second copy of it written in SQL would be a "
            "second answer to the same question."
        ),
        fields={
            "percentage": KIND_NUMERIC,
            "fixed_amount": KIND_NUMERIC,
            "name": KIND_TEXT,
            "markup_type": KIND_TEXT,
            "category": KIND_TEXT,
            "apply_to": KIND_TEXT,
            "is_active": KIND_BOOL,
            "boq_id": KIND_UUID,
            "boq_name": KIND_TEXT,
            "scope_position_id": KIND_UUID,
        },
        display_name_for={"boq_id": "boq_name"},
        narrows_to_estimate=True,
    ),
    "schedule_activity": CatalogEntity(
        name="schedule_activity",
        source_module="oe_schedule",
        description=(
            "One activity of a project schedule. Duration is a commercial "
            "figure and not only a planning one - it prices site overhead "
            "and it is what a client asks about before margin - so the "
            "values CPM has already computed are readable here the way an "
            "estimate is: ``duration_days`` per activity, ``total_float`` "
            "and ``free_float`` in days, ``progress_pct`` 0..100, and "
            "``is_critical`` to filter to the critical path, whose length "
            "in days is the sum of duration over that filter. Float is "
            "unset until CPM has run, so an unscheduled activity is left "
            "out of an average rather than read as having no slack. What "
            "is NOT here is the calendar span of the project itself: that "
            "is a latest-finish minus earliest-start over two date "
            "columns, and this engine has no span aggregate to express it."
        ),
        fields={
            "duration_days": KIND_NUMERIC,
            "total_float": KIND_NUMERIC,
            "free_float": KIND_NUMERIC,
            "progress_pct": KIND_NUMERIC,
            "sort_order": KIND_NUMERIC,
            "is_critical": KIND_BOOL,
            "schedule_id": KIND_UUID,
            "schedule_name": KIND_TEXT,
            "parent_id": KIND_UUID,
            "name": KIND_TEXT,
            "wbs_code": KIND_TEXT,
            "status": KIND_TEXT,
            "activity_type": KIND_TEXT,
            "activity_code": KIND_TEXT,
        },
        display_name_for={"schedule_id": "schedule_name"},
        # An activity belongs to a schedule, and a schedule to a project.
        # Nothing on this path names a bill, and a project's schedule is not
        # drawn up per estimate, so there is no estimate to narrow to.
        narrows_to_estimate=False,
    ),
    "cost_item_usage": CatalogEntity(
        name="cost_item_usage",
        source_module="oe_costs",
        description=(
            "One application of a catalogue rate to this project's work, from "
            "the append-only ledger written whenever a position is created "
            "with a cost-item link. ``price_age_days`` is how many days have "
            "passed since the item's recorded price date, counted today "
            "rather than when the KPI was written, so a threshold saved once "
            "keeps asking the question it was saved with. It is unset when "
            "the item carries no price date at all, and those rows are left "
            "out rather than read as zero, because an unknown price date is "
            "the opposite of a fresh one. One row per application, so a rate "
            "applied ten times weighs ten times: that is the right weighting "
            "for how much of the estimate rests on a stale price and the "
            "wrong one for counting catalogue items."
        ),
        fields={
            "price_age_days": KIND_NUMERIC,
            "unit_rate_at_use": KIND_NUMERIC,
            "cost_item_id": KIND_UUID,
            "cost_item_code": KIND_TEXT,
            "cost_item_description": KIND_TEXT,
            "unit": KIND_TEXT,
            "currency": KIND_TEXT,
            "region": KIND_TEXT,
            "context": KIND_TEXT,
        },
        display_name_for={"cost_item_id": "cost_item_code"},
        # The ledger records which PROJECT a rate was applied to and not which
        # bill it landed in, so "how old are the prices this estimate rests
        # on" cannot be answered from it today however the join is written.
        # Declared false rather than approximated: the nearest available
        # answer is the project's, and serving that under an estimate's label
        # is the failure this flag exists to prevent.
        narrows_to_estimate=False,
    ),
}


def catalog_as_dict() -> list[dict[str, Any]]:
    """The whole whitelist, in the shape the API serves it."""
    return [ENTITY_CATALOG[name].as_dict() for name in sorted(ENTITY_CATALOG)]


# ── Bindings (ORM expressions, resolved lazily) ────────────────────────


@dataclass(frozen=True)
class BoundField:
    """A whitelisted field, resolved to a SQL expression."""

    expr: Any
    kind: str
    #: The raw column to test for NULL when the field is nullable. A
    #: derived expression over NOT NULL columns leaves this unset.
    nullable_source: Any | None = None


@dataclass(frozen=True)
class BoundEntity:
    """A whitelisted entity, resolved to ORM models."""

    model: Any
    project_column: Any
    period_column: Any
    fields: dict[str, BoundField]
    #: ``(target, onclause)`` pairs applied in order before any predicate.
    joins: list[tuple[Any, Any]] = field(default_factory=list)
    #: JSON column -> a factory turning one key into a BoundField.
    #:
    #: The expression cannot be built ahead of time the way the others can,
    #: because the key is not known until a spec names it. The factory is
    #: what keeps that from meaning "assemble SQL from a string": it takes
    #: the key as a value and hands it to SQLAlchemy, which binds it.
    json_fields: dict[str, Callable[[str], BoundField]] = field(default_factory=dict)
    #: The column carrying the estimate a row belongs to, or ``None``.
    #:
    #: ``None`` is not "not wired up yet", it is the entity saying it has no
    #: single estimate - see ``narrows_to_estimate`` on the catalog entry,
    #: which the parity check holds to this.
    boq_column: Any | None = None

    def resolve_field(self, name: str) -> BoundField:
        """The bound field for a plain name or a ``<column>.<key>`` path.

        Raises:
            KeyError: The name is not bound here. Every caller reaches this
                with a name a validated spec already carried, so a miss is a
                catalog/binder disagreement rather than bad input, and the
                parity check exists to catch it before a spec is stored.
        """
        bound = self.fields.get(name)
        if bound is not None:
            return bound
        column, _, key = name.partition(".")
        factory = self.json_fields.get(column) if key else None
        if factory is None:
            raise KeyError(name)
        return factory(key)


def _bind_boq_position() -> BoundEntity:
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project

    # quantity / unit_rate / total / confidence are String columns by
    # design (see Position's own comment). ``numeric_value`` is the
    # platform's tolerant coercion: a clean decimal converts, anything
    # else reads as 0 rather than aborting the statement the way a bare
    # ``::double precision`` would on one malformed legacy row.
    #
    # Two joins rather than one. The bill was always joined, for the project
    # scoping; the project itself is joined for the currency, which is the
    # only place the money on a line says what it is denominated in. Neither
    # join can drop or duplicate a row: ``BOQ.project_id`` is NOT NULL and
    # points at a primary key, so every position has exactly one of each. And
    # the import is not a new dependency - ``oe_boq`` already declares
    # ``depends=["oe_projects"]`` and its table carries the foreign key - so
    # this cannot fail to import anywhere the positions themselves exist.
    return BoundEntity(
        model=Position,
        project_column=BOQ.project_id,
        period_column=Position.created_at,
        joins=[(BOQ, Position.boq_id == BOQ.id), (Project, BOQ.project_id == Project.id)],
        boq_column=Position.boq_id,
        fields={
            "quantity": BoundField(numeric_value(Position.quantity), KIND_NUMERIC),
            "unit_rate": BoundField(numeric_value(Position.unit_rate), KIND_NUMERIC),
            "total": BoundField(numeric_value(Position.total), KIND_NUMERIC),
            "amount": BoundField(
                numeric_value(Position.quantity) * numeric_value(Position.unit_rate),
                KIND_NUMERIC,
            ),
            "confidence": BoundField(
                numeric_value(Position.confidence),
                KIND_NUMERIC,
                nullable_source=Position.confidence,
            ),
            # Both carry a nullable source, and here that is the whole
            # design rather than a formality. An unjudged line has no
            # dispersion, and a row read as zero would say the estimator
            # declared it certain - the one reading that turns a missing
            # judgement into a reassuring one.
            "risk_dispersion": BoundField(
                numeric_value(Position.risk_dispersion),
                KIND_NUMERIC,
                nullable_source=Position.risk_dispersion,
            ),
            # The project's column, and deliberately not a copy taken onto
            # the line. A currency written per position would be a second
            # place for it to be right, and the money it labels is already
            # the project's money. NOT NULL, so no null source: an
            # unconfigured project reads as the empty string, which is its
            # own breakdown group rather than a missing one.
            "currency": BoundField(Project.currency, KIND_TEXT),
            "price_basis": BoundField(
                Position.price_basis,
                KIND_TEXT,
                nullable_source=Position.price_basis,
            ),
            "boq_id": BoundField(Position.boq_id, KIND_UUID),
            # Free: the join to BOQ is already there for the project
            # scoping, and the column is NOT NULL, so no null source.
            "boq_name": BoundField(BOQ.name, KIND_TEXT),
            "parent_id": BoundField(Position.parent_id, KIND_UUID, nullable_source=Position.parent_id),
            "ordinal": BoundField(Position.ordinal, KIND_TEXT),
            "description": BoundField(Position.description, KIND_TEXT),
            "unit": BoundField(Position.unit, KIND_TEXT),
            "source": BoundField(Position.source, KIND_TEXT),
            "validation_status": BoundField(Position.validation_status, KIND_TEXT),
            "node_type": BoundField(Position.node_type, KIND_TEXT, nullable_source=Position.node_type),
        },
        json_fields={
            # `col[key].as_string()` is the idiom this codebase already uses
            # with a variable key (costs/repository.py). SQLAlchemy binds the
            # key as a parameter, so the scheme can be din276, masterformat,
            # nrm or an estimator's own `tipo` without the catalog knowing any
            # of them in advance. A row whose classification lacks the key
            # reads NULL and lands in the null group rather than being
            # dropped, which is the same treatment every other nullable field
            # gets here.
            "classification": lambda key: BoundField(
                Position.classification[key].as_string(),
                KIND_TEXT,
                nullable_source=Position.classification[key].as_string(),
            ),
        },
    )


def _bind_boq() -> BoundEntity:
    from app.modules.boq.models import BOQ

    return BoundEntity(
        model=BOQ,
        project_column=BOQ.project_id,
        period_column=BOQ.created_at,
        joins=[],
        # The bill itself, so narrowing to one estimate leaves one row and
        # ``count`` reads 1 rather than the project's estimate count.
        boq_column=BOQ.id,
        fields={
            "name": BoundField(BOQ.name, KIND_TEXT),
            "status": BoundField(BOQ.status, KIND_TEXT),
            "estimate_type": BoundField(BOQ.estimate_type, KIND_TEXT, nullable_source=BOQ.estimate_type),
            "is_locked": BoundField(BOQ.is_locked, KIND_BOOL),
        },
    )


def _bind_project() -> BoundEntity:
    from app.modules.projects.models import Project

    # ``gross_floor_area``, ``contract_value`` and ``budget_estimate`` are all
    # decimal-strings for the same reason the BOQ money columns are, so they
    # need the same tolerant coercion - and, more importantly, the same
    # ``nullable_source``. ``numeric_value`` reads a NULL text column as 0 on
    # PostgreSQL, so without it ``min(gross_floor_area)`` over a portfolio
    # where one project records an area and thirteen do not comes back 0, and
    # ``avg`` divides one building by fourteen.
    return BoundEntity(
        model=Project,
        project_column=Project.id,
        period_column=Project.created_at,
        joins=[],
        fields={
            "gross_floor_area": BoundField(
                numeric_value(Project.gross_floor_area),
                KIND_NUMERIC,
                nullable_source=Project.gross_floor_area,
            ),
            "contract_value": BoundField(
                numeric_value(Project.contract_value),
                KIND_NUMERIC,
                nullable_source=Project.contract_value,
            ),
            "budget_estimate": BoundField(
                numeric_value(Project.budget_estimate),
                KIND_NUMERIC,
                nullable_source=Project.budget_estimate,
            ),
            "name": BoundField(Project.name, KIND_TEXT),
            "status": BoundField(Project.status, KIND_TEXT),
            "phase": BoundField(Project.phase, KIND_TEXT, nullable_source=Project.phase),
            "project_code": BoundField(Project.project_code, KIND_TEXT, nullable_source=Project.project_code),
            "project_type": BoundField(Project.project_type, KIND_TEXT, nullable_source=Project.project_type),
            "country_code": BoundField(Project.country_code, KIND_TEXT),
            "currency": BoundField(Project.currency, KIND_TEXT),
            "parent_project_id": BoundField(
                Project.parent_project_id,
                KIND_UUID,
                nullable_source=Project.parent_project_id,
            ),
        },
    )


def _bind_boq_markup() -> BoundEntity:
    from app.modules.boq.models import BOQ, BOQMarkup

    # Scoped through the same join the positions use, for the same reason: a
    # markup has no project of its own, and a KPI that could not be narrowed
    # to a project would be the one read on the dashboard that ignores which
    # project the dashboard is showing.
    return BoundEntity(
        model=BOQMarkup,
        project_column=BOQ.project_id,
        period_column=BOQMarkup.created_at,
        joins=[(BOQ, BOQMarkup.boq_id == BOQ.id)],
        # The reason this entity is worth narrowing at all: margin is the
        # textbook case of a figure that means one thing per estimate and
        # nothing averaged across the estimates of one project.
        boq_column=BOQMarkup.boq_id,
        fields={
            # Both NOT NULL with a "0" default, so an inactive or unused half
            # of a line reads as zero rather than as absent - which is what it
            # means here, unlike a price date nobody recorded.
            "percentage": BoundField(numeric_value(BOQMarkup.percentage), KIND_NUMERIC),
            "fixed_amount": BoundField(numeric_value(BOQMarkup.fixed_amount), KIND_NUMERIC),
            "name": BoundField(BOQMarkup.name, KIND_TEXT),
            "markup_type": BoundField(BOQMarkup.markup_type, KIND_TEXT),
            "category": BoundField(BOQMarkup.category, KIND_TEXT),
            "apply_to": BoundField(BOQMarkup.apply_to, KIND_TEXT),
            "is_active": BoundField(BOQMarkup.is_active, KIND_BOOL),
            "boq_id": BoundField(BOQMarkup.boq_id, KIND_UUID),
            "boq_name": BoundField(BOQ.name, KIND_TEXT),
            # NULL means bill-wide, which is the ordinary case rather than a
            # missing value, so ``is_null`` on it is how a spec asks for the
            # company standard as against a section's own exception.
            "scope_position_id": BoundField(
                BOQMarkup.scope_position_id,
                KIND_UUID,
                nullable_source=BOQMarkup.scope_position_id,
            ),
        },
    )


def _bind_cost_item_usage() -> BoundEntity:
    from app.modules.costs.models import CostItem, CostItemUsage

    # The ledger carries the project; the item carries the price date. Neither
    # alone answers "how old are the prices this project is built on", which is
    # why this entity is the join rather than either table.
    return BoundEntity(
        model=CostItemUsage,
        project_column=CostItemUsage.project_id,
        period_column=CostItemUsage.used_at,
        joins=[(CostItem, CostItemUsage.cost_item_id == CostItem.id)],
        fields={
            "price_age_days": BoundField(
                days_since(CostItem.price_as_of),
                KIND_NUMERIC,
                nullable_source=CostItem.price_as_of,
            ),
            # Numeric(18, 4) rather than text, so no coercion and no null
            # source: the ledger always records what the rate was.
            "unit_rate_at_use": BoundField(CostItemUsage.unit_rate_at_use, KIND_NUMERIC),
            "cost_item_id": BoundField(CostItemUsage.cost_item_id, KIND_UUID),
            "cost_item_code": BoundField(CostItem.code, KIND_TEXT),
            "cost_item_description": BoundField(CostItem.description, KIND_TEXT),
            "unit": BoundField(CostItem.unit, KIND_TEXT),
            "currency": BoundField(CostItem.currency, KIND_TEXT),
            "region": BoundField(CostItem.region, KIND_TEXT, nullable_source=CostItem.region),
            "context": BoundField(CostItemUsage.context, KIND_TEXT),
        },
    )


def _bind_schedule_activity() -> BoundEntity:
    from app.modules.schedule.models import Activity, Schedule

    # ``progress_pct`` is a String column like the BOQ money columns and gets
    # the same tolerant coercion; ``duration_days`` and the two floats are
    # real Integers and need none. The floats are nullable because CPM writes
    # them and may not have run, so they carry a null source and drop out of
    # averages rather than reading as zero slack.
    return BoundEntity(
        model=Activity,
        project_column=Schedule.project_id,
        period_column=Activity.created_at,
        joins=[(Schedule, Activity.schedule_id == Schedule.id)],
        fields={
            "duration_days": BoundField(Activity.duration_days, KIND_NUMERIC),
            "total_float": BoundField(
                Activity.total_float,
                KIND_NUMERIC,
                nullable_source=Activity.total_float,
            ),
            "free_float": BoundField(
                Activity.free_float,
                KIND_NUMERIC,
                nullable_source=Activity.free_float,
            ),
            "progress_pct": BoundField(numeric_value(Activity.progress_pct), KIND_NUMERIC),
            "sort_order": BoundField(Activity.sort_order, KIND_NUMERIC),
            "is_critical": BoundField(Activity.is_critical, KIND_BOOL),
            "schedule_id": BoundField(Activity.schedule_id, KIND_UUID),
            "schedule_name": BoundField(Schedule.name, KIND_TEXT),
            "parent_id": BoundField(Activity.parent_id, KIND_UUID, nullable_source=Activity.parent_id),
            "name": BoundField(Activity.name, KIND_TEXT),
            "wbs_code": BoundField(Activity.wbs_code, KIND_TEXT),
            "status": BoundField(Activity.status, KIND_TEXT),
            "activity_type": BoundField(Activity.activity_type, KIND_TEXT),
            "activity_code": BoundField(
                Activity.activity_code,
                KIND_TEXT,
                nullable_source=Activity.activity_code,
            ),
        },
    )


_BINDERS: dict[str, Callable[[], BoundEntity]] = {
    "boq_position": _bind_boq_position,
    "boq": _bind_boq,
    "project": _bind_project,
    "boq_markup": _bind_boq_markup,
    "cost_item_usage": _bind_cost_item_usage,
    "schedule_activity": _bind_schedule_activity,
}


def bind_entity(name: str) -> BoundEntity:
    """Resolve one catalog entity to ORM expressions.

    Raises:
        ImportError: The source module is not installed. Callers in the
            compute path turn this into a zero reading, the same way every
            built-in formula does.
    """
    return _BINDERS[name]()


def check_catalog_binding_parity() -> dict[str, dict[str, list[str]]]:
    """Compare the declared catalog against what the binders actually build.

    Returns a per-entity report of the differences, empty when the two
    agree. Kept as a function rather than an assertion so the caller
    decides whether a mismatch is a test failure or a log line.
    """
    report: dict[str, dict[str, list[str]]] = {}
    for name, entry in ENTITY_CATALOG.items():
        try:
            bound = bind_entity(name)
        except ImportError:  # pragma: no cover - source module absent
            report[name] = {"unbindable": [entry.source_module]}
            continue
        except KeyError:
            # A catalog entry with no binder at all. This used to escape the
            # check rather than be reported by it: `_BINDERS[name]` raises
            # KeyError, which is not an ImportError, so the parity test died
            # with a traceback naming the dict instead of failing with the
            # entity that was left half-added. That is the exact mistake the
            # check exists to catch, and it is the likeliest one, because
            # declaring an entity and binding it are two edits in two places.
            report[name] = {"unbound_entity": [name]}
            continue
        declared = set(entry.fields)
        built = set(bound.fields)
        wrong_kind = sorted(n for n in declared & built if entry.fields[n] != bound.resolve_field(n).kind)
        # A display name is a promise that grouping by one field can be
        # read through another, and the promise is kept by whoever writes
        # the catalog rather than by the type system. Either half naming a
        # field that is not declared makes the default silently do
        # nothing, and a numeric name is one the label rule rejects at
        # creation time - a spec the server itself generated.
        bad_display_name = sorted(
            f"{id_field}->{name_field}"
            for id_field, name_field in entry.display_name_for.items()
            if id_field not in declared or name_field not in declared or entry.fields[name_field] == KIND_NUMERIC
        )
        # The same parity question for the JSON columns, which need it more
        # than the plain fields rather than less. A plain field that is
        # declared and not bound fails the moment anybody uses it. A JSON
        # column that is declared and not bound is worse: the catalog offers
        # `classification.<key>` to the picker, validation accepts the path
        # because the catalog is what validation reads, the definition is
        # stored, and the failure arrives at compute time on a KPI somebody
        # has already put on a dashboard.
        declared_json = set(entry.json_fields)
        built_json = set(bound.json_fields)
        wrong_json_kind = sorted(
            n for n in declared_json & built_json if entry.json_fields[n] != bound.json_fields[n]("probe").kind
        )
        # And the same question for the estimate dimension. A catalog that
        # promises ``narrows_to_estimate`` while its binder holds no column
        # is the JSON case again in a worse place: the definition is accepted
        # with ``scope="estimate"``, stored, put on a dashboard, and the
        # narrowing silently does not happen - every estimate reads the
        # project's number under its own name, which looks like data.
        estimate_scope_mismatch = (
            ["declared but no column bound"]
            if entry.narrows_to_estimate and bound.boq_column is None
            else ["column bound but not declared"]
            if bound.boq_column is not None and not entry.narrows_to_estimate
            else []
        )
        diff = {
            "declared_only": sorted(declared - built),
            "bound_only": sorted(built - declared),
            "kind_mismatch": wrong_kind,
            "bad_display_name": bad_display_name,
            "json_declared_only": sorted(declared_json - built_json),
            "json_bound_only": sorted(built_json - declared_json),
            "json_kind_mismatch": wrong_json_kind,
            "estimate_scope_mismatch": estimate_scope_mismatch,
        }
        if any(diff.values()):
            report[name] = diff
    return report


def entity_narrows_to_estimate(name: str) -> bool:
    """Whether one value of this entity belongs to exactly one estimate.

    Reads the catalog rather than the binding, so the answer is the same
    whether or not the source module is installed - a definition is
    accepted or refused at creation time, and that decision cannot depend
    on which modules happen to be loaded on the machine taking the call.
    """
    entry = ENTITY_CATALOG.get(name)
    return bool(entry and entry.narrows_to_estimate)


# ── Validation ─────────────────────────────────────────────────────────


def _require_str(spec: dict[str, Any], key: str, path: str) -> str:
    value = spec.get(key)
    if not isinstance(value, str) or not value.strip():
        raise KPISpecError(path, f"expected a non-empty string, got {value!r}.", value=value)
    return value.strip()


def _lookup_field(entry: CatalogEntity, name: Any, path: str) -> str:
    if isinstance(name, str) and entry.kind_of(name) is not None:
        return name
    # A dotted name that got here either names an undeclared column or
    # carries a key this will not accept, and those are different mistakes.
    # Saying which one saves the author guessing, since neither is visible
    # in the list of allowed names: the column is in it, the path is not.
    if isinstance(name, str) and "." in name:
        column, _, key = name.partition(".")
        if column not in entry.json_fields:
            raise KPISpecError(
                path,
                f"'{column}' is not a JSON column on entity '{entry.name}', so '{name}' cannot name a key in it.",
                value=name,
                allowed=sorted(entry.json_fields) or sorted(entry.fields),
            )
        raise KPISpecError(
            path,
            f"'{key}' is not a usable key: a key starts with a letter and continues with "
            f"letters, digits or underscores, up to 64 characters.",
            value=name,
        )
    raise KPISpecError(
        path,
        f"unknown field {name!r} on entity '{entry.name}'.",
        value=name,
        allowed=sorted(entry.fields),
    )


def _require_numeric(entry: CatalogEntity, name: str, path: str) -> None:
    kind = entry.kind_of(name)
    if kind != KIND_NUMERIC:
        raise KPISpecError(
            path,
            f"field '{name}' is {kind}, and this aggregation needs a numeric field.",
            value=name,
            allowed=entry.numeric_fields(),
        )


def _validate_filter(entry: CatalogEntity, raw: Any, path: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise KPISpecError(path, f"expected an object with field/op/value, got {type(raw).__name__}.", value=raw)
    name = _lookup_field(entry, raw.get("field"), f"{path}.field")
    op = raw.get("op")
    if op not in FILTER_OPERATORS:
        raise KPISpecError(
            f"{path}.op",
            f"unknown operator {op!r}.",
            value=op,
            allowed=list(FILTER_OPERATORS),
        )
    # `kind_of` rather than a direct index, so a `<column>.<key>` path is
    # filterable on the same terms as the plain field it sits beside.
    kind = entry.kind_of(name)
    if op in _ORDERING_OPERATORS and kind != KIND_NUMERIC:
        raise KPISpecError(
            f"{path}.op",
            f"operator '{op}' needs a numeric field, and '{name}' is {kind}.",
            value=op,
            allowed=["eq", "ne", "in", "is_null", "not_null"],
        )
    value = raw.get("value")
    if op in _VALUELESS_OPERATORS:
        if value is not None:
            raise KPISpecError(f"{path}.value", f"operator '{op}' takes no value.", value=value)
        return {"field": name, "op": op, "value": None}
    if op == "in":
        if not isinstance(value, list) or not value:
            raise KPISpecError(f"{path}.value", "operator 'in' needs a non-empty list.", value=value)
        if len(value) > MAX_IN_VALUES:
            raise KPISpecError(
                f"{path}.value",
                f"operator 'in' accepts at most {MAX_IN_VALUES} values, got {len(value)}.",
                value=len(value),
            )
        if any(isinstance(v, (dict, list)) for v in value):
            raise KPISpecError(f"{path}.value", "operator 'in' accepts scalars only.", value=value)
        # Every member has to be a value the column could hold - a list is
        # not a way in past the type check its scalar sibling gets.
        return {
            "field": name,
            "op": op,
            "value": [_check_value_kind(kind, name, v, f"{path}.value[{i}]") for i, v in enumerate(value)],
        }
    if value is None:
        raise KPISpecError(f"{path}.value", f"operator '{op}' needs a value.", value=None)
    if isinstance(value, (dict, list)):
        raise KPISpecError(f"{path}.value", "expected a scalar value.", value=value)
    return {"field": name, "op": op, "value": _check_value_kind(kind, name, value, f"{path}.value")}


def _check_value_kind(kind: str, name: str, value: Any, path: str) -> Any:
    """Refuse a filter value the field's column could never answer to.

    The kind decided which operators the field accepts; it has to decide
    the value's shape too, and for the same reason. What the compute path
    does with the value is dialect-level and unforgiving: a bool where a
    number belongs becomes ``Decimal("True")``, a string where a boolean
    belongs is something the driver refuses to encode, and either failure
    is caught upstream and returned as an empty computation. The tile then
    reads zero forever and looks exactly like a measurement, which is the
    outcome checking at creation time exists to prevent.

    Args:
        kind: The field's kind from the catalog.
        name: The field name, for the message.
        value: The submitted value.
        path: Dotted path into the spec, for the error.

    Returns:
        The value in its stored form - identical except for a UUID, which
        is normalised to its canonical spelling.

    Raises:
        KPISpecError: The value does not fit the field's kind.
    """
    if kind == KIND_NUMERIC:
        # ``isinstance(True, int)`` is True, so the bool test has to come
        # first: left to the numeric acceptance below, a flag would be
        # taken for a quantity and only fail at compute time.
        if isinstance(value, bool) or (not isinstance(value, (int, float, Decimal)) and not _looks_numeric(value)):
            raise KPISpecError(
                path,
                f"field '{name}' is numeric, so its filter value must be a number.",
                value=value,
            )
        # Being a number is not enough - it has to be one arithmetic can
        # use. ``Decimal`` parses ``NaN``, ``sNaN`` and ``Infinity``, and
        # ``json.loads`` accepts all three as bare tokens, so each one
        # walks through the acceptance above and then fails silently:
        # a comparison against NaN is never true, so the filter keeps no
        # row and the tile reads zero forever; an infinity does the same
        # from the other end; ``sNaN`` raises inside the compute path,
        # which catches everything and returns an empty computation. Three
        # spellings, one symptom, and it is the symptom validation at
        # creation time exists to prevent.
        if not _is_finite(value):
            raise KPISpecError(
                path,
                f"field '{name}' is numeric, so its filter value must be a finite number.",
                value=value,
            )
        return value
    if kind == KIND_BOOL:
        if not isinstance(value, bool):
            raise KPISpecError(
                path,
                f"field '{name}' is boolean, so its filter value must be true or false.",
                value=value,
            )
        return value
    if kind == KIND_UUID:
        try:
            canonical = str(uuid.UUID(str(value)))
        except (AttributeError, TypeError, ValueError):
            raise KPISpecError(
                path,
                f"field '{name}' holds a UUID, so its filter value must be one.",
                value=value,
            ) from None
        # Ids are stored in their canonical lower-case spelling, so an
        # equally valid uppercase or braced form would match no row at
        # all. Normalising here is the difference between a filter that
        # works and one that reads zero without saying why.
        return canonical
    if kind == KIND_TEXT and not isinstance(value, str):
        raise KPISpecError(
            path,
            f"field '{name}' is text, so its filter value must be a string.",
            value=value,
        )
    return value


def _looks_numeric(value: Any) -> bool:
    try:
        Decimal(str(value))
    except Exception:
        return False
    return True


def _is_finite(value: Any) -> bool:
    """True when ``value`` is a number the compute path can compare against."""
    try:
        return Decimal(str(value)).is_finite()
    except Exception:
        return False


def validate_spec(raw: Any) -> dict[str, Any]:
    """Validate a submitted spec and return its normalised form.

    Every rejection is a :class:`KPISpecError` naming the path into the
    spec that failed, so the caller learns which part was refused instead
    of being told the document is bad.

    Args:
        raw: The ``spec`` object as submitted.

    Returns:
        The normalised spec - same shape, unknown keys dropped, strings
        stripped. This is what gets persisted, so what computes later is
        what validation looked at.

    Raises:
        KPISpecError: The spec names an entity, field, aggregation or
            operator outside the whitelist, or breaks one of the
            per-aggregation rules.
    """
    if not isinstance(raw, dict):
        raise KPISpecError("spec", f"expected an object, got {type(raw).__name__}.", value=raw)

    entity_name = _require_str(raw, "entity", "spec.entity")
    entry = ENTITY_CATALOG.get(entity_name)
    if entry is None:
        raise KPISpecError(
            "spec.entity",
            f"unknown entity {entity_name!r}.",
            value=entity_name,
            allowed=sorted(ENTITY_CATALOG),
        )

    aggregation = _require_str(raw, "aggregation", "spec.aggregation")
    if aggregation not in AGGREGATIONS:
        raise KPISpecError(
            "spec.aggregation",
            f"unknown aggregation {aggregation!r}.",
            value=aggregation,
            allowed=list(AGGREGATIONS),
        )

    normalised: dict[str, Any] = {"entity": entity_name, "aggregation": aggregation}

    field_name = raw.get("field")
    if aggregation in _FIELD_REQUIRED:
        if field_name is None:
            raise KPISpecError(
                "spec.field",
                f"aggregation '{aggregation}' needs a numeric field.",
                allowed=entry.numeric_fields(),
            )
        field_name = _lookup_field(entry, field_name, "spec.field")
        _require_numeric(entry, field_name, "spec.field")
        normalised["field"] = field_name
    elif field_name is not None:
        raise KPISpecError(
            "spec.field",
            "aggregation 'count' counts rows and must not name a field.",
            value=field_name,
        )

    weight = raw.get("weight_field")
    if aggregation == "weighted_avg":
        if weight is None:
            raise KPISpecError(
                "spec.weight_field",
                "aggregation 'weighted_avg' needs a numeric weight field.",
                allowed=entry.numeric_fields(),
            )
        weight = _lookup_field(entry, weight, "spec.weight_field")
        _require_numeric(entry, weight, "spec.weight_field")
        normalised["weight_field"] = weight
    elif weight is not None:
        raise KPISpecError(
            "spec.weight_field",
            f"aggregation '{aggregation}' takes no weight field.",
            value=weight,
        )

    group_by = raw.get("group_by")
    if group_by is not None:
        group_by = _lookup_field(entry, group_by, "spec.group_by")
        if entry.kind_of(group_by) == KIND_NUMERIC:
            raise KPISpecError(
                "spec.group_by",
                f"field '{group_by}' is numeric, and a breakdown keyed by a measure is one bucket per amount.",
                value=group_by,
                allowed=entry.groupable_fields(),
            )
        normalised["group_by"] = group_by

    # Read after ``group_by``, because what decides whether a label makes
    # sense is whether the spec produces rows to label. It used to be
    # decided by the aggregation alone, which refused a label to every
    # breakdown that was not ``top_by``: an amount per bid came back keyed
    # by a raw ``boq_id``, and the one thing that would have made those
    # keys readable was the thing being refused.
    label = raw.get("label_field")
    if label is not None:
        if aggregation != "top_by" and "group_by" not in normalised:
            raise KPISpecError(
                "spec.label_field",
                "a label names the rows of a breakdown, so it needs 'group_by' or the 'top_by' aggregation.",
                value=label,
            )
        label = _lookup_field(entry, label, "spec.label_field")
        if entry.kind_of(label) == KIND_NUMERIC:
            raise KPISpecError(
                "spec.label_field",
                f"field '{label}' is numeric, and a label must be something a reader can name a row by.",
                value=label,
                allowed=entry.groupable_fields(),
            )
        normalised["label_field"] = label
    elif "group_by" in normalised:
        # Nobody asks for a breakdown keyed by an id in order to read the
        # ids. The catalog knows which field names this one, so the
        # default is that name, written into the stored spec rather than
        # applied while computing: an existing definition keeps whatever
        # shape it was created with, and the author can see what they got
        # and change it. Absent a declared name there is nothing to
        # default to, and the group stays a bare value.
        default_label = entry.display_name_for.get(normalised["group_by"])
        if default_label is not None:
            normalised["label_field"] = default_label

    raw_filters = raw.get("filters") or []
    if not isinstance(raw_filters, list):
        raise KPISpecError("spec.filters", f"expected a list, got {type(raw_filters).__name__}.", value=raw_filters)
    normalised["filters"] = [
        _validate_filter(entry, item, f"spec.filters[{idx}]") for idx, item in enumerate(raw_filters)
    ]
    return normalised


def source_modules_for(spec: dict[str, Any]) -> list[str]:
    """The modules a validated spec reads from, derived rather than declared."""
    entry = ENTITY_CATALOG.get(str(spec.get("entity", "")))
    return [entry.source_module] if entry else []


# ── Evaluation ─────────────────────────────────────────────────────────


@dataclass
class SpecResult:
    """What an evaluated spec produces.

    Deliberately not ``KPIComputation``: this module must not import the
    152 KB formula registry, and the registry converts on the way out.
    """

    value: Decimal = Decimal("0")
    source_record_count: int = 0
    breakdown: dict[str, Any] = field(default_factory=dict)


def _apply_filters(stmt: Any, bound: BoundEntity, filters: list[dict[str, Any]]) -> Any:
    for item in filters:
        bf = bound.resolve_field(item["field"])
        op = item["op"]
        value = item["value"]
        if op == "is_null":
            stmt = stmt.where((bf.nullable_source if bf.nullable_source is not None else bf.expr).is_(None))
            continue
        if op == "not_null":
            stmt = stmt.where((bf.nullable_source if bf.nullable_source is not None else bf.expr).is_not(None))
            continue
        # A comparison against NULL is NULL in SQL, so the row drops out -
        # except that ``numeric_value`` reads a NULL text column as 0 on
        # PostgreSQL, which would make "confidence below 0.5" quietly
        # collect every position nobody has scored yet. Restore the
        # ordinary semantics: an unset value is not a low value. Asking
        # for the unscored rows is what ``is_null`` is for.
        if bf.nullable_source is not None:
            stmt = stmt.where(bf.nullable_source.is_not(None))
        if op == "in":
            stmt = stmt.where(bf.expr.in_(value))
            continue
        rhs: Any = float(Decimal(str(value))) if bf.kind == KIND_NUMERIC else value
        if op == "eq":
            stmt = stmt.where(bf.expr == rhs)
        elif op == "ne":
            stmt = stmt.where(bf.expr != rhs)
        elif op == "lt":
            stmt = stmt.where(bf.expr < rhs)
        elif op == "lte":
            stmt = stmt.where(bf.expr <= rhs)
        elif op == "gt":
            stmt = stmt.where(bf.expr > rhs)
        elif op == "gte":
            stmt = stmt.where(bf.expr >= rhs)
    return stmt


def _base_predicates(
    stmt: Any,
    bound: BoundEntity,
    spec: dict[str, Any],
    *,
    project_id: uuid.UUID | None,
    period_start: _date | None,
    period_end: _date | None,
    allowed_project_ids: set[uuid.UUID] | None,
    boq_id: uuid.UUID | None = None,
) -> Any:
    from app.modules.bi_dashboards.kpis import _scope_portfolio

    for target, onclause in bound.joins:
        stmt = stmt.join(target, onclause)
    if project_id is not None:
        stmt = stmt.where(bound.project_column == project_id)
    if boq_id is not None:
        # Refused rather than ignored. An entity with no estimate of its own
        # would otherwise answer with the project's figure, and the caller
        # asked for one estimate: a wrong number under the right label is the
        # failure this module is built around, and it is invisible because it
        # is the right ORDER of magnitude.
        if bound.boq_column is None:
            raise KPISpecError(
                "entity",
                f"entity '{spec.get('entity')}' has no estimate of its own, so it cannot be "
                f"narrowed to one. Its rows belong to a project.",
                value=spec.get("entity"),
                allowed=sorted(n for n, e in ENTITY_CATALOG.items() if e.narrows_to_estimate),
            )
        stmt = stmt.where(bound.boq_column == boq_id)
    # Same portfolio narrowing every built-in formula gets. A custom KPI
    # is not allowed to be the one read that ignores it.
    stmt = _scope_portfolio(stmt, bound.project_column, project_id, allowed_project_ids)
    if period_start is not None:
        stmt = stmt.where(bound.period_column >= datetime.combine(period_start, time.min, tzinfo=UTC))
    if period_end is not None:
        stmt = stmt.where(bound.period_column < datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=UTC))
    stmt = _apply_filters(stmt, bound, spec.get("filters") or [])
    # A row whose measure is unset is not a zero-valued row. Leaving it in
    # would read an estimator's "not scored yet" as "scored zero", which is
    # the quiet wrong answer this whole module is built to avoid.
    value_field = spec.get("field")
    weight_field = spec.get("weight_field")
    for name in (value_field, weight_field):
        if name is None:
            continue
        src = bound.resolve_field(name).nullable_source
        if src is not None:
            stmt = stmt.where(src.is_not(None))
    return stmt


def _measures(bound: BoundEntity, spec: dict[str, Any]) -> list[Any]:
    """The aggregate columns for one aggregation, in evaluation order."""
    aggregation = spec["aggregation"]
    if aggregation == "count":
        return [func.count()]
    expr = bound.resolve_field(spec["field"]).expr
    if aggregation == "sum":
        return [func.sum(expr)]
    if aggregation == "avg":
        return [func.avg(expr)]
    if aggregation == "min":
        return [func.min(expr)]
    if aggregation == "max":
        return [func.max(expr)]
    if aggregation == "weighted_avg":
        weight = bound.resolve_field(spec["weight_field"]).expr
        return [func.sum(expr * weight), func.sum(weight)]
    # top_by is handled by its own window query
    return [func.max(expr)]


def _fold(aggregation: str, values: list[Any]) -> Decimal:
    from app.modules.bi_dashboards.kpis import _safe_div, _to_decimal

    if aggregation == "weighted_avg":
        return _safe_div(_to_decimal(values[0]), _to_decimal(values[1]))
    return _to_decimal(values[0])


def _group_key(value: Any) -> str:
    """The breakdown key for one group's value.

    Args:
        value: The grouped column's value, ``None`` when the row had none.

    Returns:
        ``str(value)``, or :data:`NULL_GROUP_KEY` when there was none.
    """
    if value is None:
        return NULL_GROUP_KEY
    return str(value)


def _label_key(value: Any) -> str:
    """The label for one group, as something a reader can use.

    Unlike :func:`_group_key`, this does not have to keep two different
    values apart - the key beside it already does - so it may answer for
    the blank as well as the absent. A ``boq_name`` is NOT NULL and still
    reaches here empty: the create schema checks ``min_length`` before the
    HTML sanitiser runs, so a name of ``<script>x</script>`` is accepted
    and stored as ``''``.

    Args:
        value: The label column's value for the group.

    Returns:
        ``str(value)``, or :data:`NULL_GROUP_KEY` when there is no name in
        it for a person to read.
    """
    if value is None:
        return NULL_GROUP_KEY
    text = str(value)
    return text if text.strip() else NULL_GROUP_KEY


async def _evaluate_top_by(
    session: AsyncSession,
    bound: BoundEntity,
    spec: dict[str, Any],
    *,
    project_id: uuid.UUID | None,
    period_start: _date | None,
    period_end: _date | None,
    allowed_project_ids: set[uuid.UUID] | None,
    boq_id: uuid.UUID | None = None,
) -> SpecResult:
    """The single highest row, optionally one per group.

    A window is used rather than ``DISTINCT ON`` so the query stays
    ordinary SQL, and rather than "order and truncate" so the answer is
    exact instead of correct only while the table is small.
    """
    from app.modules.bi_dashboards.kpis import _to_decimal

    value_expr = bound.resolve_field(spec["field"]).expr
    group_name = spec.get("group_by")
    group_expr = bound.resolve_field(group_name).expr if group_name else literal(1)
    label_name = spec.get("label_field")
    label_expr = bound.resolve_field(label_name).expr if label_name else group_expr

    inner = select(
        group_expr.label("grp"),
        label_expr.label("lbl"),
        value_expr.label("val"),
        func.row_number().over(partition_by=group_expr, order_by=value_expr.desc()).label("rn"),
    ).select_from(bound.model)
    inner = _base_predicates(
        inner,
        bound,
        spec,
        project_id=project_id,
        period_start=period_start,
        period_end=period_end,
        allowed_project_ids=allowed_project_ids,
        boq_id=boq_id,
    )
    sub = inner.subquery()
    outer = (
        select(sub.c.grp, sub.c.lbl, sub.c.val)
        .where(sub.c.rn == 1)
        .order_by(sub.c.val.desc())
        .limit(MAX_BREAKDOWN_GROUPS)
    )
    rows = (await session.execute(outer)).all()
    if not rows:
        return SpecResult()
    breakdown: dict[str, Any] = {}
    if group_name:
        for grp, lbl, val in rows:
            breakdown[_group_key(grp)] = {"label": _label_key(lbl), "value": str(_to_decimal(val))}
    else:
        breakdown["top"] = {"label": _label_key(rows[0][1]), "value": str(_to_decimal(rows[0][2]))}
    return SpecResult(
        value=_to_decimal(rows[0][2]),
        source_record_count=len(rows),
        breakdown=breakdown,
    )


async def evaluate_spec(
    spec: dict[str, Any],
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    period_start: _date | None = None,
    period_end: _date | None = None,
    allowed_project_ids: set[uuid.UUID] | None = None,
    boq_id: uuid.UUID | None = None,
) -> SpecResult:
    """Run a validated spec.

    The spec is trusted here because :func:`validate_spec` ran before it
    was stored - every name below is a dictionary key into the binding,
    so an entry that got past validation cannot address anything the
    whitelist does not hold.

    Args:
        spec: A normalised spec as returned by :func:`validate_spec`.
        session: Database session.
        project_id: Restrict to one project, already access-checked by
            the caller.
        period_start: Include rows created on or after this date.
        period_end: Include rows created on or before this date.
        allowed_project_ids: The caller's accessible projects, applied in
            portfolio mode exactly as the built-in formulas apply it.
        boq_id: Narrow to one estimate. ``None`` is the whole project,
            which is what every reading was before this existed. The
            caller is responsible for having access-checked the project
            the estimate belongs to - passing an estimate id alone must
            not be a way around ``allowed_project_ids``.

    Returns:
        The aggregate, the number of rows behind it, and the per-group
        breakdown when the spec asked for one.

    Raises:
        KPISpecError: An estimate was asked for on an entity whose rows do
            not belong to one.
    """
    bound = bind_entity(spec["entity"])
    aggregation = spec["aggregation"]
    if aggregation == "top_by":
        return await _evaluate_top_by(
            session,
            bound,
            spec,
            project_id=project_id,
            period_start=period_start,
            period_end=period_end,
            allowed_project_ids=allowed_project_ids,
            boq_id=boq_id,
        )

    measures = _measures(bound, spec)
    headline = select(*measures, func.count().label("n")).select_from(bound.model)
    headline = _base_predicates(
        headline,
        bound,
        spec,
        project_id=project_id,
        period_start=period_start,
        period_end=period_end,
        allowed_project_ids=allowed_project_ids,
        boq_id=boq_id,
    )
    row = (await session.execute(headline)).one()
    values = list(row)
    record_count = int(values.pop())
    result = SpecResult(
        value=_fold(aggregation, values),
        source_record_count=record_count,
    )

    group_name = spec.get("group_by")
    if group_name:
        group_expr = bound.resolve_field(group_name).expr
        # The label is aggregated rather than added to GROUP BY. Grouping
        # by both would split one group into a row per distinct label, and
        # both rows assign into ``breakdown[key]`` - the later write wins
        # and a group disappears, the same silent loss ``NULL_GROUP_KEY``
        # was introduced for. ``min`` keeps exactly one row per group and
        # picks the same label every run.
        label_name = spec.get("label_field")
        label_measures = [func.min(bound.resolve_field(label_name).expr).label("lbl")] if label_name else []
        grouped = select(group_expr.label("grp"), *label_measures, *measures).select_from(bound.model)
        grouped = _base_predicates(
            grouped,
            bound,
            spec,
            project_id=project_id,
            period_start=period_start,
            period_end=period_end,
            allowed_project_ids=allowed_project_ids,
            boq_id=boq_id,
        )
        # ``count`` has no measure to rank by, so groups come back by key.
        order = cast(measures[0], Integer).desc() if aggregation == "count" else measures[0].desc()
        grouped = grouped.group_by(group_expr).order_by(order).limit(MAX_BREAKDOWN_GROUPS)
        for grow in (await session.execute(grouped)).all():
            parts = list(grow)
            key = _group_key(parts.pop(0))
            # With a label the group becomes the same ``{label, value}``
            # record ``top_by`` returns, so one consumer reads both. Without
            # one it stays a bare value string, because changing that shape
            # for every existing breakdown would be a silent contract break
            # for the widgets already reading them.
            if label_name:
                label_value = _label_key(parts.pop(0))
                result.breakdown[key] = {"label": label_value, "value": str(_fold(aggregation, parts))}
            else:
                result.breakdown[key] = str(_fold(aggregation, parts))
    return result


# ── Definition lookup ──────────────────────────────────────────────────


@dataclass(frozen=True)
class LoadedSpec:
    """One stored custom KPI, as the compute path needs it.

    A record rather than a tuple because ``scope`` joined it later: an
    unpacking call site would have kept working with the wrong number of
    names in exactly one of the two places, and the compute path is where
    a mistake becomes a number on a dashboard.
    """

    spec: dict[str, Any]
    unit: str
    scope: str


async def load_custom_spec(session: AsyncSession, code: str) -> LoadedSpec | None:
    """Fetch the stored spec for a custom KPI code.

    Returns ``None`` when the code has no definition row or its row
    carries no spec (every system KPI is the latter).
    """
    stmt = select(KPIDefinition.spec_json, KPIDefinition.unit, KPIDefinition.scope).where(KPIDefinition.code == code)
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    spec, unit, scope = row
    if not isinstance(spec, dict) or not spec:
        return None
    return LoadedSpec(spec=spec, unit=unit or "ratio", scope=scope or SCOPE_PROJECT)


__all__ = [
    "AGGREGATIONS",
    "ENTITY_CATALOG",
    "FILTER_OPERATORS",
    "MAX_BREAKDOWN_GROUPS",
    "MAX_IN_VALUES",
    "NULL_GROUP_KEY",
    "KPI_SCOPES",
    "SCOPE_ESTIMATE",
    "SCOPE_PROJECT",
    "BoundEntity",
    "BoundField",
    "CatalogEntity",
    "KPISpecError",
    "LoadedSpec",
    "SpecResult",
    "bind_entity",
    "catalog_as_dict",
    "check_catalog_binding_parity",
    "entity_narrows_to_estimate",
    "evaluate_spec",
    "load_custom_spec",
    "source_modules_for",
    "validate_spec",
]
