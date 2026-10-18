# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo data feeds the position-level productivity KPIs.

Hours per installed unit reads approved hours booked to a BoQ position over that
position's installed quantity. A fresh demo had neither half: the field-time seed
coded hours to a position's cost code but never named the position, and demo
progress was project-level only. These tests pin both halves:

* the field-time line builder names the position each cost code came from;
* the progress seed writes one marked reading per position with approved hours,
  and only those, once;
* the result makes ``labour_hours_per_installed_unit`` produce a value;
* the cleanup recogniser lists exactly the marked readings, never a person's.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bi_dashboards import performance
from app.modules.field_time import seed as field_time_seed
from app.modules.progress import seed as progress_seed
from app.modules.progress.models import ProgressEntry
from tests._pg import transactional_session

D = Decimal

HOURS_PER_UNIT = performance.VALIDATED_PRESETS["labour_hours_per_installed_unit"]


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _user(session: AsyncSession) -> uuid.UUID:
    from app.modules.users.models import User

    uid = uuid.uuid4()
    session.add(User(id=uid, email=f"pp-{uid.hex[:8]}@test.io", hashed_password="x", full_name="P", role="editor"))
    await session.flush()
    return uid


async def _project(session: AsyncSession, owner: uuid.UUID, name: str) -> uuid.UUID:
    from app.modules.boq.models import BOQ
    from app.modules.projects.models import Project

    pid = uuid.uuid4()
    session.add(Project(id=pid, name=name, owner_id=owner, currency="EUR", status="active"))
    await session.flush()
    session.add(BOQ(id=pid, project_id=pid, name=f"{name} bill"))
    await session.flush()
    return pid


async def _position(
    session: AsyncSession,
    project_id: uuid.UUID,
    ordinal: str,
    *,
    quantity: str = "50",
    unit: str = "m2",
) -> uuid.UUID:
    from app.modules.boq.models import Position

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
            total=str(D(quantity) * D("10")),
            classification={"din276": "330"},
            metadata_={},
        )
    )
    await session.flush()
    return pos_id


