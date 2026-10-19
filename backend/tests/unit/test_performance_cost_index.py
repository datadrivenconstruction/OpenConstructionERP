# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Historical cost brought to a reference date and region with the price index register.

The contracts, each pinned by a case the obvious wrong implementation fails:

* every month of a project's money moves by its own index factor, so a project whose costs span
  years is not restated with one factor taken from its first, last or average month;
* a month the index series has no point for excludes the reading with a reason, it is never
  counted unadjusted beside adjusted ones;
* a region without a location factor excludes the reading too, it is not read as the national 1;
* a reading without money (hours per m2) does not move, and currencies stay in their own groups;
* the provenance (series, base periods, target period, factors, value before) travels with the
  reading, and the drilldown's records restate the same way so their totals still reconcile.

The figures are invented and worked out in the comments.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bi_dashboards import kpi_spec, performance
from app.modules.bi_dashboards.kpi_spec import ProjectReading
from tests._pg import transactional_session

D = Decimal

RATE_PER_UNIT = performance.VALIDATED_PRESETS["estimate_rate_per_unit"]
HOURS_PER_UNIT = performance.VALIDATED_PRESETS["labour_hours_per_installed_unit"]

# Index points: 2020-06 at 100, 2022-06 at 120, 2024-06 at 150.
POINTS = {"2020-06": D("100"), "2022-06": D("120"), "2024-06": D("150")}


def _part(
    pid: uuid.UUID,
    money: str,
    qty: str,
    period: str | None,
    *,
    currency: str = "EUR",
    unit: str = "m2",
    records: int = 1,
) -> ProjectReading:
    dims: dict[str, str | None] = {"currency": currency, "unit": unit}
    value, reason = kpi_spec.ratio_value(D(money), D(qty))
    return ProjectReading(
        project_id=pid,
        group_key=kpi_spec.dimension_key(list(dims.values())),
        dimensions=dims,
        value=value,
        records=records,
        numerator=D(money),
        denominator=D(qty),
        unavailable_reason=reason,
        period=period,
    )


def _index(**kw: object) -> performance.CostIndex:
    base: dict[str, object] = {
        "series_id": uuid.uuid4(),
        "series_name": "Building cost index",
        "points": POINTS,
        "target_period": "2024-06",
    }
    base.update(kw)
    return performance.CostIndex(**base)  # type: ignore[arg-type]


# ── Pure: temporal factor per month ─────────────────────────────────────


def test_one_project_across_two_years_moves_each_month_by_its_own_factor() -> None:
    # 1000 EUR on 10 m2 in 2020-06 (x 150/100 = 1.5) and 3000 EUR on 10 m2 in 2022-06 (x 150/120 = 1.25).
    # Adjusted: 1500 + 3750 = 5250 over 20 m2 = 262.5 EUR/m2. Unadjusted 4000 / 20 = 200.
    # Wrong answers this rules out: one factor from the first month 300, from the last month 250,
    # the mean factor 1.375 -> 275, nothing adjusted 200.
    pid = uuid.uuid4()
    out = performance.normalise_costs(
        [_part(pid, "1000", "10", "2020-06"), _part(pid, "3000", "10", "2022-06")],
        RATE_PER_UNIT,
        _index(),
        project_regions={},
    )
    (reading,) = out
    assert reading.value == D("262.5")
    assert (reading.numerator, reading.denominator) == (D("5250"), D("20"))
    assert reading.records == 2
    assert reading.unadjusted_value == D("200")
    assert reading.index_base_periods == ["2020-06", "2022-06"]
    assert reading.index_target_period == "2024-06"
    assert reading.index_series == "Building cost index"
    # The effective factor is what the reader multiplies the before-value by: 262.5 / 200.
    assert reading.index_factor == D("1.3125")
    assert reading.location_factor is None
    assert reading.period is None


def test_a_single_month_carries_its_exact_factor() -> None:
    pid = uuid.uuid4()
    (reading,) = performance.normalise_costs(
        [_part(pid, "1200", "10", "2022-06")], RATE_PER_UNIT, _index(), project_regions={}
    )
    assert reading.index_factor == D("1.25")
    assert reading.value == D("150")


def test_a_month_the_series_lacks_excludes_the_whole_reading_with_a_reason() -> None:
    # 2019-01 has no index point. Counting the other month alone, or the 2019 money unadjusted
    # beside the adjusted 2022 money, would both print a figure; neither is one.
    pid, other = uuid.uuid4(), uuid.uuid4()
    out = performance.normalise_costs(
        [
            _part(pid, "1000", "10", "2019-01"),
            _part(pid, "1200", "10", "2022-06"),
            _part(other, "1200", "10", "2022-06"),
        ],
        RATE_PER_UNIT,
        _index(),
        project_regions={},
    )
    by_project = {r.project_id: r for r in out}
    gap = by_project[pid]
    assert gap.value is None
    assert gap.numerator is None and gap.denominator is None
    assert gap.unavailable_reason == performance.INDEX_PERIOD_MISSING
    assert gap.index_missing_periods == ["2019-01"]
    assert gap.records == 2
    assert by_project[other].value == D("150")

    summary = performance.summarise(out, "ratio")
    assert summary.excluded == {performance.INDEX_PERIOD_MISSING: 1}
    assert summary.weighted == D("150")


