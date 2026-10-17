# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Benchmark sets, unit conversion and the estimate-against-history check.

What an estimator relies on here:

* two readings in compatible units (m2 and ft2) become one group only when
  asked, every conversion is listed, a quantity moves by the factor and a
  rate per unit by its reciprocal, and units nothing can convert, or units of
  another dimension, stay apart;
* a saved set is a definition, read fresh over the cohort intersected with
  what the reader may open, so sharing a set shares no project;
* a group below the set's minimum evidence is served but flagged;
* checking an estimate places it in the range with a sample size and a
  confidence, and changes nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.unit_conversion import convert_strict, strict_unit_factor, unit_dimension
from app.modules.bi_dashboards import kpi_spec, performance
from app.modules.bi_dashboards.kpi_spec import ProjectReading
from app.modules.bi_dashboards.schemas import (
    BenchmarkSetCreate,
    BenchmarkSetEvaluateRequest,
    BenchmarkSetUpdate,
    PerformanceBenchmarkRequest,
    PerformanceCheckRequest,
)
from tests._pg import transactional_session

D = Decimal

HOURS = kpi_spec.validate_spec(
    {
        "entity": "position_progress",
        "aggregation": "ratio",
        "field": "labour_hours",
        "denominator_field": "installed_quantity",
    }
)
RATE = performance.VALIDATED_PRESETS["estimate_rate_per_unit"]


def _reading(
    unit: str | None,
    numerator: str,
    denominator: str,
    *,
    project: uuid.UUID | None = None,
    currency: str | None = None,
    records: int = 1,
) -> ProjectReading:
    dims: dict[str, str | None] = {"unit": unit}
    if currency is not None:
        dims = {"currency": currency, "unit": unit}
    names = sorted(dims)
    value, reason = kpi_spec.ratio_value(D(numerator), D(denominator))
    return ProjectReading(
        project_id=project or uuid.uuid4(),
        group_key=kpi_spec.dimension_key([dims[n] for n in names]),
        dimensions=dims,
        value=value,
        records=records,
        numerator=D(numerator),
        denominator=D(denominator),
        unavailable_reason=reason,
    )


# ── Unit vocabulary ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("src", "dst", "expected"),
    [
        ("m2", "ft2", "10.7639"),
        ("m²", "M2", "1"),
        ("m3", "yd3", "1.30795"),
        ("m3", "cy", "1.30795"),
        ("kg", "t", "0.001"),
        ("t", "lb", "2204.62"),
        ("hr", "h", "1"),
        ("h", "min", "60"),
    ],
)
def test_strict_unit_factor_within_a_dimension(src: str, dst: str, expected: str) -> None:
    assert strict_unit_factor(src, dst) == D(expected)


@pytest.mark.parametrize(
    ("src", "dst"),
    [("m2", "m3"), ("pcs", "m2"), ("set", "set"), ("шт", "pcs"), (None, "m2"), ("m2", ""), ("day", "h")],
)
def test_strict_unit_factor_refuses_what_it_cannot_convert(src: str | None, dst: str) -> None:
    # A missing unit is unknown, never "the same as the other one", and a
    # day has no fixed number of working hours.
    assert strict_unit_factor(src, dst) is None


def test_convert_strict_is_exact_both_ways() -> None:
    # 10.7639 ft2 per m2 exactly as the table states it, with no reciprocal
    # rounding left behind in either direction.
    assert convert_strict(D("2152.78"), "ft2", "m2") == D("200")
    assert convert_strict(D("2"), "ft2", "m2", -1) == D("21.5278")
    assert convert_strict(D("21.5278"), "m2", "ft2", -1) == D("2")
    assert convert_strict(D("5"), "m2", "ft2", 0) == D("5")
    assert convert_strict(D("5"), "m2", "pcs") is None


def test_unit_dimension_reads_the_shared_table() -> None:
    assert unit_dimension("M²") == "area"
    assert unit_dimension("ton_us") == "mass"
    assert unit_dimension("hrs") == "time"
    assert unit_dimension("lsum") is None
    assert unit_dimension(None) is None


def test_every_field_with_a_unit_dimension_says_how_it_converts() -> None:
    declared = {
        (name, field)
        for name, entry in kpi_spec.ENTITY_CATALOG.items()
        for field, dims in entry.dimensions.items()
        if "unit" in dims
    }
    assert declared == set(performance.UNIT_EXPONENTS)


