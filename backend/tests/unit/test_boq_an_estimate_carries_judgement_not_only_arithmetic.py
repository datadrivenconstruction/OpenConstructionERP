# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An estimate carries judgement, not only arithmetic - issue #453.

Three measures had no home in the model. Each is here for a different reason
and each fails in its own way if it is put in the wrong place:

* **Dispersion.** ``confidence`` says how sure the estimator is. It cannot say
  how wrong the line could be, and that is the question an offer is tested
  against: a margin that survives the declared risk is ``target - z * sigma``
  weighted by amount. With a confidence score alone there is no sigma to put
  in it. ``risk_dispersion`` is that sigma, and the thing to get right is that
  an unjudged line has to stay out of the average rather than read as zero,
  because a zero dispersion is a claim of certainty and it is the one reading
  that makes a bill look safer than it is.

* **Schedule.** Duration prices site overhead and it is what a client asks
  about before margin, but the KPI catalogue offered only bills and their
  lines, so no KPI could answer how long anything takes. The values CPM has
  already computed are enough; what this does NOT add is a calendar span for
  the project itself, and the test at the bottom says so out loud rather than
  leaving a reader to find out from an empty picker.

* **Price basis.** ``source`` looks like the answer and is not. It records how
  the row was entered, defaults to ``manual``, and is written literally by
  every ordinary create path - so on a typed bill it is ``manual`` on nearly
  every row and a KPI grouped by it returns a number near 100% that means
  nothing at all. The reporter measured 257 of 258. A hand-typed row can have
  an invoice behind it and a catalogue row can rest on a guess, which is why
  the two axes cannot share a column, and the tests here assert they are two
  columns rather than two names for one.

Run:
    cd backend
    python -m pytest tests/unit/test_boq_an_estimate_carries_judgement_not_only_arithmetic.py -q
