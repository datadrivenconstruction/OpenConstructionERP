# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The tenant backfill against a populated PostgreSQL database.

ADR 005 moves every ``tenant_id`` in the schema from naming a user to naming an
organization. That is a rewrite of other people's data, so it is tested here
against the real embedded PostgreSQL 16 rather than against a stand-in, for four
reasons a fake cannot cover:

* the rewrite is SQL, and PostgreSQL reports rows *matched* rather than rows
  *changed* - the difference between an idempotent repair and one that reports
  progress forever is only visible on a real server;
* ``NOT NULL`` on ten of the 31 tenant columns means "re-point this value" and
  "empty this value" are different statements, and only one of them is allowed;
* the ledger has to record ``NULL`` as a previous value, which is a fact about a
  real column, not about a dictionary;
* the downgrade has to put a populated database back, and a rollback-only fixture
  cannot tell "restored" from "never happened".

Everything runs inside :func:`tests.pg.conftest.pg_session`, which wraps the test
in an outer transaction and rolls it back, so dropping and rebuilding the tenancy
schema here does not survive the test.

Every assertion that touches the server also records ``current_user`` and
``rolsuper`` (see :func:`_role_facts`), because a result observed as a superuser
is not evidence about the role the application connects with.
"""

from __future__ import annotations

import importlib.util
import pathlib
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.core.tenant_scope import DEFAULT_ORGANIZATION_SLUG, MEMBERSHIP_ACTIVE

pytestmark = pytest.mark.asyncio

_REVISION_PATH = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v3325_organization_tenancy.py"

_ORGANIZATION = "oe_users_organization"
_MEMBERSHIP = "oe_users_membership"
_LEDGER = "oe_users_tenant_backfill"
_PROJECT = "oe_projects_project"

#: The tables the fixture writes into, chosen from the 31 by what each one proves:
#: ``oe_job_run`` has a nullable tenant and no ``created_by``; ``oe_pipeline`` has
#: a nullable tenant *and* a ``created_by``; ``oe_eac_block_graph`` has a NOT NULL
#: tenant; ``oe_governance_catalogue`` has a NOT NULL tenant in a VARCHAR(64), the
#: widest in the schema, beside its own ``created_by``.
#:
#: Each was chosen by asking the schema which columns a *raw SQL* insert must
#: supply, which is not the question "which columns will the ORM fill in": a
#: Python-side default does nothing for a statement that never reaches the mapper.
#: ``oe_waste_factors_factor`` looks like it needs nothing at all, right up to the
#: server refusing a NULL ``category``.
_NULLABLE_NO_CREATED_BY = "oe_job_run"
_NULLABLE_WITH_CREATED_BY = "oe_pipeline"
_NOT_NULL_TENANT = "oe_eac_block_graph"
_WIDEST_TENANT = "oe_governance_catalogue"


# ── plumbing ────────────────────────────────────────────────────────────────


def _load_revision():
    """Import the revision file, which is not on any import path."""
    spec = importlib.util.spec_from_file_location("v3325_organization_tenancy", _REVISION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run_revision(session, direction: str) -> None:  # noqa: ANN001
    """Execute ``upgrade()`` or ``downgrade()`` on the session's own connection.

    On the session's connection rather than a fresh one so the DDL joins the
    fixture's transaction and is rolled back with it. The operations proxy is what
    makes the module-level ``op`` in the revision resolve to this connection.
    """
    module = _load_revision()
    connection = await session.connection()

    if direction == "downgrade":
        await _drop_later_dependents(session)

    def _apply(sync_connection) -> None:  # noqa: ANN001
        context = MigrationContext.configure(sync_connection)
        operations = Operations(context)
        operations._install_proxy()  # noqa: SLF001 - the documented way to drive a revision by hand
        try:
            getattr(module, direction)()
        finally:
            operations._remove_proxy()  # noqa: SLF001

    await connection.run_sync(_apply)


async def _role_facts(session) -> dict[str, object]:  # noqa: ANN001
    """Who the server thinks is asking, recorded beside every observation."""
    row = (
        await session.execute(
            text(
                "SELECT current_user AS current_user, session_user AS session_user, "
                "       (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) AS rolsuper"
            )
        )
    ).one()
    return {"current_user": row.current_user, "session_user": row.session_user, "rolsuper": row.rolsuper}


#: Tables a *later* revision added that hold a foreign key into the tenancy schema
#: this revision creates. They are not this revision's objects, and nothing here
#: tests them; they are moved only because a foreign key from a later table makes
#: ``DROP TABLE`` refuse.
#:
#: ``oe_projects_participant_grant`` (ADR 006, revision ``v3326``) references the
#: organization twice: as the grantee, and as the company the grant was made on
#: behalf of. Named rather than cascaded, because ``DROP TABLE ... CASCADE`` would
#: remove a table belonging to another revision silently, and a helper that
#: destroys something it was not asked about is how a test starts passing for the
#: wrong reason.
_DEPENDENTS_OF_ORGANIZATION = ("oe_projects_participant_grant",)

#: The two references that belong to *this* revision and that its own
#: ``downgrade()`` removes - the column it adds to the project, and the membership
#: table it creates. Tolerated by the catalog question below, because a helper that
#: runs before the revision does has to expect them, and because naming them is what
#: makes the question about anything else.
_TENANCYS_OWN_REFERENCES = frozenset({_PROJECT, _MEMBERSHIP})


async def _drop_later_dependents(session) -> None:  # noqa: ANN001
    """Move the tables a later revision hung off this revision's schema.

    A real ``alembic downgrade`` reaches ``v3325`` by running ``v3326``'s
    downgrade first, so the grant table would already be gone and the organization
    table would drop without argument. This file drives one revision's
    ``downgrade()`` by hand, which is the right way to test that revision and the
    reason the later one has to be stood in for here.

    The catalog question is what keeps the list above honest. A dependent nobody
    added does not fail as "this helper is out of date"; it fails as an ``asyncpg``
    ``DependentObjectsStillExistError`` naming a constraint, several frames below
    anything that explains it - which is how the grant table arrived, with five
    tests in this file failing on a drop that had nothing to do with tenancy.
    Asked before the drop rather than after, because after a successful drop the
    table has no oid for the question to compare against. ``to_regclass`` rather
    than a cast, so a database that never had the table asks nothing of it.
    """
    for dependent in _DEPENDENTS_OF_ORGANIZATION:
        await session.execute(text(f"DROP TABLE IF EXISTS {dependent}"))
    still_referencing = [
        (row.dependent_table, row.conname)
        for row in (
            await session.execute(
                text(
                    "SELECT conrelid::regclass::text AS dependent_table, conname "
                    "FROM pg_constraint "
                    "WHERE contype = 'f' "
                    "  AND confrelid = to_regclass('oe_users_organization') "
                    "ORDER BY 1, 2"
                )
            )
        ).all()
        if row.dependent_table not in _TENANCYS_OWN_REFERENCES
    ]
    assert not still_referencing, (
        "the organization table cannot be dropped while a table this revision does not own still "
        f"references it; add each one to _DEPENDENTS_OF_ORGANIZATION: {still_referencing}"
    )


async def _drop_tenancy_schema(session) -> None:  # noqa: ANN001
    """Remove what the revision creates, in the order its own dependencies allow.

    The session's schema is built by ``create_all``, so these tables exist before
    a test starts. Removing them is what lets ``upgrade()`` be tested as the thing
    that builds the schema rather than as a no-op that happens to pass.

    Two kinds of object have to move before the organization table can be dropped,
    and they are handled separately because they are different claims. The
    revision's own objects - the project's column and its constraint, the ledger,
    the membership - are what ``downgrade()`` removes, so removing them here is
    what makes the test a test; they are the statements below. The tables a later
    revision hung off this schema are not this revision's business at all, and
    :func:`_drop_later_dependents` moves them and says why. Everything is inside
    the fixture's transaction, so nothing is actually lost.
    """
    for statement in (
        f"ALTER TABLE {_PROJECT} DROP CONSTRAINT IF EXISTS "
        f"fk_oe_projects_project_organization_id_oe_users_organization",
        "DROP INDEX IF EXISTS ix_oe_projects_project_organization_id",
        f"ALTER TABLE {_PROJECT} DROP COLUMN IF EXISTS organization_id",
        f"DROP TABLE IF EXISTS {_LEDGER}",
        f"DROP TABLE IF EXISTS {_MEMBERSHIP}",
    ):
        await session.execute(text(statement))
    await _drop_later_dependents(session)
    await session.execute(text(f"DROP TABLE IF EXISTS {_ORGANIZATION}"))


async def _insert(session, table: str, **columns: object) -> str:  # noqa: ANN001
    """One row by raw SQL, naming only the columns that matter.

    Raw SQL deliberately: it ignores every Python-side default, so a row written
    this way is a row this database would accept from any client, and the required
    columns had to be found by inspecting the schema rather than assumed.
    """
    row_id = str(uuid.uuid4())
    names = ["id", *columns]
    values = [":id", *(f":{name}" for name in columns)]
    await session.execute(
        text(f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join(values)})"),
        {"id": row_id, **columns},
    )
    return row_id


async def _tenant_of(session, table: str, row_id: str) -> str | None:  # noqa: ANN001
    return await session.scalar(text(f"SELECT tenant_id FROM {table} WHERE id = :id"), {"id": row_id})


class _Populated:
    """The database the tests share: three users, one organization, some old rows."""

    def __init__(self) -> None:
        self.session = None
        self.owner = ""
        self.colleague = ""
        self.suspended = ""
        self.organization = ""
        self.person_named: dict[str, str] = {}
        self.null_with_created_by = ""
        self.null_unattributable = ""
        self.not_null_row = ""
        self.widest_row = ""
        self.linked_project = ""
        self.orphan_project = ""


async def _populate(session) -> _Populated:  # noqa: ANN001, ANN201
    """Build an install exactly as it looks before this change ships.

    Three users: two with no organization at all, one whose only membership is
    suspended. One organization that already exists, so the repair has to adopt it
    rather than create a second. Rows in five tenant tables covering a person-named
    tenant, a ``NULL`` with a creator to attribute it from, a ``NULL`` with nothing
    to attribute it from, a ``NOT NULL`` tenant, and the widest tenant column in the
    schema. Two projects: one whose owner will have an organization, one whose
    owner will not.
    """
    from app.modules.projects.models import Project
    from app.modules.users.models import Membership, Organization, User

    state = _Populated()
    state.session = session

    users = {}
    for key, email in (
        ("owner", "owner@backfill.test"),
        ("colleague", "colleague@backfill.test"),
        ("suspended", "suspended@backfill.test"),
    ):
        user = User(
            id=uuid.uuid4(),
            email=email,
            hashed_password="not-a-real-hash",
            full_name=key.title(),
            role="editor" if key != "owner" else "admin",
            locale="en",
            is_active=True,
            metadata_={},
        )
        session.add(user)
        users[key] = user
    await session.flush()
    state.owner = str(users["owner"].id)
    state.colleague = str(users["colleague"].id)
    state.suspended = str(users["suspended"].id)

    organization = Organization(
        id=uuid.uuid4(), name="Existing Company", slug=f"existing-{uuid.uuid4().hex[:8]}", status="active"
    )
    session.add(organization)
    # Flushed before the membership, and not merely added beside it: the
    # membership names the organization through a plain column rather than a
    # relationship, so the unit of work has no dependency edge to order by and
    # would otherwise insert the child first and fail the foreign key.
    await session.flush()
    session.add(
        Membership(
            id=uuid.uuid4(),
            user_id=users["suspended"].id,
            organization_id=organization.id,
            role="editor",
            status="suspended",
            is_default=False,
        )
    )
    await session.flush()
    state.organization = str(organization.id)

    state.person_named[_NULLABLE_NO_CREATED_BY] = await _insert(
        session, _NULLABLE_NO_CREATED_BY, tenant_id=state.owner, kind="backfill-probe"
    )
    state.person_named[_WIDEST_TENANT] = await _insert(
        session,
        _WIDEST_TENANT,
        tenant_id=state.owner,
        kind="phase_model",
        code=f"CAT-{uuid.uuid4().hex[:8]}",
        name="Catalogue probe",
        based_on="",
        state="draft",
        draft_body="{}",
    )
    state.null_with_created_by = await _insert(
        session,
        _NULLABLE_WITH_CREATED_BY,
        tenant_id=None,
        created_by=state.colleague,
        name=f"pipeline-{uuid.uuid4().hex[:8]}",
    )
    state.null_unattributable = await _insert(
        session, _NULLABLE_NO_CREATED_BY, tenant_id=None, kind="backfill-probe-unattributable"
    )
    state.not_null_row = await _insert(
        session, _NOT_NULL_TENANT, tenant_id=state.owner, name=f"block-graph-{uuid.uuid4().hex[:8]}"
    )

    for key, column in (("linked_project", "owner"), ("orphan_project", "suspended")):
        project = Project(id=uuid.uuid4(), name=f"Project {key}", owner_id=users[column].id)
        session.add(project)
        setattr(state, key, str(project.id))
    await session.flush()
    return state


async def _repair(session) -> int:  # noqa: ANN001
    from app.modules.users.repairs import _run_tenant_organization_backfill

    return await _run_tenant_organization_backfill(session)


# ── the revision ────────────────────────────────────────────────────────────


async def test_a_create_all_database_reaches_the_revision_and_does_nothing(pg_session) -> None:  # noqa: ANN001
    """The schema ``create_all`` already built is not rebuilt, and not damaged.

    This product creates missing tables and then stamps head, so an ordinary
    install arrives here with the tables already present. Every step is
    inspector-guarded for exactly that case.
    """
    before = {
        table: await pg_session.scalar(text(f"SELECT count(*) FROM {table}"))
        for table in (_ORGANIZATION, _MEMBERSHIP, _LEDGER)
    }
    await _run_revision(pg_session, "upgrade")

    facts = await _role_facts(pg_session)
    assert facts["current_user"] == facts["session_user"], facts
    for table, count in before.items():
        assert await pg_session.scalar(text(f"SELECT count(*) FROM {table}")) == count
    column = await pg_session.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'organization_id'"
        ),
        {"t": _PROJECT},
    )
    assert column.scalar_one() == "YES", "the project edge must stay nullable"


async def test_upgrade_builds_the_tenancy_schema_when_it_is_absent(pg_session) -> None:  # noqa: ANN001
    """From nothing: three tables, the project edge, and the constraints that matter."""
    await _drop_tenancy_schema(pg_session)
    await _run_revision(pg_session, "upgrade")

    for table in (_ORGANIZATION, _MEMBERSHIP, _LEDGER):
        found = await pg_session.scalar(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"), {"t": table}
        )
        assert found == 1, f"{table} was not created"

    slug_unique = await pg_session.scalar(
        text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_name = :t AND constraint_name = 'uq_oe_users_organization_slug'"
        ),
        {"t": _ORGANIZATION},
    )
    assert slug_unique == 1, "the slug must be unique: two boots race on it and one has to win"

    membership_unique = await pg_session.scalar(
        text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_name = :t AND constraint_name = 'uq_oe_users_membership_user_org'"
        ),
        {"t": _MEMBERSHIP},
    )
    assert membership_unique == 1, "a duplicate membership has to be impossible, not merely unlikely"

    ledger_width = await pg_session.execute(
        text(
            "SELECT column_name, character_maximum_length, is_nullable FROM information_schema.columns "
            "WHERE table_name = :t ORDER BY column_name"
        ),
        {"t": _LEDGER},
    )
    widths = {row.column_name: (row.character_maximum_length, row.is_nullable) for row in ledger_width}
    assert widths["previous_tenant_id"] == (64, "YES"), (
        "the ledger must hold the widest tenant value in the schema (64) and must accept NULL, "
        "because NULL is a previous value worth recording"
    )

    project_column = await pg_session.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'organization_id'"
        ),
        {"t": _PROJECT},
    )
    assert project_column.scalar_one() == "YES"
    facts = await _role_facts(pg_session)
    assert facts["rolsuper"] is not None, facts


async def test_upgrade_run_twice_builds_the_same_schema_once(pg_session) -> None:  # noqa: ANN001
    """A second pass finds everything present and changes nothing."""
    await _drop_tenancy_schema(pg_session)
    await _run_revision(pg_session, "upgrade")
    await _run_revision(pg_session, "upgrade")

    organizations = await pg_session.scalar(text(f"SELECT count(*) FROM {_ORGANIZATION}"))
    assert organizations == 0, "the revision creates schema, never rows: the boot repair owns the data"
    indexes = await pg_session.scalar(
        text(
            "SELECT count(*) FROM pg_indexes WHERE tablename = :t AND indexname = "
            "'ix_oe_projects_project_organization_id'"
        ),
        {"t": _PROJECT},
    )
    assert indexes == 1, f"the project index was created {indexes} times"


# ── the repair ──────────────────────────────────────────────────────────────


async def test_the_repair_reports_zero_on_a_database_without_the_schema(pg_session) -> None:  # noqa: ANN001
    """A boot can happen before the tables exist, and that is a no-op, not a crash."""
    await _drop_tenancy_schema(pg_session)
    assert await _repair(pg_session) == 0


async def test_an_existing_organization_is_adopted_and_not_duplicated(pg_session) -> None:  # noqa: ANN001
    """The install's company is the one it already had.

    Creating a second ``default`` organization beside an existing one would split
    the install in two, and nothing would report it: readiness counts NULL rows and
    person-named rows, not organizations.
    """
    state = await _populate(pg_session)
    await _repair(pg_session)

    rows = (await pg_session.execute(text(f"SELECT id, name, slug FROM {_ORGANIZATION}"))).all()
    assert len(rows) == 1, f"the repair created an organization beside the existing one: {rows}"
    assert str(rows[0].id) == state.organization
    assert rows[0].name == "Existing Company", "an adopted organization was renamed"
    assert rows[0].slug != DEFAULT_ORGANIZATION_SLUG


async def test_a_fresh_database_gets_exactly_one_default_organization(pg_session) -> None:  # noqa: ANN001
    """The other shape: no organizations at all, so the default one is created."""
    from app.modules.users.models import User

    pg_session.add(
        User(
            id=uuid.uuid4(),
            email=f"first-{uuid.uuid4().hex[:8]}@backfill.test",
            hashed_password="not-a-real-hash",
            full_name="First",
            role="admin",
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    await pg_session.flush()

    assert await _repair(pg_session) > 0
    rows = (await pg_session.execute(text(f"SELECT name, slug, status FROM {_ORGANIZATION}"))).all()
    assert len(rows) == 1, rows
    assert rows[0].slug == DEFAULT_ORGANIZATION_SLUG
    assert rows[0].status == "active"


async def test_users_without_a_membership_get_an_active_default_one(pg_session) -> None:  # noqa: ANN001
    """Two users, two memberships, and the role is copied rather than invented."""
    state = await _populate(pg_session)
    await _repair(pg_session)

    # Scoped to the three users this test created, and that is the point of the
    # scoping rather than a way to make a number come out. This runs on the lane's
    # shared database, where an earlier file may have committed a user of its own;
    # the repair gives every user it finds a default membership, so an unscoped
    # count here measures the whole lane and not this test. Counting the rows that
    # belong to the people named below keeps the assertion about the repair.
    rows = (
        await pg_session.execute(
            text(
                f"SELECT user_id::text AS user_id, organization_id::text AS organization_id, role, status, is_default "
                f"  FROM {_MEMBERSHIP} "
                f" WHERE user_id::text IN (:owner, :colleague, :suspended) ORDER BY created_at, id"
            ),
            {"owner": state.owner, "colleague": state.colleague, "suspended": state.suspended},
        )
    ).all()
    assert len(rows) == 3, (
        "expected the pre-existing suspended row plus two new ones for the three users this test "
        f"created, got {len(rows)}"
    )

    created = [row for row in rows if row.user_id in (state.owner, state.colleague)]
    assert len(created) == 2
    for row in created:
        assert row.organization_id == state.organization
        assert row.status == MEMBERSHIP_ACTIVE
        assert row.is_default is True
    by_user = {row.user_id: row.role for row in created}
    assert by_user[state.owner] == "admin", "belonging to an organization must not change what a person may do"
    assert by_user[state.colleague] == "editor"


async def test_a_suspended_membership_is_left_exactly_as_it_was(pg_session) -> None:  # noqa: ANN001
    """A suspension is somebody's decision, and a boot path may not undo it.

    The repair only creates memberships for users with none at all. Giving this
    user an active one beside the suspended one would re-admit them to the company
    on every boot, with no audit trail and no request from anybody.
    """
    state = await _populate(pg_session)
    await _repair(pg_session)

    rows = (
        await pg_session.execute(
            text(f"SELECT status, is_default FROM {_MEMBERSHIP} WHERE user_id = :u"), {"u": state.suspended}
        )
    ).all()
    assert len(rows) == 1, f"the suspended user was given a second membership: {rows}"
    assert rows[0].status == "suspended"
    assert rows[0].is_default is False


async def test_a_tenant_naming_a_person_becomes_their_organization(pg_session) -> None:  # noqa: ANN001
    """The rewrite itself, on a table with nothing required and on the widest column."""
    state = await _populate(pg_session)
    changed = await _repair(pg_session)
    assert changed > 0

    for table, row_id in state.person_named.items():
        assert await _tenant_of(pg_session, table, row_id) == state.organization, (
            f"{table} still names a person instead of their organization"
        )


async def test_a_null_tenant_is_attributed_through_created_by_where_one_exists(pg_session) -> None:  # noqa: ANN001
    """A NULL with a creator is a question the data can answer."""
    state = await _populate(pg_session)
    await _repair(pg_session)

    tenant = await _tenant_of(pg_session, _NULLABLE_WITH_CREATED_BY, state.null_with_created_by)
    assert tenant == state.organization, "a row whose creator is known was left unowned"


async def test_a_null_tenant_with_nothing_to_attribute_it_from_stays_null(pg_session) -> None:  # noqa: ANN001
    """A NULL with no creator stays NULL, and stays visible to readiness.

    Inventing an owner here would be the permissive ``tenant_id IS NULL`` bypass
    wearing a different hat: a row nobody can account for, filed under a company
    nobody chose. ``null_tenant_rows`` in the readiness report is where it belongs
    until somebody who knows answers the question.
    """
    state = await _populate(pg_session)
    await _repair(pg_session)

    assert await _tenant_of(pg_session, _NULLABLE_NO_CREATED_BY, state.null_unattributable) is None


async def test_a_not_null_tenant_column_is_repointed_without_being_emptied(pg_session) -> None:  # noqa: ANN001
    """Ten of the 31 columns are NOT NULL: re-pointing them may not clear them.

    An implementation that set the organization and then filtered the row out, or
    one that wrote NULL for a user with no active membership, would raise here
    rather than in production.
    """
    state = await _populate(pg_session)
    await _repair(pg_session)

    row = (
        await pg_session.execute(
            text(f"SELECT tenant_id, name FROM {_NOT_NULL_TENANT} WHERE id = :id"), {"id": state.not_null_row}
        )
    ).one()
    assert row.tenant_id == state.organization
    assert row.name.startswith("block-graph-"), "the row was replaced rather than updated"


async def test_the_ledger_records_what_was_overwritten_including_null(pg_session) -> None:  # noqa: ANN001
    """Every overwritten value is written down before it is overwritten."""
    state = await _populate(pg_session)
    await _repair(pg_session)

    entries = (
        await pg_session.execute(
            text(f"SELECT table_name, row_id, previous_tenant_id FROM {_LEDGER} ORDER BY table_name, row_id")
        )
    ).all()
    by_row = {(entry.table_name, entry.row_id): entry.previous_tenant_id for entry in entries}

    assert len(by_row) == len(entries), "a (table_name, row_id) pair was recorded twice"
    for table, row_id in state.person_named.items():
        assert by_row[(table, row_id)] == state.owner, f"{table}: the previous value was not recorded"
    assert by_row[(_NOT_NULL_TENANT, state.not_null_row)] == state.owner
    assert by_row[(_NULLABLE_WITH_CREATED_BY, state.null_with_created_by)] is None, (
        "NULL is a previous value and the ledger has to hold it, or the downgrade cannot restore it"
    )
    assert (_NULLABLE_NO_CREATED_BY, state.null_unattributable) not in by_row, (
        "a row the repair did not change must not appear in the ledger"
    )


async def test_a_second_and_a_third_pass_change_nothing(pg_session) -> None:  # noqa: ANN001
    """Idempotence, measured rather than assumed.

    This is the assertion PostgreSQL makes easy to get wrong: it reports rows
    *matched*, not rows *changed*, so an ``UPDATE ... WHERE tenant_id IS NULL``
    whose subquery yields NULL re-matches the same row on every boot and reports
    progress forever. A repair that only ran once would pass every other test here.
    """
    state = await _populate(pg_session)
    # Read before the first pass, because every count below is about what the three
    # passes added and not about what the database holds. This is the lane's shared
    # database: an earlier file can commit a user, and the repair gives every user it
    # finds a default membership, so absolute counts here measure the whole lane.
    ledger_before = await pg_session.scalar(text(f"SELECT count(*) FROM {_LEDGER}"))
    first = await _repair(pg_session)
    assert first > 0

    second = await _repair(pg_session)
    third = await _repair(pg_session)
    assert second == 0, f"the second pass still changed {second} rows"
    assert third == 0, f"the third pass still changed {third} rows"

    ledger = await pg_session.scalar(text(f"SELECT count(*) FROM {_LEDGER}")) - ledger_before
    memberships = await pg_session.scalar(
        text(f"SELECT count(*) FROM {_MEMBERSHIP}  WHERE user_id::text IN (:owner, :colleague, :suspended)"),
        {"owner": state.owner, "colleague": state.colleague, "suspended": state.suspended},
    )
    organizations = await pg_session.scalar(
        text(
            f"SELECT count(DISTINCT organization_id) FROM {_MEMBERSHIP} "
            f" WHERE user_id::text IN (:owner, :colleague, :suspended)"
        ),
        {"owner": state.owner, "colleague": state.colleague, "suspended": state.suspended},
    )
    assert ledger == 4, f"three passes added {ledger} ledger entries, expected the 4 rows this test populated"
    assert memberships == 3, f"the three users this test created hold {memberships} memberships, expected 3"
    assert organizations == 1, (
        f"the repair spread this test's users over {organizations} organizations; both new memberships "
        "belong in the one that already existed"
    )

    # The rows that were honestly unresolvable are still unresolvable, and still
    # say so rather than having been quietly filled in on a later pass.
    assert await _tenant_of(pg_session, _NULLABLE_NO_CREATED_BY, state.null_unattributable) is None
    project = await pg_session.scalar(
        text(f"SELECT organization_id FROM {_PROJECT} WHERE id = :id"), {"id": state.orphan_project}
    )
    assert project is None


async def test_a_row_naming_a_suspended_member_is_left_alone(pg_session) -> None:  # noqa: ANN001
    """No active membership means no organization to name, so the value is not touched.

    Left person-named on purpose. That keeps ``tenant_is_user`` raised in the
    readiness report for as long as the data really is ambiguous, which is the
    honest state: an administrator has to say whether this person's rows belong to
    the company they were suspended from.
    """
    state = await _populate(pg_session)
    row_id = await _insert(pg_session, _NULLABLE_NO_CREATED_BY, tenant_id=state.suspended, kind="suspended-probe")
    await _repair(pg_session)

    assert await _tenant_of(pg_session, _NULLABLE_NO_CREATED_BY, row_id) == state.suspended


async def test_no_row_anywhere_still_names_a_person_who_has_an_organization(pg_session) -> None:  # noqa: ANN001
    """A sweep of all 31 tenant tables, not just the five the fixture wrote into.

    The five prove the shapes; this proves the coverage. Anything left behind is
    reported with its table and its owner, so a failure names the gap instead of
    failing a count.
    """
    from app.core.rls_setup import tenant_tables
    from app.database import Base

    state = await _populate(pg_session)
    await _repair(pg_session)

    declared = tenant_tables(Base)
    assert len(declared) == 31, f"the tenant inventory moved to {len(declared)} tables; this test pins 31"

    leftovers: list[tuple[str, str]] = []
    for table in declared:
        present = await pg_session.scalar(
            text("SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = 'tenant_id'"),
            {"t": table},
        )
        if present is None:
            continue
        rows = (
            await pg_session.execute(
                text(
                    f"SELECT t.tenant_id AS tenant_id FROM {table} t "
                    f"  JOIN oe_users_user u ON u.id::text = t.tenant_id "
                    f" WHERE EXISTS (SELECT 1 FROM {_MEMBERSHIP} m "
                    f"                WHERE m.user_id = u.id AND m.status = :active)"
                ),
                {"active": MEMBERSHIP_ACTIVE},
            )
        ).all()
        leftovers.extend((table, str(row.tenant_id)) for row in rows)

    assert leftovers == [], f"rows still name a person who has an organization: {leftovers}"


async def test_projects_inherit_their_owners_organization(pg_session) -> None:  # noqa: ANN001
    """The ``Organization -> Project`` edge, and the orphan that stays an orphan."""
    state = await _populate(pg_session)
    await _repair(pg_session)

    linked = await pg_session.scalar(
        text(f"SELECT organization_id::text FROM {_PROJECT} WHERE id = :id"), {"id": state.linked_project}
    )
    orphan = await pg_session.scalar(
        text(f"SELECT organization_id FROM {_PROJECT} WHERE id = :id"), {"id": state.orphan_project}
    )
    assert linked == state.organization
    assert orphan is None, "a project whose owner has no active membership was given an organization anyway"


# ── the downgrade ───────────────────────────────────────────────────────────


async def test_downgrade_puts_a_populated_database_back_and_removes_the_schema(
    pg_session,  # noqa: ANN001
) -> None:
    """Upgrade, repair, downgrade: values, counts and schema all return.

    This is the half that decides whether the change is reversible on a database
    that has been used, which is the only kind anybody has. The ledger is replayed
    before the tables are dropped, because dropping them first would remove the
    only record of what to restore.
    """
    state = await _populate(pg_session)
    await _run_revision(pg_session, "upgrade")
    await _repair(pg_session)

    for table, row_id in state.person_named.items():
        assert await _tenant_of(pg_session, table, row_id) == state.organization, "the repair did not run"

    await _run_revision(pg_session, "downgrade")

    for table, row_id in state.person_named.items():
        assert await _tenant_of(pg_session, table, row_id) == state.owner, f"{table} was not put back"
    assert await _tenant_of(pg_session, _NOT_NULL_TENANT, state.not_null_row) == state.owner
    assert await _tenant_of(pg_session, _NULLABLE_WITH_CREATED_BY, state.null_with_created_by) is None, (
        "a value restored from the ledger has to be able to come back as NULL"
    )
    assert await _tenant_of(pg_session, _NULLABLE_NO_CREATED_BY, state.null_unattributable) is None

    for table in (_ORGANIZATION, _MEMBERSHIP, _LEDGER):
        gone = await pg_session.scalar(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"), {"t": table}
        )
        assert gone is None, f"{table} survived the downgrade"
    column = await pg_session.scalar(
        text("SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = 'organization_id'"),
        {"t": _PROJECT},
    )
    assert column is None, "the project edge survived the downgrade"

    # The rows themselves are still there: a downgrade removes the tenancy schema,
    # not the data that was in it.
    for table, row_id in state.person_named.items():
        count = await pg_session.scalar(text(f"SELECT count(*) FROM {table} WHERE id = :id"), {"id": row_id})
        assert count == 1, f"{table} lost a row"


async def test_downgrade_on_an_install_that_never_ran_the_repair_changes_no_data(
    pg_session,  # noqa: ANN001
) -> None:
    """An empty ledger means an empty replay, not a failure and not a rewrite."""
    state = await _populate(pg_session)
    await _run_revision(pg_session, "upgrade")

    assert await pg_session.scalar(text(f"SELECT count(*) FROM {_LEDGER}")) == 0
    await _run_revision(pg_session, "downgrade")

    untouched = state.person_named[_NULLABLE_NO_CREATED_BY]
    assert await _tenant_of(pg_session, _NULLABLE_NO_CREATED_BY, untouched) == state.owner
    gone = await pg_session.scalar(
        text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"), {"t": _ORGANIZATION}
    )
    assert gone is None


async def test_the_role_observing_all_of_this_is_recorded(pg_session) -> None:  # noqa: ANN001
    """Who ran the repair, written down beside the result.

    A backfill observed as a superuser proves less than one observed as the role
    the application connects with, and the difference is invisible in a passing
    assertion unless it is written down.
    """
    await _populate(pg_session)
    await _repair(pg_session)

    facts = await _role_facts(pg_session)
    assert facts["current_user"], facts
    assert facts["current_user"] == facts["session_user"], f"the repair ran under a role switch: {facts}"
    assert isinstance(facts["rolsuper"], bool), facts


def _codes(report: dict[str, object]) -> list[str]:
    """The blocker codes in a readiness report, in the order the report gives them."""
    return [str(blocker["code"]) for blocker in report["blockers"]]  # type: ignore[union-attr,index]


async def test_the_strict_gate_opens_only_when_the_data_proves_ownership(pg_session) -> None:  # noqa: ANN001
    """Readiness measured across the repair, on a populated install.

    Phase 02 could not clear ``tenant_is_user`` without weakening the check, because
    on a populated install the tenant columns really did hold people. This measures
    the two halves of the answer Phase 02b gives instead: the backfill re-points every
    person-shaped tenant at an organization, which is what makes the data prove
    ownership, and the gate stays shut for as long as it honestly must.

    ``apply_rls`` is deliberately not called here. ``CREATE ROLE`` is not
    transactional and this session is rolled back when the test ends, so the
    enable/refuse/rollback cycle is measured against a real cluster in
    ``tests/pg/test_rls_strict_mode_is_refused_until_the_database_is_ready_and_rolls_back.py``,
    driven by exactly this report. What that file cannot see, and this one can, is
    that the tenancy backfill is what moves the report - and that it does not move it
    by inventing an owner for a row nobody can account for.
    """
    from app.core.rls_setup import rls_readiness_report, tenant_tables
    from app.database import Base

    tables = tenant_tables(Base)
    # The pg lane imports every module, so the tenant table set is the real one; an
    # empty list here would make every assertion below vacuously true.
    assert tables, "no tenant tables were discovered"

    # Recorded beside the observations rather than assumed: this session is the
    # connecting superuser, which is why the report is what is under test here and
    # enforcement is not. A superuser bypasses every policy.
    facts = await _role_facts(pg_session)
    assert facts["rolsuper"] is True, facts

    conn = await pg_session.connection()
    state = await _populate(pg_session)

    before = await rls_readiness_report(conn, tables)
    assert before["ready_for_strict"] is False, before
    assert "tenant_is_user" in _codes(before), _codes(before)
    assert "null_tenant_rows" in _codes(before), _codes(before)

    assert await _repair(pg_session) > 0

    after = await rls_readiness_report(conn, tables)
    # The blocker Phase 02 named is gone, and not because the check was relaxed: no
    # tenant column holds a person's id any more.
    assert "tenant_is_user" not in _codes(after), _codes(after)
    # The gate is still shut, and still honestly: this install has a row nobody can
    # account for. Attributing it inside the backfill would be the permissive
    # ``tenant_id IS NULL`` bypass wearing a different hat.
    assert after["ready_for_strict"] is False, after
    assert "null_tenant_rows" in _codes(after), _codes(after)
    assert await _tenant_of(pg_session, _NULLABLE_NO_CREATED_BY, state.null_unattributable) is None

    # Somebody who knows answers the question, explicitly, and the gate opens. That is
    # the only route to ``ready_for_strict`` on a populated install: a decision,
    # recorded as data, rather than a relaxation of the check.
    await pg_session.execute(
        text(f"UPDATE {_NULLABLE_NO_CREATED_BY} SET tenant_id = :org WHERE id = :id"),
        {"org": state.organization, "id": state.null_unattributable},
    )
    resolved = await rls_readiness_report(conn, tables)
    assert resolved["blockers"] == [], resolved["blockers"]
    assert resolved["ready_for_strict"] is True, resolved
    assert await _tenant_of(pg_session, _NULLABLE_NO_CREATED_BY, state.null_unattributable) == state.organization

    # And the report is a measurement, not a latch: one more row nobody can account
    # for closes the gate again. This is what "refusal still works with an injected
    # blocker" means for a report rather than for an installed policy.
    injected = await _insert(pg_session, _NULLABLE_NO_CREATED_BY, tenant_id=None, kind="injected-blocker")
    closed = await rls_readiness_report(conn, tables)
    assert closed["ready_for_strict"] is False, closed
    assert "null_tenant_rows" in _codes(closed), _codes(closed)
    assert await _tenant_of(pg_session, _NULLABLE_NO_CREATED_BY, injected) is None