def test_exponents_follow_the_kpi_shape() -> None:
    assert performance.value_exponent(HOURS) == -1
    assert performance.quotient_exponents(HOURS) == (0, 1)
    assert performance.value_exponent(RATE) == -1
    per_hour = kpi_spec.validate_spec(
        {
            "entity": "position_progress",
            "aggregation": "ratio",
            "field": "installed_quantity",
            "denominator_field": "labour_hours",
        }
    )
    assert performance.value_exponent(per_hour) == 1
    total = kpi_spec.validate_spec({"entity": "position_progress", "aggregation": "sum", "field": "installed_quantity"})
    assert performance.value_exponent(total) == 1


# ── Conversion of readings ──────────────────────────────────────────────


def test_conversion_merges_ft2_into_m2_as_a_ratio_of_sums() -> None:
    a = _reading("m2", "100", "50")
    c = _reading("m2", "10", "10")
    b = _reading("ft2", "300", "2152.78")  # 200 m2
    converted, conversions = performance.convert_units([a, b, c], HOURS)
    groups = performance.group_readings(converted, "ratio", conversions)
    assert len(groups) == 1
    group = groups[0]
    assert group.dimensions == {"unit": "m2"}
    assert [(x.from_unit, x.to_unit, x.factor) for x in group.conversions] == [("ft2", "m2", 1 / D("10.7639"))]
    moved = next(r for r in group.readings if r.project_id == b.project_id)
    assert moved.converted_from == ["ft2"]
    assert moved.denominator == D("200")
    assert moved.value == D("1.5")
    assert group.summary is not None
    assert group.summary.weighted == D("410") / D("260")
    # Off, the same readings stay in two groups.
    assert len(performance.group_readings([a, b, c], "ratio")) == 2


def test_a_rate_per_unit_moves_by_the_reciprocal() -> None:
    m2 = _reading("m2", "100", "10", currency="EUR")
    m2b = _reading("m2", "60", "6", currency="EUR")
    ft2 = _reading("ft2", "100", "107.639", currency="EUR")  # EUR 100 for 10 m2
    converted, _ = performance.convert_units([m2, m2b, ft2], RATE)
    values = {r.project_id: r.value for r in converted}
    assert values[ft2.project_id] == D("10")
    assert values[m2.project_id] == D("10")


def test_currencies_other_dimensions_and_unknown_units_stay_apart() -> None:
    readings = [
        _reading("m2", "10", "1", currency="EUR"),
        _reading("ft2", "10", "1", currency="USD"),
        _reading("m3", "10", "1", currency="EUR"),
        _reading("set", "10", "1", currency="EUR"),
        _reading(None, "10", "1", currency="EUR"),
    ]
    converted, conversions = performance.convert_units(readings, RATE)
    assert conversions == {}
    assert len({r.group_key for r in converted}) == 5


def test_one_project_in_two_compatible_units_is_one_row() -> None:
    project = uuid.uuid4()
    rows = [
        _reading("m2", "20", "10", project=project),
        _reading("ft2", "20", "107.639", project=project, records=2),
        _reading("m2", "5", "5"),
    ]
    converted, _ = performance.convert_units(rows, HOURS)
    mine = [r for r in converted if r.project_id == project]
    assert len(mine) == 1
    assert (mine[0].numerator, mine[0].denominator, mine[0].records) == (D("40"), D("20"), 3)
    assert mine[0].value == D("2")


def test_a_sum_of_quantity_converts_and_adds() -> None:
    spec = kpi_spec.validate_spec({"entity": "position_progress", "aggregation": "sum", "field": "installed_quantity"})
    project = uuid.uuid4()
    rows = [
        ProjectReading(project, "m2", {"unit": "m2"}, D("10"), 1),
        ProjectReading(project, "m2", {"unit": "m2"}, D("4"), 1),
        ProjectReading(project, "ft2", {"unit": "ft2"}, D("10.7639"), 1),
    ]
    rows[1] = ProjectReading(uuid.uuid4(), "m2", {"unit": "m2"}, D("4"), 1)
    converted, _ = performance.convert_units(rows, spec)
    assert {r.value for r in converted if r.project_id == project} == {D("11")}


# ── Evidence, headline and the check ────────────────────────────────────


