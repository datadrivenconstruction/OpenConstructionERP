# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Historical performance: statistics, splits, currency, data quality, drilldown, comparison, context.

Every figure below is invented and worked out by hand in the comment beside it, so a failure says
which arithmetic moved. The contracts:

* the leading benchmark of a ratio is a ratio of sums, the mean of projects and the median are served
  beside it and never in its place; P10/P90 only from ten projects, dispersion from two;
* a split (a project attribute or a row field such as ``classification.din276``) is one more group key,
  never a merge;
* money is restated in a reporting currency only on request and only with a rate the FX register has,
  and the original value, currency and rate travel with the result;
* the coverage figures are unavailable, not zero, when their whole is zero;
* a drilldown's totals equal the reading it explains, including through unit conversion;
* no route reads, names or counts a project or a position the caller cannot open.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bi_dashboards import kpi_spec, performance
from app.modules.bi_dashboards.kpi_spec import KPISpecError, ProjectReading
from tests._pg import transactional_session

D = Decimal

HOURS_PER_UNIT = performance.VALIDATED_PRESETS["labour_hours_per_installed_unit"]
RATE_PER_UNIT = performance.VALIDATED_PRESETS["estimate_rate_per_unit"]


def _reading(
    pid: uuid.UUID,
    num: str,
    den: str,
    *,
    unit: str = "m2",
    currency: str | None = None,
    records: int = 1,
) -> ProjectReading:
    dims: dict[str, str | None] = {}
    if currency is not None:
        dims["currency"] = currency
    dims["unit"] = unit
    value, reason = kpi_spec.ratio_value(D(num), D(den))
    return ProjectReading(
        project_id=pid,
        group_key=kpi_spec.dimension_key(list(dims.values())),
        dimensions=dims,
        value=value,
        records=records,
        numerator=D(num),
        denominator=D(den),
        unavailable_reason=reason,
    )


# ── Statistics ──────────────────────────────────────────────────────────


def test_weighted_mean_and_median_are_three_different_answers() -> None:
    # A 100 h / 50 m2 = 2.0, B 300 h / 200 m2 = 1.5, C 20 h / 40 m2 = 0.5.
    # Weighted: 420 / 290 = 1.448275862...; mean of projects (2.0 + 1.5 + 0.5) / 3 = 1.3333...; median 1.5.
    readings = [
        _reading(uuid.uuid4(), "100", "50"),
        _reading(uuid.uuid4(), "300", "200"),
        _reading(uuid.uuid4(), "20", "40"),
    ]
    summary = performance.summarise(readings, "ratio")
    assert summary.weighted == D("420") / D("290")
    assert summary.mean == D("4") / D("3")
    assert summary.median == D("1.5")
    assert (summary.p25, summary.p75) == (D("1.0"), D("1.75"))
    assert performance.headline(summary, "weighted") == (D("420") / D("290"), "weighted")
    assert performance.headline(summary, "mean") == (D("4") / D("3"), "mean")


def test_tails_only_from_ten_projects_and_dispersion_from_two() -> None:
    # Values 1..10: PERCENTILE.INC P10 at index 0.9 -> 1.9, P90 at index 8.1 -> 9.1.
    # Mean 5.5, squared deviations sum to 82.5, sample variance 82.5 / 9, sd = sqrt(9.1666...).
    ten = [_reading(uuid.uuid4(), str(v), "1") for v in range(1, 11)]
    summary = performance.summarise(ten, "ratio")
    assert (summary.p10, summary.p90) == (D("1.9"), D("9.1"))
    expected_sd = (D("82.5") / D("9")).sqrt()
    assert summary.stddev == expected_sd
    assert summary.cv == expected_sd / D("5.5")

    nine = performance.summarise(ten[:9], "ratio")
    assert (nine.p10, nine.p90) == (None, None)
    one = performance.summarise(ten[:1], "ratio")
    assert (one.stddev, one.cv) == (None, None)


def test_dispersion_has_no_cv_around_a_zero_mean() -> None:
    readings = [
        ProjectReading(project_id=uuid.uuid4(), group_key="", dimensions={}, value=D(v), records=1) for v in ("-2", "2")
    ]
    summary = performance.summarise(readings, "sum")
    assert summary.mean == D("0")
    assert summary.stddev is not None and summary.stddev > 0
    assert summary.cv is None


