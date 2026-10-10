"""Integration: deleting schedules and activities, and the reach of a new link.

Against real PostgreSQL with foreign keys enforced:

* deleting a schedule must not leave its baselines behind (the baseline table
  holds the schedule id without a foreign key, so nothing cascaded to it);
* deleting a summary moves its children up one level, under the summary's own
  parent, instead of dropping them to the top of the plan;
* a dependency link may only join two activities of the schedule it is created
  on: the endpoint rewrites the successor's dependency list, so an activity id
  from another schedule let a caller edit a plan they had no access to;
* the link and generate endpoints answer with a code the screen translates,
  never with a bare English sentence or "check server logs".
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.modules.schedule import router as schedule_router
from app.modules.schedule.models import Activity, ScheduleBaseline
from app.modules.schedule.schemas import ActivityCreate, GenerateFromBOQRequest, RelationshipCreate, ScheduleCreate
from app.modules.schedule.service import ScheduleService
from tests._pg import transactional_session


async def _noop_verify(service, _session, schedule_id, *_args, **_kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
    return await service.get_schedule(schedule_id)


@pytest.fixture
def no_owner_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(schedule_router, "_verify_schedule_owner", _noop_verify)


async def _schedule(service: ScheduleService, name: str = "S") -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    session = service.session
    user = User(
        email=f"del-{uuid.uuid4().hex[:8]}@schedule-del.io",
        hashed_password="x",
        full_name="Owner",
        role="editor",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    project = Project(name=f"Project {name}", owner_id=user.id)
    session.add(project)
    await session.flush()
    schedule = await service.create_schedule(ScheduleCreate(project_id=project.id, name=name, start_date="2026-07-01"))
    return schedule.id


async def _activity(service: ScheduleService, schedule_id: uuid.UUID, name: str, **kw) -> uuid.UUID:  # noqa: ANN003
    act = await service.create_activity(
        ActivityCreate(schedule_id=schedule_id, name=name, start_date="2026-07-01", end_date="2026-07-03", **kw)
    )
    return act.id


@pytest.mark.asyncio
async def test_purging_an_archived_schedule_takes_its_baselines() -> None:
    async with transactional_session(disable_fks=True) as session:
        service = ScheduleService(session)
        schedule_id = await _schedule(service)
        await _activity(service, schedule_id, "A")
        session.add(
            ScheduleBaseline(
                schedule_id=schedule_id,
                project_id=uuid.uuid4(),
                name="Contract baseline",
                baseline_date="2026-07-01",
                snapshot_data={},
            )
        )
        await session.flush()

        admin = {"role": "admin"}
        await service.delete_schedule(schedule_id, actor_payload=admin)
        await service.purge_schedule(schedule_id, actor_payload=admin)
        left = (
            await session.execute(
                select(func.count()).select_from(ScheduleBaseline).where(ScheduleBaseline.schedule_id == schedule_id)
            )
        ).scalar_one()
        assert left == 0


def _baseline(schedule_id: uuid.UUID) -> ScheduleBaseline:
    return ScheduleBaseline(
        schedule_id=schedule_id,
        project_id=uuid.uuid4(),
        name="Contract baseline",
        baseline_date="2026-07-01",
        snapshot_data={},
    )


async def _count(session, model, schedule_id: uuid.UUID) -> int:  # noqa: ANN001
    column = model.schedule_id if model is ScheduleBaseline else model.id
    return (await session.execute(select(func.count()).select_from(model).where(column == schedule_id))).scalar_one()


@pytest.mark.asyncio
async def test_an_editor_archives_baselines_but_a_non_owner_cannot_purge(no_owner_check: None) -> None:
    """Archive is reversible; baselines cannot be destroyed through its endpoint."""
    from app.modules.schedule.models import Schedule

    async with transactional_session(disable_fks=True) as session:
        service = ScheduleService(session)
        schedule_id = await _schedule(service)
        session.add(_baseline(schedule_id))
        await session.flush()

        editor = {"sub": str(uuid.uuid4()), "role": "editor", "permissions": ["schedule.delete"]}
        await schedule_router.delete_schedule(
            schedule_id, _user_id=editor["sub"], payload=editor, session=session, service=service
        )
        with pytest.raises(HTTPException) as refused:
            await service.purge_schedule(schedule_id, actor_payload=editor)
        assert refused.value.status_code == 403
        assert (await service.get_schedule(schedule_id)).status == "archived"
        assert await _count(session, Schedule, schedule_id) == 1
        assert await _count(session, ScheduleBaseline, schedule_id) == 1

        # The confirmation asks first, so it never offers the Delete refused above.
        impact = await schedule_router.schedule_delete_impact(
            schedule_id, _user_id=editor["sub"], payload=editor, session=session, service=service
        )
        assert (impact.can_delete, impact.blocked_reason) == (False, "permission_denied")
        admin = {"sub": str(uuid.uuid4()), "role": "admin", "permissions": []}
        impact = await schedule_router.schedule_delete_impact(
            schedule_id, _user_id=admin["sub"], payload=admin, session=session, service=service
        )
        assert (impact.can_delete, impact.blocked_reason) == (True, None)

        await schedule_router.purge_schedule(
            schedule_id, _user_id=admin["sub"], payload=admin, session=session, service=service
        )
        assert await _count(session, Schedule, schedule_id) == 0
        assert await _count(session, ScheduleBaseline, schedule_id) == 0


@pytest.mark.asyncio
async def test_an_editor_archives_an_active_schedule_without_baselines(no_owner_check: None) -> None:
    from app.modules.schedule.models import Schedule
    from app.modules.schedule.schemas import ScheduleUpdate

    async with transactional_session() as session:
        service = ScheduleService(session)
        schedule_id = await _schedule(service)
        await _activity(service, schedule_id, "A")
        await service.update_schedule(schedule_id, ScheduleUpdate(status="active"))

        editor = {"sub": str(uuid.uuid4()), "role": "editor", "permissions": ["schedule.delete"]}
        await schedule_router.delete_schedule(
            schedule_id, _user_id=editor["sub"], payload=editor, session=session, service=service
        )
        assert await _count(session, Schedule, schedule_id) == 1
        assert (await service.get_schedule(schedule_id)).status == "archived"


@pytest.mark.asyncio
async def test_deleting_a_summary_moves_its_children_up_one_level() -> None:
    async with transactional_session() as session:
        service = ScheduleService(session)
        schedule_id = await _schedule(service)
        top = await _activity(service, schedule_id, "Top", activity_type="summary")
        mid = await _activity(service, schedule_id, "Mid", activity_type="summary", parent_id=top)
        leaf_a = await _activity(service, schedule_id, "Leaf A", parent_id=mid)
        leaf_b = await _activity(service, schedule_id, "Leaf B", parent_id=mid)

        await service.delete_activity(mid)
        session.expire_all()
        parents = {
            row.id: row.parent_id
            for row in (await session.execute(select(Activity).where(Activity.id.in_([leaf_a, leaf_b])))).scalars()
        }
        assert parents == {leaf_a: top, leaf_b: top}


@pytest.mark.asyncio
async def test_deleting_a_summary_with_its_children_takes_the_whole_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.schedule import service as schedule_service

    published: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        schedule_service,
        "publish_after_commit",
        lambda _s, name, data=None, **_kw: published.append((name, data or {})),
    )
    async with transactional_session() as session:
        service = ScheduleService(session)
        schedule_id = await _schedule(service)
        top = await _activity(service, schedule_id, "Top", activity_type="summary")
        mid = await _activity(service, schedule_id, "Mid", activity_type="summary", parent_id=top)
        leaf = await _activity(service, schedule_id, "Leaf", parent_id=mid)
        outside = await _activity(
            service,
            schedule_id,
            "Outside",
            dependencies=[{"activity_id": str(leaf), "type": "FS", "lag_days": 0}],
        )
        published.clear()

        assert await service.delete_activity(top, cascade=True) == 3
        session.expire_all()
        left = (await session.execute(select(Activity).where(Activity.schedule_id == schedule_id))).scalars().all()
        assert [a.id for a in left] == [outside]
        assert left[0].dependencies == [], "a link to a removed activity must not survive in the mirror"
        # One announcement for the activity deleted and one for the schedule,
        # not one per activity of the branch.
        assert [name for name, _ in published] == ["schedule.activity.deleted", "schedule.activities.cleared"]
        assert published[0][1]["activity_id"] == str(top)
        assert published[1][1]["count"] == 3


@pytest.mark.asyncio
async def test_a_branch_of_more_than_ten_thousand_goes_whole() -> None:
    async with transactional_session() as session:
        service = ScheduleService(session)
        schedule_id = await _schedule(service)
        top = await _activity(service, schedule_id, "Top", activity_type="summary")
        kids = [
            Activity(
                id=uuid.uuid4(),
                schedule_id=schedule_id,
                parent_id=top,
                name=f"Kid {i}",
                start_date="2026-07-01",
                end_date="2026-07-01",
                duration_days=1,
                activity_type="task",
                dependencies=[],
                resources=[],
                sort_order=i + 1,
            )
            for i in range(10_050)
        ]
        await service.activity_repo.create_many(kids)
        last = kids[-1].id
        outside = await _activity(
            service,
            schedule_id,
            "Outside",
            dependencies=[{"activity_id": str(last), "type": "FS", "lag_days": 0}],
        )

        assert await service.delete_activity(top, cascade=True) == 10_051
        session.expire_all()
        left = (await session.execute(select(Activity).where(Activity.schedule_id == schedule_id))).scalars().all()
        assert [a.id for a in left] == [outside]
        assert left[0].dependencies == []


@pytest.mark.asyncio
async def test_a_link_is_deleted_by_its_two_activities(no_owner_check: None) -> None:
    from app.modules.schedule.models import ScheduleRelationship

    async with transactional_session() as session:
        service = ScheduleService(session)
        schedule_id = await _schedule(service)
        a = await _activity(service, schedule_id, "A")
        b = await _activity(
            service, schedule_id, "B", dependencies=[{"activity_id": str(a), "type": "FS", "lag_days": 0}]
        )
        user = {"sub": str(uuid.uuid4()), "role": "editor", "permissions": ["schedule.update"]}
        await schedule_router.delete_relationship_between(
            schedule_id,
            session=session,
            _user_id=user["sub"],
            payload=user,
            predecessor_id=a,
            successor_id=b,
            service=service,
        )
        session.expire_all()
        rels = (await session.execute(select(ScheduleRelationship).where(ScheduleRelationship.successor_id == b))).all()
        assert rels == []
        assert (await session.get(Activity, b)).dependencies == []

        with pytest.raises(HTTPException) as gone:
            await schedule_router.delete_relationship_between(
                schedule_id,
                session=session,
                _user_id=user["sub"],
                payload=user,
                predecessor_id=a,
                successor_id=b,
                service=service,
            )
        assert gone.value.status_code == 404
        assert gone.value.detail["error"] == "relationship_not_found"


@pytest.mark.asyncio
async def test_delete_impact_counts_activities_baselines_and_linked_instalments() -> None:
    from decimal import Decimal

    from app.modules.contracts.models import Contract, ContractMilestone
    from app.modules.contracts.service import ContractsService
    from app.modules.schedule.models import Schedule

    async with transactional_session() as session:
        service = ScheduleService(session)
        schedule_id = await _schedule(service)
        milestone_id = await _activity(service, schedule_id, "Roof watertight", activity_type="milestone")
        await _activity(service, schedule_id, "Frame")
        session.add(_baseline(schedule_id))
        schedule = await session.get(Schedule, schedule_id)
        contract = Contract(
            code=f"C-{uuid.uuid4().hex[:8]}",
            title="Main works",
            project_id=schedule.project_id,
            contract_type="lump_sum",
            currency="USD",
            total_value=Decimal("100000"),
            retention_percent=Decimal("0"),
            terms={},
            status="active",
        )
        session.add(contract)
        await session.flush()
        instalment = ContractMilestone(
            contract_id=contract.id,
            code="M1",
            name="Roof",
            planned_date="2026-09-01",
            value=Decimal("30000"),
            trigger="completion",
            status="pending",
            lag_days=0,
        )
        session.add(instalment)
        await session.flush()
        await ContractsService(session).link_milestone_activity(instalment.id, milestone_id)

        assert await service.delete_impact(schedule_id) == {
            "activity_count": 2,
            "baseline_count": 1,
            "payment_milestone_count": 1,
        }

        # The delete announces the cleared schedule; the payment plan's
        # subscriber refreshes by that schedule id. Run the same refresh here:
        # the instalment lets go and falls back to its contract date.
        await service.delete_schedule(schedule_id, actor_payload={"role": "admin"})
        assert (await service.get_schedule(schedule_id)).status == "archived"
        await session.refresh(instalment)
        assert instalment.activity_id == milestone_id
        await service.purge_schedule(schedule_id, actor_payload={"role": "admin"})
        assert await ContractsService(session).refresh_linked_forecasts(schedule_id=schedule_id) == 1
        await session.refresh(instalment)
        assert instalment.activity_id is None
        assert instalment.forecast_reached_date == "2026-09-01"


@pytest.mark.asyncio
async def test_a_link_cannot_reach_into_another_schedule(no_owner_check: None) -> None:
    async with transactional_session() as session:
        service = ScheduleService(session)
        mine = await _schedule(service, "Mine")
        theirs = await _schedule(service, "Theirs")
        my_act = await _activity(service, mine, "Mine A")
        their_act = await _activity(service, theirs, "Theirs A")

        for pred, succ in ((my_act, their_act), (their_act, my_act)):
            with pytest.raises(HTTPException) as excinfo:
                await schedule_router.create_relationship(
                    schedule_id=mine,
                    data=RelationshipCreate(predecessor_id=pred, successor_id=succ, relationship_type="FS"),
                    session=session,
                    _user_id="u",
                    payload={},
                    service=service,
                )
            assert excinfo.value.status_code == 404
            assert excinfo.value.detail["error"] == "schedule_activity_not_in_schedule"

        session.expire_all()
        their_row = await session.get(Activity, their_act)
        assert their_row is not None and not their_row.dependencies


@pytest.mark.asyncio
async def test_link_refusals_carry_codes(no_owner_check: None) -> None:
    async with transactional_session() as session:
        service = ScheduleService(session)
        sid = await _schedule(service)
        a = await _activity(service, sid, "A")
        b = await _activity(service, sid, "B")

        async def _link(pred: uuid.UUID, succ: uuid.UUID):  # noqa: ANN202
            return await schedule_router.create_relationship(
                schedule_id=sid,
                data=RelationshipCreate(predecessor_id=pred, successor_id=succ, relationship_type="FS"),
                session=session,
                _user_id="u",
                payload={},
                service=service,
            )

        with pytest.raises(HTTPException) as self_link:
            await _link(a, a)
        assert self_link.value.status_code == 400
        assert self_link.value.detail["error"] == "schedule_dependency_self"

        await _link(a, b)
        with pytest.raises(HTTPException) as cycle:
            await _link(b, a)
        assert cycle.value.status_code == 400
        assert cycle.value.detail["error"] == "schedule_dependency_cycle"
        assert "message" in cycle.value.detail


@pytest.mark.asyncio
async def test_an_unexpected_generation_failure_is_a_code_with_a_reference(
    no_owner_check: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with transactional_session(disable_fks=True) as session:
        service = ScheduleService(session)
        sid = await _schedule(service)

        async def _boom(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            raise RuntimeError("synthetic")

        monkeypatch.setattr(service, "generate_from_boq", _boom)
        with pytest.raises(HTTPException) as excinfo:
            await schedule_router.generate_from_boq(
                schedule_id=sid,
                body=GenerateFromBOQRequest(boq_id=uuid.uuid4()),
                _user_id="u",
                payload={},
                session=session,
                service=service,
            )
        assert excinfo.value.status_code == 500
        detail = excinfo.value.detail
        assert detail["error"] == "schedule_generation_failed"
        assert detail["reference"]
        assert "log" not in detail["message"].lower()


def test_generate_request_accepts_replace() -> None:
    body = GenerateFromBOQRequest(boq_id=uuid.uuid4(), replace=True)
    assert body.replace is True
    assert GenerateFromBOQRequest(boq_id=uuid.uuid4()).replace is False


async def _owner_payload(service: ScheduleService, schedule_id: uuid.UUID) -> dict:
    from app.modules.projects.models import Project

    schedule = await service.get_schedule(schedule_id)
    owner_id = (
        await service.session.execute(select(Project.owner_id).where(Project.id == schedule.project_id))
    ).scalar_one()
    return {"sub": str(owner_id), "role": "editor", "permissions": ["schedule.delete"]}


@pytest.mark.asyncio
async def test_the_project_owner_deletes_an_archived_schedule(no_owner_check: None) -> None:
    """A tester could not delete their own schedule: only an admin could. The
    owner of the project may now, once it is archived; anyone else still only
    archives."""
    from app.modules.schedule.models import Schedule

    async with transactional_session(disable_fks=True) as session:
        service = ScheduleService(session)
        schedule_id = await _schedule(service)
        await _activity(service, schedule_id, "A")
        owner = await _owner_payload(service, schedule_id)
        stranger = {"sub": str(uuid.uuid4()), "role": "editor", "permissions": ["schedule.delete"]}

        with pytest.raises(HTTPException) as early:
            await service.purge_schedule(schedule_id, actor_payload=owner)
        assert early.value.status_code == 409
        await service.delete_schedule(schedule_id, actor_payload=owner)

        impact = await schedule_router.schedule_delete_impact(
            schedule_id, _user_id=stranger["sub"], payload=stranger, session=session, service=service
        )
        assert (impact.can_delete, impact.blocked_reason) == (False, "permission_denied")
        with pytest.raises(HTTPException) as refused:
            await service.purge_schedule(schedule_id, actor_payload=stranger)
        assert refused.value.status_code == 403

        impact = await schedule_router.schedule_delete_impact(
            schedule_id, _user_id=owner["sub"], payload=owner, session=session, service=service
        )
        assert (impact.can_delete, impact.blocked_reason) == (True, None)
        await schedule_router.purge_schedule(
            schedule_id, _user_id=owner["sub"], payload=owner, session=session, service=service
        )
        assert await _count(session, Schedule, schedule_id) == 0


@pytest.mark.asyncio
async def test_an_owner_leaves_a_schedule_with_baselines_to_an_admin(no_owner_check: None) -> None:
    async with transactional_session(disable_fks=True) as session:
        service = ScheduleService(session)
        schedule_id = await _schedule(service)
        session.add(_baseline(schedule_id))
        await session.flush()
        owner = await _owner_payload(service, schedule_id)
        await service.delete_schedule(schedule_id, actor_payload=owner)

        impact = await schedule_router.schedule_delete_impact(
            schedule_id, _user_id=owner["sub"], payload=owner, session=session, service=service
        )
        assert (impact.can_delete, impact.blocked_reason) == (False, "schedule_has_baselines")
        with pytest.raises(HTTPException) as refused:
            await service.purge_schedule(schedule_id, actor_payload=owner)
        assert refused.value.status_code == 409