async def _hours(
    session: AsyncSession,
    project_id: uuid.UUID,
    position_id: uuid.UUID,
    hours: str,
    *,
    status: str = "approved",
) -> None:
    from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine

    sheet = FieldTimesheet(
        project_id=project_id, reference=f"TS-{uuid.uuid4().hex[:8]}", date=date(2026, 9, 1), status=status
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


async def _readings(session: AsyncSession, project_id: uuid.UUID) -> list[ProgressEntry]:
    rows = await session.execute(
        select(ProgressEntry).where(ProgressEntry.project_id == project_id, ProgressEntry.boq_position_id.is_not(None))
    )
    return list(rows.scalars().all())


# ── Field time: every line names its position ───────────────────────────


def test_line_builder_links_every_line_to_the_position_of_its_cost_code() -> None:
    codes = [(f"0{i}", f"Work {i}", uuid.uuid4()) for i in range(1, 5)]
    position_of = {code: pid for code, _desc, pid in codes}
    workers = [(uuid.uuid4(), f"Worker {i}") for i in range(6)]
    plant = [(uuid.uuid4(), "Excavator")]
    variation = uuid.uuid4()

    lines = []
    for day in range(12):
        lines += field_time_seed._build_lines(
            random.Random(day),
            day_index=day,
            workers=workers,
            plant=plant,
            cost_codes=codes,
            variation_id=variation,
        )

    assert lines, "the builder produced no lines to check"
    assert any(line.equipment_id for line in lines), "no plant line was drawn, widen the sample"
    assert any(line.is_daywork for line in lines), "no daywork line was drawn, widen the sample"
    for line in lines:
        assert line.boq_position_id == position_of[line.cost_code]


@pytest.mark.asyncio
async def test_cost_codes_carry_the_position_they_resolve_to(session: AsyncSession) -> None:
    me = await _user(session)
    pid = await _project(session, me, "Codes")
    first = await _position(session, pid, "01")
    second = await _position(session, pid, "02")

    codes = await field_time_seed._project_cost_codes(session, pid)
    assert [(code, position_id) for code, _desc, position_id in codes] == [("01", first), ("02", second)]


# ── Progress: one marked reading per worked position ────────────────────


@pytest.mark.asyncio
async def test_seeded_readings_give_hours_per_installed_unit_a_value(session: AsyncSession) -> None:
    me = await _user(session)
    pid = await _project(session, me, "Demo")
    worked = await _position(session, pid, "01", quantity="50")
    also_worked = await _position(session, pid, "02", quantity="20")
    drafted_only = await _position(session, pid, "03")
    section = await _position(session, pid, "04", quantity="0", unit="")
    idle = await _position(session, pid, "05")
    await _hours(session, pid, worked, "80")
    await _hours(session, pid, also_worked, "16")
    await _hours(session, pid, drafted_only, "8", status="draft")
    await _hours(session, pid, section, "4")

    # Before the seed the KPI has hours but nothing installed to divide them by.
    before = await performance.benchmark(session, spec=HOURS_PER_UNIT, cohort={pid})
    assert not [g for g in before if g.summary is not None and g.summary.weighted is not None]

    totals = await progress_seed.seed_position_progress_demo(session, [pid])
    assert totals == {"projects": 1, "entries": 2}

    readings = await _readings(session, pid)
    assert {r.boq_position_id for r in readings} == {worked, also_worked}
    assert drafted_only not in {r.boq_position_id for r in readings}
    assert idle not in {r.boq_position_id for r in readings}
    for reading in readings:
        assert D("35") <= D(str(reading.percent_complete)) <= D("100")
        assert reading.metadata_ == {"demo_seed": "position_progress"}
        assert len(reading.period_label) == 7 and reading.period_label[4] == "-"

    groups = await performance.benchmark(session, spec=HOURS_PER_UNIT, cohort={pid})
    valued = [g for g in groups if g.summary is not None and g.summary.weighted is not None]
    assert valued, f"no group with a value after seeding: {groups}"

    # Installed = 50 * p1 / 100 + 20 * p2 / 100; hours 80 + 16.
    by_position = {r.boq_position_id: D(str(r.percent_complete)) for r in readings}
    installed = D("50") * by_position[worked] / 100 + D("20") * by_position[also_worked] / 100
    assert valued[0].summary.weighted.quantize(D("0.0001")) == (D("96") / installed).quantize(D("0.0001"))


@pytest.mark.asyncio
async def test_a_second_pass_writes_nothing(session: AsyncSession) -> None:
    me = await _user(session)
    pid = await _project(session, me, "Twice")
    pos = await _position(session, pid, "01")
    await _hours(session, pid, pos, "40")

    first = await progress_seed.seed_position_progress_demo(session, [pid])
    second = await progress_seed.seed_position_progress_demo(session, [pid])
    assert first["entries"] == 1
    assert second == {"projects": 0, "entries": 0}
    assert len(await _readings(session, pid)) == 1


def test_the_same_project_draws_the_same_percent_every_time() -> None:
    pid = uuid.uuid4()
    a = [progress_seed._draw_percent(progress_seed._rng_for(pid)) for _ in range(3)]
    b = [progress_seed._draw_percent(progress_seed._rng_for(pid)) for _ in range(3)]
    assert a == b


@pytest.mark.asyncio
async def test_a_project_with_a_reading_of_its_own_is_left_alone(session: AsyncSession) -> None:
    me = await _user(session)
    pid = await _project(session, me, "Measured")
    measured = await _position(session, pid, "01")
    worked = await _position(session, pid, "02")
    await _hours(session, pid, worked, "40")
    session.add(
        ProgressEntry(project_id=pid, boq_position_id=measured, period_label="2026-09", percent_complete=D("10"))
    )
    await session.flush()

    totals = await progress_seed.seed_position_progress_demo(session, [pid])
    assert totals == {"projects": 0, "entries": 0}
    assert [r.boq_position_id for r in await _readings(session, pid)] == [measured]


# ── Cleanup: the recogniser lists the marked readings only ──────────────


@pytest.mark.asyncio
async def test_cleanup_recognises_only_the_marked_readings(session: AsyncSession) -> None:
    from app.core.demo_cleanup import _fingerprinters

    me = await _user(session)
    pid = await _project(session, me, "Leaked")
    worked = await _position(session, pid, "01")
    mine = await _position(session, pid, "02")
    await _hours(session, pid, worked, "40")
    await progress_seed.seed_position_progress_demo(session, [pid])
    seeded = {r.id for r in await _readings(session, pid)}

    person = ProgressEntry(
        project_id=pid,
        boq_position_id=mine,
        period_label="2026-09",
        percent_complete=D("60"),
        notes="Installed quantity measured on site.",
        metadata_={"source": "manual"},
    )
    project_level = ProgressEntry(
        project_id=pid, period_label="2026-09", percent_complete=D("40"), metadata_={"demo_seed": "position_progress"}
    )
    session.add_all([person, project_level])
    await session.flush()

    groups = await progress_seed.seeded_row_ids(session, [pid])
    assert [(model, label) for model, _ids, label in groups] == [(ProgressEntry, "progress_position_readings")]
    assert set(groups[0][1]) == seeded and len(groups[0][1]) == 1
    assert person.id not in groups[0][1]
    assert project_level.id not in groups[0][1]
    assert progress_seed.seeded_row_ids in _fingerprinters()