"""

from __future__ import annotations

import pathlib
import re
import uuid
from typing import Any

import pytest
from sqlalchemy import func
from sqlalchemy import select as sa_select

from app.modules.bi_dashboards import kpi_spec
from app.modules.bi_dashboards.kpi_spec import (
    ENTITY_CATALOG,
    KIND_BOOL,
    KIND_NUMERIC,
    KIND_TEXT,
    bind_entity,
    catalog_as_dict,
    check_catalog_binding_parity,
)
from app.modules.boq.models import Position
from app.modules.boq.schemas import PRICE_BASIS_VALUES, PositionCreate, PositionUpdate

REVISION = (
    pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v3316_boq_position_estimating_judgement.py"
).read_text(encoding="utf-8")


class TestTheColumnsExistWhereTheyHaveToExist:
    """Both ways of arriving at the schema have to arrive at the same one."""

    @pytest.mark.parametrize("column", ["risk_dispersion", "price_basis"])
    def test_the_model_carries_it(self, column: str) -> None:
        assert column in Position.__table__.columns
        # Nullable with no default, and that is load-bearing rather than
        # tidy. A default would put a judgement on every row already in the
        # database, and the whole point of the column is that a judgement is
        # something a person made.
        col = Position.__table__.columns[column]
        assert col.nullable is True
        assert col.default is None
        assert col.server_default is None

    @pytest.mark.parametrize("column", ["risk_dispersion", "price_basis"])
    def test_the_migration_adds_it_under_the_same_name(self, column: str) -> None:
        # A column added in two places has to be added under one name: the
        # model is what create_all builds on a fresh volume and the revision
        # is what an existing install runs, and a disagreement produces two
        # schemas that both look right in isolation.
        assert re.search(rf'sa\.Column\(\s*"{column}"', REVISION)
        assert re.search(rf'_has_column\(insp, TABLE, "{column}"\)', REVISION)

    def test_the_migration_guards_its_add_columns(self) -> None:
        # The boot path runs create_all before anybody can run alembic, so on
        # a real install these columns exist by the time an operator upgrades
        # by hand. An unguarded ADD COLUMN raises DuplicateColumn, rolls back
        # the whole upgrade rather than this revision, and takes every later
        # revision with it. The create_table gate does not cover add_column.
        assert "get_columns" in REVISION
        assert REVISION.count("op.add_column") == 2


class TestDispersionIsNotConfidence:
    def test_the_catalogue_offers_it_as_a_measure(self) -> None:
        entry = ENTITY_CATALOG["boq_position"]
        assert entry.fields["risk_dispersion"] == KIND_NUMERIC
        assert "risk_dispersion" in entry.numeric_fields()
        # And not as a breakdown key: grouping by a measure gives one bucket
        # per distinct amount, which is never the question anybody asked.
        assert "risk_dispersion" not in entry.groupable_fields()

    def test_an_unjudged_line_stays_out_of_the_average(self) -> None:
        # The failure this guards. ``numeric_value`` reads a NULL text column
        # as 0 on PostgreSQL, so without a null source the weighted average
        # would count every unjudged line as one declared perfectly certain,
        # and a bill would look safer the less of it anybody had judged.
        bound = bind_entity("boq_position")
        spec: dict[str, Any] = {
            "entity": "boq_position",
            "aggregation": "weighted_avg",
            "field": "risk_dispersion",
            "weight_field": "amount",
            "filters": [],
        }
        stmt = kpi_spec._base_predicates(
            sa_select(func.count()).select_from(bound.model),
            bound,
            spec,
            project_id=None,
            period_start=None,
            period_end=None,
            allowed_project_ids=None,
        )
        assert "risk_dispersion IS NOT NULL" in str(stmt.compile())

    def test_the_control_is_a_measure_that_is_never_unset(self) -> None:
        # The same statement over a NOT NULL measure carries no such clause,
        # so the assertion above is about this field and not about every
        # weighted average the builder emits.
        bound = bind_entity("boq_position")
        stmt = kpi_spec._base_predicates(
            sa_select(func.count()).select_from(bound.model),
            bound,
            {
                "entity": "boq_position",
                "aggregation": "weighted_avg",
                "field": "total",
                "weight_field": "quantity",
                "filters": [],
            },
            project_id=None,
            period_start=None,
            period_end=None,
            allowed_project_ids=None,
        )
        assert "IS NOT NULL" not in str(stmt.compile())

    def test_it_has_no_upper_bound(self) -> None:
        # A line can be more uncertain than it is big, and the schema has to
        # let an estimator say so. Confidence is capped at 1 because it is a
        # probability; a standard deviation is not one.
        common = {
            "boq_id": uuid.uuid4(),
            "ordinal": "1",
            "description": "Groundworks",
            "unit": "m3",
            "quantity": 120.0,
        }
        assert PositionCreate(**common, risk_dispersion=2.5).risk_dispersion == 2.5
        with pytest.raises(ValueError):
            PositionCreate(**common, risk_dispersion=-0.1)


class TestPriceBasisIsNotSource:
    def test_they_are_two_columns_and_not_two_names_for_one(self) -> None:
        bound = bind_entity("boq_position")
        assert bound.fields["source"].expr is not bound.fields["price_basis"].expr
        assert Position.__table__.columns["source"].name != Position.__table__.columns["price_basis"].name
        # source is NOT NULL with a default and price_basis is neither, which
        # is the difference that makes one a provenance record and the other
        # a judgement somebody has to make.
        assert Position.__table__.columns["source"].nullable is False
        assert Position.__table__.columns["price_basis"].nullable is True

    def test_it_is_a_breakdown_key_and_not_a_measure(self) -> None:
        entry = ENTITY_CATALOG["boq_position"]
        assert entry.fields["price_basis"] == KIND_TEXT
        assert "price_basis" in entry.groupable_fields()

    def test_the_vocabulary_is_closed(self) -> None:
        assert len(PRICE_BASIS_VALUES) == len(set(PRICE_BASIS_VALUES)) == 7
        for value in PRICE_BASIS_VALUES:
            assert PositionUpdate(price_basis=value).price_basis == value
        with pytest.raises(ValueError):
            PositionUpdate(price_basis="gut_feel")

    def test_the_catalogue_names_every_value_it_could_be(self) -> None:
        # The gate that keeps the two in step. The catalogue is what an author
        # builds a filter against, and a value that exists in the schema and
        # is not written down here is one nobody can filter on without
        # reading the source.
        description = ENTITY_CATALOG["boq_position"].description
        for value in PRICE_BASIS_VALUES:
            assert value in description, value

    def test_an_unset_basis_stays_out_of_a_filtered_reading(self) -> None:
        # "Backed by external evidence" is a filter over five of the seven,
        # and a row nobody has judged must not fall into either side of that
        # split by accident.
        bound = bind_entity("boq_position")
        assert bound.fields["price_basis"].nullable_source is not None
        stmt = kpi_spec._base_predicates(
            sa_select(func.count()).select_from(bound.model),
            bound,
            {
                "entity": "boq_position",
                "aggregation": "sum",
                "field": "amount",
                "filters": [
                    {
                        "field": "price_basis",
                        "op": "in",
                        "value": ["invoice", "quotation", "price_list", "contract_rate", "norm"],
                    }
                ],
            },
            project_id=None,
            period_start=None,
            period_end=None,
            allowed_project_ids=None,
        )
        compiled = str(stmt.compile())
        assert "price_basis IS NOT NULL" in compiled
        assert "price_basis IN" in compiled


class TestASchedulueIsReadableTheWayAnEstimateIs:
    def test_the_entity_is_declared_and_bound(self) -> None:
        assert "schedule_activity" in ENTITY_CATALOG
        assert check_catalog_binding_parity() == {}

    def test_it_is_scoped_through_its_schedule_to_a_project(self) -> None:
        # An activity has no project of its own. If the scoping column were
        # missing or wrong, a portfolio reading would either fail or, worse,
        # return every activity in the database to a caller who can see one
        # project.
        from app.modules.schedule.models import Schedule

        bound = bind_entity("schedule_activity")
        assert bound.project_column is Schedule.project_id
        assert len(bound.joins) == 1

    def test_the_two_figures_the_reporter_asked_for_are_reachable(self) -> None:
        entry = ENTITY_CATALOG["schedule_activity"]
        # Activity count is `count`, which needs no field at all.
        assert entry.name == "schedule_activity"
        # Critical-path length in days is a sum over a filter.
        assert "duration_days" in entry.numeric_fields()
        assert entry.fields["is_critical"] == KIND_BOOL
        assert "is_critical" in entry.groupable_fields()

    def test_the_critical_path_sum_is_buildable(self) -> None:
        bound = bind_entity("schedule_activity")
        stmt = kpi_spec._base_predicates(
            sa_select(func.count()).select_from(bound.model),
            bound,
            {
                "entity": "schedule_activity",
                "aggregation": "sum",
                "field": "duration_days",
                "filters": [{"field": "is_critical", "op": "eq", "value": True}],
            },
            project_id=uuid.uuid4(),
            period_start=None,
            period_end=None,
            allowed_project_ids=None,
        )
        compiled = str(stmt.compile())
        assert "is_critical" in compiled
        assert "oe_schedule_schedule" in compiled

    def test_float_is_unset_until_cpm_has_run(self) -> None:
        # Total float is written by CPM. An activity on a schedule nobody has
        # scheduled has no slack rather than zero slack, and zero slack means
        # critical, which is the opposite of what an unrun activity is.
        bound = bind_entity("schedule_activity")
        for name in ("total_float", "free_float"):
            assert bound.fields[name].nullable_source is not None, name
        assert bound.fields["duration_days"].nullable_source is None

    def test_an_activity_belongs_to_no_estimate(self) -> None:
        # A project's schedule is not drawn up per bill, so there is nothing
        # to narrow to and the entity says so rather than letting a per
        # estimate reading resolve to the project's figure.
        assert ENTITY_CATALOG["schedule_activity"].narrows_to_estimate is False
        assert bind_entity("schedule_activity").boq_column is None


def test_the_limit_this_change_does_not_remove() -> None:
    """Project duration as a calendar span is still not expressible.

    Written as a test rather than left in a comment, because it is the first
    thing somebody will look for after reading that schedules are now in the
    catalogue. The span is a latest-finish minus an earliest-start over two
    date columns and there is no span aggregate; the dates are not offered as
    fields at all, so the picker cannot promise something the engine cannot
    build. What IS reachable is the critical path in days, which is the figure
    that usually stands in for it.
    """
    served = {e["name"]: e for e in catalog_as_dict()}
    offered = {f["name"] for f in served["schedule_activity"]["fields"]}
    assert "start_date" not in offered
    assert "end_date" not in offered
    assert "duration_days" in offered
