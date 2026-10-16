# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Interface register on PostgreSQL: status history, approval routing, validated links.

Three things the register lacked, each pinned against a real database and, where
it matters, over HTTP:

* every status an interface takes leaves a history entry (who, when, from, to,
  comment), including the moves an approval route makes;
* an interface agreement can be routed through approval_routes: an approval moves
  it to agreed, a pending or rejected route keeps a person from agreeing it by
  hand, and the person who started the route cannot approve it;
* the Schedule ID and the RFI link must name rows of the same project.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.interface_management.events import handle_route_event
from app.modules.interface_management.permissions import register_interface_management_permissions
from app.modules.interface_management.router import router
from app.modules.interface_management.schemas import InterfaceCreate, InterfaceUpdate
from app.modules.interface_management.service import InterfaceManagementService
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import add_project, add_route, add_user

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/interface-management"


@dataclass
class World:
    factory: async_sessionmaker[AsyncSession]
    project_id: uuid.UUID
    other_project_id: uuid.UUID
    owner: uuid.UUID
    editor: uuid.UUID
    approver: uuid.UUID
    outsider: uuid.UUID
    activity_id: uuid.UUID
    foreign_activity_id: uuid.UUID
    rfi_id: uuid.UUID
    foreign_rfi_id: uuid.UUID
    route_id: uuid.UUID


async def _activity(session: AsyncSession, project_id: uuid.UUID, end: str) -> uuid.UUID:
    from app.modules.schedule.models import Activity, Schedule

    schedule = Schedule(project_id=project_id, name="Programme")
    session.add(schedule)
    await session.flush()
    activity = Activity(schedule_id=schedule.id, name="Core walls L3", start_date="2026-10-01", end_date=end)
    session.add(activity)
    await session.flush()
    return activity.id


async def _rfi(session: AsyncSession, project_id: uuid.UUID, raised_by: uuid.UUID) -> uuid.UUID:
    from app.modules.rfi.models import RFI

    rfi = RFI(
        project_id=project_id,
        rfi_number=f"RFI-{uuid.uuid4().hex[:4]}",
        subject="Duct clash",
        question="Where does the duct pass the core wall?",
        raised_by=raised_by,
    )
    session.add(rfi)
    await session.flush()
    return rfi.id


@pytest_asyncio.fixture
async def world():
    register_interface_management_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as s:
            owner = await add_user(s, "manager")
            editor = await add_user(s, "editor")
            approver = await add_user(s, "manager")
            outsider = await add_user(s, "manager")
            pid = await add_project(s, owner, [editor, approver])
            other = await add_project(s, outsider, [])
            activity_id = await _activity(s, pid, "2026-11-01")
            foreign_activity_id = await _activity(s, other, "2026-11-01")
            rfi_id = await _rfi(s, pid, owner)
            foreign_rfi_id = await _rfi(s, other, outsider)
            route_id = await add_route(s, pid, "interface", approver)
            await s.commit()
        yield World(
            factory,
            pid,
            other,
            owner,
            editor,
            approver,
            outsider,
            activity_id,
            foreign_activity_id,
            rfi_id,
            foreign_rfi_id,
            route_id,
        )


@asynccontextmanager
async def client_as(w: World, user_id: uuid.UUID, role: str):
    from app.dependencies import get_current_user_id, get_current_user_payload, get_session

    app = FastAPI()
    app.include_router(router, prefix=BASE)

    async def _session():
        async with w.factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": str(user_id),
        "role": role,
        "permissions": [],
        "tenant_id": str(user_id),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://if-test") as c:
        yield c


async def _create(w: World, reference: str = "IF-001", **extra) -> uuid.UUID:
    async with w.factory() as s:
        row = await InterfaceManagementService(s).create_interface(
            w.project_id, InterfaceCreate(reference=reference, title="Duct through core wall", **extra), str(w.editor)
        )
        await s.commit()
        return row.id


