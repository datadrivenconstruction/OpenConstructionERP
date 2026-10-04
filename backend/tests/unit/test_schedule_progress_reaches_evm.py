# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Real schedule progress reaches EVM, once per project per day.

The cross-module handler that writes ``oe_finance_evm_snapshot`` from progress
listened for ``schedule.progress_updated``, a name nothing publishes, and
expected a project-level payload nobody sends. The schedule module publishes
``schedule.activity.progress_updated`` with one activity's id and percentage.
So the S-curve and the forecast surfaces only ever saw snapshots somebody typed
in by hand.

The handler now listens for the published name, resolves the project and
recomputes progress over every work-carrying activity of its master schedules.
The money assertions are written so that a wrong answer cannot pass: a second
save on the same day must replace the day's row, not add to it, and earned
value is checked against the weighted figure, not against "non-zero".

The database half runs on a throwaway PostgreSQL database because the handler
opens its own sessions through ``app.database.async_session_factory``, which
is the one thing the tests replace.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import event_handlers
from app.core.event_handlers import (
    EVM_PROGRESS_SNAPSHOT_SOURCE,
    _handle_schedule_progress,
    schedule_progress_fractions,
)
from app.core.events import Event, EventBus
from app.modules.finance.models import EVMSnapshot, ProjectBudget
from app.modules.projects.models import Project
from app.modules.schedule.models import Activity, Schedule
from app.modules.users.models import User
from tests._pg import isolated_engine

_EVENT = "schedule.activity.progress_updated"
TODAY = date.today()

#: A Monday well in the past. Planned value is counted in working days, so a
#: test that asserts it pins its dates to known weekdays instead of today.
MON = date(2026, 3, 2)
assert MON.weekday() == 0


def _d(offset: int | str) -> str:
    """An ISO date: ``offset`` days from today, or the ISO string as given."""
    if isinstance(offset, str):
        return offset
    return (TODAY + timedelta(days=offset)).isoformat()


def _on(offset: int) -> str:
    """The ISO date ``offset`` calendar days after :data:`MON`."""
    return (MON + timedelta(days=offset)).isoformat()


# ── Pure weighting ──────────────────────────────────────────────────────────


def _act(
    *,
    progress: str = "0",
    start: int | str = -10,
    end: int | str = 9,
    cost: str | None = None,
    activity_type: str = "task",
    parent_id: Any = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        parent_id=parent_id,
        activity_type=activity_type,
        progress_pct=progress,
        start_date=_d(start),
        end_date=_d(end),
        cost_planned=Decimal(cost) if cost is not None else None,
    )


def test_cost_weights_earned_value_when_every_leaf_has_a_cost() -> None:
    """900 of work at 100% and 100 of work at 0% is 90% earned, not 50%."""
    big = _act(progress="100", cost="900")
    small = _act(progress="0", cost="100")

    earned, _planned = schedule_progress_fractions([big, small], as_of=TODAY)

    assert earned == Decimal("0.9")


def test_a_missing_cost_falls_back_to_duration_for_every_leaf() -> None:
    """Money is never added to days: one missing cost switches the whole set."""
    long_done = _act(progress="100", start=-29, end=0, cost="10")  # 30 days
    short_open = _act(progress="0", start=-9, end=0, cost=None)  # 10 days

    earned, planned = schedule_progress_fractions([long_done, short_open], as_of=TODAY)

    assert earned == Decimal("30") / Decimal("40")
    assert planned == Decimal("1")


def test_summaries_and_milestones_carry_no_weight() -> None:
    """Counting a summary as well as its children would weigh the same work twice."""
    leaf = _act(progress="40", cost="100")
    summary = _act(progress="99", cost="100000", activity_type="summary")
    leaf.parent_id = summary.id
    milestone = _act(progress="0", cost="5000", activity_type="milestone", start=0, end=0)
    # A parent typed "task" is still a parent.
    child = _act(progress="0", cost="100")
    parent_task = _act(progress="100", cost="100")
    child.parent_id = parent_task.id

    earned, _ = schedule_progress_fractions([leaf, summary, milestone, child, parent_task], as_of=TODAY)

    assert earned == Decimal("0.2")


