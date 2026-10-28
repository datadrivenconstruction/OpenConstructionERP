# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cross-project performance: ratio KPIs, actuals entities and the benchmark.

The contract under test is the one an estimator relies on when reading
historical productivity off finished work:

* a ratio is a ratio of sums - 100 h over 50 m2 and 300 h over 200 m2 is
  400 / 250 = 1.60 h/m2, never the 1.75 an average of the two ratios gives;
* a zero or absent denominator is unavailable with a reason, never 0;
* units are never mixed, each one is its own group;
* only approved, non-reversed timesheets count, exactly as post-calculation
  counts them;
* installed quantity is one definition, read identically by post-calculation
  and by the KPI catalog;
* a benchmark never reads, names or counts a project the caller cannot open.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.stats import median, percentile, quartiles, weighted_mean
from app.modules.bi_dashboards import kpi_spec, performance
from app.modules.bi_dashboards.kpi_spec import KPISpecError, ProjectReading
from app.modules.bi_dashboards.schemas import PerformanceBenchmarkRequest
from tests._pg import transactional_session

D = Decimal

HOURS_PER_INSTALLED = {
    "entity": "position_progress",
    "aggregation": "ratio",
    "field": "labour_hours",
    "denominator_field": "installed_quantity",
}


# ── Shared stats helper ────────────────────────────────────────────────


def test_percentile_interpolates_linearly_in_decimal() -> None:
    values = [D("1"), D("2"), D("4"), D("8")]
    assert percentile(values, 50) == D("3")
    assert percentile(values, 25) == D("1.75")
    assert isinstance(percentile(values, 75), Decimal)


def test_percentile_of_floats_matches_the_helper_it_replaced() -> None:
    from app.modules.boq.cost_risk_engine import _percentile

    data = sorted([3.2, 1.1, 9.7, 4.4, 5.0])
    for pct in (5, 25, 50, 75, 95):
        idx = pct / 100.0 * (len(data) - 1)
        lower = int(idx)
        upper = min(lower + 1, len(data) - 1)
        expected = data[lower] + (idx - lower) * (data[upper] - data[lower])
        assert percentile(data, pct) == expected
        assert _percentile(data, pct) == expected
    # The engine's own contract for an empty sample is 0.0, the core's is None.
    assert _percentile([], 50) == 0.0
    assert percentile([], 50) is None


def test_median_quartiles_and_weighted_mean() -> None:
    assert median([D("2"), D("1.5")]) == D("1.75")
    assert quartiles([]) == (None, None, None)
    assert weighted_mean([D("2"), D("1.5")], [D("50"), D("200")]) == D("1.6")
    assert weighted_mean([D("2")], [D("0")]) is None
    assert weighted_mean([], []) is None
    with pytest.raises(ValueError, match="same length"):
        weighted_mean([D("1")], [])


# ── Ratio semantics (pure) ─────────────────────────────────────────────


def test_ratio_value_is_unavailable_not_zero() -> None:
    assert kpi_spec.ratio_value(D("10"), D("0")) == (None, kpi_spec.UNAVAILABLE_ZERO_DENOMINATOR)
    assert kpi_spec.ratio_value(D("10"), None) == (None, kpi_spec.UNAVAILABLE_NO_DATA)
    assert kpi_spec.ratio_value(D("400"), D("250")) == (D("1.6"), None)


def _reading(pid: uuid.UUID, num: str, den: str, key: str = "m2") -> ProjectReading:
    value, reason = kpi_spec.ratio_value(D(num), D(den))
    return ProjectReading(
        project_id=pid,
        group_key=key,
        dimensions={"unit": key},
        value=value,
        records=1,
        numerator=D(num),
        denominator=D(den),
        unavailable_reason=reason,
    )


def test_benchmark_of_a_ratio_is_a_ratio_of_sums_not_a_mean_of_ratios() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    summary = performance.summarise([_reading(a, "100", "50"), _reading(b, "300", "200")], "ratio")
    assert summary.weighted == D("1.6")
    # The median is over per-project values and answers a different question;
    # it is served beside the weighted figure, not instead of it.
    assert summary.median == D("1.75")
    assert (summary.p25, summary.p75) == (D("1.625"), D("1.875"))
    assert summary.projects_with_value == 2


def test_benchmark_leaves_an_unavailable_project_out_of_every_figure() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    summary = performance.summarise(
        [_reading(a, "100", "50"), _reading(b, "300", "200"), _reading(c, "80", "0")],
        "ratio",
    )
    assert summary.weighted == D("1.6")
    assert summary.minimum == D("1.5")
    assert summary.projects_with_data == 3
    assert summary.projects_with_value == 2