async def _start_route(w: World, interface_id: uuid.UUID, started_by: uuid.UUID) -> uuid.UUID:
    from app.modules.approval_routes.schemas import InstanceCreate
    from app.modules.approval_routes.service import ApprovalRouteService

    async with w.factory() as s:
        instance = await ApprovalRouteService(s).start_instance(
            InstanceCreate(route_id=w.route_id, target_kind="interface", target_id=interface_id),
            started_by=started_by,
        )
        await s.commit()
        instance_id = instance.id
    await handle_route_event(
        {"target_kind": "interface", "target_id": str(interface_id), "instance_id": str(instance_id)},
        verdict="started",
        session_factory=w.factory,
    )
    return instance_id


async def _decide(w: World, instance_id: uuid.UUID, decider: uuid.UUID, verdict: str, comment: str | None = None):
    from app.modules.approval_routes.schemas import DecisionSubmit
    from app.modules.approval_routes.service import ApprovalRouteService

    async with w.factory() as s:
        svc = ApprovalRouteService(s)
        instance = await svc.get_instance(instance_id)
        step = next(st for st in await svc.repo.list_steps(instance.route_id) if st.ordinal == 1)
        await svc.submit_decision(
            instance_id,
            DecisionSubmit(step_id=step.id, decision=verdict, comment=comment),
            approver_id=decider,
            caller_role="manager",
        )
        await s.commit()
        final = (await svc.get_instance(instance_id)).status
    if final in ("approved", "rejected"):
        await handle_route_event(
            {
                "target_kind": "interface",
                "target_id": str(instance.target_id),
                "instance_id": str(instance_id),
                "decided_by": str(decider),
                "comment": comment,
            },
            verdict=final,
            session_factory=w.factory,
        )
    return final


async def _history(w: World, interface_id: uuid.UUID) -> list[dict]:
    async with w.factory() as s:
        return await InterfaceManagementService(s).list_history(w.project_id, interface_id)


async def _status(w: World, interface_id: uuid.UUID) -> tuple[str, object]:
    from app.modules.interface_management.models import InterfaceRecord

    async with w.factory() as s:
        row = await s.get(InterfaceRecord, interface_id)
        return row.status, row.agreed_date


# -- Status history ---------------------------------------------------------


async def test_every_status_change_leaves_a_history_entry_over_http(world: World) -> None:
    iid = await _create(world)
    p = f"{BASE}/projects/{world.project_id}/interfaces/{iid}"
    async with client_as(world, world.editor, "editor") as c:
        moved = await c.patch(p, json={"status": "in_progress", "status_comment": "Kick-off held"})
        untouched = await c.patch(p, json={"title": "Duct through core wall, level 3"})
        history = await c.get(f"{p}/history")
    assert moved.status_code == 200
    assert untouched.status_code == 200
    rows = history.json()
    assert [(r["event"], r["from_status"], r["to_status"]) for r in rows] == [
        ("created", None, "identified"),
        ("status_changed", "identified", "in_progress"),
    ]
    assert rows[1]["comment"] == "Kick-off held"
    assert rows[1]["actor_id"] == str(world.editor)
    assert rows[1]["actor_name"] == "Test editor"
    assert rows[1]["changed_at"]


async def test_history_is_mirrored_to_the_platform_activity_log(world: World) -> None:
    from app.core.audit_log import get_activity_for_entity

    iid = await _create(world)
    async with world.factory() as s:
        await InterfaceManagementService(s).update_interface(
            world.project_id, iid, InterfaceUpdate(status="open"), actor_id=world.editor
        )
        await s.commit()
        rows = await get_activity_for_entity(s, entity_type="interface", entity_id=iid, limit=10, offset=0)
    assert [(r.action, r.from_status, r.to_status) for r in rows] == [
        ("created", None, "identified"),
        ("status_changed", "identified", "open"),
    ]


async def test_a_stranger_cannot_read_the_history(world: World) -> None:
    iid = await _create(world)
    async with client_as(world, world.outsider, "manager") as c:
        r = await c.get(f"{BASE}/projects/{world.project_id}/interfaces/{iid}/history")
        foreign = await c.get(f"{BASE}/projects/{world.other_project_id}/interfaces/{iid}/history")
    assert r.status_code == 404
    assert foreign.status_code == 404


