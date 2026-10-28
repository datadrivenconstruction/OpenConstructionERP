# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Who may reach a personnel file, what leaves it, and how it ends, against PostgreSQL.

These pin the privacy and authorisation defects of the independent review:
nobody grants themself a relationship to a person, a personnel document is
not readable through the credentials register, a file cannot be erased by
ending it in the past, and a document belongs to exactly one person.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.staffing.errors import StaffingError
from app.modules.staffing.permissions import register_staffing_permissions
from app.modules.staffing.service import Actor, StaffingService
from tests._pg import isolated_engine
from tests.pg.staffing_fixtures import (
    START,
    admin,
    build_world,
    call,
    confirm,
    days,
    fill,
    hr,
    members,
    personnel_file,
    position,
    record,
    staffed,
)

pytestmark = pytest.mark.asyncio


def _flag(flag: dict) -> dict:
    """A ``can`` flag without ``applies``: these tests are about whether and why, not about relevance."""
    return {k: v for k, v in flag.items() if k != "applies"}


@pytest_asyncio.fixture
async def factory():
    register_staffing_permissions()
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _refused(awaitable) -> StaffingError:
    with pytest.raises(StaffingError) as err:
        await awaitable
    return err.value


async def _row(w, model, row_id):
    async with w.factory() as s:
        return await s.get(model, row_id)


# ── finding 1: nobody grants themself the relationship ─────────────────────


async def test_an_editor_cannot_name_a_line_manager_on_create_or_update(factory) -> None:
    from app.modules.staffing.models import StaffingPosition

    w = await build_world(factory, governance=False)
    data = {"role_code": "site_manager", "phase": "execution", "entry_date": START, "owner_user_id": w.editor}
    err = await _refused(call(w, "create_position", data, hr(w.editor)))
    assert (err.code, err.status_code) == ("owner_assignment_forbidden", 403)

    pid = await position(w, "site_manager", owner_user_id=None)
    err = await _refused(call(w, "update_position", pid, {"owner_user_id": w.editor}, hr(w.editor)))
    assert (err.code, err.status_code) == ("owner_assignment_forbidden", 403)
    assert (await _row(w, StaffingPosition, pid)).owner_user_id is None

    # The other fields stay editable for the same caller.
    await call(w, "update_position", pid, {"title": "Site lead"}, hr(w.editor))
    # With the assignment permission the owner is set, and audited.
    await call(w, "update_position", pid, {"owner_user_id": w.owner}, admin(w))
    assert (await _row(w, StaffingPosition, pid)).owner_user_id == w.owner


async def test_a_line_manager_must_be_a_member_of_the_project(factory) -> None:
    w = await build_world(factory, governance=False)
    data = {"role_code": "site_manager", "phase": "execution", "entry_date": START, "owner_user_id": w.outsider}
    err = await _refused(call(w, "create_position", data, admin(w)))
    assert (err.code, err.status_code) == ("owner_not_project_member", 422)


async def test_a_proposed_fill_is_no_relationship_and_the_owner_cannot_confirm_their_own(factory) -> None:
    w = await build_world(factory, governance=False)
    person = (await members(w))[0]
    file_id = await personnel_file(w, person.id)
    pid = await position(w, "site_manager", owner_user_id=w.owner)
    fid = await fill(w, pid, person.id, "0.50")

    err = await _refused(call(w, "open_file", file_id, hr(w.owner)))
    assert (err.code, err.status_code) == ("no_relationship_to_person", 403)

    # The line manager confirming a fill on their own position would grant themself the file.
    err = await _refused(call(w, "confirm_fill", fid, hr(w.owner)))
    assert (err.code, err.status_code) == ("owner_cannot_confirm_own_fill", 403)
    await _refused(call(w, "open_file", file_id, hr(w.owner)))

    await call(w, "confirm_fill", fid, hr(w.decider))
    await call(w, "open_file", file_id, hr(w.owner))