def test_a_sum_has_no_weighted_benchmark() -> None:
    reading = ProjectReading(project_id=uuid.uuid4(), group_key="", dimensions={}, value=D("12"), records=3)
    summary = performance.summarise([reading], "sum")
    assert summary.weighted is None
    assert summary.weighted_unavailable_reason == performance.WEIGHT_NOT_APPLICABLE
    assert summary.median == D("12")


def test_groups_keep_units_apart() -> None:
    a = uuid.uuid4()
    groups = performance.group_readings([_reading(a, "10", "5", "m2"), _reading(a, "10", "2", "m3")], "ratio")
    assert {g.key for g in groups} == {"m2", "m3"}
    assert {g.key: g.summary.weighted for g in groups if g.summary} == {"m2": D("2"), "m3": D("5")}


def test_cohort_is_the_request_narrowed_to_what_may_be_seen() -> None:
    mine, theirs, missing = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert performance.resolve_cohort([mine, theirs, missing], {mine}) == {mine}
    assert performance.resolve_cohort([], {mine}) == {mine}
    assert performance.resolve_cohort([theirs], set()) == set()


# ── Spec validation ────────────────────────────────────────────────────


def test_ratio_spec_validates_and_reports_its_dimensions() -> None:
    spec = kpi_spec.validate_spec(HOURS_PER_INSTALLED)
    assert spec["denominator_field"] == "installed_quantity"
    assert kpi_spec.spec_dimensions(spec) == ["unit"]
    rate = kpi_spec.validate_spec(
        {"entity": "boq_position", "aggregation": "ratio", "field": "amount", "denominator_field": "quantity"}
    )
    assert kpi_spec.spec_dimensions(rate) == ["currency", "unit"]


@pytest.mark.parametrize(
    ("spec", "path"),
    [
        ({**HOURS_PER_INSTALLED, "denominator_field": None}, "spec.denominator_field"),
        ({**HOURS_PER_INSTALLED, "denominator_field": "labour_hours"}, "spec.denominator_field"),
        ({**HOURS_PER_INSTALLED, "denominator_field": "unit"}, "spec.denominator_field"),
        ({**HOURS_PER_INSTALLED, "denominator_field": "nope"}, "spec.denominator_field"),
        ({**HOURS_PER_INSTALLED, "group_by": "unit"}, "spec.group_by"),
        ({**HOURS_PER_INSTALLED, "weight_field": "planned_quantity"}, "spec.weight_field"),
        (
            {"entity": "position_progress", "aggregation": "sum", "field": "labour_hours", "denominator_field": "x"},
            "spec.denominator_field",
        ),
    ],
)
def test_ratio_spec_rejections_name_their_path(spec: dict, path: str) -> None:
    with pytest.raises(KPISpecError) as info:
        kpi_spec.validate_spec(spec)
    assert info.value.path == path


def test_new_entities_are_bound_as_declared() -> None:
    assert kpi_spec.check_catalog_binding_parity() == {}
    names = {e["name"] for e in kpi_spec.catalog_as_dict()}
    assert {"field_time_line", "position_progress"} <= names


def test_every_preset_is_a_valid_spec() -> None:
    assert set(performance.VALIDATED_PRESETS) == set(performance.PRESETS)
    for spec in performance.VALIDATED_PRESETS.values():
        assert spec["aggregation"] != "top_by"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"kpi": "labour_hours_per_installed_unit", "spec": HOURS_PER_INSTALLED},
        {"kpi": "x", "period_start": "2026-02-01", "period_end": "2026-01-01"},
        {"kpi": "x", "project_ids": [str(uuid.uuid4())] * 501},
        {"kpi": "x", "unexpected": 1},
    ],
)
def test_benchmark_request_validation(payload: dict) -> None:
    with pytest.raises(ValidationError):
        PerformanceBenchmarkRequest.model_validate(payload)


# ── Database: entities, parity, access ─────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    # FKs off: timesheet lines point at resources and equipment rows that are
    # not what is under test.
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _user(session: AsyncSession, role: str = "editor") -> uuid.UUID:
    from app.modules.users.models import User

    uid = uuid.uuid4()
    session.add(User(id=uid, email=f"perf-{uid.hex[:8]}@test.io", hashed_password="x", full_name="P", role=role))
    await session.flush()
    return uid


async def _project(session: AsyncSession, owner: uuid.UUID, name: str, currency: str = "EUR") -> uuid.UUID:
    from app.modules.boq.models import BOQ
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    session.add(Project(id=pid, name=name, owner_id=owner, currency=currency))
    await session.flush()
    session.add(BOQ(id=pid, project_id=pid, name=f"{name} bill"))
    await session.flush()
    return pid


