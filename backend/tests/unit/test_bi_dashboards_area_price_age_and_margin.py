# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Three columns that exist in the schema become readable by a custom KPI.

Gross floor area, the age of a catalogue price, and the markup rate an
estimate carries. None of the three needs a schema change; each was one
catalogue entry away from being useful, and each entry had to be put in the
right place rather than the nearest one.

Where each of them goes, and why it is not the obvious place
-----------------------------------------------------------
``gross_floor_area`` belongs to a project. The tempting shortcut is to borrow it
onto ``boq`` or ``boq_position``, where the money already lives, so that cost and
area sit in one entity. That produces a number that is wrong in the direction
nobody checks: a project with four estimates reports four buildings' worth of
floor area, and a sum over its lines reports one building per line. So area is
offered on a ``project`` entity, which has one row per building, and deliberately
nowhere else.

``price_as_of`` belongs to the cost catalogue, which has no project. The ledger
that records a rate being applied to a project's work does have one, and it is
written on the ordinary position-create path. So the entity is the join of the
two, and it is offered as an AGE in days rather than as a date, because a
threshold saved in a KPI definition has to keep meaning what it said: "older
than 90 days" stays true next quarter and "before 2026-06-01" does not.

The markup rows are offered; the markup MONEY is not. What a markup line adds to
a total depends on the compounding order, on whether it applies to the direct
cost or cumulatively, and on whether a section-scoped line overrides a bill-wide
one. That cascade lives in the BOQ service and this module is not going to keep a
second copy of it in SQL. So a KPI can answer what margin an estimate carries and
how many estimates carry none; separating markup money from direct cost is the
part left out, and it is left out on purpose.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Column
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.sql import visitors

from app.modules.bi_dashboards.kpi_spec import (
    _BINDERS,
    ENTITY_CATALOG,
    KIND_NUMERIC,
    KIND_TEXT,
    CatalogEntity,
    KPISpecError,
    bind_entity,
    catalog_as_dict,
    check_catalog_binding_parity,
    validate_spec,
)


def _columns_under(expr: Any) -> list[Column]:
    """Every real table column an expression is built from.

    The walk yields ORM attributes rather than columns - ``numeric_value``
    holds a ``Project.gross_floor_area``, not the ``Column`` behind it - so
    each node is unwrapped before it is tested. Written the obvious way, the
    isinstance check matched nothing and every test built on this helper
    passed by looking at an empty list, which is why the control test below
    exists.
    """
    found: list[Column] = []
    for node in visitors.iterate(expr):
        candidate = getattr(node, "expression", node)
        if isinstance(candidate, Column):
            found.append(candidate)
    return found


class TestTheCatalogueAndTheBindersStillAgree:
    def test_parity_holds_across_every_entity(self) -> None:
        assert check_catalog_binding_parity() == {}

    def test_every_declared_entity_has_a_binder(self) -> None:
        assert set(ENTITY_CATALOG) == set(_BINDERS)

    def test_an_entity_with_no_binder_is_reported_rather_than_crashing(self, monkeypatch) -> None:
        # Declaring an entity and binding it are two edits in two places, so
        # doing one and not the other is the likeliest way this catalogue
        # breaks. It used to be the one failure the parity check could not
        # report: `_BINDERS[name]` raises KeyError, the check caught only
        # ImportError, and the test died with a traceback naming a dict
        # instead of failing with the name of the entity left half-added.
        monkeypatch.setitem(
            ENTITY_CATALOG,
            "half_added",
            CatalogEntity(
                name="half_added",
                source_module="oe_nothing",
                description="Declared and never bound.",
                fields={"amount": KIND_NUMERIC},
            ),
        )
        assert check_catalog_binding_parity() == {"half_added": {"unbound_entity": ["half_added"]}}

    @pytest.mark.parametrize("name", sorted(ENTITY_CATALOG))
    def test_every_entity_can_be_narrowed_to_a_project_and_a_period(self, name: str) -> None:
        # A KPI that could not be narrowed would be the one reading on a
        # dashboard that ignores which project the dashboard is showing.
        bound = bind_entity(name)
        assert bound.project_column is not None
        assert bound.period_column is not None