def test_planned_completion_is_linear_in_working_days_inside_each_window() -> None:
    """Mon 2 Mar to Mon 16 Mar is ten working days; Mon 9 Mar is five of them."""
    window = _act(start=_on(0), end=_on(14), cost="100")

    def planned(as_of: date) -> Decimal:
        return schedule_progress_fractions([window], as_of=as_of)[1]

    assert planned(MON - timedelta(days=1)) == Decimal("0")
    assert planned(MON) == Decimal("0"), "nothing has elapsed at the planned start"
    assert planned(MON + timedelta(days=7)) == Decimal("0.5")
    assert planned(MON + timedelta(days=14)) == Decimal("1")
    assert planned(MON + timedelta(days=30)) == Decimal("1")


def test_a_weekend_plans_no_work() -> None:
    """On Saturday 7 Mar four of ten working days have elapsed, not five of fourteen days.

    Counting calendar days planned every weekend as work, which inflated planned
    value and understated the SPI.
    """
    window = _act(start=_on(0), end=_on(14), cost="100")
    saturday, sunday = MON + timedelta(days=5), MON + timedelta(days=6)

    assert schedule_progress_fractions([window], as_of=saturday)[1] == Decimal("0.4")
    assert schedule_progress_fractions([window], as_of=sunday)[1] == Decimal("0.4")


def test_each_activity_is_planned_on_its_own_calendar() -> None:
    """A seven-day site works the weekend; a holiday stops a five-day one."""
    from app.modules.schedule.progress_math import WorkCalendar

    seven_day = WorkCalendar(work_weekdays=frozenset(range(7)))
    with_holiday = WorkCalendar(holidays=frozenset({_on(3)}))  # Thursday 5 Mar
    weekend_crew = _act(start=_on(0), end=_on(14), cost="100")
    office = _act(start=_on(0), end=_on(14), cost="100")
    calendars = {weekend_crew.id: seven_day, office.id: with_holiday}
    saturday = MON + timedelta(days=5)

    _, planned = schedule_progress_fractions(
        [weekend_crew, office],
        as_of=saturday,
        calendar_for=lambda activity: calendars[activity.id],
    )

    # Seven-day: 5 of 14 days. Five-day with Thursday off: 3 of 9 working days.
    assert planned == (Decimal(5) / Decimal(14) + Decimal(3) / Decimal(9)) / 2


def test_garbage_and_out_of_range_progress_is_clamped() -> None:
    a = _act(progress="not a number", cost="100")
    b = _act(progress="250", cost="100")

    earned, _ = schedule_progress_fractions([a, b], as_of=TODAY)

    assert earned == Decimal("0.5")


def test_nothing_that_carries_work_returns_none() -> None:
    summary = _act(activity_type="summary")
    milestone = _act(activity_type="milestone")

    assert schedule_progress_fractions([], as_of=TODAY) is None
    assert schedule_progress_fractions([summary, milestone], as_of=TODAY) is None


# ── Wiring ──────────────────────────────────────────────────────────────────


