# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-backed tests for the Full EVM baseline and measurement register.

Driven against a PostgreSQL session inside an outer transaction that is rolled
back on teardown, so every test starts from an empty but fully schema-loaded
database.

What these cover that the pure-maths tests cannot: that the derived metrics are
actually persisted with the right precision and the right nullability, that
validation really runs on write instead of merely being registered, that
approval is gated on it, and that the declared relationship loading strategies
behave the way the module documents.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.full_evm.models import EVMBaseline, EVMMeasure
from app.modules.full_evm.schemas import (
    BaselineCreate,
    BaselinePeriodWrite,
    BaselineResponse,
    BaselineSCurveResponse,
    BaselineUpdate,
    MeasureCreate,
    MeasureResponse,
)
from app.modules.full_evm.service import EVMBaselineService, planned_value_at
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session():
    """Per-test isolated PostgreSQL session, rolled back on teardown."""
    async with transactional_session() as s:
        yield s


@pytest.fixture
def project_id() -> uuid.UUID:
    """A project scope for the baselines created in a test."""
    return uuid.uuid4()


def _curve() -> list[BaselinePeriodWrite]:
    """A sound three-period curve: rising, and ending exactly at the budget."""
    return [
        BaselinePeriodWrite(period_end=date(2026, 1, 31), label="M1", planned_value=Decimal("250000")),
        BaselinePeriodWrite(period_end=date(2026, 2, 28), label="M2", planned_value=Decimal("600000")),
        BaselinePeriodWrite(period_end=date(2026, 3, 31), label="M3", planned_value=Decimal("1000000")),
    ]


def _create_payload(
    project_id: uuid.UUID,
    *,
    name: str = "Original baseline",
    bac: str = "1000000",
    periods: list[BaselinePeriodWrite] | None = None,
) -> BaselineCreate:
    return BaselineCreate(
        project_id=project_id,
        name=name,
        bac=Decimal(bac),
        currency="EUR",
        minor_units=2,
        start_date=date(2026, 1, 1),
        finish_date=date(2026, 3, 31),
        periods=_curve() if periods is None else periods,
    )


# ── Baseline lifecycle ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_creating_a_baseline_validates_it_immediately(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """A new baseline carries a real validation status, never an unchecked one."""
    service = EVMBaselineService(session)

    baseline = await service.create_baseline(_create_payload(project_id))

    assert baseline.status == "draft"
    assert baseline.validation_status == "passed"
    assert baseline.validation_findings == []
    assert baseline.validation_score == 1.0
    assert len(baseline.periods) == 3
    assert baseline.periods[0].ordinal == 0


