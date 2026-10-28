# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The staffing service against PostgreSQL: derived status, approval through governance, reminders, rule 4.

Each test builds its own throwaway database (``isolated_engine``), so commits,
row locks and the governance frame document behave as they do in production.
The approval tests go through a real gate decision and a real frame change
request; nothing sets a governance status by hand.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.project_governance.service import GovernanceService
from app.modules.staffing.errors import StaffingError
from app.modules.staffing.permissions import register_staffing_permissions
from app.modules.staffing.service import Actor, StaffingService
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import add_revision, decide, only_evidence, prepare_gate
from tests.pg.staffing_fixtures import (
    GATE,
    PERSONNEL_FRAME,
    admin,
    build_world,
    call,
    confirm,
    days,
    drop_frame_document,
    fill,
    hr,
    members,
    personnel_file,
    position,
    record,
    submittable_plan,
)

pytestmark = pytest.mark.asyncio


def _flag(flag: dict) -> dict:
    """A ``can`` flag without ``applies``: these tests are about whether and why, not about relevance."""
    return {k: v for k, v in flag.items() if k != "applies"}


@pytest_asyncio.fixture
async def factory():
    from app.modules.staffing.evidence import register_gate_evidence

    register_staffing_permissions()
    # Only this module's evidence answers: the other modules' providers would refuse a gate this test needs to pass.
    with only_evidence(register=register_gate_evidence):
        async with isolated_engine() as engine:
            yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _plan(w):
    from app.modules.staffing.models import StaffingPlan

    async with w.factory() as s:
        return (await s.execute(select(StaffingPlan).where(StaffingPlan.project_id == w.project_id))).scalar_one()


async def _approved_at_the_gate(w):
    """Submit a complete plan and pass the gate that makes the personnel frame document binding."""
    await submittable_plan(w, fill_key_roles=True)
    await call(w, "submit", w.manager)
    gate = await prepare_gate(w, GATE)
    await decide(w, gate.id, "go")
    return gate


async def test_a_confirmed_fill_makes_the_position_filled_and_ending_it_reopens_it(factory) -> None:
    w = await build_world(factory, governance=False)
    pid = await position(w, "site_manager")
    fid = await fill(w, pid, (await members(w))[0].id)

    views = {v["id"]: v for v in await call(w, "position_views")}
    assert views[str(pid)]["status"] == "open"

    await confirm(w, fid)
    views = {v["id"]: v for v in await call(w, "position_views")}
    assert views[str(pid)]["status"] == "filled"

    await call(w, "end_fill", fid, w.manager)
    views = {v["id"]: v for v in await call(w, "position_views")}
    assert views[str(pid)]["status"] == "open"


async def test_filled_cannot_be_set_by_hand(factory) -> None:
    w = await build_world(factory, governance=False)
    pid = await position(w, "site_manager")
    with pytest.raises(StaffingError) as err:
        await call(w, "set_position_status", pid, "filled", w.manager)
    assert err.value.code == "status_is_derived"


async def test_submission_refuses_an_incomplete_plan_and_lists_what_is_missing(factory, monkeypatch) -> None:
    w = await build_world(factory)
    await position(w, "site_manager")
    with pytest.raises(StaffingError) as err:
        await call(w, "submit", w.manager)
    codes = {v["code"] for v in err.value.violations or []}
    assert "key_role_missing" in codes
    assert (await _plan(w)).status == "draft"


async def test_a_plan_with_no_frame_document_to_carry_it_cannot_be_submitted(factory, monkeypatch) -> None:
    # A project with no gates at all is another story: test_staffing_without_gates_on_pg walks it by hand.
    # The model hosts staffing, but this project has no document row of that type: refused, no guess.
    rowless = await build_world(factory)
    await drop_frame_document(rowless)
    await submittable_plan(rowless)
    with pytest.raises(StaffingError) as err:
        await call(rowless, "submit", rowless.manager)
    assert (err.value.code, err.value.status_code) == ("frame_document_missing", 409)
    view = await call(rowless, "plan_view", Actor(rowless.manager, edit=True))
    assert _flag(view["can"]["submit"]) == {"allowed": False, "reason": "frame_document_missing"}

    # The shipped model names the host by tag and the project has the row: the plan goes to review.
    hosted = await build_world(factory)
    await submittable_plan(hosted)
    view = await call(hosted, "plan_view", Actor(hosted.manager, edit=True))
    assert _flag(view["can"]["submit"]) == {"allowed": True, "reason": None}
    assert _flag(view["can"]["return"]) == {"allowed": False, "reason": "plan_not_in_review"}
    assert (await call(hosted, "plan_view", Actor(hosted.editor)))["can"]["submit"]["reason"] == (
        "edit_permission_required"
    )
    await call(hosted, "submit", hosted.manager)
    plan = await _plan(hosted)
    assert plan.status == "in_review" and plan.governance_document_id is not None
    view = await call(hosted, "plan_view", Actor(hosted.manager, edit=True))
    assert view["can"]["return"]["allowed"] is True
    assert _flag(view["can"]["change_catalogue"]) == {"allowed": False, "reason": "plan_in_review"}