async def _position(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    quantity: str,
    unit: str = "m2",
    percent: str | None = "100",
    labour_hours: str | None = None,
    ordinal: str = "01",
) -> uuid.UUID:
    """A position on the project's bill (the bill shares the project's id)."""
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
            unit_rate="10",
            total=str(D(quantity) * 10),
        )
    )
    await session.flush()
    if percent is not None:
        session.add(
            ProgressEntry(
                project_id=project_id,
                boq_position_id=pos_id,
                period_label="2026-09",
                percent_complete=D(percent),
            )
        )
        await session.flush()
    if labour_hours is not None:
        await _book(session, project_id, pos_id, labour_hours)
    return pos_id


async def _book(
    session: AsyncSession,
    project_id: uuid.UUID,
    position_id: uuid.UUID,
    hours: str,
    *,
    status: str = "approved",
    reverses_id: uuid.UUID | None = None,
) -> uuid.UUID:
    from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine

    sheet = FieldTimesheet(
        project_id=project_id,
        reference=f"TS-{uuid.uuid4().hex[:8]}",
        date=date(2026, 9, 1),
        status=status,
        reverses_id=reverses_id,
    )
    session.add(sheet)
    await session.flush()
    session.add(
        FieldTimesheetLine(
            timesheet_id=sheet.id,
            resource_id=uuid.uuid4(),
            hours=D(hours),
            cost_code="",
            boq_position_id=position_id,
        )
    )
    await session.flush()
    return sheet.id


@pytest.mark.asyncio
async def test_hours_per_installed_unit_across_projects_is_400_over_250(session: AsyncSession) -> None:
    owner = await _user(session)
    a = await _project(session, owner, "A")
    b = await _project(session, owner, "B")
    await _position(session, a, quantity="50", labour_hours="100")
    await _position(session, b, quantity="200", labour_hours="300")

    spec = kpi_spec.validate_spec(HOURS_PER_INSTALLED)
    result = await kpi_spec.evaluate_spec(spec, session, allowed_project_ids={a, b})
    assert result.unavailable_reason is None
    assert result.value == D("1.6")
    assert D(result.breakdown["m2"]["numerator"]) == D("400")

    groups = await performance.benchmark(session, spec=spec, cohort={a, b})
    assert len(groups) == 1
    summary = groups[0].summary
    assert summary is not None
    assert summary.weighted == D("1.6")
    assert summary.median == D("1.75")


@pytest.mark.asyncio
async def test_zero_installed_is_unavailable_and_mixed_units_have_no_headline(session: AsyncSession) -> None:
    owner = await _user(session)
    p = await _project(session, owner, "P")
    await _position(session, p, quantity="50", percent="0", labour_hours="40")

    spec = kpi_spec.validate_spec(HOURS_PER_INSTALLED)
    result = await kpi_spec.evaluate_spec(spec, session, project_id=p)
    assert result.value is None
    assert result.unavailable_reason == kpi_spec.UNAVAILABLE_ZERO_DENOMINATOR

    await _position(session, p, quantity="10", unit="m3", labour_hours="20", ordinal="02")
    mixed = await kpi_spec.evaluate_spec(spec, session, project_id=p)
    assert mixed.value is None
    assert mixed.unavailable_reason == kpi_spec.UNAVAILABLE_MIXED_DIMENSIONS
    assert mixed.breakdown["m3"]["value"] == "2"
    assert mixed.breakdown["m2"]["unavailable_reason"] == kpi_spec.UNAVAILABLE_ZERO_DENOMINATOR

    # A position nobody reported on has no installed quantity and is left out.
    empty = await _project(session, owner, "Empty")
    await _position(session, empty, quantity="50", percent=None, labour_hours="40")
    none = await kpi_spec.evaluate_spec(spec, session, project_id=empty)
    assert (none.value, none.unavailable_reason) == (None, kpi_spec.UNAVAILABLE_NO_DATA)


