# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode the project roster holds only project people.

``POST /teams/project/{id}/roster`` takes a ``user_id`` or a ``contact_id`` from
the request body and copies that person's name, email and phone into the new
roster line, which it returns. Access to the project was the only check, so on
an academy box a learner could paste another learner's id and read back their
name and email, or paste the id of another learner's address-book contact and
read back theirs; a 404 for an unknown user also answered "does this account
exist". In academy mode a linked user must already be in the project
(422 ``user_not_in_project``) and a linked contact must be in the caller's own
address book (404, the same answer as a missing contact). Granting access
through the roster is the membership path, which only an admin may take there.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.academy_isolation import ADMIN_ADDS_MEMBERS, USER_NOT_IN_PROJECT
from app.modules.contacts.models import Contact
from app.modules.teams.models import RosterMember
from app.modules.teams.roster_schemas import RosterMemberCreate
from app.modules.teams.roster_service import RosterService
from tests.pg.academy_isolation.rows import add_member, make_project, make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _setup(session):
    alice = await make_user(session, name="Alice Owner")
    bob = await make_user(session, name="Bob Outsider", email=f"bob-{uuid.uuid4().hex[:6]}@academy.example")
    carol = await make_user(session, name="Carol Member")
    project = await make_project(session, alice)
    await add_member(session, project, carol)
    mine = Contact(contact_type="supplier", company_name="Alice supplier", tenant_id=str(alice.id))
    theirs = Contact(
        contact_type="supplier",
        company_name="Bob supplier",
        primary_email="buyer@bob.example",
        primary_phone="+49 30 1234",
        tenant_id=str(bob.id),
    )
    session.add_all([mine, theirs])
    await session.flush()
    return project, alice, bob, carol, mine, theirs


async def _lines(session, project) -> int:
    return (
        await session.execute(select(func.count(RosterMember.id)).where(RosterMember.project_id == project.id))
    ).scalar_one()


async def _add(session, project, actor, **fields):
    return await RosterService(session).add_members(project.id, [RosterMemberCreate(**fields)], actor_id=actor.id)


async def test_academy_on_another_learner_cannot_be_rostered(pg_session, academy) -> None:
    academy(True)
    project, alice, bob, _carol, _mine, _theirs = await _setup(pg_session)

    with pytest.raises(HTTPException) as caught:
        await _add(pg_session, project, alice, user_id=bob.id)
    assert caught.value.status_code == 422
    assert caught.value.detail["error"] == USER_NOT_IN_PROJECT
    # An id that names nobody gets the same answer, not a 404.
    with pytest.raises(HTTPException) as unknown:
        await _add(pg_session, project, alice, user_id=uuid.uuid4())
    assert unknown.value.status_code == 422
    assert await _lines(pg_session, project) == 0


async def test_academy_on_another_learners_contact_reads_as_missing(pg_session, academy) -> None:
    academy(True)
    project, alice, _bob, _carol, _mine, theirs = await _setup(pg_session)

    with pytest.raises(HTTPException) as caught:
        await _add(pg_session, project, alice, contact_id=theirs.id)
    assert caught.value.status_code == 404
    assert caught.value.detail == "Contact not found"
    assert "bob.example" not in str(caught.value.detail)
    assert await _lines(pg_session, project) == 0


async def test_academy_on_project_people_and_own_contacts_still_work(pg_session, academy) -> None:
    academy(True)
    project, alice, _bob, carol, mine, _theirs = await _setup(pg_session)

    rows = await _add(pg_session, project, alice, user_id=carol.id)
    assert rows[0].display_name == "Carol Member"
    rows = await _add(pg_session, project, alice, contact_id=mine.id)
    assert rows[0].company_name == "Alice supplier"
    rows = await _add(pg_session, project, alice, display_name="Tomasz W.", company_name="Agency")
    assert rows[0].display_name == "Tomasz W."

    # Granting access is adding a member, which only an admin does here.
    dave = await make_user(pg_session, name="Dave")
    await add_member(pg_session, project, dave)
    with pytest.raises(HTTPException) as grant:
        await _add(pg_session, project, alice, user_id=dave.id, grant_project_access=True)
    assert grant.value.status_code == 403
    assert grant.value.detail["error"] == ADMIN_ADDS_MEMBERS
    assert await _lines(pg_session, project) == 3


async def test_academy_off_unchanged(pg_session, academy) -> None:
    academy(False)
    project, alice, bob, _carol, _mine, theirs = await _setup(pg_session)

    rows = await _add(pg_session, project, alice, user_id=bob.id)
    assert rows[0].email == bob.email
    rows = await _add(pg_session, project, alice, contact_id=theirs.id)
    assert rows[0].email == "buyer@bob.example"
    with pytest.raises(HTTPException) as unknown:
        await _add(pg_session, project, alice, user_id=uuid.uuid4())
    assert unknown.value.status_code == 404
    assert await _lines(pg_session, project) == 2