async def test_every_permission_without_a_relationship_opens_nothing(factory) -> None:
    w = await build_world(factory, governance=False)
    person = (await members(w))[0]
    file_id = await personnel_file(w, person.id)
    everything = Actor(
        w.decider, personnel_read=True, personnel_edit=True, personnel_erase=True, assign_owner=True, manage=True
    )
    err = await _refused(call(w, "open_file", file_id, everything))
    assert err.code == "no_relationship_to_person"
    listed = {f["id"]: f for f in await call(w, "file_list", everything)}
    assert _flag(listed[str(file_id)]["can"]["open"]) == {"allowed": False, "reason": "no_relationship_to_person"}
    assert listed[str(file_id)]["can_open"] is False
    mine = {f["id"]: f for f in await call(w, "file_list", admin(w))}
    assert _flag(mine[str(file_id)]["can"]["open"]) == {"allowed": True, "reason": None}


async def test_a_file_is_created_only_by_someone_related_to_the_person(factory) -> None:
    w = await build_world(factory, governance=False)
    person = (await members(w))[0]
    err = await _refused(call(w, "create_file", {"roster_member_id": person.id}, admin(w)))
    assert err.code == "no_relationship_to_person"
    await staffed(w, person.id)
    await call(w, "create_file", {"roster_member_id": person.id}, admin(w))


# ── finding 2: personnel documents do not leave through credentials ────────


async def test_a_personnel_document_is_invisible_in_the_credentials_register(factory) -> None:
    from app.modules.credentials.models import Credential
    from app.modules.credentials.schemas import CredentialCreate, CredentialUpdate
    from app.modules.credentials.service import CredentialService, RequirementService

    w = await build_world(factory, governance=False)
    person = (await members(w))[0]
    file_id = await personnel_file(w, person.id, nationality_required=True)
    doc = await record(w, file_id, "work_permit", days(20), number_last4="4821")
    health = await record(w, file_id, "occupational_health_certificate", days(200), fit_for_role="yes")
    induction = await record(w, file_id, "site_induction", days(300))

    cred = await _row(w, Credential, doc.credential_id)
    assert cred.credential_type == "work_permit"
    assert (cred.identifier, cred.notes, cred.metadata_) == (None, "", {})
    # Finding 18: the reminder window is the catalogue's, not the register default.
    assert cred.notify_days_before == 60

    async with w.factory() as s:
        svc = CredentialService(s)
        listed = {c.id for c in await svc.list_credentials(w.project_id)}
        expiring = {c.id for c in await svc.list_expiring_soon(w.project_id)}
        summary = await svc.summarise(w.project_id)
        report = await RequirementService(s).build_compliance_report(w.project_id)
        for hidden in (doc.credential_id, health.credential_id):
            with pytest.raises(HTTPException) as err:
                await svc.get_credential_for_caller(hidden, actor_id=w.manager)
            assert err.value.status_code == 404
        # A site induction is an ordinary register entry and stays visible.
        assert (await svc.get_credential_for_caller(induction.credential_id, actor_id=w.manager)).id
    assert listed == {induction.credential_id}
    assert expiring == set()
    assert summary.total == 1
    assert report.holder_count == 1

    async with w.factory() as s:
        svc = CredentialService(s)
        body = CredentialCreate(project_id=w.project_id, holder_name="Somebody", credential_type="identity_document")
        with pytest.raises(HTTPException) as err:
            await svc.create_credential(body, user_id=str(w.manager))
        assert err.value.status_code == 400
        # An open credential cannot be turned into a closed one to hide a number in it.
        with pytest.raises(HTTPException) as err:
            await svc.update_credential(
                induction.credential_id, CredentialUpdate(credential_type="visa"), user_id=str(w.manager)
            )
        assert err.value.status_code == 400


