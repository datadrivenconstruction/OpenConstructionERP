# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A KPI can be read one estimate at a time.

A stored KPI value was a value of one project over one period, and a project
that holds several estimates had no way to say which one a number belonged to.
For money and contract value that rolls up honestly. For anything normalised it
does not: a house remodel quoted once and then extended by eight separately
approved and separately contracted additions has nine areas, nine durations and
nine margins, some of the additions have no area at all, and the average of
those nine is not a rougher version of the right answer. It is a number with no
referent, and it looks exactly like a measurement.

So a value gains an estimate, and the tests here are mostly about the ways that
could go quietly wrong rather than about the narrowing itself:

* ``boq_id IS NULL`` has to keep meaning "the whole project" on the read side
  too. A trend query that simply did not mention the column would start mixing
  per-estimate points into a project's sparkline the day the first
  estimate-scoped KPI was persisted, and the chart would keep drawing.
* An entity that has no estimate of its own must refuse, not widen. The
  project's figure is always reachable and is plausible, which is what makes
  serving it under an estimate's label the worst of the available failures.
* An estimate id is a caller-supplied name for a row set that
  ``allowed_project_ids`` knows nothing about, so it has to be resolved to its
  owning project before anything is read.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.modules.bi_dashboards import kpi_spec
from app.modules.bi_dashboards.kpi_spec import (
    ENTITY_CATALOG,
    KPI_SCOPES,
    SCOPE_ESTIMATE,
    SCOPE_PROJECT,
    KPISpecError,
    bind_entity,
    catalog_as_dict,
    check_catalog_binding_parity,
    entity_narrows_to_estimate,
)
from app.modules.bi_dashboards.models import KPIValue


class TestTheCatalogueSaysWhichEntitiesHaveAnEstimate:
    def test_the_three_that_do(self) -> None:
        for name in ("boq_position", "boq", "boq_markup"):
            assert ENTITY_CATALOG[name].narrows_to_estimate is True, name
            assert entity_narrows_to_estimate(name) is True, name

    def test_the_two_that_do_not_and_why(self) -> None:
        # ``project`` has one row per building, which is what makes its floor
        # area worth measuring and what stops an estimate owning it.
        # ``cost_item_usage`` records which project a rate was applied to and
        # not which bill it landed in - the nearest available answer is the
        # project's, and that is precisely the answer this must not give.
        for name in ("project", "cost_item_usage"):
            assert ENTITY_CATALOG[name].narrows_to_estimate is False, name
            assert entity_narrows_to_estimate(name) is False, name

    def test_the_usage_ledger_really_has_no_estimate_column(self) -> None:
        # The declaration above is a claim about the model, so it is checked
        # against the model rather than against itself. If a ``boq_id`` is
        # ever added to the ledger, this fails and the flag can be flipped -
        # which is the point: the refusal is a fact about today's schema, not
        # a permanent verdict.
        from app.modules.costs.models import CostItemUsage

        columns = set(CostItemUsage.__table__.columns.keys())
        assert "boq_id" not in columns
        assert "position_id" not in columns

    def test_an_unknown_entity_is_a_no_rather_than_a_key_error(self) -> None:
        assert entity_narrows_to_estimate("nope") is False

    def test_the_api_serves_the_flag_so_a_picker_can_grey_the_option_out(self) -> None:
        served = {e["name"]: e for e in catalog_as_dict()}
        assert served["boq_position"]["narrows_to_estimate"] is True
        assert served["project"]["narrows_to_estimate"] is False

    def test_the_scope_vocabulary_is_the_two_words_and_no_more(self) -> None:
        assert KPI_SCOPES == (SCOPE_PROJECT, SCOPE_ESTIMATE)


