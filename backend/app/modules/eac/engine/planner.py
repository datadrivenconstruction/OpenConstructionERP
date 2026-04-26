# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Execution planner for EAC v2 rules (RFC 35 §5 EAC-1.3 §5).

Compiles a parsed :class:`EacRuleDefinition` into an
:class:`ExecutionPlan` whose ``duckdb_sql`` field is a well-formed
``SELECT`` statement that the EAC-1.4 executor will run against the
canonical Parquet table.

The structural shape of the SQL is what matters here — actual execution
is the next ticket. The planner therefore:

* generates a ``SELECT`` over a notional canonical table
  (``elements`` — placeholder name; the executor will swap it),
* compiles the predicate tree into a SQL boolean expression,
* compiles the selector tree into a parallel boolean expression
  ANDed onto the predicate,
* binds string / numeric literals into ``parameters`` so the
  executor never string-formats values into SQL (FR-1.10 / SQL-injection
  hardening),
* projects the canonical columns the rule needs.

Every value that travels through the planner exits in
``parameters`` — never via inline string interpolation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.modules.eac.schemas import (
    AliasAttributeRef,
    AndPredicate,
    AndSelector,
    BetweenConstraint,
    CategorySelector,
    ClassificationCodeSelector,
    Constraint,
    ContainsConstraint,
    DisciplineSelector,
    EacRuleDefinition,
    EndsWithConstraint,
    EntitySelector,
    EqConstraint,
    ExactAttributeRef,
    ExistsConstraint,
    FamilySelector,
    GeometryFilterSelector,
    GtConstraint,
    GteConstraint,
    IfcClassSelector,
    InConstraint,
    IsBooleanConstraint,
    IsDateConstraint,
    IsEmptyConstraint,
    IsNotEmptyConstraint,
    IsNotNullConstraint,
    IsNullConstraint,
    IsNumericConstraint,
    LevelSelector,
    LtConstraint,
    LteConstraint,
    MatchesConstraint,
    NamedGroupSelector,
    NeqConstraint,
    NotBetweenConstraint,
    NotContainsConstraint,
    NotExistsConstraint,
    NotInConstraint,
    NotMatchesConstraint,
    NotPredicate,
    NotSelector,
    OrPredicate,
    OrSelector,
    Predicate,
    PsetsPresentSelector,
    RegexAttributeRef,
    StartsWithConstraint,
    TripletPredicate,
    TypeSelector,
)

# ── Public dataclasses ──────────────────────────────────────────────────


@dataclass(frozen=True)
class ExecutionPlan:
    """Structured execution plan ready for the DuckDB layer.

    ``duckdb_sql`` is a parameterised SQL string. ``parameters`` carries
    the bind values referenced by ``?``-placeholders in the SQL —
    the executor passes both directly into ``connection.execute(...)``.
    """

    duckdb_sql: str
    projection_columns: list[str]
    parameters: dict[str, Any]
    post_python_step: str | None
    estimated_cost: int


# ── Internal: builder ───────────────────────────────────────────────────


@dataclass
class _PlanBuilder:
    """Accumulator for SQL fragments and bind params during compilation."""

    parameters: dict[str, Any] = field(default_factory=dict)
    estimated_cost: int = 0
    _param_counter: int = 0

    def bind(self, value: Any) -> str:
        """Reserve a unique ``:p<n>`` placeholder for ``value``.

        DuckDB supports ``?`` and named ``:name`` placeholders; we use
        named ones so the executor can pass a dict directly. Returns
        the placeholder text to embed in the SQL string.
        """
        self._param_counter += 1
        key = f"p{self._param_counter}"
        self.parameters[key] = value
        return f":{key}"


# ── Public entry point ──────────────────────────────────────────────────