def test_a_reading_without_a_date_is_excluded_not_left_unadjusted() -> None:
    pid = uuid.uuid4()
    (reading,) = performance.normalise_costs(
        [_part(pid, "1000", "10", None)], RATE_PER_UNIT, _index(), project_regions={}
    )
    assert reading.value is None
    assert reading.unavailable_reason == performance.NO_RECORD_DATE


def test_a_zero_denominator_keeps_its_own_reason() -> None:
    pid = uuid.uuid4()
    (reading,) = performance.normalise_costs(
        [_part(pid, "1000", "0", "2022-06")], RATE_PER_UNIT, _index(), project_regions={}
    )
    assert reading.value is None
    assert reading.unavailable_reason == kpi_spec.UNAVAILABLE_ZERO_DENOMINATOR


# ── Pure: location ──────────────────────────────────────────────────────


def test_location_moves_by_the_ratio_of_regions_and_a_missing_factor_excludes() -> None:
    # BER 1.2 -> MUC 1.5 is x 1.25. "XYZ" has no factor and an empty region names none: both
    # excluded, neither read as the national 1, which would print 100 for them.
    ber, xyz, blank = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    index = performance.CostIndex(
        target_region="MUC",
        region_factors={"BER": D("1.2"), "MUC": D("1.5")},
    )
    out = performance.normalise_costs(
        [_part(ber, "1000", "10", None), _part(xyz, "1000", "10", None), _part(blank, "1000", "10", None)],
        RATE_PER_UNIT,
        index,
        project_regions={ber: " ber ", xyz: "XYZ", blank: ""},
    )
    by_project = {r.project_id: r for r in out}
    assert by_project[ber].value == D("125")
    assert by_project[ber].location_factor == D("1.25")
    assert by_project[ber].location_region == "BER"
    assert by_project[ber].index_factor is None
    assert by_project[xyz].value is None
    assert by_project[xyz].unavailable_reason == performance.NO_LOCATION_FACTOR
    assert by_project[blank].value is None
    assert by_project[blank].unavailable_reason == performance.NO_PROJECT_REGION


def test_time_and_location_compose() -> None:
    # 1000 EUR / 10 m2 in 2020-06, BER -> MUC: 100 x 1.5 x 1.25 = 187.5.
    pid = uuid.uuid4()
    (reading,) = performance.normalise_costs(
        [_part(pid, "1000", "10", "2020-06")],
        RATE_PER_UNIT,
        _index(target_region="MUC", region_factors={"BER": D("1.2"), "MUC": D("1.5")}),
        project_regions={pid: "BER"},
    )
    assert reading.value == D("187.5")
    assert (reading.index_factor, reading.location_factor) == (D("1.5"), D("1.25"))


# ── Pure: what must not move ────────────────────────────────────────────


def test_hours_per_unit_has_no_money_and_does_not_move() -> None:
    pid = uuid.uuid4()
    reading = ProjectReading(
        project_id=pid,
        group_key="m2",
        dimensions={"unit": "m2"},
        value=D("2"),
        records=1,
        numerator=D("20"),
        denominator=D("10"),
        period="2020-06",
    )
    assert not performance.cost_index_applies(HOURS_PER_UNIT)
    (out,) = performance.normalise_costs([reading], HOURS_PER_UNIT, _index(), project_regions={})
    assert out.value == D("2")
    assert out.index_factor is None


def test_currencies_are_adjusted_in_place_and_never_combined() -> None:
    eur, usd = uuid.uuid4(), uuid.uuid4()
    out = performance.normalise_costs(
        [_part(eur, "1000", "10", "2022-06"), _part(usd, "1000", "10", "2022-06", currency="USD")],
        RATE_PER_UNIT,
        _index(),
        project_regions={},
    )
    groups = performance.group_readings(out, "ratio")
    assert sorted(g.dimensions["currency"] for g in groups) == ["EUR", "USD"]
    assert all(g.summary is not None and g.summary.weighted == D("125") for g in groups)