async def test_the_compliance_matrix_shows_document_states_only_to_who_may_open_the_file(factory) -> None:
    w = await build_world(factory, governance=False)
    first, second = (await members(w))[:2]
    file_id = await personnel_file(w, first.id, nationality_required=True)
    await record(w, file_id, "work_permit", days(20), number_last4="4821")
    await record(w, file_id, "occupational_health_certificate", days(200), fit_for_role="yes")
    # The second person reports to somebody else.
    theirs = await position(w, "site_manager", owner_user_id=w.owner)
    await confirm(w, await fill(w, theirs, second.id))

    async with w.factory() as s:
        catalogue = await StaffingService(s).catalogue_for(await StaffingService(s).require_plan(w.project_id))
    special = {k.code for k in catalogue.document_kinds if k.special_category}
    assert "occupational_health_certificate" in special

    # A plain reader of the plan: names and the cleared flag as on the plan, and not one document state.
    seen = await call(w, "compliance_matrix", Actor(w.editor))
    assert len(seen["items"]) == 2
    for row in seen["items"]:
        assert row["cells"] == {} and row["file_id"] is None
        assert _flag(row["can"]["see_documents"]) == {"allowed": False, "reason": "no_relationship_to_person"}
    assert seen["document_kinds"] == []
    # Two people are too few to count: any number would be a statement about one of them.
    assert seen["summary"] == [] and seen["summary_min_group"] == 5

    # Every permission and no relationship: the same nothing.
    stranger = Actor(w.decider, personnel_read=True, personnel_edit=True, personnel_erase=True, edit=True)
    assert all(row["cells"] == {} for row in (await call(w, "compliance_matrix", stranger))["items"])

    # The line manager of the first person sees that person's cells, health included, and not the other's.
    mine = await call(w, "compliance_matrix", hr(w.manager))
    rows = {row["roster_member_id"]: row for row in mine["items"]}
    assert rows[str(first.id)]["cells"]["work_permit"]["state"] == "expiring"
    assert rows[str(first.id)]["cells"]["occupational_health_certificate"]["state"] == "valid"
    assert rows[str(first.id)]["file_id"] == str(file_id)
    assert rows[str(second.id)]["cells"] == {}
    # Nothing to subtract the visible row from: the summary counts the withheld people only, and they are too few.
    assert mine["summary"] == []

    # The validation findings follow the same rule: a finding about a person's documents is that person's file.
    async def failing(actor) -> tuple[set[str], int]:
        from app.modules.staffing.validators import DocumentsNotExpiredOnStart, RequiredDocumentsPresent

        data = await call(w, "validation_payload", actor)
        refs = set(RequiredDocumentsPresent().refs(data)) | set(DocumentsNotExpiredOnStart().refs(data))
        return refs, data["restricted_people"]

    assert await failing(Actor(w.editor)) == (set(), 2)
    assert await failing(None) == (set(), 2)
    assert await failing(hr(w.manager)) == ({str(first.id)}, 1)

    # The export prints the same matrix: no state next to a name the reader may not open.
    from app.modules.staffing import export as ex

    doc = ex.compliance_document(seen, catalogue=catalogue, project_name="P", locale="en")
    assert all(len(r) == 2 for r in doc.rows)

    # Who has no file yet, and who may open one for them.
    candidates = {
        c["roster_member_id"]: _flag(c["can"]["create_file"]) for c in await call(w, "file_candidates", hr(w.manager))
    }
    assert candidates == {str(second.id): {"allowed": False, "reason": "no_relationship_to_person"}}
    assert (await call(w, "file_candidates", hr(w.owner)))[0]["can"]["create_file"]["allowed"] is True


# ── finding 3: ending is not erasure ───────────────────────────────────────