def test_excluded_readings_are_counted_by_reason_and_left_out() -> None:
    readings = [
        _reading(uuid.uuid4(), "100", "50"),
        _reading(uuid.uuid4(), "40", "0"),
        _reading(uuid.uuid4(), "10", "0"),
    ]
    readings.append(
        ProjectReading(
            project_id=uuid.uuid4(),
            group_key="m2",
            dimensions={"unit": "m2"},
            value=None,
            records=1,
            unavailable_reason=kpi_spec.UNAVAILABLE_NO_DATA,
        )
    )
    summary = performance.summarise(readings, "ratio")
    assert summary.excluded == {kpi_spec.UNAVAILABLE_ZERO_DENOMINATOR: 2, kpi_spec.UNAVAILABLE_NO_DATA: 1}
    assert summary.weighted == D("2")
    assert summary.projects_with_value == 1
    assert summary.projects_with_data == 4


# ── Compound units ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("preset", "dims", "expected"),
    [
        ("labour_hours_per_installed_unit", {"unit": "m2"}, "h/m2"),
        ("plant_hours_per_installed_unit", {"unit": "m3"}, "h/m3"),
        ("installed_units_per_labour_hour", {"unit": "pcs"}, "pcs/h"),
        ("estimate_rate_per_unit", {"currency": "EUR", "unit": "m"}, "EUR/m"),
        ("budget_per_floor_area", {"currency": "EUR"}, "EUR/m2"),
        ("actual_cost_per_floor_area", {"currency": "CHF"}, "CHF/m2"),
        ("approved_labour_hours", {}, "h"),
        ("installed_quantity", {"unit": "m3"}, "m3"),
    ],
)
def test_value_unit_is_the_compound_of_the_fields_and_the_group(preset: str, dims: dict, expected: str) -> None:
    assert performance.value_unit(performance.VALIDATED_PRESETS[preset], dims) == expected


def test_value_unit_is_unset_when_it_cannot_be_stated() -> None:
    count = kpi_spec.validate_spec({"entity": "boq_position", "aggregation": "count"})
    assert performance.value_unit(count, {}) is None
    # A rate per unit with no unit on the group is not "EUR/": it is unknown.
    assert performance.value_unit(RATE_PER_UNIT, {"currency": "EUR", "unit": None}) is None


# ── Splits ──────────────────────────────────────────────────────────────


def test_resolve_split_accepts_project_attributes_and_row_fields() -> None:
    assert performance.resolve_split(HOURS_PER_UNIT, None) is None
    assert performance.resolve_split(HOURS_PER_UNIT, "client") == performance.Split(project_attribute="client")
    by_class = performance.resolve_split(HOURS_PER_UNIT, "classification.din276")
    assert by_class == performance.Split(row_field="classification.din276")
    assert by_class.name == "classification.din276"


@pytest.mark.parametrize(
    ("split", "path"),
    [
        ("installed_quantity", "split_by"),  # a measure
        ("unit", "split_by"),  # already a dimension
        ("nonsense", "split_by"),  # not a field
    ],
)
def test_resolve_split_refuses_what_cannot_key_a_group(split: str, path: str) -> None:
    with pytest.raises(KPISpecError) as err:
        performance.resolve_split(HOURS_PER_UNIT, split)
    assert err.value.path == path


def test_a_project_split_prefixes_the_group_key() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    readings = [_reading(a, "100", "50"), _reading(b, "300", "200")]
    performance.apply_project_split(readings, {a: "Acme", b: None}, "client")
    assert [r.dimensions for r in readings] == [{"client": "Acme", "unit": "m2"}, {"client": None, "unit": "m2"}]
    groups = performance.group_readings(readings, "ratio")
    assert {g.key for g in groups} == {"Acme|m2", f"{kpi_spec.NULL_GROUP_KEY}|m2"}


def test_pick_classification_key_takes_the_requested_or_the_commonest() -> None:
    items = [{"din276": "330", "nrm": "2.1"}, {"din276": "340"}, {"nrm": ""}, {}]
    assert performance.pick_classification_key(items, None) == "din276"
    assert performance.pick_classification_key(items, "nrm") == "nrm"
    assert performance.pick_classification_key(items, "bad key") is None
    assert performance.pick_classification_key([{}, {"x": None}], None) is None


# ── Currency normalisation ──────────────────────────────────────────────


def _fx(**rates: str) -> performance.FxRates:
    return performance.FxRates(
        to_currency="EUR",
        rates={k: D(v) for k, v in rates.items()},
        as_of=date(2026, 9, 30),
        source="test",
    )