def _group(values: list[str], unit: str = "m2") -> performance.BenchmarkGroup:
    readings = [_reading(unit, v, "1") for v in values]
    return performance.group_readings(readings, "ratio")[0]


def test_evidence_shortfall_and_headline() -> None:
    group = _group(["1", "2"])
    assert group.summary is not None
    assert performance.evidence_shortfall(group.summary, min_projects=3) == [performance.SHORTFALL_PROJECTS]
    assert performance.evidence_shortfall(group.summary, min_records=3) == [performance.SHORTFALL_RECORDS]
    assert performance.evidence_shortfall(group.summary, min_projects=2, min_records=2) == []
    assert performance.headline(group.summary, "mean") == (D("1.5"), "mean")
    sums = performance.summarise(group.readings, "sum")
    # A sum has no weighted figure; the label follows the figure delivered.
    assert performance.headline(sums, "weighted") == (sums.median, "median")


def test_check_places_a_value_and_converts_a_rate_per_ft2() -> None:
    group = _group(["8", "9", "10", "11", "12", "13", "14", "15", "16", "17"])
    inside = performance.check_value(group, D("12"), spec=HOURS)
    assert inside.band == "within"
    assert inside.percentile_rank == D("45")
    assert inside.confidence == "high"
    assert inside.statistic == "weighted"
    assert inside.variance == (D("12") - D("12.5")) / D("12.5")

    per_ft2 = performance.check_value(group, D("2"), spec=HOURS, from_unit="ft2")
    assert per_ft2.value == D("2") * D("10.7639")
    assert per_ft2.unit_factor == D("10.7639")
    assert per_ft2.band == "above"

    thin = performance.check_value(_group(["1", "2", "3", "4"]), D("2"), spec=HOURS, min_projects=5)
    assert thin.confidence == "low"
    assert thin.shortfall == [performance.SHORTFALL_PROJECTS]
    assert performance.check_value(_group(["1", "2", "3", "4"]), D("2"), spec=HOURS).confidence == "medium"


def test_find_group_matches_currency_exactly_and_unit_by_conversion() -> None:
    eur = performance.group_readings([_reading("m2", "10", "1", currency="EUR")], "ratio")
    assert performance.find_group(eur, unit="ft2", currency="eur") == (eur[0], "ft2")
    assert performance.find_group(eur, unit="m2", currency="EUR") == (eur[0], None)
    assert performance.find_group(eur, unit="m2", currency="USD") is None
    assert performance.find_group(eur, unit="pcs", currency="EUR") is None


def test_position_estimate_kind() -> None:
    assert performance.position_estimate_kind(HOURS) == "labour_hours"
    assert performance.position_estimate_kind(RATE) == "unit_rate"
    assert performance.position_estimate_kind(performance.VALIDATED_PRESETS["approved_labour_hours"]) is None
    assert performance.position_estimate_kind(performance.VALIDATED_PRESETS["budget_per_floor_area"]) is None


# ── Schemas ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        {"name": " ", "kpis": ["labour_hours_per_installed_unit"]},
        {"name": "x", "kpis": []},
        {"name": "x", "kpis": ["a"] * 9},
        {"name": "x", "kpis": ["a"], "scope": "global"},
        {"name": "x", "kpis": ["a"], "statistic": "mode"},
        {"name": "x", "kpis": ["a"], "min_projects": -1},
        {"name": "x", "kpis": ["a"], "cohort": {"period_start": "2026-02-01", "period_end": "2026-01-01"}},
        {"name": "x", "kpis": ["a"], "cohort": {"clients": ["c" * 256]}},
        {"name": "x", "kpis": ["a"], "cohort": {"unknown": 1}},
    ],
)
def test_benchmark_set_validation(payload: dict) -> None:
    with pytest.raises(ValidationError):
        BenchmarkSetCreate(**payload)


def test_benchmark_set_cleans_its_lists() -> None:
    created = BenchmarkSetCreate(name="  Drywall  ", kpis=["a", " a ", "b"], cohort={"clients": ["X", " X", ""]})
    assert created.name == "Drywall"
    assert created.kpis == ["a", "b"]
    assert created.cohort.clients == ["X"]
    with pytest.raises(ValidationError):
        BenchmarkSetUpdate(statistic="mode")
    with pytest.raises(ValidationError):
        PerformanceCheckRequest(value=D("1"), boq_position_id=uuid.uuid4())
    with pytest.raises(ValidationError):
        PerformanceCheckRequest()