class TestTheBindingAgreesWithTheCatalogue:
    def test_parity_holds_including_the_estimate_dimension(self) -> None:
        assert check_catalog_binding_parity() == {}

    @pytest.mark.parametrize("name", sorted(ENTITY_CATALOG))
    def test_every_entity_that_promises_an_estimate_binds_a_column(self, name: str) -> None:
        bound = bind_entity(name)
        assert (bound.boq_column is not None) is ENTITY_CATALOG[name].narrows_to_estimate

    def test_a_promise_with_no_column_is_reported_rather_than_ignored(self, monkeypatch: Any) -> None:
        # The control for the test above. Without it, both halves of the
        # comparison could be reading the same wrong thing and the parity
        # check would agree with itself: this proves the check can actually
        # see the disagreement it exists to find.
        monkeypatch.setitem(
            ENTITY_CATALOG,
            "project",
            dataclasses.replace(ENTITY_CATALOG["project"], narrows_to_estimate=True),
        )
        report = check_catalog_binding_parity()
        assert "project" in report
        assert report["project"]["estimate_scope_mismatch"] == ["declared but no column bound"]

    def test_a_column_with_no_promise_is_reported_too(self, monkeypatch: Any) -> None:
        # The other direction. A binder that quietly gained an estimate
        # column while the catalog still said the entity had none would leave
        # the option greyed out in the picker forever.
        monkeypatch.setitem(
            ENTITY_CATALOG,
            "boq_position",
            dataclasses.replace(ENTITY_CATALOG["boq_position"], narrows_to_estimate=False),
        )
        report = check_catalog_binding_parity()
        assert report["boq_position"]["estimate_scope_mismatch"] == ["column bound but not declared"]

    def test_each_bound_column_belongs_to_the_entity_it_narrows(self) -> None:
        from app.modules.boq.models import BOQ, BOQMarkup, Position

        assert bind_entity("boq_position").boq_column is Position.boq_id
        # The bill itself, so narrowing leaves one row rather than the
        # project's estimate count.
        assert bind_entity("boq").boq_column is BOQ.id
        assert bind_entity("boq_markup").boq_column is BOQMarkup.boq_id


class TestAskingAnEntityWithoutAnEstimateIsRefused:
    """Refused, never widened. This is the whole point of the feature."""

    @pytest.mark.parametrize("entity", ["project", "cost_item_usage"])
    def test_the_evaluator_refuses_rather_than_returning_the_projects_number(self, entity: str) -> None:
        from sqlalchemy import func
        from sqlalchemy import select as sa_select

        bound = bind_entity(entity)
        spec = {"entity": entity, "aggregation": "count", "filters": []}
        stmt = sa_select(func.count()).select_from(bound.model)
        with pytest.raises(KPISpecError) as excinfo:
            kpi_spec._base_predicates(
                stmt,
                bound,
                spec,
                project_id=None,
                period_start=None,
                period_end=None,
                allowed_project_ids=None,
                boq_id=uuid.uuid4(),
            )
        assert "no estimate of its own" in str(excinfo.value)
        # And it names the entities that could have answered, so the author
        # is not left guessing which half of their spec to change.
        assert excinfo.value.allowed == ["boq", "boq_markup", "boq_position", "position_progress"]

    def test_an_entity_that_can_narrow_gets_the_predicate(self) -> None:
        from sqlalchemy import func
        from sqlalchemy import select as sa_select

        boq_id = uuid.uuid4()
        bound = bind_entity("boq_position")
        stmt = sa_select(func.count()).select_from(bound.model)
        narrowed = kpi_spec._base_predicates(
            stmt,
            bound,
            {"entity": "boq_position", "aggregation": "count", "filters": []},
            project_id=None,
            period_start=None,
            period_end=None,
            allowed_project_ids=None,
            boq_id=boq_id,
        )
        compiled = narrowed.compile()
        assert "boq_id" in str(compiled)
        assert boq_id in compiled.params.values()

    def test_without_an_estimate_the_statement_is_what_it_always_was(self) -> None:
        # The backwards-compatibility half. Passing nothing must not add a
        # predicate that happens to be true rather than absent, because
        # "boq_id IS NULL" on a positions query is a different question from
        # "every position".
        from sqlalchemy import func
        from sqlalchemy import select as sa_select

        bound = bind_entity("boq_position")
        spec: dict[str, Any] = {"entity": "boq_position", "aggregation": "count", "filters": []}
        stmt = sa_select(func.count()).select_from(bound.model)
        plain = kpi_spec._base_predicates(
            stmt,
            bound,
            spec,
            project_id=None,
            period_start=None,
            period_end=None,
            allowed_project_ids=None,
        )
        # Asked of the WHERE clause rather than of the compiled text: the
        # join condition is ``position.boq_id = boq.id`` and spells the
        # column name too, so a substring test on the whole statement reads
        # the join as a narrowing and passes for the wrong reason.
        assert plain.whereclause is None
        assert not plain.compile().params