async def test_the_gate_decision_approves_the_submitted_plan_and_freezes_a_snapshot(factory, monkeypatch) -> None:
    from app.modules.staffing.events import handle_frame_document

    w = await build_world(factory)
    gate = await _approved_at_the_gate(w)
    plan = await _plan(w)
    assert plan.status == "in_review"

    payload = {"project_id": str(w.project_id), "document_id": str(plan.governance_document_id), "status": "binding"}
    assert await handle_frame_document(payload, session_factory=w.factory) is True
    plan = await _plan(w)
    assert plan.status == "binding"
    assert (plan.approval_source, plan.approved_by) == ("gate", w.decider)
    assert len(plan.bound_snapshot["positions"]) == 9
    async with w.factory() as s:
        doc = await GovernanceService(s).repo.get_document(w.project_id, plan.governance_document_id)
    assert (doc.doc_type, doc.status, doc.approved_gate_id) == (PERSONNEL_FRAME, "binding", gate.id)
    # Idempotent: the second delivery of the same event changes nothing.
    assert await handle_frame_document(payload, session_factory=w.factory) is False

    # An edit after binding opens a revision; the bound snapshot stays in force.
    await position(w, "scheduler")
    plan = await _plan(w)
    assert plan.status == "revising"
    assert len(plan.bound_snapshot["positions"]) == 9


async def test_a_missed_event_is_reconciled_on_read_and_an_old_decision_never_binds_a_new_revision(
    factory, monkeypatch
) -> None:
    w = await build_world(factory)
    await _approved_at_the_gate(w)
    # The subscriber never ran (another process, a restart): reading the plan catches up.
    view = await call(w, "plan_view")
    assert view["status"] == "binding"
    first_approval = (await _plan(w)).approved_at

    await position(w, "scheduler")
    await call(w, "submit", w.manager)
    # The document is still binding on the OLD gate decision; that is not an approval of this revision.
    view = await call(w, "plan_view")
    assert view["status"] == "in_review"
    assert len((await _plan(w)).bound_snapshot["positions"]) == 9

    plan = await _plan(w)
    async with w.factory() as s:
        await add_revision(s, w.containers[PERSONNEL_FRAME], 2, "staffing-revision-2")
        await s.commit()
    async with w.factory() as s:
        gov = GovernanceService(s)
        cr = await gov.create_change_request(
            w.project_id,
            plan.governance_document_id,
            reason="Scheduler added to the plan",
            impact="",
            proposed_revision_id=None,
            actor_id=w.owner,
            is_manager=True,
        )
        await gov.apply_change_decision(cr.id, decision="approved", decided_by=w.decider)
        await s.commit()
    view = await call(w, "plan_view")
    assert view["status"] == "binding"
    plan = await _plan(w)
    assert plan.approval_source == "change_request"
    assert plan.approved_at > first_approval
    assert len(plan.bound_snapshot["positions"]) == 10