def test_money_is_restated_only_with_a_rate_and_keeps_its_original() -> None:
    a, b, c, d = (uuid.uuid4() for _ in range(4))
    # Rate per unit: A 1000 EUR / 10 m2 = 100; B 2000 USD / 10 m2 = 200 USD, at 0.9 -> 1800 EUR / 10 = 180;
    # C in GBP has no rate and keeps its group; D has no currency at all and keeps its group.
    readings = [
        _reading(a, "1000", "10", currency="EUR"),
        _reading(b, "2000", "10", currency="USD"),
        _reading(c, "500", "10", currency="GBP"),
        _reading(d, "700", "10", currency=""),
    ]
    out = performance.convert_currencies(readings, RATE_PER_UNIT, _fx(USD="0.9"))
    by_project = {r.project_id: r for r in out}
    converted = by_project[b]
    assert converted.dimensions["currency"] == "EUR"
    assert (converted.numerator, converted.value) == (D("1800.0"), D("180"))
    assert (converted.original_value, converted.original_currency, converted.fx_rate) == (D("200"), "USD", D("0.9"))
    assert converted.converted_from_currency == ["USD"]
    assert by_project[c].dimensions["currency"] == "GBP"
    assert by_project[d].dimensions["currency"] == ""
    assert by_project[a].original_value is None

    groups = performance.group_readings(out, "ratio", fx=_fx(USD="0.9"))
    eur = next(g for g in groups if g.dimensions["currency"] == "EUR")
    # (1000 + 1800) / (10 + 10) = 140.
    assert eur.summary is not None and eur.summary.weighted == D("140")
    assert [(c.from_currency, c.to_currency, c.rate) for c in eur.currency_conversions] == [("USD", "EUR", D("0.9"))]
    assert performance.reading_currencies(groups) == {"EUR", "GBP"}


def test_a_money_over_money_ratio_does_not_move_with_the_rate() -> None:
    spec = kpi_spec.validate_spec(
        {"entity": "project", "aggregation": "ratio", "field": "budget_estimate", "denominator_field": "contract_value"}
    )
    assert performance.currency_exponents(spec) == (1, 1)
    assert performance.currency_value_exponent(spec) == 0
    reading = ProjectReading(
        project_id=uuid.uuid4(),
        group_key="USD",
        dimensions={"currency": "USD"},
        value=D("0.8"),
        records=1,
        numerator=D("80"),
        denominator=D("100"),
    )
    (out,) = performance.convert_currencies([reading], spec, _fx(USD="0.9"))
    assert out.value == D("0.8")
    assert out.dimensions["currency"] == "EUR"


def test_currency_exponents_follow_the_kpi_shape() -> None:
    assert performance.currency_exponents(RATE_PER_UNIT) == (1, 0)
    assert performance.currency_value_exponent(RATE_PER_UNIT) == 1
    assert performance.currency_exponents(HOURS_PER_UNIT) == (0, 0)
    count = kpi_spec.validate_spec({"entity": "boq_position", "aggregation": "count"})
    assert performance.currency_exponents(count) == (0, 0)


# ── Database: fixtures ──────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _user(session: AsyncSession) -> uuid.UUID:
    from app.modules.users.models import User

    uid = uuid.uuid4()
    session.add(User(id=uid, email=f"hist-{uid.hex[:8]}@test.io", hashed_password="x", full_name="H", role="editor"))
    await session.flush()
    return uid


async def _project(
    session: AsyncSession,
    owner: uuid.UUID,
    name: str,
    *,
    client: str | None = None,
    status: str = "active",
    currency: str = "EUR",
    actual_end: str | None = None,
) -> uuid.UUID:
    from app.modules.boq.models import BOQ
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    session.add(
        Project(
            id=pid,
            name=name,
            owner_id=owner,
            currency=currency,
            client_id=client,
            status=status,
            actual_end_date=actual_end,
        )
    )
    await session.flush()
    session.add(BOQ(id=pid, project_id=pid, name=f"{name} bill"))
    await session.flush()
    return pid


async def _sheet(session: AsyncSession, project_id: uuid.UUID) -> uuid.UUID:
    from app.modules.field_time.models import FieldTimesheet

    sheet = FieldTimesheet(
        project_id=project_id, reference=f"TS-{uuid.uuid4().hex[:8]}", date=date(2026, 9, 1), status="approved"
    )
    session.add(sheet)
    await session.flush()
    return sheet.id