async def test_a_file_ends_today_once_and_a_second_end_changes_nothing(factory) -> None:
    from app.modules.staffing.models import PersonnelFile

    w = await build_world(factory, governance=False)
    person = (await members(w))[0]
    file_id = await personnel_file(w, person.id)
    await call(w, "end_file", file_id, admin(w))
    ended = await _row(w, PersonnelFile, file_id)
    assert ended.status == "ended" and ended.ended_on == date.today()
    assert ended.retention_due_at > date.today() + timedelta(days=700)

    err = await _refused(call(w, "end_file", file_id, admin(w)))
    assert (err.code, err.status_code) == ("file_not_active", 409)
    again = await _row(w, PersonnelFile, file_id)
    assert (again.ended_on, again.retention_due_at, again.updated_at) == (
        ended.ended_on,
        ended.retention_due_at,
        ended.updated_at,
    )


async def test_the_sweep_applies_the_computed_date_and_the_action_of_the_rule(factory) -> None:
    from app.modules.credentials.models import Credential
    from app.modules.staffing.models import PersonnelFile, PositionFill, TravelRecord
    from app.modules.staffing.sweep import staffing_retention_sweep

    w = await build_world(factory, governance=False)
    people = await members(w)
    pid = await position(w, "site_supervisor_civil", headcount=2, fte="0.50")
    fills = [await fill(w, pid, people[i].id, "0.50") for i in (0, 1)]
    for f in fills:
        await confirm(w, f)
    files = [await personnel_file(w, people[i].id) for i in (0, 1)]
    doc = await record(w, files[0], "employment_contract")
    travel = {"kind": "mobilisation", "depart_date": days(3), "cost": "120.00", "currency": "EUR"}
    await call(w, "create_travel", files[0], travel, admin(w))
    for f in files:
        await call(w, "end_file", f, admin(w))
    await call(w, "hold_file", files[1], "Pending dispute over overtime.", admin(w))
    due = (await _row(w, PersonnelFile, files[0])).retention_due_at

    # The day before the computed date nothing is due.
    assert await staffing_retention_sweep(session_factory=w.factory, today=due - timedelta(days=1)) == 0
    assert await staffing_retention_sweep(session_factory=w.factory, today=due) == 1
    async with w.factory() as s:
        # The neutral rule says delete: the file, its documents and travel are gone, the credential with them.
        assert await s.get(PersonnelFile, files[0]) is None
        assert await s.get(Credential, doc.credential_id) is None
        assert (await s.execute(select(TravelRecord).where(TravelRecord.personnel_file_id == files[0]))).first() is None
        assert (await s.get(PositionFill, fills[0])).roster_member_id is None
        held = await s.get(PersonnelFile, files[1])
        assert held.status == "retention_hold" and held.roster_member_id == people[1].id
        assert (await s.get(PositionFill, fills[1])).roster_member_id == people[1].id
    assert await staffing_retention_sweep(session_factory=w.factory, today=due) == 0


async def test_the_sweep_rechecks_a_running_legal_duty_before_it_removes_anything(factory) -> None:
    from app.modules.staffing.models import PersonnelFile
    from app.modules.staffing.sweep import staffing_retention_sweep

    w = await build_world(factory, catalogue_id="us", governance=False)
    person = (await members(w))[0]
    file_id = await personnel_file(w, person.id)
    await record(w, file_id, "right_to_work_check")
    await call(w, "end_file", file_id, admin(w))
    due = (await _row(w, PersonnelFile, file_id)).retention_due_at
    # A stale, too-early date (a duty added after the file ended): the sweep must not trust the column.
    async with w.factory() as s:
        (await s.get(PersonnelFile, file_id)).retention_due_at = date.today()
        await s.commit()
    assert await staffing_retention_sweep(session_factory=w.factory, today=date.today()) == 0
    kept = await _row(w, PersonnelFile, file_id)
    assert kept.status == "ended" and kept.roster_member_id == person.id
    # The sweep put the true date back instead of leaving the file due every night.
    assert kept.retention_due_at == due

    assert await staffing_retention_sweep(session_factory=w.factory, today=due) == 1
    assert await _row(w, PersonnelFile, file_id) is None