@pytest.mark.asyncio
async def test_reversed_and_unapproved_hours_do_not_count(session: AsyncSession) -> None:
    owner = await _user(session)
    p = await _project(session, owner, "Hours")
    pos = await _position(session, p, quantity="10", labour_hours="8")
    # A corrected day: the original flips to reversed, its mirror is approved
    # with reverses_id set. Both must drop out.
    original = await _book(session, p, pos, "5", status="reversed")
    await _book(session, p, pos, "5", reverses_id=original)
    await _book(session, p, pos, "7", status="draft")
    await _book(session, p, pos, "9", status="submitted")

    lines = kpi_spec.validate_spec({"entity": "field_time_line", "aggregation": "sum", "field": "labour_hours"})
    assert (await kpi_spec.evaluate_spec(lines, session, project_id=p)).value == D("8")

    per_position = kpi_spec.validate_spec(
        {"entity": "position_progress", "aggregation": "sum", "field": "labour_hours"}
    )
    assert D((await kpi_spec.evaluate_spec(per_position, session, project_id=p)).value) == D("8")

    from app.modules.costmodel.position_actuals import hours_by_position

    labour, _plant = (await hours_by_position(session, p, [pos]))[pos]
    assert labour == D("8")


@pytest.mark.asyncio
async def test_installed_quantity_parity_with_postcalc(session: AsyncSession) -> None:
    from app.modules.postcalc.service import PostCalcService

    owner = await _user(session)
    p = await _project(session, owner, "Parity")
    await _position(session, p, quantity="50", percent="40", ordinal="01")
    await _position(session, p, quantity="33.3", percent="33.3", ordinal="02")
    await _position(session, p, quantity="12", percent=None, ordinal="03")
    second = await _position(session, p, quantity="80", percent="10", ordinal="04")
    # A later, lower reading is a correction and wins.
    from app.modules.progress.models import ProgressEntry

    session.add(ProgressEntry(project_id=p, boq_position_id=second, period_label="2026-10", percent_complete=D("5")))
    await session.flush()

    report = await PostCalcService(session).generate(p)
    postcalc_by_ref = {line.ref: line.actual_quantity for line in report.lines}

    spec = kpi_spec.validate_spec({"entity": "position_progress", "aggregation": "sum", "field": "installed_quantity"})
    total = await kpi_spec.evaluate_spec(spec, session, project_id=p)
    assert D(total.value) == sum(postcalc_by_ref.values(), D("0"))

    by_line = kpi_spec.validate_spec(
        {"entity": "position_progress", "aggregation": "sum", "field": "installed_quantity", "group_by": "ordinal"}
    )
    kpi_by_ref = {k: D(v) for k, v in (await kpi_spec.evaluate_spec(by_line, session, project_id=p)).breakdown.items()}
    assert kpi_by_ref == {ref: qty for ref, qty in postcalc_by_ref.items() if ref != "03"}
    assert postcalc_by_ref["01"] == D("20")
    assert postcalc_by_ref["02"] == D("11.0889")
    assert postcalc_by_ref["04"] == D("4")
    assert postcalc_by_ref["03"] == D("0")


@pytest.mark.asyncio
async def test_benchmark_endpoint_never_reads_an_inaccessible_project(session: AsyncSession) -> None:
    from app.modules.bi_dashboards.router import performance_benchmark

    me = await _user(session)
    stranger = await _user(session)
    mine = await _project(session, me, "Mine")
    theirs = await _project(session, stranger, "Theirs")
    await _position(session, mine, quantity="50", labour_hours="100")
    await _position(session, theirs, quantity="200", labour_hours="300")

    for requested in ([mine, theirs], [theirs], []):
        payload = PerformanceBenchmarkRequest(kpi="labour_hours_per_installed_unit", project_ids=requested)
        response = await performance_benchmark(payload, user_id=str(me), session=session)
        assert theirs not in {p.project_id for p in response.projects}
        rows = [row for group in response.groups for row in group.rows]
        assert theirs not in {row.project_id for row in rows}
        if requested == [theirs]:
            assert response.projects_selected == 0
            assert response.groups == []
        else:
            assert response.projects_selected == 1
            assert [row.value for row in rows] == [D("2")]
            assert response.groups[0].coverage == D("1")
            assert response.groups[0].benchmark.weighted == D("2")


@pytest.mark.asyncio
async def test_benchmark_rejects_an_unknown_kpi_and_a_bad_spec(session: AsyncSession) -> None:
    from fastapi import HTTPException

    from app.modules.bi_dashboards.router import performance_benchmark

    me = await _user(session)
    with pytest.raises(HTTPException) as unknown:
        await performance_benchmark(PerformanceBenchmarkRequest(kpi="nope"), user_id=str(me), session=session)
    assert unknown.value.status_code == 404
    bad = PerformanceBenchmarkRequest(spec={**HOURS_PER_INSTALLED, "denominator_field": "unit"})
    with pytest.raises(HTTPException) as invalid:
        await performance_benchmark(bad, user_id=str(me), session=session)
    assert invalid.value.status_code == 422
    assert invalid.value.detail["path"] == "spec.denominator_field"