async def _hours(session: AsyncSession, project_id: uuid.UUID, hours: str, position_id: uuid.UUID | None) -> None:
    from app.modules.field_time.models import FieldTimesheetLine

    session.add(
        FieldTimesheetLine(
            timesheet_id=await _sheet(session, project_id),
            resource_id=uuid.uuid4(),
            hours=D(hours),
            cost_code="",
            boq_position_id=position_id,
        )
    )
    await session.flush()


async def _position(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    quantity: str,
    unit: str = "m2",
    hours: str | None = None,
    percent: str | None = "100",
    classification: dict | None = None,
    unit_rate: str = "10",
    labour_per_unit: str | None = None,
    ordinal: str = "01",
) -> uuid.UUID:
    from app.modules.boq.models import Position
    from app.modules.progress.models import ProgressEntry

    pos_id = uuid.uuid4()
    session.add(
        Position(
            id=pos_id,
            boq_id=project_id,
            ordinal=ordinal,
            description=f"Work {ordinal}",
            unit=unit,
            quantity=quantity,
            unit_rate=unit_rate,
            total=str(D(quantity) * D(unit_rate)),
            classification=classification or {},
            metadata_=(
                {"resources": [{"type": "labor", "quantity": labour_per_unit, "unit_rate": "40"}]}
                if labour_per_unit
                else {}
            ),
        )
    )
    await session.flush()
    if percent is not None:
        session.add(
            ProgressEntry(
                project_id=project_id, boq_position_id=pos_id, period_label="2026-09", percent_complete=D(percent)
            )
        )
        await session.flush()
    if hours is not None:
        await _hours(session, project_id, hours, pos_id)
    return pos_id


# ── Database: splits and cohort filters ─────────────────────────────────


@pytest.mark.asyncio
async def test_split_by_classification_and_by_client_are_ratio_of_sums_per_value(session: AsyncSession) -> None:
    me = await _user(session)
    a = await _project(session, me, "A", client="Acme")
    b = await _project(session, me, "B", client="Bolt")
    # 330: A 100 h / 50 m2, B 300 h / 200 m2 -> 400 / 250 = 1.6. 340: A 30 h / 10 m2 = 3.
    await _position(session, a, quantity="50", hours="100", classification={"din276": "330"})
    await _position(session, b, quantity="200", hours="300", classification={"din276": "330"})
    await _position(session, a, quantity="10", hours="30", classification={"din276": "340"}, ordinal="02")

    split = performance.resolve_split(HOURS_PER_UNIT, "classification.din276")
    groups = await performance.benchmark(session, spec=HOURS_PER_UNIT, cohort={a, b}, split=split)
    by_code = {g.dimensions["classification.din276"]: g for g in groups}
    assert set(by_code) == {"330", "340"}
    assert by_code["330"].summary is not None and by_code["330"].summary.weighted == D("1.6")
    assert by_code["340"].summary is not None and by_code["340"].summary.weighted == D("3")
    assert by_code["330"].key == "330|m2"

    by_client = await performance.benchmark(
        session, spec=HOURS_PER_UNIT, cohort={a, b}, split=performance.Split(project_attribute="client")
    )
    weighted = {g.dimensions["client"]: g.summary.weighted for g in by_client if g.summary}
    # Acme: (100 + 30) / (50 + 10) = 2.1666...; Bolt: 300 / 200 = 1.5.
    assert weighted == {"Acme": D("130") / D("60"), "Bolt": D("1.5")}