class TestADefinitionDeclaresWhatItsValueIsAValueOf:
    def test_the_column_defaults_to_project_so_nothing_registered_changes(self) -> None:
        from app.modules.bi_dashboards.models import KPIDefinition

        column = KPIDefinition.__table__.columns["scope"]
        assert column.nullable is False
        assert column.server_default is not None
        assert column.server_default.arg == SCOPE_PROJECT

    def test_the_create_payload_defaults_to_project(self) -> None:
        from app.modules.bi_dashboards.schemas import KPIDefinitionCreate

        payload = KPIDefinitionCreate(
            code="margin_per_estimate",
            name="Margin per estimate",
            spec={"entity": "boq_markup", "aggregation": "avg", "field": "percentage"},
        )
        assert payload.scope == SCOPE_PROJECT

    def test_an_unknown_scope_is_refused_by_name(self) -> None:
        from pydantic import ValidationError

        from app.modules.bi_dashboards.schemas import KPIDefinitionCreate

        with pytest.raises(ValidationError) as excinfo:
            KPIDefinitionCreate(
                code="x",
                name="X",
                scope="package",
                spec={"entity": "boq", "aggregation": "count"},
            )
        assert "unknown scope" in str(excinfo.value)

    def test_the_read_model_carries_it(self) -> None:
        from app.modules.bi_dashboards.schemas import KPIDefinitionRead

        assert "scope" in KPIDefinitionRead.model_fields


class TestAStoredValueCarriesItsEstimate:
    def test_the_column_exists_and_is_nullable(self) -> None:
        column = KPIValue.__table__.columns["boq_id"]
        assert column.nullable is True
        # NULL is the project-level reading every row written before this
        # column existed already is, so there is nothing to backfill.
        assert column.default is None
        assert column.server_default is None

    def test_it_is_indexed_because_every_read_filters_on_it(self) -> None:
        indexed = {ix.name for ix in KPIValue.__table__.indexes}
        assert "ix_oe_bi_dashboards_kpi_value_boq_id" in indexed

    def test_no_foreign_key_the_way_project_id_has_none(self) -> None:
        # This module is a read-only consumer of oe_boq. A FK here would make
        # deleting an estimate depend on a reporting table.
        assert not KPIValue.__table__.columns["boq_id"].foreign_keys
        assert not KPIValue.__table__.columns["project_id"].foreign_keys


class TestAProjectTrendDoesNotAbsorbItsEstimates:
    """The read side of ``NULL means the whole project``.

    A query that simply did not mention the column would keep passing every
    test written before this feature, keep returning rows, and silently start
    plotting nine points a period where there was one.
    """

    def _statement(self, **kwargs: Any) -> str:
        from app.modules.bi_dashboards.repository import BIDashboardsRepository

        repo = BIDashboardsRepository.__new__(BIDashboardsRepository)
        captured: dict[str, Any] = {}

        class _FakeSession:
            async def execute(self, stmt: Any) -> Any:
                captured["stmt"] = stmt
                raise _Stop

        class _Stop(Exception):
            pass

        repo.session = _FakeSession()  # type: ignore[assignment]
        import asyncio

        try:
            asyncio.run(repo.list_kpi_values("cpi", **kwargs))
        except _Stop:
            pass
        return str(captured["stmt"])

    def test_a_project_level_read_says_boq_id_is_null_out_loud(self) -> None:
        sql = self._statement(project_id=uuid.uuid4())
        assert "boq_id IS NULL" in sql

    def test_an_estimate_level_read_pins_the_estimate(self) -> None:
        sql = self._statement(boq_id=uuid.uuid4())
        assert "boq_id IS NULL" not in sql
        assert "boq_id = " in sql

    def test_the_portfolio_read_is_project_level_too(self) -> None:
        # No project and no estimate is the all-projects figure, which is
        # still a project-scope reading rather than "every row of any scope".
        assert "boq_id IS NULL" in self._statement()