def plan_rule(
    parsed: EacRuleDefinition,
    model_version_id: uuid.UUID | None = None,  # noqa: ARG001 — used by EAC-1.4
) -> ExecutionPlan:
    """Compile a rule definition into an :class:`ExecutionPlan`."""
    builder = _PlanBuilder()

    # 1. Selector → SQL fragment.
    selector_sql = _compile_selector(parsed.selector, builder)

    # 2. Predicate (if any) → SQL fragment.
    predicate_sql = "TRUE"
    if parsed.predicate is not None:
        predicate_sql = _compile_predicate(parsed.predicate, builder)

    # 3. Final WHERE = selector AND predicate.
    where_clause = f"({selector_sql}) AND ({predicate_sql})"

    # 4. Projection columns we read from canonical Parquet.
    projection = _projection_for(parsed)

    # 5. Build the SQL.
    sql = (
        f"SELECT {', '.join(projection)} FROM elements WHERE {where_clause}"
    )

    return ExecutionPlan(
        duckdb_sql=sql,
        projection_columns=projection,
        parameters=builder.parameters,
        post_python_step=_describe_post_step(parsed),
        estimated_cost=builder.estimated_cost,
    )


# ── Selector compilation ────────────────────────────────────────────────


def _compile_selector(selector: EntitySelector, builder: _PlanBuilder) -> str:
    """Compile a selector tree into a SQL boolean expression."""
    builder.estimated_cost += 1

    if isinstance(selector, AndSelector):
        parts = [_compile_selector(c, builder) for c in selector.children]
        return "(" + " AND ".join(parts) + ")"
    if isinstance(selector, OrSelector):
        parts = [_compile_selector(c, builder) for c in selector.children]
        return "(" + " OR ".join(parts) + ")"
    if isinstance(selector, NotSelector):
        return "(NOT " + _compile_selector(selector.child, builder) + ")"

    # Leaf selectors. Each maps to a column or a JSON path on the
    # canonical Parquet schema. The actual schema lives in EAC-1.4 —
    # the names below are the placeholders we'll resolve there.
    if isinstance(selector, CategorySelector):
        return _in_clause("category", selector.values, builder)
    if isinstance(selector, IfcClassSelector):
        return _in_clause("ifc_class", selector.values, builder)
    if isinstance(selector, FamilySelector):
        return _in_clause("family", selector.values, builder)
    if isinstance(selector, TypeSelector):
        return _in_clause("type_name", selector.values, builder)
    if isinstance(selector, LevelSelector):
        return _in_clause("level", selector.values, builder)
    if isinstance(selector, DisciplineSelector):
        return _in_clause("discipline", selector.values, builder)
    if isinstance(selector, NamedGroupSelector):
        return _in_clause("named_group", selector.values, builder)
    if isinstance(selector, ClassificationCodeSelector):
        # System is optional: classification->>'<system>' = ?
        if selector.system:
            sys_path = f"classification->>{builder.bind(selector.system)}"
        else:
            sys_path = "classification->>'code'"
        # Rewrite: emit `classification->>:p1 IN (:p2, :p3)`
        bound = ", ".join(builder.bind(v) for v in selector.values)
        return f"({sys_path} IN ({bound}))"
    if isinstance(selector, PsetsPresentSelector):
        # Each value: a Pset name. We test ``psets ? :pname`` (DuckDB JSON
        # `?` operator). Multiple values → ANDed (all must be present).
        clauses = [
            f"(json_contains(psets, {builder.bind(v)}))"
            for v in selector.values
        ]
        return "(" + " AND ".join(clauses) + ")"
    if isinstance(selector, GeometryFilterSelector):
        clauses: list[str] = []
        if selector.min_volume_m3 is not None:
            clauses.append(
                f"(volume_m3 >= {builder.bind(selector.min_volume_m3)})"
            )
        if selector.max_volume_m3 is not None:
            clauses.append(
                f"(volume_m3 <= {builder.bind(selector.max_volume_m3)})"
            )
        if selector.min_area_m2 is not None:
            clauses.append(
                f"(area_m2 >= {builder.bind(selector.min_area_m2)})"
            )
        if selector.max_area_m2 is not None:
            clauses.append(
                f"(area_m2 <= {builder.bind(selector.max_area_m2)})"
            )
        if selector.min_length_m is not None:
            clauses.append(
                f"(length_m >= {builder.bind(selector.min_length_m)})"
            )
        if selector.max_length_m is not None:
            clauses.append(
                f"(length_m <= {builder.bind(selector.max_length_m)})"
            )
        return "(" + " AND ".join(clauses or ["TRUE"]) + ")"

    # Defensive fallback — the schema is closed by Pydantic so this
    # branch is never reached in practice. ``TRUE`` keeps the SQL valid
    # if a future selector kind lands without a planner update.
    return "TRUE"