class TestANullableNumberIsNeverReadAsZero:
    """The invariant behind ``nullable_source``, stated once for every entity.

    ``numeric_value`` reads a NULL text column as 0 on PostgreSQL, which is the
    right answer for a malformed row and the wrong one for an absent value.
    ``_base_predicates`` excludes the unset rows, but only for fields that
    declare a ``nullable_source``; a numeric field over a nullable column
    without one reports ``min`` as 0 and divides ``avg`` by the rows that had
    no value.

    Checked by walking the bound expression down to the columns it is built
    from, rather than by listing the fields here, so an entity added later is
    covered without anybody remembering to add it.
    """

    @pytest.mark.parametrize("entity_name", sorted(ENTITY_CATALOG))
    def test_a_numeric_field_over_a_nullable_column_declares_its_null_source(self, entity_name: str) -> None:
        bound = bind_entity(entity_name)
        entry = ENTITY_CATALOG[entity_name]
        offenders = []
        for field_name, kind in sorted(entry.fields.items()):
            if kind != KIND_NUMERIC:
                continue
            bf = bound.fields[field_name]
            if bf.nullable_source is not None or bf.null_safe:
                continue
            if any(col.nullable for col in _columns_under(bf.expr)):
                offenders.append(field_name)
        assert offenders == [], f"{entity_name}: numeric over a nullable column with no nullable_source: {offenders}"

    def test_the_walk_can_actually_see_through_the_coercion(self) -> None:
        # The test above is only worth anything if the expression walk reaches
        # the column inside `numeric_value`. If it returned nothing the
        # parametrised test would pass for every entity forever.
        bound = bind_entity("project")
        cols = _columns_under(bound.fields["gross_floor_area"].expr)
        assert [c.name for c in cols] == ["gross_floor_area"]
        assert cols[0].nullable is True


class TestGrossFloorAreaIsMeasuredWhereItIsNotRepeated:
    def test_the_project_entity_offers_it_as_a_measure(self) -> None:
        spec = validate_spec({"entity": "project", "aggregation": "sum", "field": "gross_floor_area"})
        assert spec == {"entity": "project", "aggregation": "sum", "field": "gross_floor_area", "filters": []}

    def test_projects_can_be_counted_and_broken_down_by_something_a_person_reads(self) -> None:
        spec = validate_spec({"entity": "project", "aggregation": "count", "group_by": "project_type"})
        assert spec["group_by"] == "project_type"
        # And an area cannot key a breakdown, same as any other measure.
        with pytest.raises(KPISpecError):
            validate_spec({"entity": "project", "aggregation": "count", "group_by": "gross_floor_area"})

    @pytest.mark.parametrize("entity_name", ["boq", "boq_position"])
    def test_area_is_not_borrowed_onto_the_estimate_or_the_line(self, entity_name: str) -> None:
        # The whole reason `project` exists as an entity. Borrowed here, a sum
        # would count one building once per estimate or once per line, and the
        # reading would look like a portfolio rather than like a mistake.
        entry = ENTITY_CATALOG[entity_name]
        assert "gross_floor_area" not in entry.fields
        assert "project_gross_floor_area" not in entry.fields
        with pytest.raises(KPISpecError):
            validate_spec({"entity": entity_name, "aggregation": "sum", "field": "gross_floor_area"})

    def test_the_area_column_is_nullable_so_the_guard_is_load_bearing(self) -> None:
        # Stated as a fact about the schema rather than about the binder: if
        # the column were NOT NULL the guard above would be decoration, and
        # this test says which of the two situations we are in.
        bound = bind_entity("project")
        assert bound.fields["gross_floor_area"].nullable_source is not None
        assert _columns_under(bound.fields["gross_floor_area"].nullable_source)[0].nullable is True


class TestPriceAgeAnswersHowOldTheRateIs:
    def test_the_age_is_a_measure_and_the_date_is_not_offered(self) -> None:
        spec = validate_spec({"entity": "cost_item_usage", "aggregation": "max", "field": "price_age_days"})
        assert spec["field"] == "price_age_days"
        # A stored KPI outlives the day it was written, so the threshold has
        # to be an age. A date field would let somebody save "before
        # 2026-06-01", which stops being the question they asked.
        assert "price_as_of" not in ENTITY_CATALOG["cost_item_usage"].fields

    def test_the_go_no_go_filter_is_expressible(self) -> None:
        spec = validate_spec(
            {
                "entity": "cost_item_usage",
                "aggregation": "count",
                "filters": [{"field": "price_age_days", "op": "gt", "value": 90}],
            }
        )
        assert spec["filters"] == [{"field": "price_age_days", "op": "gt", "value": 90}]

    def test_an_item_with_no_price_date_is_excluded_rather_than_read_as_fresh(self) -> None:
        bound = bind_entity("cost_item_usage")
        source = bound.fields["price_age_days"].nullable_source
        assert source is not None
        assert _columns_under(source)[0].name == "price_as_of"

    def test_the_age_is_counted_today_on_both_backends_and_in_whole_days(self) -> None:
        bound = bind_entity("cost_item_usage")
        expr = bound.fields["price_age_days"].expr
        pg = str(expr.compile(dialect=postgresql.dialect()))
        lite = str(expr.compile(dialect=sqlite.dialect()))
        assert "CURRENT_DATE" in pg
        assert "julianday" in lite
        # `julianday('now')` carries the fraction of today that has elapsed, so
        # the same row would read 0 on PostgreSQL and 0.4 on SQLite. Anchoring
        # to the start of the day is what makes the two agree.
        assert "date('now')" in lite

    def test_the_ledger_is_what_carries_the_project(self) -> None:
        # The cost catalogue has no project column at all, which is why this
        # entity is the join rather than the item table.
        from app.modules.costs.models import CostItem

        bound = bind_entity("cost_item_usage")
        assert bound.project_column.name == "project_id"
        assert not hasattr(CostItem, "project_id")


