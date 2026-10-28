# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An inspector has to reach the client as a name, whoever wrote the row.

``QualityInspection.inspector_id`` is a bare 36-character string with no
foreign key, and three different writers put three different things in it: the
demo seeder writes a contact id, a picker writes a user id, and the free-text
field on the create form writes whatever somebody typed. The list endpoint used
to hand that value straight to the client, so a seeded register printed a row
of UUIDs under a column headed "Inspector".

These tests pin the resolution and, just as importantly, the fallback: a value
that resolves to nothing must come back unchanged, because a typed name is
already the answer and a deleted party's id is the only trace of it left.
"""

import uuid

import pytest

from app.core.party_names import resolve_party_names
from app.modules.contacts.models import Contact
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def test_a_contact_id_resolves_to_the_company_name(pg_session):
    contact = Contact(
        id=uuid.uuid4(),
        contact_type="consultant",
        company_name="Northgate Testing Services",
        first_name="Dana",
        last_name="Whitfield",
    )
    pg_session.add(contact)
    await pg_session.flush()

    names = await resolve_party_names(pg_session, [str(contact.id)])

    assert names[str(contact.id)] == "Northgate Testing Services"


async def test_a_person_without_a_company_resolves_to_their_full_name(pg_session):
    contact = Contact(
        id=uuid.uuid4(),
        contact_type="consultant",
        first_name="Dana",
        last_name="Whitfield",
    )
    pg_session.add(contact)
    await pg_session.flush()

    names = await resolve_party_names(pg_session, [str(contact.id)])

    assert names[str(contact.id)] == "Dana Whitfield"


async def test_a_user_id_resolves_too_because_a_picker_writes_one(pg_session):
    """The punch list writes real user ids from a picker, the seeder writes
    contact ids, and both land in columns of the same shape. Resolving only one
    table is why Deadlines reads "Unassigned" over rows that name a party."""
    user = User(
        id=uuid.uuid4(),
        email="site.engineer@example.com",
        hashed_password="x",
        full_name="Site Engineer",
    )
    pg_session.add(user)
    await pg_session.flush()

    names = await resolve_party_names(pg_session, [str(user.id)])

    assert names[str(user.id)] == "Site Engineer"


async def test_a_typed_name_is_not_looked_up_and_not_returned(pg_session):
    """A free-text value must never reach the WHERE clause.

    Comparing a uuid column against 'Dana Whitfield' raises on PostgreSQL,
    which would turn a cosmetic lookup into a 500 on the whole list endpoint.
    It is also not something the caller needs back: an absent entry means "use
    what you stored", and what was stored is the name.
    """
    names = await resolve_party_names(pg_session, ["Dana Whitfield", "", None])

    assert names == {}


async def test_an_unknown_id_is_absent_rather_than_blank(pg_session):
    """A deleted party leaves its id behind; blanking the cell loses it."""
    names = await resolve_party_names(pg_session, [str(uuid.uuid4())])

    assert names == {}


async def test_contacts_and_users_resolve_together_in_one_call(pg_session):
    contact = Contact(id=uuid.uuid4(), contact_type="subcontractor", company_name="Harlow Mechanical")
    user = User(id=uuid.uuid4(), email="qa@example.com", hashed_password="x", full_name="Quality Lead")
    pg_session.add_all([contact, user])
    await pg_session.flush()

    names = await resolve_party_names(pg_session, [str(contact.id), str(user.id), str(uuid.uuid4())])

    assert names == {str(contact.id): "Harlow Mechanical", str(user.id): "Quality Lead"}
