"""Integration: generating a schedule from a BOQ, against real PostgreSQL.

A tester's report: "Generate from BoQ always gives me errors". Reproduced, the
generator

* read only the top level and its direct children, so every position deeper
  than two levels (an Italian capitolo > categoria > voce bill, a GAEB
  Los > Titel > Position bill) silently vanished from the plan;
* refused any second run with a bare English 409 the screen could not
  translate, while nothing on the screen could clear the schedule;
* read at most 5000 positions and dropped the rest without a word;
* crashed with a 500 on a resource row that is not a mapping;
* chained every position of a section strictly one after the other, so a
  600-line section ran for years past the window the user had asked for.

These tests build real bills in those shapes, with foreign keys enforced, and
call the service the endpoint calls.
"""

from __future__ import annotations

import math
import uuid
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.modules.schedule.models import Activity, ScheduleRelationship
from app.modules.schedule.schemas import ActivityCreate, ScheduleCreate
from app.modules.schedule.service import ScheduleService
from tests._pg import transactional_session

START = "2026-05-04"  # a Monday


async def _project(session) -> uuid.UUID:  # noqa: ANN001
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"gen-{uuid.uuid4().hex[:8]}@schedule-gen.io",
        hashed_password="x",
        full_name="Generator",
        role="editor",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    project = Project(name="Generate QA", owner_id=user.id)
    session.add(project)
    await session.flush()
    return project.id


class _Bill:
    """Builds a BOQ row by row; ``add`` returns the new position id."""

    def __init__(self, session, boq_id: uuid.UUID) -> None:  # noqa: ANN001
        self.session = session
        self.boq_id = boq_id
        self.order = 0
        self.leaves: list[uuid.UUID] = []

    async def section(self, parent: uuid.UUID | None, ordinal: str, description: str) -> uuid.UUID:
        return await self._add(parent, ordinal, description, "", "0", "0", leaf=False)

    async def position(
        self,
        parent: uuid.UUID | None,
        ordinal: str,
        description: str,
        unit: str = "m2",
        qty: str = "10",
        rate: str = "10",
        meta: dict | None = None,
    ) -> uuid.UUID:
        return await self._add(parent, ordinal, description, unit, qty, rate, leaf=True, meta=meta)

    async def _add(self, parent, ordinal, description, unit, qty, rate, *, leaf, meta=None):  # noqa: ANN001, ANN202
        from app.modules.boq.models import Position

        self.order += 1
        total = str(float(qty) * float(rate))
        pos = Position(
            boq_id=self.boq_id,
            parent_id=parent,
            ordinal=ordinal,
            description=description,
            unit=unit,
            quantity=qty,
            unit_rate=rate,
            total=total,
            metadata_=meta or {},
            sort_order=self.order,
        )
        self.session.add(pos)
        await self.session.flush()
        if leaf:
            self.leaves.append(pos.id)
        return pos.id


async def _setup(session):  # noqa: ANN001, ANN202
    from app.modules.boq.models import BOQ

    project_id = await _project(session)
    service = ScheduleService(session)
    schedule = await service.create_schedule(ScheduleCreate(project_id=project_id, name="Gen", start_date=START))
    boq = BOQ(project_id=project_id, name="Computo metrico")
    session.add(boq)
    await session.flush()
    return service, schedule.id, _Bill(session, boq.id), project_id


async def _activities(service: ScheduleService, schedule_id: uuid.UUID) -> list[Activity]:
    service.session.expire_all()
    rows, _ = await service.list_activities_for_schedule(schedule_id, limit=100_000)
    return rows


def _task_positions(activities: list[Activity]) -> list[str]:
    out: list[str] = []
    for a in activities:
        if a.activity_type == "task":
            out.extend(a.boq_position_ids or [])
    return out


async def _italian_bill(bill: _Bill) -> None:
    cap = await bill.section(None, "01", "OPERE STRUTTURALI")
    cat = await bill.section(cap, "01.01", "Fondazioni")
    await bill.position(cat, "01.01.001", "Scavo di sbancamento", "m3", "120", "18")
    await bill.position(cat, "01.01.002", "Calcestruzzo per plinti C25/30", "m3", "35", "140")
    cat2 = await bill.section(cap, "01.02", "Elevazioni")
    await bill.position(cat2, "01.02.001", "Pilastri in c.a.", "m3", "22", "380")
    await bill.position(cap, "01.900", "Oneri della sicurezza", "a corpo", "1", "2500")
    cap2 = await bill.section(None, "02", "FINITURE")
    cat3 = await bill.section(cap2, "02.01", "Intonaci")
    await bill.position(cat3, "02.01.001", "Intonaco civile", "m2", "640", "22")