class TestMarkupRatesAreOfferedAndMarkupMoneyIsNot:
    def test_the_rate_an_estimate_carries_is_a_measure(self) -> None:
        spec = validate_spec(
            {
                "entity": "boq_markup",
                "aggregation": "sum",
                "field": "percentage",
                "filters": [
                    {"field": "category", "op": "eq", "value": "profit"},
                    {"field": "is_active", "op": "eq", "value": True},
                ],
            }
        )
        assert spec["field"] == "percentage"
        assert len(spec["filters"]) == 2

    def test_a_breakdown_by_estimate_is_named_rather_than_keyed_by_id(self) -> None:
        spec = validate_spec(
            {"entity": "boq_markup", "aggregation": "sum", "field": "fixed_amount", "group_by": "boq_id"}
        )
        assert spec["label_field"] == "boq_name"

    def test_the_company_standard_can_be_told_from_a_section_exception(self) -> None:
        # NULL scope means bill-wide, which is the ordinary case rather than a
        # missing value, so `is_null` is the question and not a data-quality
        # check.
        spec = validate_spec(
            {
                "entity": "boq_markup",
                "aggregation": "count",
                "filters": [{"field": "scope_position_id", "op": "is_null"}],
            }
        )
        assert spec["filters"][0]["op"] == "is_null"

    def test_markup_money_is_not_offered_anywhere(self) -> None:
        # Deliberate, and the reason is in the module docstring: the money a
        # markup adds depends on the compounding order, on apply_to, and on
        # scoped overrides, all of which live in the BOQ service. A second
        # copy of that cascade written as SQL here would be a second answer.
        for name in ("markups_total", "direct_cost_total", "grand_total", "amount"):
            assert name not in ENTITY_CATALOG["boq"].fields
            assert name not in ENTITY_CATALOG["boq_markup"].fields

    def test_the_rate_columns_are_not_null_so_zero_is_the_honest_reading(self) -> None:
        # The counterpart to the nullable-source rule: here an absent half of
        # a line really does mean zero, so excluding those rows would be the
        # wrong treatment rather than the careful one.
        bound = bind_entity("boq_markup")
        for name in ("percentage", "fixed_amount"):
            assert bound.fields[name].nullable_source is None
            assert all(not col.nullable for col in _columns_under(bound.fields[name].expr))


class TestTheApiServesTheNewEntities:
    def test_every_entity_is_served_with_the_fields_a_form_needs(self) -> None:
        # A closed set on purpose, and worth keeping closed: the catalogue is
        # what a picker offers and what a stored spec is validated against, so
        # an entity added in one place and not the other is not a missing
        # feature, it is a spec that validates today and cannot be computed
        # tomorrow. Grew by ``schedule_activity`` for issue #453, and by
        # ``field_time_line`` and ``position_progress`` for issue #492.
        served = {e["name"]: e for e in catalog_as_dict()}
        assert set(served) == {
            "boq",
            "boq_position",
            "boq_markup",
            "cost_item_usage",
            "field_time_line",
            "position_progress",
            "project",
            "schedule_activity",
        }
        for entity in served.values():
            assert entity["description"]
            assert entity["source_module"].startswith("oe_")
            assert isinstance(entity["numeric_fields"], list)
            assert isinstance(entity["groupable_fields"], list)

    def test_the_three_new_measures_are_all_reachable_from_the_served_catalogue(self) -> None:
        served = {e["name"]: e for e in catalog_as_dict()}
        assert "gross_floor_area" in served["project"]["numeric_fields"]
        assert "price_age_days" in served["cost_item_usage"]["numeric_fields"]
        assert "percentage" in served["boq_markup"]["numeric_fields"]

    def test_a_breakdown_key_is_offered_for_each_of_them(self) -> None:
        served = {e["name"]: e for e in catalog_as_dict()}
        assert "project_type" in served["project"]["groupable_fields"]
        assert "cost_item_code" in served["cost_item_usage"]["groupable_fields"]
        assert "category" in served["boq_markup"]["groupable_fields"]

    def test_a_kind_is_declared_for_every_served_field(self) -> None:
        for entity in catalog_as_dict():
            for item in entity["fields"]:
                assert item["kind"] in {"numeric", "text", "uuid", "bool"}, item

    def test_the_display_names_the_new_entities_promise_are_text(self) -> None:
        for entity in catalog_as_dict():
            for id_field, name_field in entity["display_name_for"].items():
                kinds = {f["name"]: f["kind"] for f in entity["fields"]}
                assert kinds[id_field] != KIND_NUMERIC
                assert kinds[name_field] == KIND_TEXT