class TestTheSelectStatementForOneEstimateIsBuildable:
    """A compile-level check that the whole spec path accepts an estimate.

    Cheap, and it covers the join the narrowing has to survive: a markup
    reaches its project through the bill, so both predicates land on the same
    joined statement rather than one of them silently applying to a subquery.
    """

    def test_a_markup_average_narrows_to_one_bill(self) -> None:
        from sqlalchemy import func
        from sqlalchemy import select as sa_select

        boq_id = uuid.uuid4()
        project_id = uuid.uuid4()
        bound = bind_entity("boq_markup")
        stmt = sa_select(func.avg(bound.resolve_field("percentage").expr)).select_from(bound.model)
        stmt = kpi_spec._base_predicates(
            stmt,
            bound,
            {"entity": "boq_markup", "aggregation": "avg", "field": "percentage", "filters": []},
            project_id=project_id,
            period_start=None,
            period_end=None,
            allowed_project_ids=None,
            boq_id=boq_id,
        )
        compiled = stmt.compile()
        text = str(compiled)
        assert "JOIN" in text.upper()
        params = list(compiled.params.values())
        # Both scopes reached the same statement. The project predicate alone
        # would have been satisfied by every estimate in the project.
        assert boq_id in params
        assert project_id in params


class TestTheCatalogueDescribesTheLimitItHas:
    def test_area_and_price_age_are_still_readable_and_still_not_per_estimate(self) -> None:
        # Stated as a test rather than only in prose, because it is the part
        # of the reported problem that this change does NOT solve: cost per
        # square metre needs an area and a cost from two different entities,
        # and the one carrying the area cannot be narrowed to an estimate.
        assert "gross_floor_area" in ENTITY_CATALOG["project"].fields
        assert ENTITY_CATALOG["project"].narrows_to_estimate is False
        assert "price_age_days" in ENTITY_CATALOG["cost_item_usage"].fields
        assert ENTITY_CATALOG["cost_item_usage"].narrows_to_estimate is False


