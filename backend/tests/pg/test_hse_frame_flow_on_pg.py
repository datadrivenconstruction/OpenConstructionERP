# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The HSE frame's rules against PostgreSQL, through the service.

One walk over a German project: the facts decide the duties, the register comes
from the catalogue, nothing is "met" by silence, submitting is refused with the
list of blockers, the coordinator roles and the notice lift them, a second
person approves, and a binding frame is closed to edits until it is revised.
Each refusal is asserted with the error code the API returns.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.modules.hse_frame import schemas as s
from app.modules.hse_frame.errors import HseFrameError
from app.modules.hse_frame.models import HseItem
from app.modules.hse_frame.service import HseFrameService
from tests.pg.governance_fixtures import add_project, add_user

pytestmark = pytest.mark.asyncio


async def _german_project(session, manager: uuid.UUID, members: list[uuid.UUID]) -> uuid.UUID:
    from app.modules.projects.models import Project

    pid = await add_project(session, manager, members)
    project = await session.get(Project, pid)
    project.country_code = "DE"
    await session.flush()
    return pid


async def _refused(awaitable) -> HseFrameError:
    with pytest.raises(HseFrameError) as caught:
        await awaitable
    return caught.value


async def _frame(session):
    manager = await add_user(session, "manager")
    approver = await add_user(session, "manager")
    pid = await _german_project(session, manager, [approver])
    svc = HseFrameService(session)
    await svc.ensure_frame(pid, manager)
    await svc.pin_catalogue(pid, None, "shipped", "de", None, manager)
    return svc, pid, manager, approver


async def test_facts_decide_duties_and_silence_is_never_met(pg_session) -> None:
    svc, pid, manager, _approver = await _frame(pg_session)
    today = date.today()

    # No facts yet: every duty is undecided, not absent, and no criterion is met.
    before = await svc.readiness(pid, today)
    assert all(v is None for v in before["duties"].values()), before["duties"]
    assert not [i for i in before["items"] if i["state"] == "met"]

    await svc.patch_frame(
        pid,
        s.FramePatch(
            planned_start=today + timedelta(days=60),
            duration_working_days=120,
            peak_workers=40,
            person_days=4000,
            employers_count=3,
            hazardous_work_codes=["excavation_deep"],
            hazardous_works_assessed=True,
        ),
        manager,
    )
    after = await svc.readiness(pid, today)
    assert after["duties"]["coordinator"] is True
    assert after["duties"]["advance_notice"] is True

    # A hazardous work the catalogue does not know is refused, not stored.
    refused = await _refused(svc.patch_frame(pid, s.FramePatch(hazardous_work_codes=["no_such_work"]), manager))
    assert (refused.code, refused.status_code) == ("unknown_hazardous_work", 422)

    # Few workers and one employer lift the duties again.
    small = await svc.patch_frame(
        pid,
        s.FramePatch(duration_working_days=10, peak_workers=3, person_days=30, employers_count=1),
        manager,
    )
    assert small.employers_count == 1
    assert (await svc.readiness(pid, today))["duties"]["coordinator"] is False