async def test_one_failing_file_does_not_roll_back_the_others(factory, monkeypatch, caplog) -> None:
    from app.modules.staffing.models import PersonnelFile
    from app.modules.staffing.sweep import staffing_retention_sweep

    w = await build_world(factory, governance=False)
    people = await members(w)
    files = [await personnel_file(w, people[i].id) for i in (0, 1)]
    for f in files:
        await call(w, "end_file", f, admin(w))
    due = (await _row(w, PersonnelFile, files[0])).retention_due_at
    real = StaffingService.apply_retention

    async def flaky(self, pfile, *a, **kw):
        if pfile.id == files[0]:
            raise RuntimeError("boom")
        return await real(self, pfile, *a, **kw)

    monkeypatch.setattr(StaffingService, "apply_retention", flaky)
    with caplog.at_level(logging.WARNING, logger="app.modules.staffing.sweep"):
        assert await staffing_retention_sweep(session_factory=w.factory, today=due) == 1
    assert any(str(files[0]) in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert (await _row(w, PersonnelFile, files[0])).status == "ended"
    assert await _row(w, PersonnelFile, files[1]) is None


async def test_erasure_rechecks_the_legal_duty_and_a_second_erasure_is_a_conflict(factory) -> None:
    w = await build_world(factory, catalogue_id="us", governance=False)
    people = await members(w)
    duty = await personnel_file(w, people[0].id)
    await record(w, duty, "right_to_work_check")
    err = await _refused(call(w, "erase_file", duty, "Request of the person.", admin(w)))
    assert (err.code, err.status_code) == ("retention_obligation_active", 409)
    assert err.detail

    free = await personnel_file(w, people[1].id)
    await call(w, "create_travel", free, {"kind": "business", "depart_date": days(3)}, admin(w))
    err = await _refused(call(w, "erase_file", free, "Request.", hr(w.manager)))
    assert err.status_code == 403
    await call(w, "erase_file", free, "Request of the person.", admin(w))
    from app.modules.staffing.models import PersonnelFile

    erased = await _row(w, PersonnelFile, free)
    assert erased.status == "anonymised" and erased.roster_member_id is None
    assert sum(v["travel"] for v in erased.activity_counts.values()) == 1
    err = await _refused(call(w, "erase_file", free, "Again.", admin(w)))
    assert (err.code, err.status_code) == ("file_anonymised", 409)


# ── finding 4: one document, one person ────────────────────────────────────


async def test_a_document_is_one_persons_and_erasing_one_file_leaves_the_other(factory) -> None:
    from app.modules.credentials.models import Credential
    from app.modules.staffing.models import PersonnelDocument

    w = await build_world(factory, governance=False)
    people = await members(w)
    a = await personnel_file(w, people[0].id, nationality_required=True)
    b = await personnel_file(w, people[1].id, nationality_required=True)
    doc_a = await record(w, a, "work_permit", days(400))
    doc_b = await record(w, b, "work_permit", days(400))
    assert doc_a.credential_id != doc_b.credential_id
    cred_a = await _row(w, Credential, doc_a.credential_id)
    assert cred_a.holder_name == people[0].display_name

    # Recording again renews the same credential instead of adding a second one.
    renewed = await record(w, a, "work_permit", days(800))
    assert renewed.credential_id == doc_a.credential_id
    assert (await _row(w, Credential, doc_a.credential_id)).valid_until == days(800)

    # The database refuses one credential behind two documents.
    async with w.factory() as s:
        (await s.get(PersonnelDocument, doc_b.id)).credential_id = doc_a.credential_id
        with pytest.raises(IntegrityError):
            await s.commit()

    await call(w, "erase_file", a, "Request of the person.", admin(w))
    assert await _row(w, Credential, doc_a.credential_id) is None
    assert (await _row(w, Credential, doc_b.credential_id)).valid_until == days(400)
    people_now = {p["roster_member_id"]: p for p in await call(w, "people")}
    assert people_now[people[1].id]["documents"]["work_permit"]["status"] == "active"


async def test_the_recorder_of_a_document_cannot_verify_it(factory) -> None:
    from app.modules.staffing.models import PersonnelDocument

    w = await build_world(factory, governance=False)
    person = (await members(w))[0]
    pid = await position(w, "site_manager", owner_user_id=w.owner)
    await confirm(w, await fill(w, pid, person.id, "0.50"))
    file_id = await personnel_file(w, person.id)
    doc = await record(w, file_id, "employment_contract")

    err = await _refused(call(w, "verify_document", file_id, doc.id, admin(w)))
    assert (err.code, err.status_code) == ("verifier_is_recorder", 409)
    await call(w, "verify_document", file_id, doc.id, hr(w.owner))
    verified = await _row(w, PersonnelDocument, doc.id)
    assert verified.verified_by == w.owner

    # A changed validity is a new statement: the old verification does not cover it.
    await record(w, file_id, "employment_contract", days(500), actor=hr(w.owner))
    changed = await _row(w, PersonnelDocument, doc.id)
    assert (changed.verified_by, changed.verified_at) == (None, None)
    assert changed.recorded_by == w.owner


# ── findings 7 and 11: holds and repeated transitions ──────────────────────


async def test_a_hold_needs_an_ended_file_and_release_keeps_its_retention_date(factory) -> None:
    from app.modules.staffing.models import PersonnelFile

    w = await build_world(factory, governance=False)
    person = (await members(w))[0]
    file_id = await personnel_file(w, person.id)
    err = await _refused(call(w, "hold_file", file_id, "Dispute.", admin(w)))
    assert err.status_code == 409
    assert (await _row(w, PersonnelFile, file_id)).status == "active"

    await call(w, "end_file", file_id, admin(w))
    ended = await _row(w, PersonnelFile, file_id)
    await call(w, "hold_file", file_id, "Dispute.", admin(w))
    err = await _refused(call(w, "hold_file", file_id, "Another reason.", admin(w)))
    assert (err.code, err.status_code) == ("already_in_state", 409)
    held = await _row(w, PersonnelFile, file_id)
    assert (held.hold_rationale, held.held_by) == ("Dispute.", w.manager)

    await call(w, "release_file", file_id, admin(w))
    released = await _row(w, PersonnelFile, file_id)
    assert released.status == "ended"
    assert (released.ended_on, released.retention_due_at) == (ended.ended_on, ended.retention_due_at)
    assert released.retention_due_at is not None


async def test_repeated_transitions_answer_409_and_write_nothing(factory) -> None:
    from app.core.audit_log import ActivityLog
    from app.modules.staffing.models import LeaveRecord, PositionFill

    w = await build_world(factory, governance=False)
    person = (await members(w))[0]
    pid = await position(w, "site_manager")
    fid = await fill(w, pid, person.id)
    await confirm(w, fid)
    err = await _refused(call(w, "confirm_fill", fid, admin(w)))
    assert (err.code, err.status_code) == ("already_in_state", 409)
    async with w.factory() as s:
        audits = (
            await s.execute(
                select(ActivityLog).where(ActivityLog.entity_id == str(fid), ActivityLog.action == "fill_confirmed")
            )
        ).all()
    assert len(audits) == 1

    await call(w, "end_fill", fid, w.manager)
    ended = await _row(w, PositionFill, fid)
    assert ended.to_date == date.today()
    err = await _refused(call(w, "end_fill", fid, w.manager))
    assert (err.code, err.status_code) == ("already_in_state", 409)
    assert (await _row(w, PositionFill, fid)).updated_at == ended.updated_at

    file_id = await personnel_file(w, person.id)
    leave, _ = await call(
        w, "create_leave", file_id, {"leave_type": "annual", "from_date": days(40), "to_date": days(45)}, admin(w)
    )
    err = await _refused(call(w, "update_leave", file_id, leave.id, {"leave_type": "sabbatical"}, admin(w)))
    assert (err.code, err.status_code) == ("leave_type_unknown", 422)
    await call(w, "set_leave_status", file_id, leave.id, "approved", admin(w))
    approved = await _row(w, LeaveRecord, leave.id)
    err = await _refused(call(w, "set_leave_status", file_id, leave.id, "approved", admin(w)))
    assert (err.code, err.status_code) == ("already_in_state", 409)
    err = await _refused(call(w, "update_leave", file_id, leave.id, {"to_date": days(60)}, admin(w)))
    assert (err.code, err.status_code) == ("leave_not_requested", 409)
    after = await _row(w, LeaveRecord, leave.id)
    assert (after.approved_at, after.to_date, after.updated_at) == (
        approved.approved_at,
        approved.to_date,
        approved.updated_at,
    )


# ── finding 12: the bed loses the person too ───────────────────────────────


async def test_anonymisation_cuts_the_accommodation_link(factory) -> None:
    from app.modules.accommodation.models import Accommodation, Booking, Room

    w = await build_world(factory, governance=False)
    people = await members(w)
    file_id = await personnel_file(w, people[0].id)
    async with w.factory() as s:
        camp = Accommodation(project_id=w.project_id, name="Camp")
        s.add(camp)
        await s.flush()
        room = Room(accommodation_id=camp.id, label="B2")
        s.add(room)
        await s.flush()
        mine = Booking(room_id=room.id, roster_member_id=people[0].id, check_in=START)
        other = Booking(room_id=room.id, roster_member_id=people[1].id, check_in=START)
        s.add_all([mine, other])
        await s.commit()
        mine_id, other_id = mine.id, other.id
    await call(w, "erase_file", file_id, "Request of the person.", admin(w))
    assert (await _row(w, Booking, mine_id)).roster_member_id is None
    assert (await _row(w, Booking, other_id)).roster_member_id == people[1].id


# ── finding 15: unique races ───────────────────────────────────────────────


async def test_two_racing_creates_answer_a_conflict_not_a_500(factory) -> None:
    w = await build_world(factory, governance=False)
    person = (await members(w))[0]
    await staffed(w, person.id)

    async def create():
        try:
            await call(w, "create_file", {"roster_member_id": person.id}, admin(w))
            return "ok"
        except StaffingError as exc:
            return exc.code

    assert sorted(await asyncio.gather(create(), create())) == ["file_exists", "ok"]

    other = await build_world(factory, governance=False)
    async with other.factory() as s:
        from app.modules.staffing.models import StaffingPlan

        await s.delete(
            (await s.execute(select(StaffingPlan).where(StaffingPlan.project_id == other.project_id))).scalar_one()
        )
        await s.commit()

    async def plan():
        try:
            async with other.factory() as s:
                await StaffingService(s).set_plan(other.project_id, actor_id=other.manager, tenant_id=None)
                await s.commit()
            return "ok"
        except StaffingError as exc:
            return exc.code

    assert sorted(await asyncio.gather(plan(), plan())) == ["ok", "plan_exists"]


async def test_the_own_file_is_readable_but_not_editable_by_the_person(factory) -> None:
    from app.modules.teams.models import RosterMember

    w = await build_world(factory, governance=False)
    person = (await members(w))[0]
    file_id = await personnel_file(w, person.id)
    async with w.factory() as s:
        (await s.get(RosterMember, person.id)).user_id = w.editor
        await s.commit()
    me = Actor(w.editor)
    async with w.factory() as s:
        svc = StaffingService(s)
        view = await svc.file_view(w.project_id, await svc.open_file(w.project_id, file_id, me), me)
        await s.commit()
    assert _flag(view["can"]["edit"]) == {"allowed": False, "reason": "own_file_read_only"}
    assert _flag(view["can"]["export"]) == {"allowed": True, "reason": None}
    err = await _refused(call(w, "update_file", file_id, {"employer_organisation": "X"}, me))
    assert err.code == "own_file_read_only"
    assert uuid.UUID(view["id"]) == file_id