@pytest.mark.asyncio
async def test_a_broken_curve_is_saved_with_its_findings(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """Validation reports without blocking: a half-entered plan is still saved."""
    service = EVMBaselineService(session)
    dipping = [
        BaselinePeriodWrite(period_end=date(2026, 1, 31), label="M1", planned_value=Decimal("600000")),
        BaselinePeriodWrite(period_end=date(2026, 2, 28), label="M2", planned_value=Decimal("250000")),
    ]

    baseline = await service.create_baseline(_create_payload(project_id, periods=dipping))

    assert baseline.id is not None
    assert baseline.validation_status == "errors"
    rule_ids = {f["rule_id"] for f in baseline.validation_findings}
    assert "full_evm.baseline_pv_monotonic" in rule_ids
    assert "full_evm.baseline_pv_matches_bac" in rule_ids


@pytest.mark.asyncio
async def test_a_baseline_with_errors_cannot_be_approved(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """Approval is the one place the rules are a gate rather than a report."""
    from fastapi import HTTPException

    service = EVMBaselineService(session)
    short = [BaselinePeriodWrite(period_end=date(2026, 3, 31), label="M3", planned_value=Decimal("400000"))]
    baseline = await service.create_baseline(_create_payload(project_id, periods=short))

    with pytest.raises(HTTPException) as exc:
        await service.approve_baseline(baseline)

    assert exc.value.status_code == 409
    assert baseline.status == "draft"


@pytest.mark.asyncio
async def test_approving_a_baseline_supersedes_the_previous_one(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """Only one baseline is the measurement base at a time."""
    service = EVMBaselineService(session)
    approver = uuid.uuid4()

    first = await service.create_baseline(_create_payload(project_id, name="Original"))
    await service.approve_baseline(first, approved_by=approver)
    assert first.status == "approved"
    assert first.approved_by == approver
    assert first.approved_at is not None

    second = await service.create_baseline(_create_payload(project_id, name="Re-baseline 1"))
    await service.approve_baseline(second, approved_by=approver)

    assert second.status == "approved"
    assert first.status == "superseded"
    current = await service.baselines.get_approved(project_id)
    assert current is not None
    assert current.id == second.id


@pytest.mark.asyncio
async def test_an_approved_baseline_is_not_editable_or_deletable(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """Editing the measurement base would change the meaning of reported history."""
    from fastapi import HTTPException

    service = EVMBaselineService(session)
    baseline = await service.create_baseline(_create_payload(project_id))
    await service.approve_baseline(baseline)

    with pytest.raises(HTTPException) as edit_exc:
        await service.update_baseline(baseline, BaselineUpdate(bac=Decimal("2000000")))
    assert edit_exc.value.status_code == 409

    with pytest.raises(HTTPException) as delete_exc:
        await service.delete_baseline(baseline)
    assert delete_exc.value.status_code == 409


@pytest.mark.asyncio
async def test_a_duplicate_baseline_name_is_refused(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """A re-baseline is a new, distinguishable row, never a silent overwrite."""
    from fastapi import HTTPException

    service = EVMBaselineService(session)
    await service.create_baseline(_create_payload(project_id, name="Original"))

    with pytest.raises(HTTPException) as exc:
        await service.create_baseline(_create_payload(project_id, name="Original"))

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_replacing_the_curve_renumbers_and_revalidates(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """A whole-curve write leaves no orphaned rows behind."""
    service = EVMBaselineService(session)
    baseline = await service.create_baseline(_create_payload(project_id))

    await service.replace_periods(
        baseline,
        [BaselinePeriodWrite(period_end=date(2026, 6, 30), label="H1", planned_value=Decimal("1000000"))],
    )

    stored = await service.baselines.list_periods(baseline.id)
    assert len(stored) == 1
    assert stored[0].ordinal == 0
    assert stored[0].label == "H1"
    assert baseline.validation_status == "passed"


# ── Money and precision ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_amounts_round_trip_through_the_database_as_exact_decimals(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """Money is Numeric, so a value that a float would mangle survives intact."""
    service = EVMBaselineService(session)
    awkward = Decimal("1234567.89")
    baseline = await service.create_baseline(
        _create_payload(
            project_id,
            bac=str(awkward),
            periods=[
                BaselinePeriodWrite(period_end=date(2026, 3, 31), label="M3", planned_value=awkward),
            ],
        ),
    )

    session.expunge_all()
    reloaded = await session.get(EVMBaseline, baseline.id)

    assert reloaded is not None
    assert isinstance(reloaded.bac, Decimal)
    assert reloaded.bac == awkward
    assert reloaded.periods[0].planned_value == awkward


# ── Measurements ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_planned_value_is_read_off_the_curve_when_not_supplied(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """The curve exists so a measurement never has to restate the plan."""
    service = EVMBaselineService(session)
    baseline = await service.create_baseline(_create_payload(project_id))

    measure = await service.record_measure(
        baseline,
        MeasureCreate(data_date=date(2026, 2, 28), ev=Decimal("550000"), ac=Decimal("580000")),
    )

    assert measure.pv == Decimal("600000")
    assert measure.bac == Decimal("1000000")


@pytest.mark.asyncio
async def test_a_data_date_between_periods_interpolates_the_curve(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """A cutoff that misses a reporting boundary still gets a planned value."""
    periods = _curve()
    rows = [
        type(
            "P",
            (),
            {"period_end": p.period_end, "planned_value": p.planned_value, "ordinal": i},
        )()
        for i, p in enumerate(periods)
    ]

    # 2026-02-14 is 17 of the 28 days between 2026-01-31 and 2026-02-28.
    value = planned_value_at(rows, date(2026, 2, 14), start_date=date(2026, 1, 1))  # type: ignore[arg-type]

    expected = Decimal("250000") + (Decimal("600000") - Decimal("250000")) * Decimal(14) / Decimal(28)
    assert value == expected


@pytest.mark.asyncio
async def test_the_full_metric_set_is_persisted_not_recomputed_on_read(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """Every derived value lands in its own column so reporting can aggregate."""
    service = EVMBaselineService(session)
    baseline = await service.create_baseline(_create_payload(project_id))

    await service.record_measure(
        baseline,
        MeasureCreate(
            data_date=date(2026, 2, 28),
            ev=Decimal("500000"),
            ac=Decimal("520000"),
            pv=Decimal("550000"),
            eac_method="cpi",
        ),
    )

    session.expunge_all()
    stored = (await session.execute(select(EVMMeasure).where(EVMMeasure.baseline_id == baseline.id))).scalar_one()

    assert stored.cpi == Decimal("0.961538")
    assert stored.spi == Decimal("0.909091")
    assert stored.sv == Decimal("-50000.0000")
    assert stored.cv == Decimal("-20000.0000")
    assert stored.eac == Decimal("1040000.0000")
    assert stored.etc_ == Decimal("520000.0000")
    assert stored.vac == Decimal("-40000.0000")
    assert stored.tcpi_bac == Decimal("1.041667")
    assert stored.eac_method == "cpi"
    assert stored.eac_method_effective == "cpi"
    # Every variant is kept so the chosen one can be audited against the others.
    assert set(stored.eac_variants) == {"remaining", "cpi", "combined"}


@pytest.mark.asyncio
async def test_an_early_project_stores_null_indices_not_zero(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """Undefined must reach the database as NULL.

    Storing 0 for a CPI that has no denominator would report a project that has
    not started as maximally inefficient, and every dashboard reading the column
    would repeat it.
    """
    service = EVMBaselineService(session)
    baseline = await service.create_baseline(_create_payload(project_id))

    await service.record_measure(
        baseline,
        MeasureCreate(
            data_date=date(2026, 1, 1),
            ev=Decimal("0"),
            ac=Decimal("0"),
            pv=Decimal("0"),
            eac_method="cpi",
        ),
    )

    session.expunge_all()
    stored = (await session.execute(select(EVMMeasure).where(EVMMeasure.baseline_id == baseline.id))).scalar_one()

    assert stored.cpi is None
    assert stored.spi is None
    assert stored.eac_method == "cpi"
    assert stored.eac_method_effective == "remaining"
    assert stored.validation_status == "info"


@pytest.mark.asyncio
async def test_re_recording_the_same_data_date_updates_in_place(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """One cutoff has one truth, so a correction replaces rather than duplicates."""
    service = EVMBaselineService(session)
    baseline = await service.create_baseline(_create_payload(project_id))
    payload = MeasureCreate(data_date=date(2026, 2, 28), ev=Decimal("500000"), ac=Decimal("520000"))

    first = await service.record_measure(baseline, payload)
    corrected = await service.record_measure(
        baseline,
        MeasureCreate(data_date=date(2026, 2, 28), ev=Decimal("500000"), ac=Decimal("610000")),
    )

    assert corrected.id == first.id
    assert corrected.ac == Decimal("610000")
    items, total = await service.list_measures(baseline_id=baseline.id)
    assert total == 1
    assert len(items) == 1


@pytest.mark.asyncio
async def test_a_measurement_that_breaks_a_rule_is_saved_with_its_findings(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """Earning more than the budget is an error the row carries, not a lost write."""
    service = EVMBaselineService(session)
    baseline = await service.create_baseline(_create_payload(project_id))

    measure = await service.record_measure(
        baseline,
        MeasureCreate(data_date=date(2026, 3, 31), ev=Decimal("1400000"), ac=Decimal("900000")),
    )

    assert measure.validation_status == "errors"
    assert "full_evm.measure_ev_within_bac" in {f["rule_id"] for f in measure.validation_findings}


@pytest.mark.asyncio
async def test_a_negative_amount_is_refused_by_the_schema(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """Schema-level rejection of a negative cumulative total."""
    with pytest.raises(ValueError, match="cannot be negative"):
        MeasureCreate(data_date=date(2026, 3, 31), ev=Decimal("-1"), ac=Decimal("10"))


@pytest.mark.asyncio
async def test_planned_and_actual_quantity_are_stored_alongside_the_money(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """Physical progress is recorded next to cost, and only cost and quantity."""
    service = EVMBaselineService(session)
    baseline = await service.create_baseline(_create_payload(project_id))

    measure = await service.record_measure(
        baseline,
        MeasureCreate(
            data_date=date(2026, 2, 28),
            ev=Decimal("550000"),
            ac=Decimal("580000"),
            planned_quantity=Decimal("1200"),
            actual_quantity=Decimal("1050"),
        ),
    )

    assert measure.planned_quantity == Decimal("1200")
    assert measure.actual_quantity == Decimal("1050")


# ── Relationship loading strategy ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_curve_loads_eagerly_because_it_is_the_point_of_the_baseline(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """``periods`` is ``selectin``: a plain read already has the curve."""
    service = EVMBaselineService(session)
    created = await service.create_baseline(_create_payload(project_id))

    session.expunge_all()
    baseline = await session.get(EVMBaseline, created.id)

    assert baseline is not None
    assert [p.label for p in baseline.periods] == ["M1", "M2", "M3"]


@pytest.mark.asyncio
async def test_measurement_history_refuses_to_load_itself_behind_your_back(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """``measures`` is ``raise_on_sql``: unbounded history must be asked for.

    The failure this prevents is a header render quietly pulling a project's
    whole measurement history. ``raise_on_sql`` names the relationship at the
    point of touch instead of surfacing as a MissingGreenlet further down.
    """
    service = EVMBaselineService(session)
    created = await service.create_baseline(_create_payload(project_id))
    await service.record_measure(
        created,
        MeasureCreate(data_date=date(2026, 2, 28), ev=Decimal("550000"), ac=Decimal("580000")),
    )

    session.expunge_all()
    baseline = await session.get(EVMBaseline, created.id)
    assert baseline is not None

    with pytest.raises(InvalidRequestError):
        _ = list(baseline.measures)

    # Asking explicitly is what the repository does, and it works.
    session.expunge_all()
    eager = await service.baselines.get_with_measures(created.id)
    assert eager is not None
    assert len(eager.measures) == 1


@pytest.mark.asyncio
async def test_deleting_a_baseline_cascades_to_its_curve_and_measurements(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """Cascade still works with the strict loading strategy in place."""
    service = EVMBaselineService(session)
    baseline = await service.create_baseline(_create_payload(project_id))
    await service.record_measure(
        baseline,
        MeasureCreate(data_date=date(2026, 2, 28), ev=Decimal("550000"), ac=Decimal("580000")),
    )
    baseline_id = baseline.id

    await service.delete_baseline(baseline)

    assert await session.get(EVMBaseline, baseline_id) is None
    remaining = (await session.execute(select(EVMMeasure).where(EVMMeasure.baseline_id == baseline_id))).scalars().all()
    assert list(remaining) == []


# ── Reporting ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_s_curve_leaves_unreported_periods_null(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """A month with no measurement reads as unreported, not as no progress."""
    service = EVMBaselineService(session)
    baseline = await service.create_baseline(_create_payload(project_id))
    await service.record_measure(
        baseline,
        MeasureCreate(data_date=date(2026, 2, 28), ev=Decimal("550000"), ac=Decimal("580000")),
    )

    curve = await service.build_s_curve(baseline.id)
    points = curve["points"]

    # Amounts travel as strings so a JavaScript client cannot round them;
    # the decimal-place rendering is a storage detail, so compare the values.
    assert len(points) == 3
    assert points[0]["earned_value"] is None
    assert Decimal(points[1]["earned_value"]) == Decimal("550000")
    assert Decimal(points[1]["actual_cost"]) == Decimal("580000")
    # March was never measured. Repeating February's number here would draw a
    # month of unreported progress exactly like a month of no progress, and
    # would label February's EAC as March's forecast.
    assert points[2]["earned_value"] is None
    assert points[2]["actual_cost"] is None
    assert points[2]["forecast"] is None
    # The plan is known for every period regardless.
    assert Decimal(points[2]["planned_value"]) == Decimal("1000000")
    assert Decimal(curve["bac"]) == Decimal("1000000")


@pytest.mark.asyncio
async def test_a_measurement_past_the_end_of_the_plan_still_appears(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """An overrun the plan never foresaw is exactly what has to be on the chart."""
    service = EVMBaselineService(session)
    baseline = await service.create_baseline(_create_payload(project_id))
    await service.record_measure(
        baseline,
        MeasureCreate(data_date=date(2026, 5, 31), ev=Decimal("900000"), ac=Decimal("1100000")),
    )

    curve = await service.build_s_curve(baseline.id)

    assert len(curve["points"]) == 4
    assert curve["points"][-1]["as_of"] == date(2026, 5, 31)
    assert Decimal(curve["points"][-1]["actual_cost"]) == Decimal("1100000")


# ── Router response models ───────────────────────────────────────────────────
#
# The service tests above read ORM attributes directly, which is exactly what
# the router does *not* do: it hands each row to a response model. Two of those
# models read a trailing-underscore ORM attribute through a validation alias
# and carry a default, so a mis-resolved alias is not an error - it is a null
# ETC or an empty metadata dict, returned forever, with every service test
# still green. These construct the response models the router actually returns.


@pytest.mark.asyncio
async def test_the_measure_response_carries_the_stored_etc_and_metadata(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """``etc_`` and ``metadata_`` survive the alias, rather than defaulting."""
    service = EVMBaselineService(session)
    baseline = await service.create_baseline(_create_payload(project_id))
    measure = await service.record_measure(
        baseline,
        MeasureCreate(
            data_date=date(2026, 2, 28),
            ev=Decimal("550000"),
            ac=Decimal("600000"),
            metadata={"source": "monthly valuation"},
        ),
    )

    body = MeasureResponse.model_validate(measure)

    # ETC is a computed money value; a null here would mean the alias missed
    # and the default won, which no assertion on the ORM row can detect.
    assert body.etc is not None
    assert body.etc == measure.etc_
    assert body.etc > Decimal("0")
    assert body.metadata == {"source": "monthly valuation"}
    # Both halves of the EAC provenance reach the wire.
    assert body.eac_method == "auto"
    assert body.eac_method_effective == "combined"


@pytest.mark.asyncio
async def test_the_baseline_response_carries_its_metadata_and_curve(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """The list/detail body is really constructible from a persisted row."""
    service = EVMBaselineService(session)
    payload = _create_payload(project_id)
    payload.metadata = {"contract": "NEC4 Option C"}
    baseline = await service.create_baseline(payload)

    body = BaselineResponse.model_validate(baseline)

    assert body.metadata == {"contract": "NEC4 Option C"}
    assert body.bac == Decimal("1000000")
    assert len(body.periods) == 3
    assert body.periods[0].planned_value == Decimal("250000")
    assert body.validation_status == "passed"

    # Money leaves as a string, so a JSON consumer never sees a float.
    dumped = body.model_dump(mode="json")
    assert isinstance(dumped["bac"], str)
    assert Decimal(dumped["bac"]) == Decimal("1000000")
    assert isinstance(dumped["periods"][0]["planned_value"], str)


@pytest.mark.asyncio
async def test_the_s_curve_response_is_constructible_from_the_service_output(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """``build_s_curve`` keys line up with the model, including the ``as_of`` rename."""
    service = EVMBaselineService(session)
    baseline = await service.create_baseline(_create_payload(project_id))
    await service.record_measure(
        baseline,
        MeasureCreate(data_date=date(2026, 2, 28), ev=Decimal("550000"), ac=Decimal("600000")),
    )

    body = BaselineSCurveResponse(**await service.build_s_curve(baseline.id))

    assert body.baseline_id == baseline.id
    assert Decimal(body.bac) == Decimal("1000000")
    assert len(body.points) == 3
    # `as_of` is this model's name for a period end; `date` would shadow the
    # stdlib type in the module namespace.
    assert body.points[0].as_of == date(2026, 1, 31)
    assert Decimal(body.points[1].earned_value or "0") == Decimal("550000")
    # A period with no measurement plots the plan alone, not a zero actual and
    # not a repeat of the month before.
    assert body.points[2].earned_value is None
    assert body.points[2].planned_value is not None


@pytest.mark.asyncio
async def test_a_baseline_created_without_a_curve_can_still_be_serialised(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """Create the draft first, add the curve later - the natural authoring order.

    With no periods submitted the write path never touches the collection, so
    the router's ``model_validate`` would be the first thing to read it on a
    persistent instance - the unloaded-collection access that raises
    ``MissingGreenlet`` under an async session.
    """
    service = EVMBaselineService(session)

    baseline = await service.create_baseline(_create_payload(project_id, periods=[]))

    assert baseline.periods == []
    body = BaselineResponse.model_validate(baseline)
    assert body.periods == []
    # An empty curve is a real finding, not a pass: there is no PV to earn
    # against, so every future SPI would be undefined.
    assert body.validation_status == "errors"
    assert body.validation_findings


@pytest.mark.asyncio
async def test_measuring_against_a_baseline_with_no_curve_reports_spi_undefined(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> None:
    """A curveless baseline yields no PV, so SPI is undefined rather than wrong.

    This path only became reachable once a baseline could be created without a
    curve. There is no planned value to compare against, so the schedule
    measures have no meaning - but the cost measures still do, and reporting
    SPI as zero would brand a project with no plan as maximally behind.
    """
    service = EVMBaselineService(session)
    baseline = await service.create_baseline(_create_payload(project_id, periods=[]))

    measure = await service.record_measure(
        baseline,
        MeasureCreate(data_date=date(2026, 2, 28), ev=Decimal("550000"), ac=Decimal("600000")),
    )

    # No plan to earn against: the schedule half is undefined, not zero.
    assert measure.spi is None
    # The cost half is unaffected - EV and AC are both real observations.
    assert measure.cpi is not None
    assert measure.cv == Decimal("-50000.0000")
    # A forecast is still possible without a plan, but not the combined one,
    # which needs SPI. The row has to say which formula actually ran.
    assert measure.eac_method_effective in {"cpi", "remaining"}
    assert MeasureResponse.model_validate(measure).spi is None
