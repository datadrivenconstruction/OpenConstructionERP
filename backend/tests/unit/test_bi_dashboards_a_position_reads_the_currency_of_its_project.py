# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A money reading over BOQ lines can say which currency it is in.

Every money measure a custom KPI can reach lives on ``boq_position``:
``unit_rate``, ``total`` and the derived ``amount``. The entity offered no
currency, so a ``sum`` of ``amount`` read in portfolio mode - which is what
the compute endpoint does whenever no ``project_id`` is in the address bar -
added euros to pounds to dirhams and returned one Decimal. Nothing in the
result said so: a definition's ``unit`` is the word ``currency`` out of a
closed vocabulary, not an ISO code, so the tile that renders four currencies
added together looks exactly like the tile that renders one.

The two entities that already had it show where the value comes from.
``project`` binds its own ``currency`` column; ``cost_item_usage`` binds the
catalogue item's, through the join it already had for the price date. A
position has neither - the line carries no currency of its own and neither
does the bill - so its currency is the owning project's, reached through the
bill: ``Position.boq_id`` to ``BOQ.project_id`` to ``Project.currency``. That
path is what these tests pin. Binding a column named ``currency`` from
somewhere nearer would pass a test that only asked whether the field exists.

What this buys and what it does not
-----------------------------------
The currency becomes a breakdown key and a filter, so a spec can ask for a
per-currency subtotal or narrow to one code. The headline number of a grouped
spec is still one figure over the whole population, because the headline query
has never been grouped - a sum broken down by ``unit`` mixes m2 and m3 in its
headline the same way. Making the headline currency-aware would change the
number on dashboards that already exist, which is a different decision from
this one, so the last test here states the limit rather than hiding it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Column
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import visitors

from app.modules.bi_dashboards.kpi_spec import (
    ENTITY_CATALOG,
    KIND_TEXT,
    bind_entity,
    catalog_as_dict,
    check_catalog_binding_parity,
    evaluate_spec,
    validate_spec,
)

PROJECT_TABLE = "oe_projects_project"


def _columns_under(expr: Any) -> list[Column]:
    """Every real table column an expression is built from.

    The walk yields ORM attributes rather than columns, so each node is
    unwrapped before it is tested. Same helper as the area/price-age suite,
    and it is repeated rather than shared for the same reason that one keeps
    its own copy: a probe that silently returns nothing turns every test
    built on it green, so it is checked here against a column this file
    already knows the answer for.
    """
    found: list[Column] = []
    for node in visitors.iterate(expr):
        candidate = getattr(node, "expression", node)
        if isinstance(candidate, Column):
            found.append(candidate)
    return found


class _StubResult:
    """What a session hands back, with no database behind it."""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def one(self) -> tuple:
        return self._rows[0]

    def all(self) -> list[tuple]:
        return list(self._rows)


class _CapturingSession:
    """Records the statements ``evaluate_spec`` builds instead of running them.

    The point is to read the SQL the engine actually assembles rather than a
    second copy of the assembly written here. ``rows`` only has to be foldable
    - the values are never asserted on, they exist so the evaluation reaches
    its end and every statement it makes has been captured.
    """

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _StubResult:
        self.statements.append(statement)
        return _StubResult(self._rows)


def _sql(statement: Any) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


async def _statements_for(spec: dict[str, Any], rows: list[tuple]) -> list[str]:
    """Run a validated spec against no database and return its SQL."""
    session = _CapturingSession(rows)
    await evaluate_spec(spec, session)  # type: ignore[arg-type]
    return [_sql(stmt) for stmt in session.statements]


