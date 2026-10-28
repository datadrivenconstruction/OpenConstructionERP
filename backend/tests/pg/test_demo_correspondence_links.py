# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A seeded letter must reach the database pointing at the contact it is with.

The unit tests next to the generator check that every letter names a role the
same demo seeds a contact for. They cannot check the step after that: the role
is turned into a contact id by the seeding writer, which mints the ids as it
writes and needs a session, so this is the only place the link is read back.

Two demos, because the writer chooses the contact list and the letter list
independently. office-frankfurt takes both from the generator. The Heilbronn
retail demo has a hand-curated contact list and no curated correspondence, so
it is seeded with curated contacts and generated letters, which is a pairing
the generator never produces on its own.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.demo_projects import DEMO_TEMPLATES, _seed_module_data
from app.modules.contacts.models import Contact
from app.modules.correspondence.models import Correspondence
from app.modules.projects.models import Project
from app.modules.users.models import User

_DEMOS = ["office-frankfurt", "retail-market-heilbronn"]


async def _seeded_project(session, demo_id: str) -> uuid.UUID:
    owner = User(
        email=f"corr-links-{uuid.uuid4().hex[:8]}@example.test",
        hashed_password="x",
        full_name="Correspondence Links Owner",
    )
    session.add(owner)
    await session.flush()

    project = Project(name=f"Letters for {demo_id}", owner_id=owner.id)
    session.add(project)
    await session.flush()

    await _seed_module_data(session, project.id, owner.id, demo_id, DEMO_TEMPLATES[demo_id])
    await session.flush()
    return project.id


async def _contacts_by_id(session, project_id: uuid.UUID) -> dict[str, str]:
    """Role of each contact this project seeded, keyed by id as stored.

    Filtered in Python rather than through a JSON operator so the query stays
    the same shape the rest of this file uses.
    """
    rows = (await session.execute(select(Contact.id, Contact.contact_type, Contact.metadata_))).all()
    return {str(cid): ctype for cid, ctype, meta in rows if (meta or {}).get("project_id") == str(project_id)}


@pytest.mark.parametrize("demo_id", _DEMOS)
async def test_every_seeded_letter_points_at_a_contact(pg_session, demo_id: str) -> None:
    project_id = await _seeded_project(pg_session, demo_id)
    roles_by_id = await _contacts_by_id(pg_session, project_id)
    assert roles_by_id, f"{demo_id} seeded no contacts, the check below would be vacuous"

    rows = (
        await pg_session.execute(
            select(
                Correspondence.reference_number,
                Correspondence.direction,
                Correspondence.from_contact_id,
                Correspondence.to_contact_ids,
            ).where(Correspondence.project_id == project_id)
        )
    ).all()
    assert rows, f"{demo_id} seeded no correspondence"

    unlinked = []
    for ref, direction, from_id, to_ids in rows:
        linked = to_ids[0] if direction == "outgoing" and to_ids else from_id
        if not linked or linked not in roles_by_id:
            unlinked.append((ref, direction, linked))
    assert not unlinked, (
        f"{demo_id} seeded letters that point at nobody, or at a contact this project did not create: {unlinked[:5]}"
    )


@pytest.mark.parametrize("demo_id", _DEMOS)
async def test_the_link_sits_on_the_end_the_direction_says(pg_session, demo_id: str) -> None:
    """An outgoing letter has a recipient, an incoming one has a sender.

    Filling the wrong column would still leave every row linked, so the test
    above would pass on a writer that put every party in from_contact_id.
    """
    project_id = await _seeded_project(pg_session, demo_id)
    rows = (
        await pg_session.execute(
            select(
                Correspondence.reference_number,
                Correspondence.direction,
                Correspondence.from_contact_id,
                Correspondence.to_contact_ids,
            ).where(Correspondence.project_id == project_id)
        )
    ).all()
    assert rows, f"{demo_id} seeded no correspondence"

    wrong = []
    for ref, direction, from_id, to_ids in rows:
        if direction == "outgoing" and (from_id or len(to_ids or []) != 1):
            wrong.append((ref, direction, from_id, to_ids))
        if direction == "incoming" and (not from_id or to_ids):
            wrong.append((ref, direction, from_id, to_ids))
    assert not wrong, f"{demo_id} put the party on the wrong end: {wrong[:5]}"


@pytest.mark.parametrize("demo_id", _DEMOS)
async def test_the_permit_letters_point_at_the_permitting_body(pg_session, demo_id: str) -> None:
    """The gap that started this, read back from the database.

    Three letters are with an authority and the generated contact list had none,
    so before the fix these three were the ones that could point at nothing.
    """
    project_id = await _seeded_project(pg_session, demo_id)
    roles_by_id = await _contacts_by_id(pg_session, project_id)

    rows = (
        await pg_session.execute(
            select(
                Correspondence.reference_number,
                Correspondence.subject,
                Correspondence.direction,
                Correspondence.from_contact_id,
                Correspondence.to_contact_ids,
            ).where(Correspondence.project_id == project_id)
        )
    ).all()

    linked_roles = {}
    for ref, _subject, direction, from_id, to_ids in rows:
        linked = to_ids[0] if direction == "outgoing" and to_ids else from_id
        linked_roles[ref] = roles_by_id.get(str(linked)) if linked else None

    with_authority = [ref for ref, role in linked_roles.items() if role == "authority"]
    assert len(with_authority) == 3, (
        f"{demo_id} links {len(with_authority)} letters to a permitting body, expected the "
        f"notice of commencement, its acknowledgement and the inspection report; "
        f"roles seeded were {sorted(set(roles_by_id.values()))}"
    )