@pytest.mark.asyncio
async def test_italian_three_level_bill_puts_every_voce_in_one_task() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        await _italian_bill(bill)

        await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        acts = await _activities(service, schedule_id)

        linked = _task_positions(acts)
        assert sorted(linked) == sorted(str(p) for p in bill.leaves)
        assert len(linked) == len(set(linked)), "a position landed in two tasks"

        by_id = {a.id: a for a in acts}
        by_name = {a.name: a for a in acts}
        fondazioni = by_name["Fondazioni"]
        assert fondazioni.activity_type == "summary"
        assert by_id[fondazioni.parent_id].name == "OPERE STRUTTURALI"
        assert by_name["Scavo di sbancamento"].parent_id == fondazioni.id
        assert by_name["Oneri della sicurezza"].parent_id == by_name["OPERE STRUTTURALI"].id

        # Summaries span exactly their children.
        for summary in (a for a in acts if a.activity_type == "summary"):
            kids = [a for a in acts if a.parent_id == summary.id]
            assert kids, summary.name
            assert summary.start_date == min(k.start_date for k in kids), summary.name
            assert summary.end_date == max(k.end_date for k in kids), summary.name


@pytest.mark.asyncio
async def test_gaeb_four_level_bill_keeps_the_whole_tree() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        los = await bill.section(None, "1", "Los 1 Rohbau")
        for t in range(2):
            titel = await bill.section(los, f"1.{t + 1}", f"Titel {t + 1}")
            unter = await bill.section(titel, f"1.{t + 1}.1", f"Untertitel {t + 1}.1")
            for p in range(3):
                await bill.position(unter, f"1.{t + 1}.1.{p + 1}", f"Position {t + 1}.{p + 1}", "m2", "50", "30")

        await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        acts = await _activities(service, schedule_id)

        linked = _task_positions(acts)
        assert sorted(linked) == sorted(str(p) for p in bill.leaves)
        assert len(linked) == 6
        depth = {}
        by_id = {a.id: a for a in acts}
        for a in acts:
            d, cur = 0, a
            while cur.parent_id is not None:
                d += 1
                cur = by_id[cur.parent_id]
            depth[a.name] = d
        assert depth["Position 1.1"] == 3


@pytest.mark.asyncio
async def test_empty_sections_and_blank_rows_make_no_activities() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        await bill.section(None, "01", "Added but never filled")
        s2 = await bill.section(None, "02", "Real work")
        await bill.position(s2, "02.1", "Massetto", "m2", "100", "15")
        await bill._add(s2, "02.2", "", "m2", "0", "0", leaf=False)  # the editor's blank new row

        await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        acts = await _activities(service, schedule_id)

        names = {a.name for a in acts}
        assert "Added but never filled" not in names
        assert _task_positions(acts) == [str(bill.leaves[0])]


@pytest.mark.asyncio
async def test_second_run_without_replace_is_a_structured_conflict() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        await _italian_bill(bill)
        await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        count = len(await _activities(service, schedule_id))

        with pytest.raises(HTTPException) as excinfo:
            await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        assert excinfo.value.status_code == 409
        detail = excinfo.value.detail
        assert isinstance(detail, dict)
        assert detail["error"] == "schedule_has_activities"
        assert detail["activity_count"] == count
        assert "message" in detail


@pytest.mark.asyncio
async def test_replace_regenerates_cleanly() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        await _italian_bill(bill)
        await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        first = {a.id for a in await _activities(service, schedule_id)}

        await service.generate_from_boq(schedule_id, bill.boq_id, 365, replace=True)
        acts = await _activities(service, schedule_id)
        assert first.isdisjoint({a.id for a in acts})
        assert sorted(_task_positions(acts)) == sorted(str(p) for p in bill.leaves)

        rels = (
            (await session.execute(select(ScheduleRelationship).where(ScheduleRelationship.schedule_id == schedule_id)))
            .scalars()
            .all()
        )
        ids = {a.id for a in acts}
        assert rels, "the generated plan carries its links"
        assert all(r.predecessor_id in ids and r.successor_id in ids for r in rels)
        # The JSON mirror agrees with the canonical edges.
        mirror = sum(len(a.dependencies or []) for a in acts)
        assert mirror == len(rels)