class TestThePositionsCurrencyIsTheProjectsCurrency:
    def test_the_line_and_the_bill_carry_no_currency_of_their_own(self) -> None:
        # The fact that makes the join load-bearing rather than decorative.
        # If either model grew a currency column this test would fail and the
        # binding below would be reaching past a nearer, better answer.
        from app.modules.boq.models import BOQ, Position

        assert not hasattr(Position, "currency")
        assert not hasattr(BOQ, "currency")

    def test_the_bound_field_reads_the_project_table(self) -> None:
        bound = bind_entity("boq_position")
        columns = _columns_under(bound.fields["currency"].expr)
        assert [(c.table.name, c.name) for c in columns] == [(PROJECT_TABLE, "currency")]

    def test_the_walk_can_actually_see_a_column(self) -> None:
        # The control for the helper above. Asserting on an empty list is how
        # a probe like this passes forever without looking at anything.
        bound = bind_entity("boq_position")
        columns = _columns_under(bound.fields["boq_id"].expr)
        assert [c.name for c in columns] == ["boq_id"]

    def test_the_catalogue_and_the_binder_still_agree(self) -> None:
        # A field declared in one and not the other is accepted at creation
        # and unanswerable at compute time.
        assert check_catalog_binding_parity() == {}

    def test_it_is_offered_as_a_breakdown_key_and_never_as_a_measure(self) -> None:
        entry = ENTITY_CATALOG["boq_position"]
        assert entry.fields["currency"] == KIND_TEXT
        assert "currency" in entry.groupable_fields()
        assert "currency" not in entry.numeric_fields()

    def test_the_served_catalogue_offers_it_so_a_picker_can(self) -> None:
        served = {e["name"]: e for e in catalog_as_dict()}
        assert "currency" in served["boq_position"]["groupable_fields"]

    def test_a_money_reading_can_be_narrowed_to_one_code(self) -> None:
        spec = validate_spec(
            {
                "entity": "boq_position",
                "aggregation": "sum",
                "field": "amount",
                "filters": [{"field": "currency", "op": "eq", "value": "EUR"}],
            }
        )
        assert spec["filters"] == [{"field": "currency", "op": "eq", "value": "EUR"}]


class TestTheJoinReachesEveryShapeOfQueryTheEngineBuilds:
    """Three statements are built from one binding, and each one joins.

    ``boq_position`` was bound with a single join before this, so the second
    one has to survive the grouped statement and the windowed subquery as well
    as the headline. They are compiled rather than assumed.
    """

    @pytest.mark.asyncio
    async def test_a_headline_sum_joins_the_project(self) -> None:
        spec = validate_spec({"entity": "boq_position", "aggregation": "sum", "field": "amount"})
        statements = await _statements_for(spec, [(Decimal("0"), 0)])
        assert len(statements) == 1
        assert f"JOIN {PROJECT_TABLE}" in statements[0]

    @pytest.mark.asyncio
    async def test_a_breakdown_groups_on_the_projects_column(self) -> None:
        spec = validate_spec(
            {"entity": "boq_position", "aggregation": "sum", "field": "amount", "group_by": "currency"}
        )
        # Headline first, then the grouped query: (sum, count) and (key, sum).
        statements = await _statements_for(spec, [(Decimal("0"), 0)])
        assert len(statements) == 2
        assert f"GROUP BY {PROJECT_TABLE}.currency" in statements[1]

    @pytest.mark.asyncio
    async def test_the_windowed_top_by_subquery_joins_the_project(self) -> None:
        spec = validate_spec(
            {"entity": "boq_position", "aggregation": "top_by", "field": "amount", "group_by": "currency"}
        )
        statements = await _statements_for(spec, [("EUR", "EUR", Decimal("0"))])
        assert len(statements) == 1
        assert f"JOIN {PROJECT_TABLE}" in statements[0]
        assert f"PARTITION BY {PROJECT_TABLE}.currency" in statements[0]


class TestWhatIsStillMixed:
    @pytest.mark.asyncio
    async def test_the_headline_number_is_still_one_figure_over_every_currency(self) -> None:
        # Stated rather than hidden. Grouping gives the reader an honest
        # per-code subtotal, and the scalar beside it is unchanged: it is the
        # same ungrouped sum a dashboard has been showing all along, so no
        # existing tile silently reports a different number after this.
        spec = validate_spec(
            {"entity": "boq_position", "aggregation": "sum", "field": "amount", "group_by": "currency"}
        )
        statements = await _statements_for(spec, [(Decimal("0"), 0)])
        assert "GROUP BY" not in statements[0]