async def test_closed_only_from_agreed_and_dates_are_stamped(world: World) -> None:
    iid = await _create(world)
    p = f"{BASE}/projects/{world.project_id}/interfaces/{iid}"
    async with client_as(world, world.editor, "editor") as c:
        refused = await c.patch(p, json={"status": "closed"})
        agreed = await c.patch(p, json={"status": "agreed"})
        closed = await c.patch(p, json={"status": "closed"})
    assert refused.status_code == 422
    assert agreed.status_code == 200 and agreed.json()["agreed_date"] is not None
    assert closed.status_code == 200 and closed.json()["closed_date"] is not None
    events = [(h["from_status"], h["to_status"]) for h in await _history(world, iid)]
    assert events == [(None, "identified"), ("identified", "agreed"), ("agreed", "closed")]


# -- Approval routing -------------------------------------------------------


async def test_an_approved_route_agrees_the_interface_and_writes_its_history(world: World) -> None:
    iid = await _create(world)
    instance_id = await _start_route(world, iid, started_by=world.editor)
    assert await _decide(world, instance_id, world.approver, "approved", "Sleeve detail accepted") == "approved"
    status, agreed_date = await _status(world, iid)
    assert status == "agreed"
    assert agreed_date is not None
    history = await _history(world, iid)
    assert [(h["event"], h["to_status"]) for h in history] == [
        ("created", "identified"),
        ("approval_requested", "identified"),
        ("approval_approved", "agreed"),
    ]
    assert history[1]["actor_id"] == world.editor
    assert history[2]["actor_id"] == world.approver
    assert history[2]["comment"] == "Sleeve detail accepted"
    assert history[2]["approval_instance_id"] == instance_id


async def test_the_initiator_cannot_approve_their_own_interface_agreement(world: World) -> None:
    """Segregation of duties: the starter is also the step's approver, and is still refused."""
    iid = await _create(world)
    instance_id = await _start_route(world, iid, started_by=world.approver)
    with pytest.raises(HTTPException) as refused:
        await _decide(world, instance_id, world.approver, "approved")
    assert refused.value.status_code == 403
    status, _ = await _status(world, iid)
    assert status == "identified"


async def test_the_initiator_may_still_reject_their_own_request(world: World) -> None:
    iid = await _create(world)
    instance_id = await _start_route(world, iid, started_by=world.approver)
    assert await _decide(world, instance_id, world.approver, "rejected", "Withdrawn") == "rejected"


async def test_other_kinds_keep_the_engines_previous_behaviour(world: World) -> None:
    """The guard is scoped to the segregated kinds; an RFI route still lets its starter approve."""
    from app.modules.approval_routes.schemas import DecisionSubmit, InstanceCreate
    from app.modules.approval_routes.service import ApprovalRouteService

    async with world.factory() as s:
        route_id = await add_route(s, world.project_id, "rfi", world.approver)
        svc = ApprovalRouteService(s)
        instance = await svc.start_instance(
            InstanceCreate(route_id=route_id, target_kind="rfi", target_id=world.rfi_id), started_by=world.approver
        )
        step = (await svc.repo.list_steps(route_id))[0]
        decided = await svc.submit_decision(
            instance.id, DecisionSubmit(step_id=step.id, decision="approved"), approver_id=world.approver
        )
        assert decided.status == "approved"
        await s.rollback()


async def test_a_pending_or_rejected_route_blocks_agreeing_by_hand(world: World) -> None:
    iid = await _create(world)
    instance_id = await _start_route(world, iid, started_by=world.editor)
    p = f"{BASE}/projects/{world.project_id}/interfaces/{iid}"
    async with client_as(world, world.editor, "editor") as c:
        pending = await c.patch(p, json={"status": "agreed"})
    assert pending.status_code == 409
    assert await _decide(world, instance_id, world.approver, "rejected", "Clash not resolved") == "rejected"
    async with client_as(world, world.editor, "editor") as c:
        rejected = await c.patch(p, json={"status": "agreed"})
        other_move = await c.patch(p, json={"status": "disputed"})
    assert rejected.status_code == 409
    assert other_move.status_code == 200
    events = [h["event"] for h in await _history(world, iid)]
    assert events == ["created", "approval_requested", "approval_rejected", "status_changed"]