def test_the_handler_listens_for_the_name_the_schedule_module_publishes(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = EventBus()
    monkeypatch.setattr(event_handlers, "event_bus", bus)

    event_handlers.register_event_handlers()

    assert _handle_schedule_progress in bus._handlers.get(_EVENT, [])
    assert "schedule.progress_updated" not in bus._handlers, "the dead name is still subscribed"
    # Registering twice must not double-write a day's snapshot.
    event_handlers.register_event_handlers()
    assert bus._handlers[_EVENT].count(_handle_schedule_progress) == 1


# ── Against PostgreSQL ──────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def _module_db() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def factory(
    _module_db: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> async_sessionmaker[AsyncSession]:
    """The throwaway database, also handed to the handler as its session factory."""
    import app.database as database_module

    monkeypatch.setattr(database_module, "async_session_factory", _module_db)
    return _module_db


async def _project(
    factory: async_sessionmaker[AsyncSession],
    *,
    currency: str = "EUR",
    budgets: list[tuple[str, str, str]] | None = None,
    schedule_type: str = "master",
    activities: list[dict[str, Any]] | None = None,
    data_date: str | None = None,
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """A project with budget lines ``(original, revised, actual)`` and a schedule."""
    async with factory() as s:
        user = User(
            email=f"evm-{uuid.uuid4().hex[:10]}@datadrivenconstruction.io",
            hashed_password="x" * 16,
            full_name="EVM Test",
        )
        s.add(user)
        await s.flush()
        project = Project(
            id=uuid.uuid4(),
            name=f"EVM {uuid.uuid4().hex[:6]}",
            owner_id=user.id,
            currency=currency,
            region="DACH",
            classification_standard="din276",
            metadata_={},
            fx_rates=[],
        )
        s.add(project)
        await s.flush()
        for original, revised, actual in budgets or [("100000", "100000", "30000")]:
            s.add(
                ProjectBudget(
                    project_id=project.id,
                    category="construction",
                    currency_code=currency,
                    original_budget=Decimal(original),
                    revised_budget=Decimal(revised),
                    actual=Decimal(actual),
                )
            )
        schedule = Schedule(project_id=project.id, name="Master", schedule_type=schedule_type, data_date=data_date)
        s.add(schedule)
        await s.flush()
        ids: list[uuid.UUID] = []
        for spec in activities or [
            {"progress": "50", "start": -9, "end": 10, "cost": "60000"},
            {"progress": "0", "start": -9, "end": 10, "cost": "40000"},
        ]:  # today-relative: the tests using these assert nothing about PV
            activity = Activity(
                schedule_id=schedule.id,
                name=f"A{len(ids)}",
                start_date=_d(spec["start"]),
                end_date=_d(spec["end"]),
                progress_pct=spec["progress"],
                activity_type=spec.get("type", "task"),
                cost_planned=Decimal(spec["cost"]) if spec.get("cost") else None,
            )
            s.add(activity)
            await s.flush()
            ids.append(activity.id)
        await s.commit()
        return project.id, ids


async def _snapshots(factory: async_sessionmaker[AsyncSession], project_id: uuid.UUID) -> list[EVMSnapshot]:
    async with factory() as s:
        rows = await s.execute(select(EVMSnapshot).where(EVMSnapshot.project_id == project_id))
        return list(rows.scalars().all())


async def _deliver(activity_id: uuid.UUID, pct: float) -> None:
    """Hand the handler the event the schedule publishes, and nothing else."""
    await _handle_schedule_progress(Event(name=_EVENT, data={"activity_id": str(activity_id), "progress_pct": pct}))


async def _progress(activity_id: uuid.UUID, pct: float) -> None:
    """A progress save as the schedule makes it: commit the row, then publish."""
    import app.database as database_module

    async with database_module.async_session_factory() as s:
        await s.execute(update(Activity).where(Activity.id == activity_id).values(progress_pct=str(pct)))
        await s.commit()
    await _deliver(activity_id, pct)


async def _stored_progress(factory: async_sessionmaker[AsyncSession], *ids: uuid.UUID) -> list[Decimal]:
    async with factory() as s:
        return [Decimal((await s.get(Activity, i)).progress_pct) for i in ids]


async def test_a_progress_save_writes_one_snapshot_with_weighted_earned_value(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id, (a, _b) = await _project(
        factory,
        activities=[
            {"progress": "0", "start": _on(0), "end": _on(14), "cost": "60000"},
            {"progress": "0", "start": _on(0), "end": _on(14), "cost": "40000"},
        ],
        data_date=_on(7),
    )

    await _progress(a, 50)

    rows = await _snapshots(factory, project_id)
    assert len(rows) == 1, "no snapshot reached EVM, or more than one"
    snap = rows[0]
    # 60000 at 50% + 40000 at 0% = 30000 earned of 100000. Planned: both run
    # Mon 2 Mar .. Mon 16 Mar, ten working days, and the data date Mon 9 Mar
    # is five of them, so PV = 50000.
    assert Decimal(snap.bac) == Decimal("100000")
    assert Decimal(snap.ev) == Decimal("30000")
    assert Decimal(snap.pv) == Decimal("50000")
    assert Decimal(snap.ac) == Decimal("30000")
    assert Decimal(snap.sv) == Decimal("-20000")
    assert Decimal(snap.cv) == Decimal("0")
    assert Decimal(snap.spi) == Decimal("0.6")
    assert Decimal(snap.cpi) == Decimal("1")
    # The forecast family comes from the canonical writer, not left at "0".
    assert Decimal(snap.eac) == Decimal("100000")
    assert Decimal(snap.etc) == Decimal("70000")
    # PV and EV are measured at the schedule's data date, and the point sits there.
    assert snap.snapshot_date == _on(7)
    assert snap.metadata_["source"] == EVM_PROGRESS_SNAPSHOT_SOURCE
    assert snap.metadata_["status_date_source"] == "data_date"


async def test_without_a_data_date_the_snapshot_is_taken_today(factory: async_sessionmaker[AsyncSession]) -> None:
    project_id, (a, _b) = await _project(factory)

    await _progress(a, 50)

    (snap,) = await _snapshots(factory, project_id)
    assert snap.snapshot_date == TODAY.isoformat()
    assert snap.metadata_["status_date_source"] == "today"


async def test_planned_value_is_measured_at_the_data_date_not_today(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """Progress entered on a later day "as of" the data date.

    Measured at today the work is long since planned complete and the SPI reads
    0.3; at the data date the plan was half done and the SPI is 0.6.
    """
    project_id, (a, _b) = await _project(
        factory,
        activities=[
            {"progress": "0", "start": _on(0), "end": _on(14), "cost": "60000"},
            {"progress": "0", "start": _on(0), "end": _on(14), "cost": "40000"},
        ],
        data_date=_on(7),
    )

    await _progress(a, 50)

    (snap,) = await _snapshots(factory, project_id)
    assert Decimal(snap.pv) == Decimal("50000")
    assert Decimal(snap.spi) == Decimal("0.6")


async def test_a_data_date_after_today_is_read_as_today(factory: async_sessionmaker[AsyncSession]) -> None:
    """A mistyped year must not leave a future point every "latest" query picks."""
    project_id, (a, _b) = await _project(factory, data_date=(TODAY + timedelta(days=3650)).isoformat())

    await _progress(a, 50)

    (snap,) = await _snapshots(factory, project_id)
    assert snap.snapshot_date == TODAY.isoformat()


async def test_an_activity_calendar_from_the_schedule_is_honoured(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """The handler resolves each activity's calendar as the progress engine does."""
    from app.modules.schedule_advanced.models import Calendar

    project_id, (a, b) = await _project(
        factory,
        activities=[
            {"progress": "0", "start": _on(0), "end": _on(14), "cost": "60000"},
            {"progress": "0", "start": _on(0), "end": _on(14), "cost": "40000"},
        ],
        data_date=_on(5),  # Saturday 7 Mar
    )
    async with factory() as s:
        seven_day = Calendar(project_id=project_id, name="Seven-day site", work_days=[0, 1, 2, 3, 4, 5, 6])
        s.add(seven_day)
        await s.flush()
        (await s.get(Activity, a)).calendar_id = seven_day.id
        await s.commit()

    await _progress(b, 10)

    (snap,) = await _snapshots(factory, project_id)
    # a: 5 of 14 days on its seven-day calendar. b: 4 of 10 working days.
    expected = Decimal("60000") * Decimal(5) / Decimal(14) + Decimal("40000") * Decimal("0.4")
    assert Decimal(snap.pv) == expected.quantize(Decimal("0.01"))


async def test_a_second_save_on_the_same_day_replaces_the_row_rather_than_adding_one(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id, (a, b) = await _project(factory)

    await _progress(a, 50)
    await _progress(b, 25)

    rows = await _snapshots(factory, project_id)
    assert len(rows) == 1, f"{len(rows)} snapshots for one day, the S-curve would plot each"
    # 60000*50% + 40000*25% = 40000. Doubling would give 70000 or 80000.
    assert Decimal(rows[0].ev) == Decimal("40000")


async def test_concurrent_saves_still_leave_one_row(factory: async_sessionmaker[AsyncSession]) -> None:
    """A person ticking through activities fires the handlers together.

    The handlers reach the lock in whatever order their lookups return, so the
    surviving row must match what is stored at the end, not whichever event
    happened to be handled last.
    """
    project_id, (a, b) = await _project(factory)

    await asyncio.gather(*(_progress(a if i % 2 else b, 10 * i) for i in range(6)))

    (snap,) = await _snapshots(factory, project_id)
    pa, pb = await _stored_progress(factory, a, b)
    assert Decimal(snap.ev) == (Decimal("60000") * pa + Decimal("40000") * pb) / Decimal("100")


async def test_a_late_event_does_not_overwrite_a_newer_save(factory: async_sessionmaker[AsyncSession]) -> None:
    """5% typed, corrected to 50% a second later, and the 5% handler runs last.

    Both saves are committed by then, so the stored 50 is the truth. Reading
    the event's figure instead would leave a day's S-curve point and forecast
    computed on 5%.
    """
    project_id, (a, _b) = await _project(factory)
    await _progress(a, 50)

    await _deliver(a, 5)

    (snap,) = await _snapshots(factory, project_id)
    # 60000 at 50% + 40000 at 0%. The stale event would give 3000.
    assert Decimal(snap.ev) == Decimal("30000")
    assert snap.metadata_["earned_pct"] == "30.00"


async def test_saves_queued_behind_one_run_are_recomputed_once(
    factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A diary sync of many saves must not recompute the project once per save.

    Each run reads every stored row, so when several saves are queued for the
    lock only the last one needs to run.
    """
    project_id, (a, b) = await _project(factory)
    runs: list[str] = []
    real_write = event_handlers._write_progress_snapshot

    async def counting_write(project: uuid.UUID, *, trigger_activity_id: str) -> None:
        runs.append(trigger_activity_id)
        await real_write(project, trigger_activity_id=trigger_activity_id)

    monkeypatch.setattr(event_handlers, "_write_progress_snapshot", counting_write)

    lock = event_handlers._evm_project_lock(str(project_id))
    start = event_handlers._evm_latest_generation(str(project_id))
    await lock.acquire()
    try:
        tasks = [asyncio.create_task(_progress(a if i % 2 else b, 10 + i)) for i in range(5)]
        for _ in range(500):
            if event_handlers._evm_latest_generation(str(project_id)) - start == 5:
                break
            await asyncio.sleep(0.01)
        assert event_handlers._evm_latest_generation(str(project_id)) - start == 5, "not every save queued"
    finally:
        lock.release()
    await asyncio.gather(*tasks)

    assert len(runs) == 1, f"{len(runs)} recomputations for five queued saves"
    (snap,) = await _snapshots(factory, project_id)
    pa, pb = await _stored_progress(factory, a, b)
    assert Decimal(snap.ev) == (Decimal("60000") * pa + Decimal("40000") * pb) / Decimal("100")


async def test_the_recompute_reads_columns_not_activity_graphs(factory: async_sessionmaker[AsyncSession]) -> None:
    """Activity entities drag their children, parent and work orders along.

    Each relationship is ``selectin``, so loading entities issues one more
    query per relationship on every save. Only the columns the arithmetic
    uses are read.
    """
    from sqlalchemy import event as sa_event

    project_id, (a, _b) = await _project(factory)
    async with factory() as s:
        engine = s.bind
    statements: list[str] = []

    def _record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    sa_event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        await _deliver(a, 50)
    finally:
        sa_event.remove(engine.sync_engine, "before_cursor_execute", _record)

    assert len(await _snapshots(factory, project_id)) == 1
    assert not [q for q in statements if "oe_schedule_work_order" in q], "work orders were loaded"
    assert not [q for q in statements if "parent_id IN" in q], "the activity hierarchy was walked"


async def test_a_snapshot_a_person_recorded_today_is_left_alone(factory: async_sessionmaker[AsyncSession]) -> None:
    project_id, (a, _b) = await _project(factory)
    async with factory() as s:
        s.add(
            EVMSnapshot(
                project_id=project_id,
                snapshot_date=TODAY.isoformat(),
                bac="1",
                pv="1",
                ev="1",
                ac="1",
                metadata_={},
            )
        )
        await s.commit()

    await _progress(a, 80)

    rows = await _snapshots(factory, project_id)
    assert len(rows) == 1
    assert rows[0].bac == "1", "the recorded snapshot was overwritten"


async def test_yesterdays_automatic_snapshot_is_kept(factory: async_sessionmaker[AsyncSession]) -> None:
    """Replacement is per day; history is the S-curve."""
    project_id, (a, _b) = await _project(factory)
    async with factory() as s:
        s.add(
            EVMSnapshot(
                project_id=project_id,
                snapshot_date=(TODAY - timedelta(days=1)).isoformat(),
                bac="100000",
                ev="10000",
                metadata_={"source": EVM_PROGRESS_SNAPSHOT_SOURCE},
            )
        )
        await s.commit()

    await _progress(a, 50)

    dates = sorted(r.snapshot_date for r in await _snapshots(factory, project_id))
    assert dates == [(TODAY - timedelta(days=1)).isoformat(), TODAY.isoformat()]


async def test_progress_on_a_what_if_schedule_earns_nothing(factory: async_sessionmaker[AsyncSession]) -> None:
    project_id, (a, _b) = await _project(factory, schedule_type="what_if")

    await _progress(a, 100)

    assert await _snapshots(factory, project_id) == []


async def test_a_project_without_a_budget_gets_no_snapshot(factory: async_sessionmaker[AsyncSession]) -> None:
    project_id, (a, _b) = await _project(factory, budgets=[("0", "0", "0")])

    await _progress(a, 50)

    assert await _snapshots(factory, project_id) == []


async def test_revised_budget_is_the_bac(factory: async_sessionmaker[AsyncSession]) -> None:
    """An approved change raises the budget the work is earned against."""
    project_id, (a, _b) = await _project(factory, budgets=[("100000", "120000", "0")])

    await _progress(a, 50)

    (snap,) = await _snapshots(factory, project_id)
    assert Decimal(snap.bac) == Decimal("120000")
    assert Decimal(snap.ev) == Decimal("36000")


@pytest.mark.parametrize("currency", ["KWD", "JPY", "EUR"])
async def test_every_money_field_is_stored_at_the_currency_precision(
    factory: async_sessionmaker[AsyncSession],
    currency: str,
) -> None:
    """A dinar keeps its fils and a yen gets no invented decimals.

    Replaces the stub-session test of the old handler: these rows are what the
    forecast surfaces read, so the precision is checked on the stored row.
    """
    from app.core.money import money_quantum

    project_id, (a, _b) = await _project(
        factory,
        currency=currency,
        budgets=[("1000001", "1000001", "333333")],
        activities=[
            {"progress": "0", "start": -2, "end": 4, "cost": "700"},
            {"progress": "0", "start": -2, "end": 4, "cost": "300"},
        ],
    )

    await _progress(a, 33.3)

    (snap,) = await _snapshots(factory, project_id)
    want = -money_quantum(currency).as_tuple().exponent
    for field in ("bac", "pv", "ev", "ac", "sv", "cv"):
        value = getattr(snap, field)
        assert -Decimal(value).as_tuple().exponent == want, f"{currency}: {field}={value!r}, expected {want} places"
    for field in ("spi", "cpi"):
        assert -Decimal(getattr(snap, field)).as_tuple().exponent == 4, f"{field} is an index, not money"


async def test_an_unknown_activity_is_ignored(factory: async_sessionmaker[AsyncSession]) -> None:
    await _progress(uuid.uuid4(), 50)
    await _handle_schedule_progress(Event(name=_EVENT, data={}))
    await _handle_schedule_progress(Event(name=_EVENT, data={"activity_id": "not-a-uuid"}))


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """What the schedule module really hands the bus, captured at publish_detached."""
    from app.core.events import event_bus

    seen: list[tuple[str, dict[str, Any]]] = []

    def _record(name: str, data: dict | None = None, source_module: str | None = None) -> None:
        seen.append((name, dict(data or {})))

    monkeypatch.setattr(event_bus, "publish_detached", _record)
    return seen


async def test_update_progress_publishes_after_commit_and_drives_the_handler(
    factory: async_sessionmaker[AsyncSession],
    published: list[tuple[str, dict[str, Any]]],
) -> None:
    """What the publisher sends is what the handler reads, and only once saved.

    A save that fails after the publish must not leave a snapshot for progress
    that was never stored, so the event waits for the commit.
    """
    from app.modules.schedule.service import ScheduleService

    project_id, (a, _b) = await _project(factory)

    async with factory() as s:
        await ScheduleService(s).update_progress(a, 75.0)
        assert _EVENT not in [n for n, _ in published], "published before the commit"
        await s.commit()

    progress_events = [data for name, data in published if name == _EVENT]
    assert len(progress_events) == 1, f"update_progress published {[n for n, _ in published]}"
    await _handle_schedule_progress(Event(name=_EVENT, data=progress_events[0]))

    (snap,) = await _snapshots(factory, project_id)
    # 60000 at 75% + 40000 at 0% = 45000.
    assert Decimal(snap.ev) == Decimal("45000")


async def test_a_rolled_back_progress_save_publishes_nothing(
    factory: async_sessionmaker[AsyncSession],
    published: list[tuple[str, dict[str, Any]]],
) -> None:
    from app.modules.schedule.service import ScheduleService

    _project_id, (a, _b) = await _project(factory)

    async with factory() as s:
        await ScheduleService(s).update_progress(a, 75.0)
        await s.rollback()

    assert _EVENT not in [n for n, _ in published]


async def test_typed_progress_publishes_after_commit_and_drives_the_handler(
    factory: async_sessionmaker[AsyncSession],
    published: list[tuple[str, dict[str, Any]]],
) -> None:
    from app.modules.schedule.progress_schemas import TypedProgressRequest
    from app.modules.schedule.progress_service import ScheduleProgressService

    project_id, (a, _b) = await _project(factory)

    async with factory() as s:
        outcome = await ScheduleProgressService(s).set_typed_progress(
            a,
            TypedProgressRequest(percent_complete_type="physical", percent=40.0),
        )
        assert _EVENT not in [n for n, _ in published], "published before the commit"
        await s.commit()

    progress_events = [data for name, data in published if name == _EVENT]
    assert len(progress_events) == 1
    await _handle_schedule_progress(Event(name=_EVENT, data=progress_events[0]))

    (snap,) = await _snapshots(factory, project_id)
    pct = Decimal(str(outcome.result.percent_complete))
    assert pct > 0, "the engine resolved no progress, so this test would prove nothing"
    assert Decimal(snap.ev) == (Decimal("60000") * pct / Decimal("100")).quantize(Decimal("0.01"))