@pytest.mark.asyncio
async def test_replace_takes_rows_that_hang_off_the_old_activities() -> None:
    """Work orders and progress steps on the old plan must not block replacing it."""
    from app.modules.schedule.models import WorkOrder
    from app.modules.schedule.progress_models import ProgressStep

    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        await _italian_bill(bill)
        await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        task = next(a for a in await _activities(service, schedule_id) if a.activity_type == "task")
        session.add(WorkOrder(activity_id=task.id, code="WO-1"))
        session.add(ProgressStep(activity_id=task.id, name="Formwork", weight=1, percent_complete=40, sort_order=0))
        await service.activity_repo.update_fields(task.id, status="in_progress", progress_pct="40")
        await session.flush()

        with pytest.raises(HTTPException) as refused:
            await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        assert refused.value.detail["started_count"] == 1

        await service.generate_from_boq(schedule_id, bill.boq_id, 365, replace=True)
        for model in (WorkOrder, ProgressStep):
            left = (
                await session.execute(select(func.count()).select_from(model).where(model.activity_id == task.id))
            ).scalar_one()
            assert left == 0, model.__name__
        assert sorted(_task_positions(await _activities(service, schedule_id))) == sorted(str(p) for p in bill.leaves)


@pytest.mark.asyncio
async def test_empty_bill_is_a_structured_error() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        await bill.section(None, "01", "Only a header")
        with pytest.raises(HTTPException) as excinfo:
            await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        assert excinfo.value.status_code == 422
        assert excinfo.value.detail["error"] == "boq_has_no_positions"


@pytest.mark.asyncio
async def test_a_bill_of_another_project_is_not_found() -> None:
    from app.modules.boq.models import BOQ

    async with transactional_session() as session:
        service, schedule_id, _bill, _ = await _setup(session)
        other_project = await _project(session)
        foreign = BOQ(project_id=other_project, name="Someone else's bill")
        session.add(foreign)
        await session.flush()
        foreign_bill = _Bill(session, foreign.id)
        await foreign_bill.position(None, "1", "Foreign work")

        with pytest.raises(HTTPException) as excinfo:
            await service.generate_from_boq(schedule_id, foreign.id, 365)
        assert excinfo.value.status_code == 404
        assert excinfo.value.detail["error"] == "boq_not_found"


@pytest.mark.asyncio
async def test_more_than_five_thousand_positions_are_all_scheduled() -> None:
    from app.modules.boq.models import Position

    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        section = await bill.section(None, "01", "Huge")
        rows = [
            Position(
                boq_id=bill.boq_id,
                parent_id=section,
                ordinal=f"01.{i:05d}",
                description=f"P{i}",
                unit="m2",
                quantity="10",
                unit_rate="1",
                total="10",
                metadata_={},
                sort_order=i + 10,
            )
            for i in range(5200)
        ]
        session.add_all(rows)
        await session.flush()

        await service.generate_from_boq(schedule_id, bill.boq_id, 3650)
        acts = await _activities(service, schedule_id)
        assert len(_task_positions(acts)) == 5200


@pytest.mark.asyncio
async def test_a_big_section_runs_in_crews_to_fit_the_window() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        section = await bill.section(None, "01", "Masonry")
        for i in range(40):
            await bill.position(
                section, f"01.{i:03d}", f"Wall {i}", "m2", "40", "30"
            )  # 32 h, a gang of three: 2 working days each

        await service.generate_from_boq(schedule_id, bill.boq_id, 90)
        acts = await _activities(service, schedule_id)

        last_day = date.fromisoformat(START) + timedelta(days=89)
        assert max(date.fromisoformat(a.end_date) for a in acts) <= last_day
        schedule = await service.get_schedule(schedule_id)
        generation = schedule.metadata_["boq_generation"]
        assert generation["warnings"] == []
        assert generation["crews"] > 1
        assert generation["positions_scheduled"] == 40


@pytest.mark.asyncio
async def test_a_plan_that_cannot_fit_carries_a_warning() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        section = await bill.section(None, "01", "Too much")
        for i in range(300):
            await bill.position(section, f"01.{i:03d}", f"Item {i}", "m2", "100", "10")

        await service.generate_from_boq(schedule_id, bill.boq_id, 30, workers_per_position=1)
        schedule = await service.get_schedule(schedule_id)
        warnings = schedule.metadata_["boq_generation"]["warnings"]
        assert [w["code"] for w in warnings] == ["plan_exceeds_window"]
        warning = warnings[0]
        assert warning["requested_end"] == (date.fromisoformat(START) + timedelta(days=29)).isoformat()
        assert warning["planned_end"] > warning["requested_end"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resources",
    [["Operaio", None], {"a": 1}, [{"type": 3, "unit": None, "quantity": "x"}], "labor"],
    ids=["strings", "mapping", "odd-types", "plain-string"],
)
async def test_malformed_resource_rows_do_not_crash(resources: object) -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        section = await bill.section(None, "01", "Sezione")
        await bill.position(section, "01.1", "Odd resources", "m3", "20", "75", meta={"resources": resources})

        await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        assert _task_positions(await _activities(service, schedule_id)) == [str(bill.leaves[0])]