async def test_route_events_for_other_kinds_or_gone_interfaces_are_ignored(world: World) -> None:
    assert not await handle_route_event({"target_kind": "rfi", "target_id": str(uuid.uuid4())}, verdict="approved")
    gone = {"target_kind": "interface", "target_id": str(uuid.uuid4()), "instance_id": str(uuid.uuid4())}
    assert not await handle_route_event(gone, verdict="approved", session_factory=world.factory)


# -- Validated links --------------------------------------------------------


async def test_links_must_name_rows_of_the_same_project(world: World) -> None:
    p = f"{BASE}/projects/{world.project_id}/interfaces"
    async with client_as(world, world.editor, "editor") as c:
        foreign_activity = await c.post(
            p, json={"reference": "IF-A", "title": "t", "schedule_activity_id": str(world.foreign_activity_id)}
        )
        missing_activity = await c.post(
            p, json={"reference": "IF-B", "title": "t", "schedule_activity_id": str(uuid.uuid4())}
        )
        foreign_rfi = await c.post(p, json={"reference": "IF-C", "title": "t", "rfi_id": str(world.foreign_rfi_id)})
        not_a_uuid = await c.post(p, json={"reference": "IF-D", "title": "t", "rfi_id": "RFI-007"})
        good = await c.post(
            p,
            json={
                "reference": "IF-E",
                "title": "t",
                "rfi_id": str(world.rfi_id),
                "schedule_activity_id": str(world.activity_id),
            },
        )
        repoint = await c.patch(f"{p}/{good.json()['id']}", json={"rfi_id": str(world.foreign_rfi_id)})
        cleared = await c.patch(f"{p}/{good.json()['id']}", json={"rfi_id": None})
    assert [r.status_code for r in (foreign_activity, missing_activity, foreign_rfi, not_a_uuid)] == [422] * 4
    assert good.status_code == 201
    assert good.json()["rfi_id"] == str(world.rfi_id)
    assert repoint.status_code == 422
    assert cleared.status_code == 200 and cleared.json()["rfi_id"] is None


async def test_rule_set_flags_stale_links_and_late_need_by(world: World) -> None:
    from app.modules.interface_management.models import InterfaceRecord
    from app.modules.rfi.models import RFI

    late = await _create(world, "IF-LATE", schedule_activity_id=world.activity_id, need_by_date="2026-11-20")
    linked = await _create(world, "IF-RFI", rfi_id=world.rfi_id)
    async with world.factory() as s:
        # The RFI is deleted after the link was made, and a legacy row was closed without an agreement.
        await s.delete(await s.get(RFI, world.rfi_id))
        legacy = await s.get(InterfaceRecord, linked)
        legacy.status = "closed"
        await s.commit()
    async with client_as(world, world.editor, "editor") as c:
        r = await c.get(f"{BASE}/projects/{world.project_id}/validation")
    assert r.status_code == 200
    body = r.json()
    failing = {(x["rule_id"], x["element_ref"]) for x in body["results"] if not x["passed"]}
    assert ("interface_management.rfi_in_project", str(linked)) in failing
    assert ("interface_management.closed_was_agreed", str(linked)) in failing
    assert ("interface_management.agreed_has_agreed_date", str(linked)) in failing
    assert ("interface_management.need_by_before_activity_finish", str(late)) in failing
    assert ("interface_management.schedule_activity_in_project", str(late)) not in failing
    assert body["status"] == "errors"
    assert body["warnings"] == 1


# -- Register statistics ----------------------------------------------------


async def test_register_reports_ageing_and_overdue(world: World) -> None:
    await _create(world, "IF-1", need_by_date="2026-10-01")
    await _create(world, "IF-2")
    async with client_as(world, world.editor, "editor") as c:
        r = await c.get(f"{BASE}/projects/{world.project_id}/register", params={"as_of": "2026-10-20"})
    assert r.status_code == 200
    body = r.json()
    assert body["open_count"] == 2
    assert body["overdue_count"] == 1
    assert body["max_days_overdue"] == 19
    assert body["overdue_ageing"]["8_30"] == 1
    assert sum(body["ageing"].values()) == 2
    assert body["overdue"][0]["days_overdue"] == 19