async def test_in_review_locks_everything_the_reviewer_reads(factory, monkeypatch) -> None:
    w = await build_world(factory)
    ids = await submittable_plan(w)
    people = await members(w)
    spare = await fill(w, ids["site_manager"], people[2].id, "0.10")
    handovers = await call(w, "handover_views")
    proposed = next(v for v in await call(w, "position_views") if v["id"] == str(ids["project_manager"]))["fills"][0]
    await call(w, "submit", w.manager)

    async def refused(fn, *args):
        with pytest.raises(StaffingError) as err:
            await call(w, fn, *args)
        assert (err.value.code, err.value.status_code) == ("plan_in_review", 409), fn

    await refused("patch_plan", {"commissioning_date": days(5)}, w.manager)
    await refused("delete_handover", handovers[0]["id"], w.manager)
    await refused("update_handover", handovers[0]["id"], {"overlap_days": 0}, w.manager)
    await refused(
        "create_handover",
        {"from_fill_id": proposed["id"], "to_position_id": ids["site_manager"], "overlap_days": 5, "scope": ""},
        w.manager,
    )
    await refused("confirm_fill", spare, admin(w))
    await refused("delete_fill", spare, w.manager)
    await refused(
        "create_fill", ids["site_manager"], {"roster_member_id": people[3].id, "from_date": days(1)}, w.manager
    )
    assert len(await call(w, "handover_views")) == len(handovers)
    assert (await _plan(w)).commissioning_date != days(5)

    await call(w, "return_plan", w.manager)
    await call(w, "delete_fill", spare, w.manager)


async def test_changing_the_plan_frame_of_a_binding_plan_opens_a_revision(factory, monkeypatch) -> None:
    w = await build_world(factory)
    await _approved_at_the_gate(w)
    assert (await call(w, "plan_view"))["status"] == "binding"
    await call(w, "patch_plan", {"commissioning_date": days(700)}, w.manager)
    plan = await _plan(w)
    assert plan.status == "revising" and plan.commissioning_date == days(700)


async def test_an_expiry_alert_notifies_only_rule_10_recipients_and_writes_nothing_to_the_file(factory) -> None:
    from app.modules.staffing.events import handle_expiry_alert
    from app.modules.staffing.models import PersonnelDocument
    from app.modules.teams.models import RosterMember

    w = await build_world(factory)
    person = (await members(w))[0]
    async with w.factory() as s:
        (await s.get(RosterMember, person.id)).user_id = w.editor
        await s.commit()
    pid = await position(w, "site_manager", owner_user_id=w.owner)
    await confirm(w, await fill(w, pid, person.id))
    file_id = await personnel_file(w, person.id, actor=hr(w.owner), nationality_required=True)
    doc = await record(w, file_id, "work_permit", days(20), actor=hr(w.owner))
    cred = doc.credential_id

    async with w.factory() as s:
        recipients = await StaffingService(s).reminder_recipients(cred)
    assert len(recipients) == 1
    _doc, users = recipients[0]
    assert users == {w.owner, w.editor}

    async with w.factory() as s:
        before = (
            await s.execute(select(PersonnelDocument).where(PersonnelDocument.credential_id == cred))
        ).scalar_one()
        snapshot = (before.updated_at, before.verified_at, before.number_last4)
    sent = await handle_expiry_alert(
        {"credential_id": str(cred), "valid_until": days(20).isoformat(), "status": "expiring_soon"},
        session_factory=w.factory,
    )
    assert sent == len(users)
    async with w.factory() as s:
        after = (await s.execute(select(PersonnelDocument).where(PersonnelDocument.credential_id == cred))).scalar_one()
        assert (after.updated_at, after.verified_at, after.number_last4) == snapshot


async def test_the_credential_sweep_fires_the_alert_for_a_credential_nobody_edited(factory) -> None:
    from app.modules.credentials.models import Credential
    from app.modules.staffing.sweep import credential_expiry_sweep

    w = await build_world(factory, governance=False)
    person = (await members(w))[0]
    file_id = await personnel_file(w, person.id, nationality_required=True)
    cred = (await record(w, file_id, "work_permit", days(10))).credential_id
    async with w.factory() as s:
        (await s.get(Credential, cred)).status = "active"
        await s.commit()
    assert await credential_expiry_sweep(session_factory=w.factory) >= 1
    async with w.factory() as s:
        assert (await s.get(Credential, cred)).status == "expiring_soon"
    # Idempotent: nothing drifted, nothing updated.
    assert await credential_expiry_sweep(session_factory=w.factory) == 0


async def test_rule_4_holds_when_two_confirms_race_for_the_same_person(factory) -> None:
    w = await build_world(factory, governance=False)
    person = (await members(w))[0]
    a = await fill(w, await position(w, "site_manager"), person.id, "0.6")
    b = await fill(w, await position(w, "hse_manager"), person.id, "0.6")

    async def one(fill_id):
        try:
            await confirm(w, fill_id)
            return "ok"
        except StaffingError as exc:
            return exc.code

    outcomes = sorted(await asyncio.gather(one(a), one(b)))
    assert outcomes == ["ok", "person_overallocated"]