@pytest.mark.asyncio
async def test_a_long_ordinal_never_overflows_the_wbs_code() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        section = await bill.section(None, "X" * 50, "D" * 5000)
        await bill.position(section, "", "Q" * 5000)  # a legacy row with no ordinal

        await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        acts = await _activities(service, schedule_id)
        assert all(len(a.wbs_code) <= 50 and len(a.name) <= 255 for a in acts)


@pytest.mark.asyncio
async def test_one_summary_one_task_per_position_and_two_milestones() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        section = await bill.section(None, "01", "S")
        for i in range(30):
            await bill.position(section, f"01.{i}", f"P{i}")
        await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        n = (
            await session.execute(select(func.count()).select_from(Activity).where(Activity.schedule_id == schedule_id))
        ).scalar_one()
        # 30 tasks + 1 summary + 2 milestones
        assert n == 33


# ── Preview, start day, notes, completion, language ─────────────────────────


@pytest.mark.asyncio
async def test_completion_waits_for_every_task_nothing_else_waits_for() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        await _italian_bill(bill)
        await bill.position(None, "99", "Loose item after the sections", "m2", "5", "10")

        await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        acts = await _activities(service, schedule_id)
        completion = next(a for a in acts if a.wbs_code == "MS-999")
        rels = (
            (await session.execute(select(ScheduleRelationship).where(ScheduleRelationship.schedule_id == schedule_id)))
            .scalars()
            .all()
        )
        followed = {r.predecessor_id for r in rels if r.relationship_type == "FS" and r.successor_id != completion.id}
        tasks = {a.id for a in acts if a.activity_type == "task"}
        into_completion = {r.predecessor_id for r in rels if r.successor_id == completion.id}
        assert into_completion == tasks - followed
        assert any(a.name == "Loose item after the sections" and a.id in into_completion for a in acts)
        # The milestone sits on the working day after the last work, wherever
        # that work is: where CPM puts a milestone that follows it.
        last_work = date.fromisoformat(max(a.end_date for a in acts if a.activity_type == "task"))
        next_day = last_work + timedelta(days=1)
        while next_day.weekday() >= 5:
            next_day += timedelta(days=1)
        assert completion.end_date == next_day.isoformat()


@pytest.mark.asyncio
async def test_a_loose_lump_sum_runs_from_the_first_day_to_the_last() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        safety = await bill.position(None, "00", "Oneri della sicurezza", "LS", "1", "25000")
        await _italian_bill(bill)

        preview = await service.preview_generation(schedule_id, bill.boq_id, 365)
        await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        acts = await _activities(service, schedule_id)
        site = next(a for a in acts if a.boq_position_ids == [str(safety)])
        others = [a for a in acts if a.activity_type == "task" and a.id != site.id]
        assert site.start_date == min(a.start_date for a in others)
        assert site.end_date == max(a.end_date for a in others)
        assert site.metadata_["duration_method"] == "spans_works"

        completion = next(a for a in acts if a.wbs_code == "MS-999")
        rels = (
            (await session.execute(select(ScheduleRelationship).where(ScheduleRelationship.schedule_id == schedule_id)))
            .scalars()
            .all()
        )
        # Nothing waits for it and it waits for nothing; the completion does.
        assert {r.relationship_type for r in rels if site.id in (r.predecessor_id, r.successor_id)} == {"FS"}
        assert [r.successor_id for r in rels if r.predecessor_id == site.id] == [completion.id]

        note = next(n for n in preview["notes"] if n["position_id"] == str(safety))
        assert note["note"] == "spans_works"
        assert note["days"] == site.duration_days


@pytest.mark.asyncio
async def test_a_reschedule_right_after_generating_moves_no_bar() -> None:
    from app.modules.schedule_advanced.models import Calendar

    async with transactional_session() as session:
        service, schedule_id, bill, project_id = await _setup(session)
        # The project's own calendar, with holidays inside the plan: the
        # generator has to draw on it, or CPM moves every bar after them.
        holidays = ["2026-05-25", "2026-06-02", "2026-07-15"]
        session.add(
            Calendar(project_id=project_id, name="Site", work_days=[0, 1, 2, 3, 4], holidays=holidays, is_default=True)
        )
        await session.flush()
        await _italian_bill(bill)
        cap3 = await bill.section(None, "03", "IMPIANTI")
        for i in range(6):
            await bill.position(cap3, f"03.{i:03d}", f"Impianto {i}", "m", "300", "40")

        await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        before = {a.id: (a.start_date, a.end_date) for a in await _activities(service, schedule_id)}
        assert not any(day in holidays for span in before.values() for day in span)

        await service.reschedule(schedule_id)
        after = {a.id: (a.start_date, a.end_date) for a in await _activities(service, schedule_id)}
        moved = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
        assert moved == {}