async def test_register_roles_review_and_the_closed_frame(pg_session) -> None:
    svc, pid, manager, approver = await _frame(pg_session)
    today = date.today()
    await svc.patch_frame(
        pid,
        s.FramePatch(
            planned_start=today + timedelta(days=90),
            duration_working_days=200,
            peak_workers=60,
            person_days=9000,
            employers_count=4,
            hazardous_works_assessed=True,
        ),
        manager,
    )

    created = await svc.apply_templates(pid, manager)
    assert created["created"] > 0
    assert (await svc.apply_templates(pid, manager))["created"] == 0
    items = await svc.repo.list(HseItem, pid)
    template_row = next(i for i in items if i.template_code and i.obligation == "mandatory")
    assert (await _refused(svc.delete_item(pid, template_row.id))).code == "template_item_not_deletable"

    # Submitting lists every blocker at once.
    blocked = await _refused(svc.submit(pid, manager, today))
    assert (blocked.code, blocked.status_code) == ("frame_incomplete", 422)
    codes = {v["code"] for v in blocked.violations}
    assert "coordinator_missing" in codes

    # A manual row on an unknown topic is refused; a known one is accepted and closes with a note.
    bad = await _refused(svc.create_item(pid, s.ItemCreate(topic="no_such_topic", title="x"), manager))
    assert bad.status_code == 422
    manual = await svc.create_item(
        pid, s.ItemCreate(topic="hse_requirements", title="Site rules for deliveries", responsible_party="GC"), manager
    )
    future = await _refused(
        svc.meet_item(pid, manual.id, s.ItemMeet(met_on=today + timedelta(days=2), evidence_note="x"))
    )
    assert future.code == "date_in_future"
    # The author cannot waive their own mandatory duty.
    own = await svc.create_item(pid, s.ItemCreate(topic="hse_requirements", title="Own duty"), manager)
    assert (await _refused(svc.waive_item(pid, own.id, s.ItemWaive(reason="not needed"), manager))).code == (
        "waiver_by_author"
    )
    waived = await svc.waive_item(pid, own.id, s.ItemWaive(reason="Covered by the framework contract"), approver)
    assert waived.status == "waived"
    reopened = await svc.reopen_item(pid, own.id)
    assert reopened.status == "open" and reopened.waive_reason == ""

    # Every mandatory row done, both coordinators in force, notice sent and plan issued.
    for item in await svc.repo.list(HseItem, pid):
        if item.obligation == "mandatory" and item.status not in ("met", "waived", "not_applicable"):
            await svc.meet_item(pid, item.id, s.ItemMeet(met_on=today, evidence_note="Filed"))
    for code in ("safety_coordinator_design", "safety_coordinator_execution"):
        await svc.create_role(
            pid,
            s.RoleCreate(
                role_code=code,
                person_name="Test Coordinator",
                status="appointed",
                appointed_on=today - timedelta(days=5),
                qualification="Qualified",
                qualification_valid_until=today + timedelta(days=400),
            ),
            manager,
        )
    await svc.patch_frame(
        pid,
        s.FramePatch(
            advance_notice_sent_on=today - timedelta(days=3),
            advance_notice_reference="VA-1",
            plan_status="issued",
            later_works_status="complete",
        ),
        manager,
    )
    readiness = await svc.readiness(pid, today)
    by_code = {i["code"]: i["state"] for i in readiness["items"]}
    assert by_code["safety_coordination_appointed"] == "met"

    submitted = await svc.submit(pid, manager, today)
    assert submitted.state == "in_review"
    assert (await _refused(svc.approve(pid, manager))).code == "approver_is_submitter"
    approved = await svc.approve(pid, approver)
    assert approved.state == "binding" and approved.approved_by == approver

    # A binding frame cannot be re-pinned and only a revision opens it again.
    pinned = await _refused(svc.pin_catalogue(pid, None, "shipped", "neutral", None, manager))
    assert (pinned.code, pinned.status_code) == ("frame_not_editable", 409)
    for closed in (
        svc.create_item(pid, s.ItemCreate(topic="hse_requirements", title="Late row"), manager),
        svc.meet_item(pid, template_row.id, s.ItemMeet()),
        svc.patch_frame(pid, s.FramePatch(notes="late"), manager),
        svc.delete_role(pid, uuid.uuid4()),
    ):
        assert (await _refused(closed)).code == "frame_not_editable"
    again = await _refused(svc.submit(pid, manager, today))
    assert again.code == "invalid_transition"
    revised = await svc.revise(pid, manager, "Scope of works changed")
    assert revised.state == "revising" and revised.approved_by is None
    assert (await _refused(svc.revise(pid, manager))).code == "invalid_transition"
    # A revising frame is editable again and goes through review once more.
    await svc.patch_frame(pid, s.FramePatch(notes="Second revision"), manager)
    assert (await svc.submit(pid, manager, today)).state == "in_review"


async def test_a_single_user_installation_can_approve_when_four_eyes_is_off(pg_session) -> None:
    svc, pid, manager, _approver = await _frame(pg_session)
    today = date.today()
    await svc.patch_frame(
        pid, s.FramePatch(employers_count=1, peak_workers=2, duration_working_days=5, person_days=10), manager
    )

    async def off(_project_id) -> bool:
        return False

    svc._four_eyes = off  # the project setting, as governance states it
    await svc.patch_frame(pid, s.FramePatch(hazardous_works_assessed=True), manager)
    for item in await svc.repo.list(HseItem, pid):
        if item.obligation == "mandatory":
            await svc.meet_item(pid, item.id, s.ItemMeet(met_on=today))
    await svc.submit(pid, manager, today)
    assert (await svc.approve(pid, manager)).state == "binding"


async def test_an_item_of_another_project_is_not_found(pg_session) -> None:
    svc, pid, manager, _approver = await _frame(pg_session)
    other_owner = await add_user(pg_session, "manager")
    other = await _german_project(pg_session, other_owner, [])
    foreign = await svc.create_item(other, s.ItemCreate(topic="hse_requirements", title="Other project"), other_owner)
    assert (await _refused(svc.item(pid, foreign.id))).status_code == 404
    assert (await _refused(svc.meet_item(pid, foreign.id, s.ItemMeet()))).status_code == 404
    assert (
        await _refused(svc.add_link(pid, foreign.id, s.LinkCreate(link_kind="hse_ptw", link_id="x"), manager))
    ).code == ("item_not_found")