def test_a_sum_of_money_moves_month_by_month_too() -> None:
    # Sum KPI: 100 in 2020-06 (x1.5) and 100 in 2022-06 (x1.25) = 275.
    pid = uuid.uuid4()
    spec = {"entity": "boq_position", "aggregation": "sum", "field": "total"}
    parts = [
        ProjectReading(
            project_id=pid,
            group_key="EUR",
            dimensions={"currency": "EUR"},
            value=D("100"),
            records=1,
            period=period,
        )
        for period in ("2020-06", "2022-06")
    ]
    assert performance.cost_index_applies(spec)
    (out,) = performance.normalise_costs(parts, spec, _index(), project_regions={})
    assert out.value == D("275")
    assert out.unadjusted_value == D("200")


def test_target_period_defaults_to_the_latest_point_and_must_exist() -> None:
    assert performance.pick_target_period(POINTS, None) == "2024-06"
    assert performance.pick_target_period(POINTS, "2022-06") == "2022-06"
    with pytest.raises(performance.CostIndexError):
        performance.pick_target_period(POINTS, "2025-01")
    with pytest.raises(performance.CostIndexError):
        performance.pick_target_period({}, None)


# ── Database ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession) -> uuid.UUID:
    from app.modules.users.models import User

    uid = uuid.uuid4()
    session.add(User(id=uid, email=f"idx-{uid.hex[:8]}@test.io", hashed_password="x", full_name="I", role="editor"))
    await session.flush()
    return uid


async def _project(session: AsyncSession, owner: uuid.UUID, name: str, *, region: str = "") -> uuid.UUID:
    from app.modules.boq.models import BOQ
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    session.add(Project(id=pid, name=name, owner_id=owner, currency="EUR", region=region))
    await session.flush()
    session.add(BOQ(id=pid, project_id=pid, name=f"{name} bill"))
    await session.flush()
    return pid


async def _position(
    session: AsyncSession, project_id: uuid.UUID, *, quantity: str, unit_rate: str, created: date, ordinal: str
) -> uuid.UUID:
    from app.modules.boq.models import Position

    pos_id = uuid.uuid4()
    session.add(
        Position(
            id=pos_id,
            boq_id=project_id,
            ordinal=ordinal,
            description=f"Work {ordinal}",
            unit="m2",
            quantity=quantity,
            unit_rate=unit_rate,
            total=str(D(quantity) * D(unit_rate)),
            classification={},
            metadata_={},
            created_at=datetime(created.year, created.month, created.day, 12, tzinfo=UTC),
        )
    )
    await session.flush()
    return pos_id


async def _series(session: AsyncSession, points: dict[str, Decimal]) -> uuid.UUID:
    from app.modules.price_index.models import CostIndexPoint, CostIndexSeries

    series = CostIndexSeries(name=f"Test index {uuid.uuid4().hex[:6]}", description="")
    session.add(series)
    await session.flush()
    for period, value in points.items():
        session.add(CostIndexPoint(series_id=series.id, period=period, factor=value))
    await session.flush()
    return series.id


async def _region(session: AsyncSession, code: str, factor: str) -> None:
    from app.modules.price_index.models import LocationFactor

    session.add(LocationFactor(region_code=code, label=code, factor=D(factor)))
    await session.flush()