# ── Database ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _user(session: AsyncSession) -> uuid.UUID:
    from app.modules.users.models import User

    uid = uuid.uuid4()
    session.add(User(id=uid, email=f"bset-{uid.hex[:8]}@test.io", hashed_password="x", full_name="B", role="editor"))
    await session.flush()
    return uid


async def _project(
    session: AsyncSession, owner: uuid.UUID, name: str, *, client: str | None = None, region: str = ""
) -> uuid.UUID:
    from app.modules.boq.models import BOQ
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    session.add(Project(id=pid, name=name, owner_id=owner, currency="EUR", client_id=client, region=region))
    await session.flush()
    session.add(BOQ(id=pid, project_id=pid, name=f"{name} bill"))
    await session.flush()
    return pid


async def _position(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    quantity: str,
    unit: str,
    labour_hours: str,
    unit_rate: str = "10",
    labour_per_unit: str | None = None,
) -> uuid.UUID:
    from app.modules.boq.models import Position
    from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine
    from app.modules.progress.models import ProgressEntry

    pos_id = uuid.uuid4()
    metadata = (
        {"resources": [{"type": "labor", "quantity": labour_per_unit, "unit_rate": "40"}]} if labour_per_unit else {}
    )
    session.add(
        Position(
            id=pos_id,
            boq_id=project_id,
            ordinal="01",
            description="Work",
            unit=unit,
            quantity=quantity,
            unit_rate=unit_rate,
            total=str(D(quantity) * D(unit_rate)),
            metadata_=metadata,
        )
    )
    await session.flush()
    session.add(
        ProgressEntry(project_id=project_id, boq_position_id=pos_id, period_label="2026-09", percent_complete=D("100"))
    )
    sheet = FieldTimesheet(
        project_id=project_id, reference=f"TS-{uuid.uuid4().hex[:8]}", date=date(2026, 9, 1), status="approved"
    )
    session.add(sheet)
    await session.flush()
    session.add(
        FieldTimesheetLine(
            timesheet_id=sheet.id,
            resource_id=uuid.uuid4(),
            hours=D(labour_hours),
            cost_code="",
            boq_position_id=pos_id,
        )
    )
    await session.flush()
    return pos_id