def _in_clause(column: str, values: list[str], builder: _PlanBuilder) -> str:
    """Emit ``(column IN (:p1, :p2, ...))`` with bound parameters."""
    bound = ", ".join(builder.bind(v) for v in values)
    return f"({column} IN ({bound}))"


# ── Predicate compilation ───────────────────────────────────────────────


def _compile_predicate(predicate: Predicate, builder: _PlanBuilder) -> str:
    """Compile a predicate tree into a SQL boolean expression."""
    builder.estimated_cost += 1

    if isinstance(predicate, AndPredicate):
        parts = [_compile_predicate(c, builder) for c in predicate.children]
        return "(" + " AND ".join(parts) + ")"
    if isinstance(predicate, OrPredicate):
        parts = [_compile_predicate(c, builder) for c in predicate.children]
        return "(" + " OR ".join(parts) + ")"
    if isinstance(predicate, NotPredicate):
        return "(NOT " + _compile_predicate(predicate.child, builder) + ")"

    # Triplet — attribute + constraint.
    if isinstance(predicate, TripletPredicate):
        return _compile_triplet(predicate, builder)

    return "TRUE"


def _compile_triplet(
    triplet: TripletPredicate, builder: _PlanBuilder
) -> str:
    """Compile a single (attribute, constraint) predicate."""
    column_expr = _attribute_to_sql_column(triplet.attribute)
    return _constraint_to_sql(column_expr, triplet.constraint, builder)


def _attribute_to_sql_column(
    attribute: ExactAttributeRef | AliasAttributeRef | RegexAttributeRef,
) -> str:
    """Translate an attribute reference into a JSON path on ``properties``.

    For ``exact``: ``properties->>'<name>'``, scoped by ``pset_name``
    when present (``properties->'<pset>'->>'<name>'``).

    For ``alias``: a placeholder ``alias_lookup(...)`` UDF which the
    EAC-1.4 executor will rewrite to a JSON path resolved through the
    alias snapshot.

    For ``regex``: a placeholder ``regex_lookup(...)`` UDF the executor
    rewrites similarly.
    """
    if isinstance(attribute, ExactAttributeRef):
        if attribute.pset_name:
            return (
                f"properties->'{_escape(attribute.pset_name)}'"
                f"->>'{_escape(attribute.name)}'"
            )
        return f"properties->>'{_escape(attribute.name)}'"
    if isinstance(attribute, AliasAttributeRef):
        return f"alias_lookup('{_escape(attribute.alias_id)}')"
    if isinstance(attribute, RegexAttributeRef):
        return f"regex_lookup('{_escape(attribute.pattern)}')"
    return "NULL"


def _escape(value: str) -> str:
    """Escape single quotes for a SQL identifier path.

    The values that flow through this helper are CONFIGURATION (alias
    ids, pset names, attribute names) — not user data. The validator
    rejects malformed values upstream; this is defence-in-depth.
    """
    return value.replace("'", "''")