@pytest.mark.asyncio
async def test_replacing_the_plan_carries_payment_instalments_to_the_same_milestone() -> None:
    from decimal import Decimal

    from app.modules.contracts.models import Contract, ContractMilestone
    from app.modules.contracts.service import ContractsService

    async with transactional_session() as session:
        service, schedule_id, bill, project_id = await _setup(session)
        await _italian_bill(bill)
        await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        acts = await _activities(service, schedule_id)
        completion = next(a for a in acts if a.wbs_code == "MS-999")
        handover = await service.create_activity(
            ActivityCreate(
                schedule_id=schedule_id,
                name="Handover to the client",
                start_date="2026-12-01",
                end_date="2026-12-01",
                activity_type="milestone",
            )
        )
        contract = Contract(
            code=f"C-{uuid.uuid4().hex[:8]}",
            title="Main works",
            project_id=project_id,
            contract_type="lump_sum",
            currency="EUR",
            total_value=Decimal("100000"),
            retention_percent=Decimal("0"),
            terms={},
            status="active",
        )
        session.add(contract)
        await session.flush()
        contracts = ContractsService(session)
        instalments = []
        for code, activity_id in (("FINAL", completion.id), ("HANDOVER", handover.id)):
            instalment = ContractMilestone(
                contract_id=contract.id,
                code=code,
                name=code,
                planned_date="2027-01-15",
                value=Decimal("10000"),
                trigger="completion",
                status="pending",
                lag_days=0,
            )
            session.add(instalment)
            await session.flush()
            await contracts.link_milestone_activity(instalment.id, activity_id)
            instalments.append(instalment)

        preview = await service.preview_generation(schedule_id, bill.boq_id, 365)
        assert (preview["instalments_relinked"], preview["instalments_unlinked"]) == (1, 1)
        with pytest.raises(HTTPException) as refused:
            await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        assert refused.value.detail["instalments_relinked"] == 1
        assert refused.value.detail["instalments_unlinked"] == 1

        await service.generate_from_boq(schedule_id, bill.boq_id, 365, replace=True)
        # What the cleared event runs after the commit.
        await contracts.refresh_linked_forecasts(schedule_id=schedule_id)
        new_completion = next(a for a in await _activities(service, schedule_id) if a.wbs_code == "MS-999")
        final, handover_instalment = instalments
        await session.refresh(final)
        await session.refresh(handover_instalment)
        assert final.activity_id == new_completion.id
        assert final.forecast_reached_date == new_completion.end_date
        assert handover_instalment.activity_id is None


@pytest.mark.asyncio
async def test_a_lump_sum_priced_by_its_total_alone_is_scheduled() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        section = await bill.section(None, "01", "ALLESTIMENTO")
        await bill.position(section, "01.1", "Recinzione", "m", "120", "15")
        site = await bill.position(section, "01.2", "Oneri di cantiere", "LS", "0", "0")
        from app.modules.boq.models import Position

        await session.execute(
            Position.__table__.update().where(Position.id == site).values(total="12000", unit_rate="12000")
        )
        await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        task = next(a for a in await _activities(service, schedule_id) if a.boq_position_ids == [str(site)])
        assert task.metadata_["duration_method"] == "cost_proportional"
        assert "(1 LS)" in task.description


@pytest.mark.asyncio
async def test_a_position_with_no_quantity_is_left_out_with_a_note() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        section = await bill.section(None, "02", "DEMOLIZIONI E RIMOZIONI")
        await bill.position(section, "02.1", "Demolizione di intonaco", "m2", "842.35", "14.10")
        zero = await bill.position(section, "02.2", "Trasporto a discarica", "m3", "0", "38.50")

        preview = await service.preview_generation(schedule_id, bill.boq_id, 365)
        skipped = [n for n in preview["notes"] if n["note"] == "skipped_zero_qty"]
        assert [n["position_id"] for n in skipped] == [str(zero)]
        assert preview["skipped_count"] == 1

        await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        assert str(zero) not in _task_positions(await _activities(service, schedule_id))


