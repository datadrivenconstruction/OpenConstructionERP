# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Conditions, the stop freeze and gate planning, over HTTP against PostgreSQL.

What a condition is today does not wait for a sweep, who may close one is
answered per row for the caller, a stop freezes the whole frame, and a gate's
planned date comes from the schedule when the gate is linked to it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.project_governance.events as gov_events
from app.modules.project_governance import evaluator as ev
from app.modules.project_governance.models import GovernanceCondition, GovernanceModel
from app.modules.project_governance.permissions import register_governance_permissions
from app.modules.project_governance.service import GovernanceService
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import (
    World,
    add_activity,
    add_revision,
    add_user,
    areas,
    build_world,
    client_as,
    decide,
    documents,
    gate,
    prepare_gate,
    project_url,
)

pytestmark = pytest.mark.asyncio

G1 = "strategy_to_brief"
G2 = "brief_to_concept"
TODAY = datetime.now(UTC).date()


@pytest.fixture(autouse=True)
def _today_of_this_test() -> None:
    """Writes read the server day when they run; a day fixed at import goes stale at midnight UTC."""
    global TODAY
    TODAY = datetime.now(UTC).date()


@pytest_asyncio.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    register_governance_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(gov_events, "async_session_factory", factory)
        yield await build_world(factory)


def _code(response) -> str | None:
    detail = response.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


def _cond(w: World, *, due: date | None, area: str | None = "cost_finance") -> ev.ProposedCondition:
    return ev.ProposedCondition(
        area_code=area, document_type=None, text="Funding letter", owner_user_id=str(w.owner), due_date=due
    )


async def _passed_with_condition(w: World, *, due: date | None, area: str | None = "cost_finance") -> uuid.UUID:
    """Gate one passed with one condition owned by ``w.owner``; returns the condition id."""
    g = await prepare_gate(w, G1)
    await decide(w, g.id, "go_with_conditions", conditions=(_cond(w, due=due, area=area),), today=TODAY)
    async with w.factory() as s:
        rows, _ = await GovernanceService(s).repo.list_conditions(w.project_id)
    return rows[0].id


async def _stored(w: World, condition_id: uuid.UUID) -> GovernanceCondition:
    async with w.factory() as s:
        return await s.get(GovernanceCondition, condition_id)