@pytest.mark.asyncio
async def test_benchmark_endpoint_converts_on_request_and_filters_by_client(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.router import performance_benchmark

    me = await _user(session)
    a = await _project(session, me, "A", client="Acme")
    b = await _project(session, me, "B", client="Acme")
    c = await _project(session, me, "C", client="Other")
    await _position(session, a, quantity="50", unit="m2", labour_hours="100")
    await _position(session, b, quantity="2152.78", unit="ft2", labour_hours="300")
    await _position(session, c, quantity="10", unit="m2", labour_hours="10")

    plain = await performance_benchmark(
        PerformanceBenchmarkRequest(kpi="labour_hours_per_installed_unit", clients=["Acme"]),
        user_id=str(me),
        session=session,
    )
    assert plain.projects_selected == 2
    assert len(plain.groups) == 2

    merged = await performance_benchmark(
        PerformanceBenchmarkRequest(
            kpi="labour_hours_per_installed_unit", clients=["Acme"], convert_units=True, min_projects=3
        ),
        user_id=str(me),
        session=session,
    )
    assert len(merged.groups) == 1
    group = merged.groups[0]
    assert group.benchmark.weighted == D("1.6")
    assert group.headline == D("1.6")
    # A tie on evidence goes to the base unit of the dimension.
    assert [(x.from_unit, x.to_unit) for x in group.conversions] == [("ft2", "m2")]
    assert group.sufficient is False
    assert group.shortfall == [performance.SHORTFALL_PROJECTS]
    assert {r.project_id for r in group.rows} == {a, b}


@pytest.mark.asyncio
async def test_benchmark_set_lifecycle_and_visibility(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.router import (
        create_benchmark_set,
        delete_benchmark_set,
        evaluate_benchmark_set,
        get_benchmark_set,
        list_benchmark_sets,
        update_benchmark_set,
    )
    from app.modules.bi_dashboards.service import BIDashboardsService

    service = BIDashboardsService(session)
    me = await _user(session)
    colleague = await _user(session)
    mine = await _project(session, me, "Mine", region="EU")
    theirs = await _project(session, colleague, "Theirs", region="EU")
    await _position(session, mine, quantity="50", unit="m2", labour_hours="100")
    await _position(session, theirs, quantity="200", unit="m2", labour_hours="300")

    shared = await create_benchmark_set(
        BenchmarkSetCreate(
            name="Drywall EU",
            scope="shared",
            kpis=["labour_hours_per_installed_unit", "estimate_rate_per_unit"],
            cohort={"regions": ["EU"]},
            min_projects=1,
        ),
        user_id=str(colleague),
        service=service,
    )
    private = await create_benchmark_set(
        BenchmarkSetCreate(name="Private", kpis=["approved_labour_hours"]),
        user_id=str(colleague),
        service=service,
    )
    assert shared.is_owner is True

    listed = await list_benchmark_sets(user_id=str(me), service=service, offset=0, limit=100)
    assert [s.name for s in listed.items] == ["Drywall EU"]
    assert listed.items[0].is_owner is False
    with pytest.raises(HTTPException) as hidden:
        await get_benchmark_set(private.id, user_id=str(me), service=service)
    assert hidden.value.status_code == 404

    # The colleague's shared set, read by me, shows my project and never theirs.
    mine_view = await evaluate_benchmark_set(
        shared.id, BenchmarkSetEvaluateRequest(), user_id=str(me), session=session, service=service
    )
    assert {p.project_id for p in mine_view.projects} == {mine}
    assert mine_view.groups[0].benchmark.weighted == D("2")
    assert mine_view.convert_units is True
    their_view = await evaluate_benchmark_set(
        shared.id, BenchmarkSetEvaluateRequest(), user_id=str(colleague), session=session, service=service
    )
    assert {p.project_id for p in their_view.projects} == {theirs}
    with pytest.raises(HTTPException) as not_in_set:
        await evaluate_benchmark_set(
            shared.id,
            BenchmarkSetEvaluateRequest(kpi="approved_labour_hours"),
            user_id=str(me),
            session=session,
            service=service,
        )
    assert not_in_set.value.status_code == 404

    # Only the owner edits or deletes, shared or not.
    with pytest.raises(HTTPException) as foreign_edit:
        await update_benchmark_set(shared.id, BenchmarkSetUpdate(name="Mine now"), user_id=str(me), service=service)
    assert foreign_edit.value.status_code == 404
    with pytest.raises(HTTPException) as foreign_delete:
        await delete_benchmark_set(shared.id, user_id=str(me), service=service)
    assert foreign_delete.value.status_code == 404

    renamed = await update_benchmark_set(
        shared.id, BenchmarkSetUpdate(name="Drywall", statistic="median"), user_id=str(colleague), service=service
    )
    assert (renamed.name, renamed.statistic, renamed.kpis[0]) == (
        "Drywall",
        "median",
        "labour_hours_per_installed_unit",
    )
    await delete_benchmark_set(private.id, user_id=str(colleague), service=service)
    assert (await list_benchmark_sets(user_id=str(colleague), service=service, offset=0, limit=100)).total == 1


@pytest.mark.asyncio
async def test_benchmark_set_definition_is_checked_on_save(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.router import create_benchmark_set
    from app.modules.bi_dashboards.service import BIDashboardsService

    service = BIDashboardsService(session)
    me = await _user(session)
    with pytest.raises(HTTPException) as unknown:
        await create_benchmark_set(BenchmarkSetCreate(name="x", kpis=["nope"]), user_id=str(me), service=service)
    assert unknown.value.status_code == 422
    assert unknown.value.detail["value"] == "nope"

    # A classification filter fits a position KPI and not a timesheet KPI,
    # and the rejection names the KPI it did not fit.
    by_class = {"row_filters": [{"field": "classification.din276", "op": "eq", "value": "330"}]}
    ok = await create_benchmark_set(
        BenchmarkSetCreate(name="KG 330", kpis=["labour_hours_per_installed_unit"], cohort=by_class),
        user_id=str(me),
        service=service,
    )
    assert ok.cohort.row_filters[0]["value"] == "330"
    with pytest.raises(HTTPException) as misfit:
        await create_benchmark_set(
            BenchmarkSetCreate(name="KG 330", kpis=["approved_labour_hours"], cohort=by_class),
            user_id=str(me),
            service=service,
        )
    assert misfit.value.status_code == 422
    assert misfit.value.detail["path"].startswith("kpis.approved_labour_hours.")


@pytest.mark.asyncio
async def test_check_reads_a_position_and_changes_nothing(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.router import check_against_benchmark_set, create_benchmark_set
    from app.modules.bi_dashboards.service import BIDashboardsService
    from app.modules.boq.models import Position

    service = BIDashboardsService(session)
    me = await _user(session)
    stranger = await _user(session)
    projects = [await _project(session, me, f"P{i}") for i in range(4)]
    for pid, (qty, hours) in zip(projects, [("10", "10"), ("10", "15"), ("10", "20"), ("10", "25")], strict=True):
        await _position(session, pid, quantity=qty, unit="m2", labour_hours=hours)
    new_project = await _project(session, me, "New")
    estimate = await _position(
        session, new_project, quantity="100", unit="ft2", labour_hours="0", unit_rate="7", labour_per_unit="0.2"
    )
    foreign = await _position(
        session, await _project(session, stranger, "Foreign"), quantity="1", unit="m2", labour_hours="1"
    )

    bset = await create_benchmark_set(
        BenchmarkSetCreate(
            name="Hours",
            kpis=["labour_hours_per_installed_unit", "approved_labour_hours"],
            cohort={"project_ids": projects},
            min_projects=3,
        ),
        user_id=str(me),
        service=service,
    )

    typed = await check_against_benchmark_set(
        bset.id,
        PerformanceCheckRequest(value=D("1.6"), unit="m2"),
        user_id=str(me),
        session=session,
        service=service,
    )
    assert typed.status == "ok"
    assert typed.band == "within"
    assert typed.confidence == "medium"
    assert typed.percentile_rank == D("50")
    assert typed.group is not None
    assert typed.group.evidence.projects_with_value == 4

    from_position = await check_against_benchmark_set(
        bset.id,
        PerformanceCheckRequest(boq_position_id=estimate),
        user_id=str(me),
        session=session,
        service=service,
    )
    # 0.2 h per ft2 is 2.15278 h per m2: above P75 (2.125), three of the four projects below it.
    assert from_position.status == "ok"
    assert from_position.input_value == D("0.2")
    assert from_position.input_unit == "ft2"
    assert from_position.value == D("0.2") * D("10.7639")
    assert from_position.band == "above"
    assert from_position.percentile_rank == D("75")

    position = await session.get(Position, estimate)
    assert position is not None
    assert (position.unit_rate, position.metadata_["resources"][0]["quantity"]) == ("7", "0.2")

    with pytest.raises(HTTPException) as hidden:
        await check_against_benchmark_set(
            bset.id,
            PerformanceCheckRequest(boq_position_id=foreign),
            user_id=str(me),
            session=session,
            service=service,
        )
    assert hidden.value.status_code == 404

    not_per_unit = await check_against_benchmark_set(
        bset.id,
        PerformanceCheckRequest(kpi="approved_labour_hours", boq_position_id=estimate),
        user_id=str(me),
        session=session,
        service=service,
    )
    assert not_per_unit.status == performance.CHECK_NOT_PER_UNIT

    elsewhere = await check_against_benchmark_set(
        bset.id,
        PerformanceCheckRequest(value=D("1"), unit="pcs"),
        user_id=str(me),
        session=session,
        service=service,
    )
    assert elsewhere.status == performance.CHECK_NO_GROUP

    # The same check against the same cohort described ad hoc, unsaved.
    from app.modules.bi_dashboards.router import check_against_cohort
    from app.modules.bi_dashboards.schemas import PerformanceAdHocCheckRequest

    ad_hoc = await check_against_cohort(
        PerformanceAdHocCheckRequest(
            kpi="labour_hours_per_installed_unit",
            project_ids=projects,
            convert_units=True,
            min_projects=3,
            value=D("1.6"),
            unit="m2",
        ),
        user_id=str(me),
        session=session,
    )
    assert (ad_hoc.band, ad_hoc.percentile_rank, ad_hoc.confidence, ad_hoc.headline) == (
        typed.band,
        typed.percentile_rank,
        typed.confidence,
        typed.headline,
    )