@pytest.mark.asyncio
async def test_benchmark_restates_each_position_by_its_month_and_reports_provenance(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.router import performance_benchmark
    from app.modules.bi_dashboards.schemas import PerformanceBenchmarkRequest

    me = await _user(session)
    series = await _series(session, POINTS)
    a = await _project(session, me, "A")
    gap = await _project(session, me, "Gap")
    # A: 10 m2 at 100 in 2020-06 and 10 m2 at 300 in 2022-06 -> (1500 + 3750) / 20 = 262.5.
    await _position(session, a, quantity="10", unit_rate="100", created=date(2020, 6, 3), ordinal="01")
    await _position(session, a, quantity="10", unit_rate="300", created=date(2022, 6, 9), ordinal="02")
    # Gap: one position in 2019-01, which the series does not carry.
    await _position(session, gap, quantity="10", unit_rate="100", created=date(2019, 1, 15), ordinal="01")

    plain = await performance_benchmark(
        PerformanceBenchmarkRequest(kpi="estimate_rate_per_unit"), user_id=str(me), session=session
    )
    assert plain.cost_index is None
    (plain_group,) = plain.groups
    assert next(r for r in plain_group.rows if r.project_id == a).value == D("200")

    out = await performance_benchmark(
        PerformanceBenchmarkRequest(kpi="estimate_rate_per_unit", index_series_id=series),
        user_id=str(me),
        session=session,
    )
    assert out.cost_index is not None
    assert out.cost_index.applicable is True
    assert out.cost_index.target_period == "2024-06"
    (group,) = out.groups
    row = next(r for r in group.rows if r.project_id == a)
    assert row.value == D("262.5")
    assert row.unadjusted_value == D("200")
    assert row.index_factor == D("1.3125")
    assert row.index_base_periods == ["2020-06", "2022-06"]
    gap_row = next(r for r in group.rows if r.project_id == gap)
    assert gap_row.value is None
    assert gap_row.unavailable_reason == performance.INDEX_PERIOD_MISSING
    assert gap_row.index_missing_periods == ["2019-01"]
    assert group.excluded == {performance.INDEX_PERIOD_MISSING: 1}
    assert group.headline == D("262.5")


@pytest.mark.asyncio
async def test_a_target_period_or_region_the_register_lacks_is_refused(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.router import performance_benchmark
    from app.modules.bi_dashboards.schemas import PerformanceBenchmarkRequest

    me = await _user(session)
    series = await _series(session, POINTS)
    for request in (
        PerformanceBenchmarkRequest(
            kpi="estimate_rate_per_unit", index_series_id=series, index_target_period="2025-01"
        ),
        PerformanceBenchmarkRequest(kpi="estimate_rate_per_unit", index_series_id=uuid.uuid4()),
        PerformanceBenchmarkRequest(kpi="estimate_rate_per_unit", location_target_region="NOWHERE"),
    ):
        with pytest.raises(HTTPException) as caught:
            await performance_benchmark(request, user_id=str(me), session=session)
        assert caught.value.status_code == 422


@pytest.mark.asyncio
async def test_location_uses_the_project_region_and_the_check_compares_with_the_restated_range(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards.router import check_against_cohort, performance_benchmark
    from app.modules.bi_dashboards.schemas import PerformanceAdHocCheckRequest, PerformanceBenchmarkRequest

    me = await _user(session)
    await _region(session, "IDX-LOW", "0.8")
    await _region(session, "IDX-HIGH", "1.2")
    low = await _project(session, me, "Low", region="IDX-LOW")
    high = await _project(session, me, "High", region="IDX-HIGH")
    await _position(session, low, quantity="10", unit_rate="80", created=date(2024, 6, 1), ordinal="01")
    await _position(session, high, quantity="10", unit_rate="120", created=date(2024, 6, 1), ordinal="01")

    # Brought to IDX-HIGH: 80 x 1.2 / 0.8 = 120 and 120 x 1 = 120. Unadjusted they span 80 to 120.
    out = await performance_benchmark(
        PerformanceBenchmarkRequest(kpi="estimate_rate_per_unit", location_target_region="IDX-HIGH"),
        user_id=str(me),
        session=session,
    )
    (group,) = out.groups
    assert {r.project_id: r.value for r in group.rows} == {low: D("120"), high: D("120")}
    assert next(r for r in group.rows if r.project_id == low).location_factor == D("1.5")
    assert out.cost_index is not None and out.cost_index.target_region == "IDX-HIGH"

    # An estimate of 120 sits on the restated benchmark; against the raw one it would read high.
    check = await check_against_cohort(
        PerformanceAdHocCheckRequest(
            kpi="estimate_rate_per_unit",
            location_target_region="IDX-HIGH",
            value=D("120"),
            unit="m2",
            currency="EUR",
        ),
        user_id=str(me),
        session=session,
    )
    assert check.status == "ok"
    assert check.headline == D("120")
    assert check.variance == D("0")


@pytest.mark.asyncio
async def test_drilldown_restates_each_record_by_its_month_and_reconciles(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.router import performance_benchmark, performance_drilldown
    from app.modules.bi_dashboards.schemas import PerformanceBenchmarkRequest, PerformanceDrilldownRequest

    me = await _user(session)
    series = await _series(session, POINTS)
    a = await _project(session, me, "A")
    await _position(session, a, quantity="10", unit_rate="100", created=date(2020, 6, 3), ordinal="01")
    await _position(session, a, quantity="10", unit_rate="300", created=date(2022, 6, 9), ordinal="02")

    bench = await performance_benchmark(
        PerformanceBenchmarkRequest(kpi="estimate_rate_per_unit", index_series_id=series),
        user_id=str(me),
        session=session,
    )
    row = bench.groups[0].rows[0]
    drill = await performance_drilldown(
        PerformanceDrilldownRequest(
            kpi="estimate_rate_per_unit",
            project_id=a,
            dimensions={"currency": ["EUR"], "unit": ["m2"]},
            index_series_id=series,
        ),
        user_id=str(me),
        session=session,
    )
    assert (drill.numerator, drill.denominator, drill.value) == (row.numerator, row.denominator, row.value)
    factors = {r.description: r.index_factor for r in drill.records}
    assert factors == {"Work 01": D("1.5"), "Work 02": D("1.25")}
    counted = {r.description: r.counted_numerator for r in drill.records}
    assert counted == {"Work 01": D("1500"), "Work 02": D("3750")}