async def _conditions(w: World, user: uuid.UUID, role: str, **params) -> dict:
    async with client_as(w, user, role) as c:
        r = await c.get(f"{project_url(w)}/conditions", params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def _post(w: World, user: uuid.UUID, role: str, path: str, json: dict | None = None):
    async with client_as(w, user, role) as c:
        return await c.post(f"{project_url(w)}/{path}", json=json or {})


# ── effective status and the sweep ──


async def test_a_condition_past_its_due_date_reads_overdue_before_any_sweep(world: World) -> None:
    cid = await _passed_with_condition(world, due=TODAY - timedelta(days=1))

    listed = await _conditions(world, world.editor, "editor")
    overdue = await _conditions(world, world.editor, "editor", status="overdue")
    still_open = await _conditions(world, world.editor, "editor", status="open")

    assert [c["status"] for c in listed["items"]] == ["overdue"]
    assert (overdue["total"], [c["id"] for c in overdue["items"]]) == (1, [str(cid)])
    assert (still_open["total"], still_open["items"]) == (0, [])
    # reading is not escalating: the stored row is untouched and nobody was told
    stored = await _stored(world, cid)
    assert stored.status == "open" and stored.escalated_at is None


async def test_a_condition_due_today_or_without_a_date_stays_open(world: World) -> None:
    await _passed_with_condition(world, due=TODAY)

    listed = await _conditions(world, world.editor, "editor")
    still_open = await _conditions(world, world.editor, "editor", status="open")

    assert [c["status"] for c in listed["items"]] == ["open"]
    assert still_open["total"] == 1
    assert (await _conditions(world, world.editor, "editor", status="overdue"))["total"] == 0


async def test_the_periodic_sweep_escalates_every_project_with_a_late_condition(world: World) -> None:
    from app.modules.project_governance.escalation import escalate_all

    cid = await _passed_with_condition(world, due=TODAY - timedelta(days=3))
    quiet = await build_world(world.factory)
    quiet_cid = await _passed_with_condition(quiet, due=TODAY + timedelta(days=3))

    async with world.factory() as s:
        first = await escalate_all(s, today=TODAY)
        await s.commit()
    async with world.factory() as s:
        second = await escalate_all(s, today=TODAY)
        await s.commit()

    assert (first, second) == (1, 0)
    late = await _stored(world, cid)
    assert late.status == "overdue" and late.escalated_at is not None
    assert (await _stored(quiet, quiet_cid)).status == "open"


# ── who may clear and who may waive, told per row ──


async def test_each_condition_says_what_the_caller_may_do_with_it(world: World) -> None:
    await _passed_with_condition(world, due=TODAY + timedelta(days=10))

    async def can(user: uuid.UUID, role: str) -> dict:
        return (await _conditions(world, user, role))["items"][0]["can"]

    assert await can(world.owner, "editor") == {
        "clear": True,
        "clear_reason": None,
        "waive": False,
        "waive_reason": "missing_permission",
    }
    assert await can(world.editor, "editor") == {
        "clear": False,
        "clear_reason": "not_condition_owner",
        "waive": False,
        "waive_reason": "missing_permission",
    }
    assert await can(world.owner, "viewer") == {
        "clear": False,
        "clear_reason": "missing_permission",
        "waive": False,
        "waive_reason": "missing_permission",
    }
    assert await can(world.decider, "manager") == {
        "clear": True,
        "clear_reason": None,
        "waive": True,
        "waive_reason": None,
    }
    # a manager the route does not name may clear (manager) but not waive (no authority)
    assert await can(world.manager, "manager") == {
        "clear": True,
        "clear_reason": None,
        "waive": False,
        "waive_reason": "decider_not_entitled",
    }


async def test_the_row_capability_is_what_the_endpoints_answer(world: World) -> None:
    cid = await _passed_with_condition(world, due=TODAY + timedelta(days=10))

    not_owner = await _post(world, world.editor, "editor", f"conditions/{cid}/clear", {"evidence": "x"})
    no_authority = await _post(world, world.manager, "manager", f"conditions/{cid}/waive", {"rationale": "Not needed"})

    assert (not_owner.status_code, _code(not_owner)) == (403, "not_condition_owner")
    assert (no_authority.status_code, _code(no_authority)) == (403, "decider_not_entitled")
    assert (await _stored(world, cid)).status == "open"
    cleared = await _post(world, world.owner, "editor", f"conditions/{cid}/clear", {"evidence": "Letter filed"})
    assert cleared.status_code == 200, cleared.text
    body = cleared.json()
    assert body["status"] == "cleared"
    assert body["can"] == {
        "clear": False,
        "clear_reason": "condition_not_open",
        "waive": False,
        "waive_reason": "missing_permission",
    }


async def test_a_role_alias_of_admin_counts_as_a_manager(world: World) -> None:
    """``owner`` and ``superuser`` are admin by alias; a compared role string would turn them away."""
    cid = await _passed_with_condition(world, due=TODAY + timedelta(days=10))
    async with world.factory() as s:
        company_owner = await add_user(s, "admin")
        await s.commit()

    r = await _post(world, company_owner, "owner", f"conditions/{cid}/clear", {"evidence": "Seen"})

    assert r.status_code == 200, r.text
    assert (await _stored(world, cid)).status == "cleared"


async def test_the_decider_waives_and_under_four_eyes_not_the_owner_of_that_area(world: World) -> None:
    cid = await _passed_with_condition(world, due=TODAY + timedelta(days=10))
    cost = (await areas(world))["cost_finance"]
    async with world.factory() as s:
        await GovernanceService(s).update_area(
            world.project_id, cost.id, changes={"deputy_user_id": world.decider}, actor_id=world.manager
        )
        await s.commit()
    own_area = (await _conditions(world, world.decider, "manager"))["items"][0]["can"]
    assert (own_area["waive"], own_area["waive_reason"]) == (False, "decider_is_area_owner")

    blocked = await _post(world, world.decider, "manager", f"conditions/{cid}/waive", {"rationale": "Not needed"})

    assert (blocked.status_code, _code(blocked)) == (403, "decider_is_area_owner")
    async with world.factory() as s:
        await GovernanceService(s).update_area(
            world.project_id, cost.id, changes={"deputy_user_id": None}, actor_id=world.manager
        )
        await s.commit()
    waived = await _post(world, world.decider, "manager", f"conditions/{cid}/waive", {"rationale": "Not needed"})
    assert waived.status_code == 200, waived.text
    assert waived.json()["status"] == "waived" and waived.json()["can"]["waive_reason"] == "condition_not_open"


async def test_a_further_condition_is_added_by_the_decider_only(world: World) -> None:
    await _passed_with_condition(world, due=None)
    g = await gate(world, G1)
    body = {"area_code": "risk", "text": "Update the risk register", "owner_user_id": str(world.owner)}

    refused = await _post(world, world.manager, "manager", f"gates/{g.id}/conditions", body)
    added = await _post(world, world.decider, "manager", f"gates/{g.id}/conditions", body)

    assert (refused.status_code, _code(refused)) == (403, "decider_not_entitled")
    assert added.status_code == 201, added.text
    assert added.json()["can"]["waive"] is True
    assert (await _conditions(world, world.editor, "editor"))["total"] == 2


# ── stop ──


async def test_a_stop_freezes_binding_documents_and_refuses_change_requests(world: World) -> None:
    g1 = await prepare_gate(world, G1)
    await decide(world, g1.id, "go")
    doc = (await documents(world))["business_case"]
    assert doc.status == "binding" and doc.read_only is False
    async with world.factory() as s:
        await add_revision(s, world.containers["business_case"], 2, "business_case-hash-2")
        await s.commit()
    g2 = await prepare_gate(world, G2)
    await decide(world, g2.id, "stop", rationale="Funding withdrawn")

    r = await _post(world, world.owner, "editor", f"documents/{doc.id}/change-requests", {"reason": "New cost plan"})

    assert (r.status_code, _code(r)) == (409, "project_stopped")
    frozen = (await documents(world))["business_case"]
    assert frozen.read_only is True and frozen.bound_content_hash == "business_case-hash-1"


# ── planning: the schedule owns the date ──


async def _plan(w: World, gate_id: uuid.UUID, body: dict, user: uuid.UUID | None = None, role: str = "manager"):
    async with client_as(w, user or w.manager, role) as c:
        return await c.patch(f"{project_url(w)}/gates/{gate_id}", json=body)


async def _findings(w: World, rule: str) -> list[dict]:
    async with client_as(w, w.manager, "manager") as c:
        items = (await c.get(f"{project_url(w)}/validation")).json()["items"]
    return [i for i in items if i["rule_id"].endswith(rule)]


async def test_a_gate_planned_before_the_gate_ahead_of_it_is_found_by_validation(world: World) -> None:
    g1, g2 = await gate(world, G1), await gate(world, G2)
    assert await _findings(world, "gate_date_after_previous") == []

    first = await _plan(world, g1.id, {"target_date": "2027-03-01"})
    second = await _plan(world, g2.id, {"target_date": "2027-02-01"})

    assert first.status_code == 200 and first.json()["target_date"] == "2027-03-01", first.text
    assert second.status_code == 200, second.text
    findings = await _findings(world, "gate_date_after_previous")
    assert [f["passed"] for f in findings] == [False]
    assert (await _plan(world, g2.id, {"target_date": "2027-04-01"})).status_code == 200
    assert [f["passed"] for f in await _findings(world, "gate_date_after_previous")] == [True]
    cleared = await _plan(world, g2.id, {"target_date": None})
    assert cleared.json()["target_date"] == ""


async def test_a_linked_gate_reads_its_date_from_the_schedule(world: World) -> None:
    from app.modules.schedule.models import Activity

    g1 = await gate(world, G1)
    await _plan(world, g1.id, {"target_date": "2027-03-01"})
    async with world.factory() as s:
        activity_id = await add_activity(s, world.project_id, "Brief approved", "2027-05-15")
        await s.commit()

    linked = await _plan(world, g1.id, {"schedule_activity_id": str(activity_id)})

    assert linked.status_code == 200, linked.text
    assert (linked.json()["schedule_activity_id"], linked.json()["target_date"]) == (str(activity_id), "2027-05-15")
    async with world.factory() as s:
        (await s.get(Activity, activity_id)).end_date = "2027-06-20"
        await s.commit()
    async with client_as(world, world.editor, "editor") as c:
        listed = (await c.get(f"{project_url(world)}/gates")).json()["items"]
        detail = (await c.get(f"{project_url(world)}/gates/{g1.id}")).json()["gate"]
        matrix = (await c.get(f"{project_url(world)}/matrix")).json()["gates"]
    assert {x["code"]: x["target_date"] for x in listed}[G1] == "2027-06-20"
    assert detail["target_date"] == "2027-06-20"
    assert {x["code"]: x["target_date"] for x in matrix}[G1] == "2027-06-20"
    own_date = await _plan(world, g1.id, {"target_date": "2027-01-01"})
    assert (own_date.status_code, _code(own_date)) == (422, "target_date_owned_by_schedule")
    unlinked = await _plan(world, g1.id, {"schedule_activity_id": None, "target_date": "2027-01-01"})
    assert (unlinked.json()["schedule_activity_id"], unlinked.json()["target_date"]) == (None, "2027-01-01")


async def test_planning_a_gate_is_a_management_act(world: World) -> None:
    g1 = await gate(world, G1)

    r = await _plan(world, g1.id, {"target_date": "2027-03-01"}, user=world.editor, role="editor")

    assert r.status_code == 403
    assert (await gate(world, G1)).target_date == ""


async def test_the_model_row_is_not_touched_by_reading_conditions(world: World) -> None:
    """A GET commits its session; nothing a read computes may land in a row."""
    cid = await _passed_with_condition(world, due=TODAY - timedelta(days=1))
    async with world.factory() as s:
        before = (
            await s.execute(select(GovernanceModel.updated_at).where(GovernanceModel.project_id == world.project_id))
        ).scalar_one()
    stored_before = (await _stored(world, cid)).updated_at

    await _conditions(world, world.decider, "manager")
    async with client_as(world, world.decider, "manager") as c:
        await c.get(f"{project_url(world)}/gates/{(await gate(world, G1)).id}")

    async with world.factory() as s:
        after = (
            await s.execute(select(GovernanceModel.updated_at).where(GovernanceModel.project_id == world.project_id))
        ).scalar_one()
    assert after == before
    assert (await _stored(world, cid)).updated_at == stored_before