@pytest.mark.asyncio
class TestTheServiceRefusesLoudlyWhereTheWidgetPathDegrades:
    async def test_a_built_in_formula_cannot_be_narrowed(self) -> None:
        from app.modules.bi_dashboards.service import BIDashboardsService, KPIScopeUnavailable

        service = BIDashboardsService.__new__(BIDashboardsService)
        code = next(iter(_registered_formula_codes()))
        with pytest.raises(KPIScopeUnavailable) as excinfo:
            await service._refuse_a_reading_this_kpi_does_not_give(code, uuid.uuid4())
        assert "built-in" in str(excinfo.value)

    async def test_a_custom_kpi_over_a_project_entity_is_refused_by_name(self, monkeypatch) -> None:
        # The branch a person actually reaches. The built-in test above
        # short-circuits on the first line of the method and never touches
        # the definition, so without this one the refusal that names the
        # offending entity is never executed at all.
        from app.modules.bi_dashboards import kpi_spec as _kpi_spec
        from app.modules.bi_dashboards.service import BIDashboardsService, KPIScopeUnavailable

        async def _loaded(_session, _code):
            return _kpi_spec.LoadedSpec(
                spec={"entity": "project", "aggregate": "sum", "field": "gross_floor_area"},
                unit="m2",
                scope=_kpi_spec.SCOPE_PROJECT,
            )

        monkeypatch.setattr(_kpi_spec, "load_custom_spec", _loaded)
        service = BIDashboardsService.__new__(BIDashboardsService)
        service.session = None
        with pytest.raises(KPIScopeUnavailable) as excinfo:
            await service._refuse_a_reading_this_kpi_does_not_give("area_of_everything", uuid.uuid4())
        # Names the entity, because "cannot be scoped" without it leaves the
        # reader to guess which half of their spec is the problem.
        assert "project" in str(excinfo.value)

    async def test_a_per_estimate_definition_asked_for_a_whole_project_is_refused(self, monkeypatch) -> None:
        # The inverse direction, and the one that is easy to leave open: a
        # definition stored with scope="estimate", a caller who named no
        # estimate. The spec path answers that with a zero, and a zero on a
        # tile reading "margin per estimate" says the margin is nothing
        # rather than that nobody said which estimate.
        from app.modules.bi_dashboards import kpi_spec as _kpi_spec
        from app.modules.bi_dashboards.service import BIDashboardsService, KPIScopeUnavailable

        async def _loaded(_session, _code):
            return _kpi_spec.LoadedSpec(
                spec={"entity": "boq_position", "aggregate": "sum", "field": "amount"},
                unit="EUR",
                scope=_kpi_spec.SCOPE_ESTIMATE,
            )

        monkeypatch.setattr(_kpi_spec, "load_custom_spec", _loaded)
        service = BIDashboardsService.__new__(BIDashboardsService)
        service.session = None
        with pytest.raises(KPIScopeUnavailable) as excinfo:
            await service._refuse_a_reading_this_kpi_does_not_give("margin_per_estimate", None)
        assert excinfo.value.asked_for == "a whole project"

    async def test_the_same_definition_with_an_estimate_named_is_allowed(self, monkeypatch) -> None:
        # The control for both of the above, and the reason they are not
        # simply a method that always raises.
        from app.modules.bi_dashboards import kpi_spec as _kpi_spec
        from app.modules.bi_dashboards.service import BIDashboardsService

        async def _loaded(_session, _code):
            return _kpi_spec.LoadedSpec(
                spec={"entity": "boq_position", "aggregate": "sum", "field": "amount"},
                unit="EUR",
                scope=_kpi_spec.SCOPE_ESTIMATE,
            )

        monkeypatch.setattr(_kpi_spec, "load_custom_spec", _loaded)
        service = BIDashboardsService.__new__(BIDashboardsService)
        service.session = None
        await service._refuse_a_reading_this_kpi_does_not_give("margin_per_estimate", uuid.uuid4())

    async def test_an_unregistered_code_keeps_the_answer_it_has_always_given(self, monkeypatch) -> None:
        # A project-wide reading of a code nobody has defined is not a new
        # failure and must not become one here: every stale dashboard tile
        # in the field is that call, and it has always returned a zero.
        from app.modules.bi_dashboards import kpi_spec as _kpi_spec
        from app.modules.bi_dashboards.service import BIDashboardsService, CustomKPINotFound

        async def _loaded(_session, _code):
            return None

        monkeypatch.setattr(_kpi_spec, "load_custom_spec", _loaded)
        service = BIDashboardsService.__new__(BIDashboardsService)
        service.session = None
        await service._refuse_a_reading_this_kpi_does_not_give("gone_last_year", None)
        # Named an estimate for it, though, and there is nothing to scope.
        with pytest.raises(CustomKPINotFound):
            await service._refuse_a_reading_this_kpi_does_not_give("gone_last_year", uuid.uuid4())

    async def test_the_compute_path_returns_a_zero_rather_than_raising(self) -> None:
        # The other half of the same rule. ``kpis.compute`` is consumer code
        # that promises never to raise at its callers, so there the refusal
        # has to be a zero with a log line - the service is where a person
        # who asked for it finds out.
        from app.modules.bi_dashboards import kpis as _kpis

        code = next(iter(_registered_formula_codes()))
        result = await _kpis.compute(code, session=None, boq_id=uuid.uuid4())  # type: ignore[arg-type]
        assert result.value == 0
        assert result.source_record_count == 0


def _registered_formula_codes() -> list[str]:
    from app.modules.bi_dashboards import kpis as _kpis

    return sorted(_kpis.KPI_FORMULAS)


def test_the_kpi_value_model_and_the_migration_agree_on_the_column_name() -> None:
    # A column added in two places has to be added under one name. The model
    # is what ``create_all`` builds on a fresh volume and the revision is what
    # an existing install runs, and a disagreement between them produces two
    # schemas that both look right in isolation.
    import pathlib
    import re

    revision = (
        pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v3315_bi_kpi_estimate_scope.py"
    ).read_text(encoding="utf-8")
    assert 'sa.Column("boq_id"' in revision
    assert re.search(r'sa\.Column\(\s*"scope"', revision)
    # And the same guard the create_table gate demands, applied to add_column,
    # which that gate's population does not cover.
    assert "get_columns" in revision
    assert re.search(r"_has_column\(insp, VALUE_TABLE, \"boq_id\"\)", revision)


def test_the_kpi_value_table_still_has_its_old_columns() -> None:
    columns = set(KPIValue.__table__.columns.keys())
    for name in ("kpi_code", "project_id", "period_start", "period_end", "value", "unit", "computed_at"):
        assert name in columns


def test_select_is_importable_from_the_service_module() -> None:
    # ``estimate_owner_project`` is the only place in the service that builds
    # a statement of its own, so the import it needs is easy to leave out and
    # would only fail at request time.
    from app.modules.bi_dashboards import service as _service

    assert _service.select is select
