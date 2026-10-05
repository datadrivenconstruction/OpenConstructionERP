# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode the roster picker offers only project people (gate E7b).

``GET /teams/project/{id}/roster/candidates`` searches every active user by name
and email and every address-book contact on the install, and its ``total``
counts them. Access to any one project is enough to call it, so on an academy
box it was a directory of every learner (and of every learner's contacts) and
an oracle for "does this address have an account". The hosted demo already
narrows the user side to the caller and the project's people; academy mode now
does the same, and narrows the contact side to the caller's own address book.
Admins keep the full picker, and with the flag off nothing changes.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import pytest

from app.modules.contacts.models import Contact
from app.modules.teams.roster_service import RosterService
from tests.pg.academy_isolation.rows import add_member, make_project, make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _setup(session):
    alice = await make_user(session, name="Alice Owner")
    bob = await make_user(session, name="Bob Outsider")
    carol = await make_user(session, name="Carol Member")
    operator = await make_user(session, role="admin", name="Operator")
    project = await make_project(session, alice)
    await add_member(session, project, carol)
    mine = Contact(contact_type="client", company_name="Alice client", tenant_id=str(alice.id))
    theirs = Contact(
        contact_type="client", company_name="Bob client", primary_email="buyer@bob.example", tenant_id=str(bob.id)
    )
    session.add_all([mine, theirs])
    await session.flush()
    return project, alice, bob, carol, operator, mine, theirs


async def _candidates(session, project, caller, query: str = ""):
    items, total = await RosterService(session).list_candidates(project.id, actor_id=caller.id, query=query, limit=200)
    users = {c.id for c in items if c.source == "user"}
    contacts = {c.id for c in items if c.source == "contact"}
    return users, contacts, total


async def test_academy_on_another_learner_and_their_contacts_are_not_offered(pg_session, academy) -> None:
    academy(True)
    project, alice, bob, carol, operator, mine, theirs = await _setup(pg_session)

    users, contacts, total = await _candidates(pg_session, project, alice)
    assert users == {alice.id, carol.id}
    assert contacts == {mine.id}
    assert total == len(users) + len(contacts)

    # The count no longer answers "does this address have an account".
    assert await _candidates(pg_session, project, alice, query=bob.email) == (set(), set(), 0)
    assert await _candidates(pg_session, project, alice, query="buyer@bob") == (set(), set(), 0)


async def test_academy_on_project_people_and_admins_are_still_offered(pg_session, academy) -> None:
    academy(True)
    project, alice, bob, carol, operator, mine, theirs = await _setup(pg_session)

    users, _, total = await _candidates(pg_session, project, alice, query=carol.email)
    assert (users, total) == ({carol.id}, 1)
    everyone, contacts, _ = await _candidates(pg_session, project, operator)
    assert {alice.id, bob.id, carol.id, operator.id} <= everyone
    assert {mine.id, theirs.id} <= contacts


async def test_academy_off_unchanged(pg_session, academy) -> None:
    academy(False)
    project, alice, bob, carol, operator, mine, theirs = await _setup(pg_session)

    users, contacts, total = await _candidates(pg_session, project, alice)
    assert {alice.id, bob.id, carol.id, operator.id} <= users
    assert {mine.id, theirs.id} <= contacts
    assert await _candidates(pg_session, project, alice, query=bob.email) == ({bob.id}, set(), 1)