@pytest.mark.asyncio
async def test_the_preview_writes_nothing_and_is_the_plan_that_gets_written() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        await _italian_bill(bill)
        await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        before = sorted((a.name, a.start_date, a.end_date) for a in await _activities(service, schedule_id))

        preview = await service.preview_generation(schedule_id, bill.boq_id, 200, start_date=date(2026, 9, 7))
        after = sorted((a.name, a.start_date, a.end_date) for a in await _activities(service, schedule_id))
        assert after == before, "a preview must not touch the schedule"
        assert (await service.get_schedule(schedule_id)).start_date == START
        assert preview["existing_activity_count"] == len(before)
        assert preview["planned_start"] == "2026-09-07"
        # The lump sum goes by its cost share, the four measured positions by
        # their unit; none of the bill carries labour norms.
        assert preview["estimated_count"] == 5
        assert preview["note_counts"]["estimated_from_unit"] == 4
        assert preview["note_counts"]["cost_share"] == 1
        assert preview["lump_sum_positions"] == 1

        await service.generate_from_boq(schedule_id, bill.boq_id, 200, replace=True, start_date=date(2026, 9, 7))
        written = await _activities(service, schedule_id)
        assert len(written) == preview["activity_count"]
        assert max(a.end_date for a in written) == preview["planned_end"]


@pytest.mark.asyncio
async def test_the_start_day_in_the_request_is_written_with_the_plan() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        section = await bill.section(None, "01", "S")
        await bill.position(section, "01.1", "P", "m2", "10", "10")

        await service.generate_from_boq(schedule_id, bill.boq_id, 30, start_date=date(2026, 9, 7))
        schedule = await service.get_schedule(schedule_id)
        assert schedule.start_date == "2026-09-07"
        assert schedule.metadata_["boq_generation"]["requested_end"] == "2026-10-06"
        assert min(a.start_date for a in await _activities(service, schedule_id)) == "2026-09-07"


@pytest.mark.asyncio
async def test_without_a_schedule_start_the_project_planned_start_is_used() -> None:
    from app.modules.boq.models import BOQ
    from app.modules.projects.models import Project

    async with transactional_session() as session:
        project_id = await _project(session)
        project = await session.get(Project, project_id)
        project.planned_start_date = "2027-02-01"
        await session.flush()
        service = ScheduleService(session)
        schedule = await service.create_schedule(ScheduleCreate(project_id=project_id, name="No start"))
        boq = BOQ(project_id=project_id, name="Bill")
        session.add(boq)
        await session.flush()
        bill = _Bill(session, boq.id)
        section = await bill.section(None, "01", "S")
        await bill.position(section, "01.1", "P", "m2", "10", "10")

        preview = await service.preview_generation(schedule.id, boq.id)
        assert preview["planned_start"] == "2027-02-01"
        assert preview["requested_end"] is None
        assert preview["fits"] is True


@pytest.mark.asyncio
async def test_generated_names_follow_the_readers_language() -> None:
    from app.core.i18n import get_locale, is_locale_loaded, load_translations, set_locale

    if not is_locale_loaded("it"):
        load_translations()
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        section = await bill.section(None, "01", "S")
        await bill.position(section, "01.1", "Intonaco civile", "mq", "640", "22")

        previous = get_locale()
        set_locale("it")
        try:
            await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        finally:
            set_locale(previous)
        acts = await _activities(service, schedule_id)
        names = {a.wbs_code: a.name for a in acts if a.activity_type == "milestone"}
        assert names == {"MS-001": "Inizio lavori", "MS-999": "Fine lavori"}
        task = next(a for a in acts if a.activity_type == "task")
        assert task.description == "Generato automaticamente dalla voce 01.1 del computo metrico (640 mq)"


@pytest.mark.asyncio
async def test_a_guess_from_the_unit_is_held_to_the_positions_price() -> None:
    # The measured restoration bill: 6,252 m2 of scaffold hire (1,250 m2 for
    # five more months) at 1.62 reads as 5,000 hours from the m2 rate, more
    # than half the bill's guessed hours, for a tenth of its money.
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        temp = await bill.section(None, "01", "OPERE PROVVISIONALI")
        await bill.position(temp, "01.1", "Ponteggio, primo mese", "m2", "1250.40", "12.85")
        hire = await bill.position(temp, "01.2", "Ponteggio, ogni mese successivo", "m2", "6252", "1.62")
        demo = await bill.section(None, "02", "DEMOLIZIONI")
        await bill.position(demo, "02.1", "Demolizione di intonaco", "mq", "842.35", "14.10")
        finishes = await bill.section(None, "04", "FINITURE")
        await bill.position(finishes, "04.1", "Intonaco a calce", "m2", "1650.8", "28.90")
        await bill.position(finishes, "04.2", "Tinteggiatura a calce", "m2", "1650.8", "9.40")

        preview = await service.preview_generation(schedule_id, bill.boq_id, 365)
        note = next(n for n in preview["notes"] if n["position_id"] == str(hire))
        basis = note["basis"]
        assert basis["capped_by_price"] is True
        assert basis["hours_from_unit"] == pytest.approx(6252 * 0.8)
        # Three times its share of the guessed money, in guessed hours.
        guessed_cost = 1250.40 * 12.85 + 6252 * 1.62 + 842.35 * 14.10 + 1650.8 * 28.90 + 1650.8 * 9.40
        guessed_hours = (1250.40 + 6252 + 842.35 + 1650.8 + 1650.8) * 0.8
        cap = 3 * 6252 * 1.62 / guessed_cost * guessed_hours
        assert basis["hours"] == pytest.approx(cap, abs=0.1)
        assert basis["gang"] == 3
        assert note["days"] == math.ceil(round(cap, 1) / (3 * 8))