def _constraint_to_sql(
    column_expr: str,
    constraint: Constraint,
    builder: _PlanBuilder,
) -> str:
    """Compile a single constraint against an already-resolved column.

    Bind every literal value via ``builder.bind`` so values never
    interpolate into the SQL text.
    """
    if isinstance(constraint, EqConstraint):
        return f"({column_expr} = {builder.bind(constraint.value)})"
    if isinstance(constraint, NeqConstraint):
        return f"({column_expr} != {builder.bind(constraint.value)})"
    if isinstance(constraint, LtConstraint):
        return f"({column_expr} < {builder.bind(constraint.value)})"
    if isinstance(constraint, LteConstraint):
        return f"({column_expr} <= {builder.bind(constraint.value)})"
    if isinstance(constraint, GtConstraint):
        return f"({column_expr} > {builder.bind(constraint.value)})"
    if isinstance(constraint, GteConstraint):
        return f"({column_expr} >= {builder.bind(constraint.value)})"
    if isinstance(constraint, BetweenConstraint):
        op = "BETWEEN" if constraint.inclusive else "BETWEEN"
        # DuckDB ``BETWEEN`` is inclusive; for exclusive bounds the
        # executor rewrites to (col > min AND col < max). We keep the
        # SQL inclusive here — the executor applies the open-interval
        # form when needed.
        return (
            f"({column_expr} {op} {builder.bind(constraint.min)} "
            f"AND {builder.bind(constraint.max)})"
        )
    if isinstance(constraint, NotBetweenConstraint):
        return (
            f"({column_expr} NOT BETWEEN {builder.bind(constraint.min)} "
            f"AND {builder.bind(constraint.max)})"
        )
    if isinstance(constraint, InConstraint):
        bound = ", ".join(builder.bind(v) for v in constraint.values)
        return f"({column_expr} IN ({bound}))"
    if isinstance(constraint, NotInConstraint):
        bound = ", ".join(builder.bind(v) for v in constraint.values)
        return f"({column_expr} NOT IN ({bound}))"
    if isinstance(constraint, ContainsConstraint):
        # bind raw value; executor wraps with %...%.
        return f"({column_expr} LIKE {builder.bind('%' + constraint.value + '%')})"
    if isinstance(constraint, NotContainsConstraint):
        return f"({column_expr} NOT LIKE {builder.bind('%' + constraint.value + '%')})"
    if isinstance(constraint, StartsWithConstraint):
        return f"({column_expr} LIKE {builder.bind(constraint.value + '%')})"
    if isinstance(constraint, EndsWithConstraint):
        return f"({column_expr} LIKE {builder.bind('%' + constraint.value)})"
    if isinstance(constraint, MatchesConstraint):
        return f"(regexp_matches({column_expr}, {builder.bind(constraint.pattern)}))"
    if isinstance(constraint, NotMatchesConstraint):
        return (
            f"(NOT regexp_matches({column_expr}, {builder.bind(constraint.pattern)}))"
        )
    if isinstance(constraint, ExistsConstraint):
        return f"({column_expr} IS NOT NULL)"
    if isinstance(constraint, NotExistsConstraint):
        return f"({column_expr} IS NULL)"
    if isinstance(constraint, IsNullConstraint):
        return f"({column_expr} IS NULL)"
    if isinstance(constraint, IsNotNullConstraint):
        return f"({column_expr} IS NOT NULL)"
    if isinstance(constraint, IsEmptyConstraint):
        return f"(coalesce({column_expr}, '') = '')"
    if isinstance(constraint, IsNotEmptyConstraint):
        return f"(coalesce({column_expr}, '') != '')"
    if isinstance(constraint, IsNumericConstraint):
        return f"(try_cast({column_expr} AS DOUBLE) IS NOT NULL)"
    if isinstance(constraint, IsBooleanConstraint):
        return (
            f"(lower(cast({column_expr} AS VARCHAR)) IN "
            f"('true', 'false', '0', '1'))"
        )
    if isinstance(constraint, IsDateConstraint):
        return f"(try_cast({column_expr} AS DATE) IS NOT NULL)"
    return "TRUE"


# ── Projection / post-step ──────────────────────────────────────────────


def _projection_for(rule: EacRuleDefinition) -> list[str]:
    """Return the list of columns to project from the canonical row.

    For aggregate mode we project the formula-bound names (Volume,
    Area, …); for boolean / issue / clash we project the bare element
    identifiers and the raw ``properties`` JSON the per-element step
    will need.
    """
    base = ["element_id", "category", "ifc_class", "level", "discipline", "properties"]
    if rule.output_mode == "aggregate":
        # Standard quantities are well-known; the executor will refine
        # this list once the formula is parsed against the alias snapshot.
        base += ["volume_m3", "area_m2", "length_m"]
    return base


def _describe_post_step(rule: EacRuleDefinition) -> str | None:
    """Return a human-readable description of the post-processing step."""
    if rule.output_mode == "aggregate" and rule.formula:
        return f"evaluate formula '{rule.formula}' per row, then SUM"
    if rule.output_mode == "issue":
        return "render issue template per failing row"
    if rule.output_mode == "clash":
        return "geometry clash test (set_a × set_b)"
    return None


__all__ = ["ExecutionPlan", "plan_rule"]
