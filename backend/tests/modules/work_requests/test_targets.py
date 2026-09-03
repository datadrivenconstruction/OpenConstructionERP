# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Turnaround targets: working days from acceptance, what that makes late,
and the bell that is about the DEPARTMENT'S promise rather than the
requester's date."""

from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_requests import notifying, service
from tests._pg import transactional_session
from tests.modules.work_requests._helpers import day, make_project, make_user, raise_request, seeded
from tests.modules.work_requests.conftest import API_BASE, API_MANAGER


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


def test_working_days_step_over_the_weekend() -> None:
    friday = date(2026, 9, 4)
    assert friday.strftime("%A") == "Friday"
    # Three WORKING days from Friday is Wednesday, not Monday: the
    # department does not work the weekend and is not judged as if it did.
    assert service.add_working_days(friday, 1) == date(2026, 9, 7)
    assert service.add_working_days(friday, 3) == date(2026, 9, 9)
    assert service.add_working_days(friday, 5) == date(2026, 9, 11)
    assert service.add_working_days(friday, 0) == friday
    # Starting ON a Saturday still lands on working days only.
    assert service.add_working_days(date(2026, 9, 5), 1) == date(2026, 9, 7)


@pytest.mark.asyncio
async def test_a_target_needs_both_a_number_and_an_acceptance(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    dept = (await seeded(session))["workshop"]
    req = await raise_request(session, project=proj, user=pm)

    assert service.lateness(req, dept) == (None, None, False), "no target, no lateness"
    await service.update_department(session, dept, {"target_days": 3})
    assert req.accepted_at is None
    assert service.lateness(req, dept) == (None, None, False), "nobody has accepted it yet, so it cannot be late"

    req.accepted_at = "2026-09-04"  # a Friday
    target, days_late, is_late = service.lateness(req, dept, today=date(2026, 9, 9))
    assert target == "2026-09-09" and days_late == 0 and is_late is False
    target, days_late, is_late = service.lateness(req, dept, today=date(2026, 9, 11))
    assert target == "2026-09-09" and days_late == 2 and is_late is True


@pytest.mark.asyncio
async def test_the_clock_starts_when_the_department_takes_it_on(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    await seeded(session)
    accepted = await raise_request(session, project=proj, user=pm, title="MSB-01 main switchboard")
    boarded = await raise_request(session, project=proj, user=pm, title="MSB-02 main switchboard")

    await service.update_request(session, accepted, {"status": "accepted"}, user_id=str(pm.id), can_manage=True)
    assert accepted.accepted_at == day(0)

    # A board move skips the accepted state - the clock must still start.
    await service.move_stage(session, boarded, "build", user_id=str(pm.id), can_manage=False)
    assert boarded.accepted_at == day(0)

    first = accepted.accepted_at
    await service.update_request(session, accepted, {"status": "in_progress"}, user_id=str(pm.id), can_manage=True)
    assert accepted.accepted_at == first, "written once - a later move never restarts the clock"


@pytest.mark.asyncio
async def test_the_payload_and_the_summary_agree_about_late(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    dept = (await seeded(session))["workshop"]
    await service.update_department(session, dept, {"target_days": 1})
    late_one = await raise_request(session, project=proj, user=pm, title="MSB-01 main switchboard")
    on_time = await raise_request(session, project=proj, user=pm, title="MSB-02 main switchboard")
    for req in (late_one, on_time):
        await service.update_request(session, req, {"status": "accepted"}, user_id=str(pm.id), can_manage=True)
    late_one.accepted_at = day(-21)  # three weeks of working days ago, whatever weekday today is
    await session.flush()

    p = await service.payload(session, late_one)
    assert p["target_days"] == 1
    assert p["target_date"] == service.add_working_days(date.fromisoformat(day(-21)), 1).isoformat()
    assert p["days_late"] > 0 and p["is_late"] is True
    assert p["accepted_at"] == day(-21)

    fine = await service.payload(session, on_time)
    assert fine["is_late"] is False and fine["days_late"] == 0

    summary = await service.summary(session, project_ids=None, project_id=proj.id)
    workshop = next(d for d in summary["departments"] if d["key"] == "workshop")
    assert workshop["late"] == 1 and workshop["target_days"] == 1
    drafting = next(d for d in summary["departments"] if d["key"] == "drafting")
    assert drafting["late"] == 0 and drafting["target_days"] is None


@pytest.mark.asyncio
async def test_a_finished_request_stops_being_late(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    dept = (await seeded(session))["workshop"]
    await service.update_department(session, dept, {"target_days": 1})
    req = await raise_request(session, project=proj, user=pm)
    await service.move_stage(session, req, "build", user_id=str(pm.id), can_manage=False)
    req.accepted_at = day(-21)
    await session.flush()
    assert (await service.payload(session, req))["is_late"] is True

    await service.move_stage(session, req, "delivered", user_id=str(pm.id), can_manage=False)
    await service.update_request(session, req, {"status": "closed"}, user_id=str(pm.id), can_manage=True)
    p = await service.payload(session, req)
    assert p["is_late"] is False, "a closed request is not still running late"
    assert p["days_late"] is not None and p["days_late"] > 0, "but the record of how late it finished remains"


@pytest.mark.asyncio
async def test_the_sweep_rings_late_separately_and_once(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    dept = (await seeded(session))["workshop"]
    await service.update_department(session, dept, {"target_days": 1})
    req = await raise_request(session, project=proj, user=pm, due_date=day(-1))
    await service.update_request(session, req, {"status": "accepted"}, user_id=str(pm.id), can_manage=True)
    req.accepted_at = day(-21)
    await session.flush()

    first = await notifying.sweep(session, project_ids=None)
    assert sorted(first["detail"]) == sorted([f"{req.reference} late", f"{req.reference} overdue"]), (
        "late and overdue are two different facts and ring separately"
    )
    again = await notifying.sweep(session, project_ids=None)
    assert again["published"] == 0, "each reason rings once per request per day"

    no_target = await raise_request(session, project=proj, user=pm, department="drafting", request_type="drafting_only")
    await service.update_request(session, no_target, {"status": "accepted"}, user_id=str(pm.id), can_manage=True)
    assert (await notifying.sweep(session, project_ids=None))["published"] == 0


@pytest.mark.asyncio
async def test_target_days_over_http(api) -> None:
    client, pid, state = api
    state["payload"] = dict(API_MANAGER)
    assert (await client.get(f"{API_BASE}/departments")).status_code == 200, "first read plants the seeds"
    r = await client.patch(f"{API_BASE}/departments/workshop", json={"target_days": 5})
    assert r.status_code == 200 and r.json()["target_days"] == 5

    listed = await client.get(f"{API_BASE}/departments")
    assert next(d for d in listed.json()["items"] if d["key"] == "workshop")["target_days"] == 5

    made = await client.post(
        f"{API_BASE}/requests",
        json={"project_id": pid, "department": "workshop", "request_type": "switchboard", "title": "MSB-01"},
    )
    assert made.json()["target_days"] == 5 and made.json()["target_date"] is None

    accepted = await client.patch(f"{API_BASE}/requests/{made.json()['id']}", json={"status": "accepted"})
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["accepted_at"] == date.today().isoformat()
    assert body["target_date"] == service.add_working_days(date.today(), 5).isoformat()
    assert body["is_late"] is False and body["days_late"] == 0

    cleared = await client.patch(f"{API_BASE}/departments/workshop", json={"target_days": None})
    assert cleared.status_code == 200 and cleared.json()["target_days"] is None