# ── Workers per position ─────────────────────────────────────────────────────


def _labour_row(hours_per_unit: float) -> dict:
    # What a real bill carries: one labour row in hours per unit, no crew.
    return {"resources": [{"type": "labor", "name": "Manodopera", "unit": "hr", "quantity": hours_per_unit}]}


async def _bill_without_crews(bill: _Bill) -> list[uuid.UUID]:
    # Three trades of four positions, 10,000 man-hours each: one worker a
    # position would need years, far past an 880-day window.
    ids = []
    for s in range(3):
        section = await bill.section(None, f"0{s + 1}", f"Capitolo {s + 1}")
        for i in range(4):
            ids.append(
                await bill.position(
                    section, f"0{s + 1}.{i + 1}", f"Voce {s + 1}.{i + 1}", "m2", "20000", "10", meta=_labour_row(0.5)
                )
            )
    return ids


@pytest.mark.asyncio
async def test_a_bill_without_crews_gets_the_fewest_workers_that_fit() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        await _bill_without_crews(bill)

        preview = await service.preview_generation(schedule_id, bill.boq_id, 880)
        workers = preview["workers_per_position"]
        assert 1 < workers < 20, workers
        assert preview["workers_assumed"] is True
        assert preview["positions_without_workers"] == 12
        # It fits at the estimates themselves, nothing squeezed.
        assert preview["fits"] and preview["compressed_pct"] is None and preview["warnings"] == []

        # And it is the fewest: one worker less needs shortening or overruns.
        fewer = await service.preview_generation(schedule_id, bill.boq_id, 880, workers_per_position=workers - 1)
        assert fewer["workers_per_position"] == workers - 1
        assert fewer["workers_assumed"] is False
        assert fewer["warnings"] != []


@pytest.mark.asyncio
async def test_without_an_end_date_the_workers_fit_the_default_window_and_say_so() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        await _bill_without_crews(bill)
        preview = await service.preview_generation(schedule_id, bill.boq_id, None)
        workers = preview["workers_per_position"]
        assert 1 < workers < 20, workers
        assert preview["workers_assumed"] is True
        # A residential bill's default: a year from the start.
        assert preview["fitted_window"] == {
            "days": 365,
            "end": (date.fromisoformat(START) + timedelta(days=364)).isoformat(),
            "default": True,
            "fits": True,
        }
        assert preview["requested_end"] is None and preview["compressed_pct"] is None
        assert preview["planned_end"] <= preview["fitted_window"]["end"]

        explicit = await service.preview_generation(schedule_id, bill.boq_id, 880)
        assert explicit["fitted_window"]["default"] is False
        assert explicit["workers_per_position"] < workers


@pytest.mark.asyncio
async def test_when_even_twenty_workers_do_not_fit_the_preview_says_so() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        section = await bill.section(None, "01", "Troppo")
        for i in range(4):
            # 2,000,000 man-hours a position: 20 workers still need years.
            await bill.position(section, f"01.{i}", f"Voce {i}", "m2", "1000000", "10", meta=_labour_row(2))
        preview = await service.preview_generation(schedule_id, bill.boq_id, None)
        assert preview["workers_per_position"] == 20
        assert preview["fitted_window"]["fits"] is False
        # Years past the window, not a day: no rounding of the window decides it.
        assert preview["planned_end"] > (date.fromisoformat(START) + timedelta(days=3 * 365)).isoformat()
        for days in (199, 200, 201):
            explicit = await service.preview_generation(schedule_id, bill.boq_id, days)
            assert explicit["workers_per_position"] == 20, days
            assert explicit["fitted_window"]["fits"] is False
            # Halving every duration does not save it either, and the plan says so.
            assert explicit["fits"] is False and explicit["compressed_pct"] == 50
            assert [w["code"] for w in explicit["warnings"]] == ["plan_exceeds_window"]


