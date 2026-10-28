# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The deadline register has to name whoever the row was given to.

``owner_user_id`` is normalised from columns that carry no foreign key, and the
three writers behind them store three different things: a contact id when the
party is external (the demo seeder puts the main contractor on every punch
item), a user id when a picker names a teammate, and free text when somebody
types a name. The register resolved all of that against ``User`` alone, so
every row naming a contact came back with no ``owner_name`` - and the client,
which has no fallback of its own, printed "Unassigned" over a row that does
name somebody. That is a false statement about the row, not a missing one.

These tests pin the resolution and, just as importantly, the two misses that
have to stay misses: a row nobody was given to, and an id that resolves to
nothing. Echoing the second would print a raw UUID under a column headed by a
person's name, which is the defect this fix shares a root with.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.modules.contacts.models import Contact
from app.modules.deadlines import service
from app.modules.deadlines.schemas import DeadlineItem
from app.modules.projects.models import Project
from app.modules.punchlist.models import PunchItem
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

# A fixed clock with the due date a fortnight behind it, so every row below
# lands on the register as overdue whatever day the suite runs.
_NOW = datetime(2026, 3, 15, 9, 0, tzinfo=UTC)
_DUE = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


async def _a_project(session) -> uuid.UUID:
    """A project with an owner, which is all the register needs to scope a query."""
    owner = User(
        id=uuid.uuid4(),
        email=f"pm-{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="x",
        full_name="Project Manager",
    )
    session.add(owner)
    await session.flush()
    project = Project(name="Deadline owner resolution", owner_id=owner.id)
    session.add(project)
    await session.flush()
    return project.id


def _punch_item(project_id: uuid.UUID, assigned_to: str | None, title: str = "Snagging item") -> PunchItem:
    """An overdue punch item given to ``assigned_to``, whatever that holds.

    The punch list is used because it is where the defect is visible: its
    collector hands ``assigned_to`` to the register raw, and the seeder writes
    a contact id into it.
    """
    return PunchItem(
        id=uuid.uuid4(),
        project_id=project_id,
        title=title,
        description="",
        status="open",
        due_date=_DUE,
        assigned_to=assigned_to,
    )


async def _register_row(session, assigned_to: str | None) -> DeadlineItem:
    """Put one overdue punch item on the register and hand back its row.

    The length assertion is not decoration: a row that failed to classify as
    overdue would leave an empty register, and every name check below would
    then pass without having looked at anything.
    """
    project_id = await _a_project(session)
    session.add(_punch_item(project_id, assigned_to))
    await session.flush()

    register = await service.compute_deadlines(session, [project_id], now=_NOW, module="punchlist")

    assert len(register.items) == 1, "the punch item never reached the register"
    return register.items[0]


async def test_a_contact_id_reads_as_the_party_it_names(pg_session):
    """The row that used to read "Unassigned".

    The party on a punch item is external - it goes to the main contractor,
    who allocates it onwards - so what the seeder stores is a contact id, and
    a lookup against users alone can never resolve it.
    """
    contact = Contact(id=uuid.uuid4(), contact_type="contractor", company_name="Harlow Mechanical")
    pg_session.add(contact)
    await pg_session.flush()

    row = await _register_row(pg_session, str(contact.id))

    assert row.owner_name == "Harlow Mechanical"


async def test_a_user_id_still_reads_as_the_persons_name(pg_session):
    """A picker writes a teammate's id, and that resolution must not regress."""
    assignee = User(
        id=uuid.uuid4(),
        email="site.engineer@example.com",
        hashed_password="x",
        full_name="Site Engineer",
    )
    pg_session.add(assignee)
    await pg_session.flush()

    row = await _register_row(pg_session, str(assignee.id))

    assert row.owner_name == "Site Engineer"


async def test_a_typed_name_is_shown_rather_than_called_unassigned(pg_session):
    """A free-text value is already the answer.

    It is never looked up - comparing a uuid column against 'Dana Whitfield'
    raises on PostgreSQL - so the register echoes what was stored instead of
    asserting that nobody holds the row.
    """
    row = await _register_row(pg_session, "Dana Whitfield")

    assert row.owner_name == "Dana Whitfield"


async def test_an_id_that_resolves_to_nothing_keeps_the_column_empty(pg_session):
    """A deleted party must not become a UUID on screen.

    This client renders ``owner_name`` alone and never falls back to the id it
    was given, so echoing an unresolved id here would print the raw value under
    a column headed by a person's name. The id itself is still carried, which
    keeps the row diagnosable.
    """
    missing = str(uuid.uuid4())

    row = await _register_row(pg_session, missing)

    assert row.owner_name is None
    assert row.owner_user_id == missing


async def test_a_row_nobody_holds_stays_unassigned(pg_session):
    """The one case where "Unassigned" is true, and it has to survive the fix."""
    row = await _register_row(pg_session, None)

    assert row.owner_name is None
    assert row.owner_user_id is None


async def test_an_id_stored_in_another_case_resolves_too(pg_session):
    """The stored spelling is whatever wrote the row, the resolved map is canonical.

    PostgreSQL matches a uuid column case-blind, so an id written in upper case
    is found - and then looked up in the returned map under a key that is not
    there, which reads on screen exactly like a party that does not exist.
    """
    contact = Contact(id=uuid.uuid4(), contact_type="subcontractor", company_name="Northgate Testing Services")
    pg_session.add(contact)
    await pg_session.flush()

    row = await _register_row(pg_session, str(contact.id).upper())

    assert row.owner_name == "Northgate Testing Services"


async def test_every_kind_of_owner_resolves_in_a_single_pass(pg_session):
    """All five shapes together, resolved once for the whole register.

    The register is a cross-module read that already caps each source at 500
    rows; resolving a name per row would put five hundred round trips behind
    one page load, so the lookup stays batched over the collected items.
    """
    project_id = await _a_project(pg_session)
    contact = Contact(id=uuid.uuid4(), contact_type="contractor", company_name="Harlow Mechanical")
    assignee = User(
        id=uuid.uuid4(),
        email="quality.lead@example.com",
        hashed_password="x",
        full_name="Quality Lead",
    )
    pg_session.add_all([contact, assignee])
    await pg_session.flush()

    pg_session.add_all(
        [
            _punch_item(project_id, str(contact.id), title="Contact id"),
            _punch_item(project_id, str(assignee.id), title="User id"),
            _punch_item(project_id, "Dana Whitfield", title="Typed name"),
            _punch_item(project_id, str(uuid.uuid4()), title="Deleted party"),
            _punch_item(project_id, None, title="Nobody"),
        ],
    )
    await pg_session.flush()

    register = await service.compute_deadlines(pg_session, [project_id], now=_NOW, module="punchlist")

    by_title = {it.title: it for it in register.items}
    assert sorted(by_title) == ["Contact id", "Deleted party", "Nobody", "Typed name", "User id"]
    assert by_title["Contact id"].owner_name == "Harlow Mechanical"
    assert by_title["User id"].owner_name == "Quality Lead"
    assert by_title["Typed name"].owner_name == "Dana Whitfield"
    assert by_title["Deleted party"].owner_name is None
    assert by_title["Nobody"].owner_name is None