@pytest.mark.asyncio
async def test_status_filter_exclusion_and_end_year_split_through_the_endpoint(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.router import performance_benchmark
    from app.modules.bi_dashboards.schemas import PerformanceBenchmarkRequest

    me = await _user(session)
    done = await _project(session, me, "Done", status="completed", actual_end="2025-06-30")
    running = await _project(session, me, "Running", status="active")
    await _position(session, done, quantity="50", hours="100")
    await _position(session, running, quantity="200", hours="300")

    completed = await performance_benchmark(
        PerformanceBenchmarkRequest(kpi="labour_hours_per_installed_unit", statuses=["completed"]),
        user_id=str(me),
        session=session,
    )
    assert [p.project_id for p in completed.projects] == [done]
    assert completed.groups[0].benchmark.weighted == D("2")
    assert completed.groups[0].value_unit == "h/m2"

    without = await performance_benchmark(
        PerformanceBenchmarkRequest(kpi="labour_hours_per_installed_unit", exclude_project_ids=[done]),
        user_id=str(me),
        session=session,
    )
    assert [p.project_id for p in without.projects] == [running]

    by_year = await performance_benchmark(
        PerformanceBenchmarkRequest(kpi="labour_hours_per_installed_unit", split_by="end_year"),
        user_id=str(me),
        session=session,
    )
    assert by_year.split_by == "end_year"
    assert {g.dimensions["end_year"] for g in by_year.groups} == {"2025", None}

    with pytest.raises(HTTPException) as bad:
        await performance_benchmark(
            PerformanceBenchmarkRequest(kpi="labour_hours_per_installed_unit", split_by="installed_quantity"),
            user_id=str(me),
            session=session,
        )
    assert bad.value.status_code == 422


@pytest.mark.asyncio
async def test_rows_carry_variance_and_the_response_counts_projects_without_data(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.router import performance_benchmark
    from app.modules.bi_dashboards.schemas import PerformanceBenchmarkRequest

    me = await _user(session)
    a = await _project(session, me, "A")
    b = await _project(session, me, "B")
    await _project(session, me, "Empty")
    await _position(session, a, quantity="50", hours="100")
    await _position(session, b, quantity="200", hours="300")

    out = await performance_benchmark(
        PerformanceBenchmarkRequest(kpi="labour_hours_per_installed_unit"),
        user_id=str(me),
        session=session,
    )
    assert out.projects_selected == 3
    assert out.projects_without_data == 1
    rows = {r.project_id: r for r in out.groups[0].rows}
    # Weighted 1.6: A 2.0 is +25 %, B 1.5 is -6.25 %.
    assert rows[a].variance == D("0.25")
    assert rows[b].variance == D("-0.0625")
    assert out.groups[0].benchmark.stddev is not None


# ── Database: currency through the endpoint ─────────────────────────────


@pytest.mark.asyncio
async def test_reporting_currency_uses_the_fx_register_and_names_what_it_could_not_price(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards.router import performance_benchmark
    from app.modules.bi_dashboards.schemas import PerformanceBenchmarkRequest

    me = await _user(session)
    eur = await _project(session, me, "Euro", currency="EUR")
    usd = await _project(session, me, "Dollar", currency="USD")
    odd = await _project(session, me, "Odd", currency="XQQ")
    await _position(session, eur, quantity="10", unit_rate="100")
    await _position(session, usd, quantity="10", unit_rate="200")
    await _position(session, odd, quantity="10", unit_rate="50")

    apart = await performance_benchmark(
        PerformanceBenchmarkRequest(kpi="estimate_rate_per_unit"), user_id=str(me), session=session
    )
    assert {g.dimensions["currency"] for g in apart.groups} == {"EUR", "USD", "XQQ"}

    out = await performance_benchmark(
        PerformanceBenchmarkRequest(kpi="estimate_rate_per_unit", reporting_currency="eur"),
        user_id=str(me),
        session=session,
    )
    assert out.reporting_currency == "EUR"
    assert out.currencies_unconverted == ["XQQ"]
    group = next(g for g in out.groups if g.dimensions["currency"] == "EUR")
    assert group.value_unit == "EUR/m2"
    row = next(r for r in group.rows if r.project_id == usd)
    assert (row.original_currency, row.original_value) == ("USD", D("200"))
    assert row.fx_rate is not None and row.fx_rate > 0
    assert row.value == D("200") * row.fx_rate
    (conversion,) = group.currency_conversions
    assert (conversion.from_currency, conversion.to_currency, conversion.rate) == ("USD", "EUR", row.fx_rate)


# ── Database: data quality ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_data_quality_shares_and_unavailable_when_the_whole_is_zero(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.router import performance_data_quality
    from app.modules.bi_dashboards.schemas import PerformanceDataQualityRequest

    me = await _user(session)
    stranger = await _user(session)
    p = await _project(session, me, "P")
    # 100 h on a position, 25 h on none: linked 100 / 125 = 0.8.
    # Three priced positions, two with progress: 0.6667. One classified under din276: 0.3333.
    await _position(session, p, quantity="10", hours="100", classification={"din276": "330"})
    await _position(session, p, quantity="5", ordinal="02")
    await _position(session, p, quantity="5", percent=None, ordinal="03")
    await _hours(session, p, "25", None)
    theirs = await _project(session, stranger, "Theirs")
    await _hours(session, theirs, "1000", None)

    out = await performance_data_quality(
        PerformanceDataQualityRequest(classification_key="din276"), user_id=str(me), session=session
    )
    assert out.projects == 1
    assert (out.hours_total, out.hours_linked, out.hours_linked_share) == (D("125"), D("100"), D("0.8"))
    assert (out.positions_total, out.positions_with_progress, out.progress_share) == (3, 2, D("0.6667"))
    assert (out.positions_classified, out.classification_share) == (1, D("0.3333"))

    empty = await _project(session, me, "Empty")
    nothing = await performance_data_quality(
        PerformanceDataQualityRequest(project_ids=[empty]), user_id=str(me), session=session
    )
    assert nothing.hours_total == D("0")
    assert nothing.hours_linked_share is None
    assert nothing.progress_share is None
    assert nothing.classification_key is None

    # Naming only someone else's project measures nothing at all.
    hidden = await performance_data_quality(
        PerformanceDataQualityRequest(project_ids=[theirs]), user_id=str(me), session=session
    )
    assert hidden.projects == 0
    assert hidden.hours_total is None


# ── Database: drilldown ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_drilldown_totals_reconcile_with_the_reading_through_unit_conversion(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.router import performance_benchmark, performance_drilldown
    from app.modules.bi_dashboards.schemas import PerformanceBenchmarkRequest, PerformanceDrilldownRequest

    me = await _user(session)
    a = await _project(session, me, "A")
    b = await _project(session, me, "B")
    # A: 40 h / 20 m2 and 60 h / 30 m2, plus 10 h on 107.639 ft2 (10 m2): 110 h / 60 m2.
    await _position(session, a, quantity="20", hours="40")
    await _position(session, a, quantity="30", hours="60", ordinal="02")
    await _position(session, a, quantity="107.639", unit="ft2", hours="10", ordinal="03")
    await _position(session, b, quantity="100", hours="150")

    bench = await performance_benchmark(
        PerformanceBenchmarkRequest(kpi="labour_hours_per_installed_unit", convert_units=True),
        user_id=str(me),
        session=session,
    )
    group = next(g for g in bench.groups if g.dimensions["unit"] == "m2")
    row = next(r for r in group.rows if r.project_id == a)
    assert row.converted_from == ["ft2"]

    drill = await performance_drilldown(
        PerformanceDrilldownRequest(
            kpi="labour_hours_per_installed_unit",
            project_id=a,
            dimensions={"unit": ["m2", *row.converted_from]},
            target_unit="m2",
            limit=2,
        ),
        user_id=str(me),
        session=session,
    )
    assert drill.total_records == 3
    assert drill.numerator == row.numerator
    assert drill.denominator == row.denominator
    assert drill.value == row.value
    assert drill.value_unit == "h/m2"
    assert len(drill.records) == 2
    assert [r.numerator for r in drill.records] == [D("60"), D("40")]

    rest = await performance_drilldown(
        PerformanceDrilldownRequest(
            kpi="labour_hours_per_installed_unit",
            project_id=a,
            dimensions={"unit": ["m2", "ft2"]},
            target_unit="m2",
            offset=2,
            limit=2,
        ),
        user_id=str(me),
        session=session,
    )
    (ft2,) = rest.records
    assert ft2.dimensions["unit"] == "ft2"
    assert ft2.denominator == D("107.639")
    assert ft2.counted_denominator is not None and abs(ft2.counted_denominator - D("10")) < D("0.0001")
    assert ft2.position_id is not None and ft2.boq_id == a


@pytest.mark.asyncio
async def test_drilldown_never_opens_another_users_project(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.router import performance_drilldown
    from app.modules.bi_dashboards.schemas import PerformanceDrilldownRequest

    me = await _user(session)
    stranger = await _user(session)
    theirs = await _project(session, stranger, "Theirs")
    await _position(session, theirs, quantity="10", hours="10")
    for project in (theirs, uuid.uuid4()):
        with pytest.raises(HTTPException) as hidden:
            await performance_drilldown(
                PerformanceDrilldownRequest(
                    kpi="labour_hours_per_installed_unit", project_id=project, dimensions={"unit": ["m2"]}
                ),
                user_id=str(me),
                session=session,
            )
        assert hidden.value.status_code == 404


# ── Database: comparison ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compare_reads_every_kpi_over_one_cohort_without_leaking(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.router import compare_projects
    from app.modules.bi_dashboards.schemas import PerformanceCompareRequest

    me = await _user(session)
    stranger = await _user(session)
    a = await _project(session, me, "A", client="Acme")
    b = await _project(session, me, "B")
    theirs = await _project(session, stranger, "Theirs")
    await _position(session, a, quantity="50", hours="100")
    await _position(session, b, quantity="200", hours="300")
    await _position(session, b, quantity="4", unit="pcs", hours="8", ordinal="02")
    await _position(session, theirs, quantity="1", hours="1000")

    out = await compare_projects(
        PerformanceCompareRequest(
            kpis=["labour_hours_per_installed_unit", "approved_labour_hours"],
            project_ids=[a, b, theirs],
        ),
        user_id=str(me),
        session=session,
    )
    assert out.projects_selected == 2
    assert {p.project_id for p in out.projects} == {a, b}
    assert next(p for p in out.projects if p.project_id == a).client == "Acme"
    columns = [(c.kpi, c.group.dimensions.get("unit")) for c in out.columns]
    assert columns == [
        ("labour_hours_per_installed_unit", "m2"),
        ("labour_hours_per_installed_unit", "pcs"),
        ("approved_labour_hours", None),
    ]
    hours = out.columns[2].group
    assert {r.project_id: r.value for r in hours.rows} == {a: D("100"), b: D("308")}
    assert all(r.project_id != theirs for c in out.columns for r in c.group.rows)
    m2 = out.columns[0].group
    assert m2.benchmark.weighted == D("1.6")
    assert {r.project_id: r.variance for r in m2.rows} == {a: D("0.25"), b: D("-0.0625")}

    with pytest.raises(HTTPException) as unknown:
        await compare_projects(PerformanceCompareRequest(kpis=["nope"]), user_id=str(me), session=session)
    assert unknown.value.status_code == 404


@pytest.mark.asyncio
async def test_compare_reads_each_kpi_in_one_query_whatever_the_cohort_size(session: AsyncSession) -> None:
    """No per-project query: the statement count does not grow with the number of projects."""
    from sqlalchemy import event

    from app.modules.bi_dashboards.router import compare_projects
    from app.modules.bi_dashboards.schemas import PerformanceCompareRequest

    me = await _user(session)

    async def run() -> int:
        statements: list[str] = []

        def count(*_args: object, **_kwargs: object) -> None:
            statements.append("x")

        engine = session.bind.sync_engine if hasattr(session.bind, "sync_engine") else session.bind
        event.listen(engine, "before_cursor_execute", count)
        try:
            await compare_projects(
                PerformanceCompareRequest(kpis=["labour_hours_per_installed_unit", "approved_labour_hours"]),
                user_id=str(me),
                session=session,
            )
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return len(statements)

    for i in range(2):
        pid = await _project(session, me, f"S{i}")
        await _position(session, pid, quantity="10", hours="10")
    small = await run()
    for i in range(8):
        pid = await _project(session, me, f"L{i}")
        await _position(session, pid, quantity="10", hours="10")
    large = await run()
    assert large == small


# ── Database: historical context for positions ──────────────────────────


@pytest.mark.asyncio
async def test_position_context_compares_with_past_positions_of_the_same_code(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.router import performance_position_context
    from app.modules.bi_dashboards.schemas import PerformancePositionContextRequest
    from app.modules.boq.models import Position

    me = await _user(session)
    stranger = await _user(session)
    past = [await _project(session, me, f"Past{i}") for i in range(3)]
    # Code 330 in the past: 10 h / 10 m2 = 1.0, 15 / 10 = 1.5, 20 / 10 = 2.0 -> median 1.5, P25 1.25, P75 1.75.
    for pid, hours in zip(past, ("10", "15", "20"), strict=True):
        await _position(session, pid, quantity="10", hours=hours, classification={"din276": "330"})
    # Code 340 elsewhere must not be compared with a 330 position.
    await _position(session, past[0], quantity="10", hours="90", classification={"din276": "340"}, ordinal="02")
    current = await _project(session, me, "Current")
    planned = await _position(
        session,
        current,
        quantity="50",
        percent=None,
        classification={"din276": "330"},
        labour_per_unit="1.8",
    )
    # Its own project's history must not count: a 330 job here at 100 h / 10 m2.
    await _position(session, current, quantity="10", hours="100", classification={"din276": "330"}, ordinal="02")
    unclassified = await _position(session, current, quantity="5", percent=None, labour_per_unit="1", ordinal="03")
    foreign = await _position(
        session,
        await _project(session, stranger, "Foreign"),
        quantity="10",
        hours="10",
        classification={"din276": "330"},
    )

    out = await performance_position_context(
        PerformancePositionContextRequest(position_ids=[planned, unclassified, foreign]),
        user_id=str(me),
        session=session,
    )
    assert out.classification_key == "din276"
    assert [i.position_id for i in out.items] == [planned, unclassified]
    item = out.items[0]
    assert item.status == "ok"
    assert item.classification_code == "330"
    assert (item.median, item.p25, item.p75) == (D("1.5"), D("1.25"), D("1.75"))
    assert item.estimate == D("1.8")
    assert item.band == "above"
    assert item.projects == 3
    assert item.value_unit == "h/m2"
    assert item.statistic == "median"
    assert item.variance == (D("1.8") - D("1.5")) / D("1.5")
    assert out.items[1].status == performance.CONTEXT_NO_CLASSIFICATION

    position = await session.get(Position, planned)
    assert position is not None and position.metadata_["resources"][0]["quantity"] == "1.8"


# ── Database: saved sets remember split and currency ────────────────────


@pytest.mark.asyncio
async def test_benchmark_set_keeps_split_and_currency_and_checks_the_split_on_save(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.router import create_benchmark_set, evaluate_benchmark_set, update_benchmark_set
    from app.modules.bi_dashboards.schemas import (
        BenchmarkSetCreate,
        BenchmarkSetEvaluateRequest,
        BenchmarkSetUpdate,
    )
    from app.modules.bi_dashboards.service import BIDashboardsService

    service = BIDashboardsService(session)
    me = await _user(session)
    a = await _project(session, me, "A", client="Acme")
    await _position(session, a, quantity="50", hours="100")

    created = await create_benchmark_set(
        BenchmarkSetCreate(
            name="By client",
            kpis=["labour_hours_per_installed_unit"],
            split_by="client",
            reporting_currency="chf",
        ),
        user_id=str(me),
        service=service,
    )
    assert (created.split_by, created.reporting_currency) == ("client", "CHF")
    read = await evaluate_benchmark_set(
        created.id, BenchmarkSetEvaluateRequest(), user_id=str(me), session=session, service=service
    )
    assert read.split_by == "client"
    assert read.groups[0].dimensions["client"] == "Acme"

    cleared = await update_benchmark_set(
        created.id, BenchmarkSetUpdate(split_by="", reporting_currency=""), user_id=str(me), service=service
    )
    assert (cleared.split_by, cleared.reporting_currency) == (None, None)

    with pytest.raises(HTTPException) as bad:
        await create_benchmark_set(
            BenchmarkSetCreate(name="Bad", kpis=["approved_labour_hours"], split_by="classification.din276"),
            user_id=str(me),
            service=service,
        )
    assert bad.value.status_code == 422


# ── Database: a conceptual estimate against actual cost per floor area ──


@pytest.mark.asyncio
async def test_conceptual_cost_per_area_is_checked_against_actuals_only(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.router import check_against_cohort
    from app.modules.bi_dashboards.schemas import PerformanceAdHocCheckRequest
    from app.modules.costmodel.models import BudgetLine
    from app.modules.projects.models import Project

    me = await _user(session)
    stranger = await _user(session)
    # Actual cost per m2: 2,000,000 / 1000 = 2000; 3,000,000 / 1000 = 3000; 4,000,000 / 1000 = 4000.
    # Median 3000, P25 2500, P75 3500. A 3600 estimate is above P75, +20 % on the median.
    owners = [me, me, me, stranger]
    actuals = ["2000000", "3000000", "4000000", "1"]
    for owner, actual in zip(owners, actuals, strict=True):
        pid = await _project(session, owner, f"Built {actual}")
        project = await session.get(Project, pid)
        assert project is not None
        project.gross_floor_area = "1000"
        session.add(BudgetLine(project_id=pid, category="construction", actual_amount=actual, currency="EUR"))
    await session.flush()

    out = await check_against_cohort(
        PerformanceAdHocCheckRequest(
            kpi="actual_cost_per_floor_area", value=D("3600"), currency="EUR", statistic="median"
        ),
        user_id=str(me),
        session=session,
    )
    assert out.status == "ok"
    assert out.group is not None
    assert out.group.evidence.projects_with_value == 3
    assert (out.group.benchmark.median, out.group.benchmark.p25, out.group.benchmark.p75) == (
        D("3000"),
        D("2500"),
        D("3500"),
    )
    assert out.band == "above"
    assert out.variance == D("0.2")