@pytest.mark.asyncio
async def test_twenty_workers_that_fit_only_shortened_are_not_called_a_fit() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        await _bill_without_crews(bill)
        # 10,000 man-hours a position at 20 workers is about 96 calendar days,
        # well inside 150, so no position is held to the window on its own;
        # the twelve together still need shortening to fit.
        preview = await service.preview_generation(schedule_id, bill.boq_id, 150)
        assert preview["workers_per_position"] == 20
        assert preview["workers_assumed"] is True
        # The plan fits the end date, but only shortened: the window was not
        # met at the estimates, which is what fitted_window reports.
        assert preview["fits"] is True
        assert preview["compressed_pct"] is not None
        assert preview["fitted_window"]["fits"] is False
        assert preview["warnings"] == [{"code": "durations_shortened", "percent": preview["compressed_pct"]}]


@pytest.mark.asyncio
async def test_workers_asked_for_win_over_the_fitted_number() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        await _bill_without_crews(bill)
        await service.generate_from_boq(schedule_id, bill.boq_id, 880, workers_per_position=10)
        tasks = [a for a in await _activities(service, schedule_id) if a.activity_type == "task"]
        # 10,000 h / (10 x 8 h) = 125 days, + 10% mobilisation, on a 5-day week.
        assert {a.duration_days for a in tasks} == {math.ceil(round(125 * 1.1 * 7 / 5) * 5 / 7)}
        generation = (await service.get_schedule(schedule_id)).metadata_["boq_generation"]
        assert generation["workers_per_position"] == 10
        assert generation["workers_assumed"] is False


@pytest.mark.asyncio
async def test_a_crew_the_bill_states_is_kept() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        await _bill_without_crews(bill)
        section = await bill.section(None, "09", "Con squadra")
        stated = await bill.position(
            section, "09.1", "Voce con squadra", "m2", "1000", "10", meta={"labor_hours": 0.8, "workers_per_unit": 2}
        )

        # No end date: nothing is shortened, so durations are the estimates.
        durations = {}
        for workers in (1, 12):
            preview = await service.preview_generation(schedule_id, bill.boq_id, None, workers_per_position=workers)
            assert preview["positions_without_workers"] == 12
            await service.generate_from_boq(schedule_id, bill.boq_id, None, replace=True, workers_per_position=workers)
            acts = await _activities(service, schedule_id)
            durations[workers] = {
                str(a.boq_position_ids[0]): a.duration_days for a in acts if a.activity_type == "task"
            }
        # 800 h for the two people the bill names, whatever is assumed elsewhere.
        assert durations[1][str(stated)] == durations[12][str(stated)]
        others = [pid for pid in durations[1] if pid != str(stated)]
        assert all(durations[12][pid] < durations[1][pid] for pid in others)


@pytest.mark.asyncio
async def test_the_assumption_never_gives_a_position_fewer_workers_than_before() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        section = await bill.section(None, "01", "Scavi")
        # No labour data: the unit table's gang for m3 is four.
        await bill.position(section, "01.1", "Scavo", "m3", "800", "18")
        preview = await service.preview_generation(schedule_id, bill.boq_id, 365, workers_per_position=2)
        note = preview["notes"][0]
        assert note["basis"]["gang"] == 4
        preview = await service.preview_generation(schedule_id, bill.boq_id, 365, workers_per_position=6)
        assert preview["notes"][0]["basis"]["gang"] == 6


@pytest.mark.asyncio
async def test_generating_writes_the_plan_the_preview_showed_and_records_the_workers() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        await _bill_without_crews(bill)
        preview = await service.preview_generation(schedule_id, bill.boq_id, 880)

        # The dialog sends back exactly the number the preview showed.
        await service.generate_from_boq(
            schedule_id, bill.boq_id, 880, workers_per_position=preview["workers_per_position"]
        )
        written = await _activities(service, schedule_id)
        assert len(written) == preview["activity_count"]
        assert max(a.end_date for a in written) == preview["planned_end"]
        generation = (await service.get_schedule(schedule_id)).metadata_["boq_generation"]
        assert generation["workers_per_position"] == preview["workers_per_position"]

        # Left to fit on its own, generate lands on the same number and plan.
        await service.generate_from_boq(schedule_id, bill.boq_id, 880, replace=True)
        again = await _activities(service, schedule_id)
        assert sorted((a.name, a.start_date, a.end_date) for a in again) == sorted(
            (a.name, a.start_date, a.end_date) for a in written
        )
        generation = (await service.get_schedule(schedule_id)).metadata_["boq_generation"]
        assert generation["workers_per_position"] == preview["workers_per_position"]
        assert generation["workers_assumed"] is True
