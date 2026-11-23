# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The participant grant table, built by the revision and by ``create_all``, on a real server.

ADR 006 stage 1 adds one table: ``oe_projects_participant_grant``. Nothing about
it is a data transformation, so what has to be proven is narrower and stricter
than a backfill test - the schema has to be *the same schema* however it arrived.

This product does not run ``alembic upgrade head`` against an existing database.
``postgres_auto_migrate`` creates missing tables with ``create_all`` and then
stamps head, and ``alembic/env.py`` builds a blank server the same way, so the
revision is reached by installations that already have the table and by sites
that run alembic deliberately. Two install shapes that disagree about a
constraint name are not a cosmetic problem: the boot heal in
``app.core.postgres_migrator`` compares the names the models declare against the
names the catalog holds, and a constraint it cannot recognise is added a second
time on every boot. ``_effective_name`` exists because that already happened to
a check constraint whose wrapped name exceeded 63 characters and was stored
hash-mangled.

So the central test here is a catalog comparison rather than a list of
assertions about individual names: snapshot what ``create_all`` built, drop it,
let ``upgrade()`` rebuild it, snapshot again, and compare the two snapshots
column by column, index by index and constraint by constraint, definitions
included. A name that is merely *present* on both sides proves less than a
definition that is *identical*, because PostgreSQL normalises what it stores -
which is also why the comparison is against the catalog and not against the SQL
either side emitted.

Four reasons this runs against the embedded PostgreSQL 16 and not a stand-in:

* the partial unique index is the constraint the whole design rests on, and
  ``WHERE status <> 'revoked'`` is a PostgreSQL predicate. A fake can prove the
  revision calls ``create_index``; only a server can prove a second live grant is
  refused and a re-grant after a revocation is accepted.
* the check constraints on ``scope`` and ``status`` have to refuse a value
  nobody can interpret. On a server that is an ``IntegrityError`` with a name in
  it; anywhere else it is a claim.
* the downgrade has to be shown removing the table from a database that holds
  grants, projects, organizations and audit rows, and leaving all of the others
  standing. A rollback-only fixture cannot tell "removed" from "never happened".
* the identifier limit is a PostgreSQL limit, and the two names this table could
  not leave to the naming convention (69 and 91 characters) are the reason every
  name in it is spelled out.

Every observation records ``current_user`` and ``rolsuper`` beside it, because a
result observed as a superuser is not evidence about the role the application
connects with - and this file's DDL *is* run as the connecting superuser, which
is a fact worth stating rather than leaving implicit: ``oe_app`` cannot create a
table, and a migration that pretended otherwise would be a migration that fails
on an installation that got its roles provisioned.
"""

from __future__ import annotations

import importlib.util
import pathlib
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.rls import APP_ROLE

pytestmark = pytest.mark.asyncio

_REVISION_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v3326_project_participant_grant.py"
)

_GRANT = "oe_projects_participant_grant"
_PROJECT = "oe_projects_project"
_ORGANIZATION = "oe_users_organization"
_USER = "oe_users_user"
_ACTIVITY = "oe_activity_log"


def _model_columns() -> list[str]:
    """The columns the model declares, in the order the database will store them.

    Read off the model rather than written down here, because a list in a test is
    a second copy of a fact and the two drift apart silently. ``Base`` declares
    ``id``, ``created_at`` and ``updated_at``, and an inherited column lands after
    the subclass's own ones, so the stored order is not the order the ADR's table
    lists them in - which is exactly the kind of thing a hand-written tuple gets
    wrong and then "fixes" by reordering the assertion.
    """
    from app.modules.projects.models import ProjectParticipantGrant

    return [column.name for column in ProjectParticipantGrant.__table__.columns]


# ── plumbing ────────────────────────────────────────────────────────────────


def _load_revision():  # noqa: ANN202
    """Import the revision file, which is not on any import path."""
    spec = importlib.util.spec_from_file_location("v3326_project_participant_grant", _REVISION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run_revision(session, direction: str) -> None:  # noqa: ANN001
    """Execute ``upgrade()`` or ``downgrade()`` on the session's own connection.

    On the session's connection rather than a fresh one so the DDL joins the
    fixture's transaction and is rolled back with it. The operations proxy is
    what makes the module-level ``op`` in the revision resolve to this
    connection.

    Configured with ``target_metadata`` because ``alembic/env.py`` configures it
    that way, and because it changes what this revision produces: the metadata
    carries the naming convention in ``app.database``, and the convention for a
    check constraint is ``ck_%(table_name)s_%(constraint_name)s``, which is
    applied to a constraint that already has a name. A context without the
    metadata stores the short name the revision declares, ``create_all`` stores
    the wrapped one, and the two installations then disagree about an identifier
    the boot heal matches on. Driving the revision the way the product drives it
    is what makes the comparison below mean something.
    """
    from app.database import Base

    module = _load_revision()
    connection = await session.connection()

    def _apply(sync_connection) -> None:  # noqa: ANN001
        context = MigrationContext.configure(sync_connection, opts={"target_metadata": Base.metadata})
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


async def _catalog(session) -> dict[str, Any]:  # noqa: ANN001
    """Everything PostgreSQL stores about the grant table, as comparable values.

    Read from the catalogs rather than from ``information_schema`` alone, because
    the two facts that matter most here - the predicate of a partial index and
    the definition of a check constraint - are only in ``pg_indexes`` and
    ``pg_get_constraintdef``, and both are normalised by the server. Comparing
    normalised values is what makes "the same schema however it arrived" a
    statement about the database rather than about the SQL text this repository
    happens to emit today.
    """
    columns = (
        await session.execute(
            text(
                "SELECT column_name, data_type, character_maximum_length, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t "
                "ORDER BY ordinal_position"
            ),
            {"t": _GRANT},
        )
    ).all()
    indexes = (
        await session.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = :t "
                "ORDER BY indexname"
            ),
            {"t": _GRANT},
        )
    ).all()
    constraints = (
        await session.execute(
            text(
                "SELECT c.conname, c.contype, pg_catalog.pg_get_constraintdef(c.oid, true) AS definition "
                "FROM pg_catalog.pg_constraint c "
                "JOIN pg_catalog.pg_class r ON r.oid = c.conrelid "
                "JOIN pg_catalog.pg_namespace n ON n.oid = r.relnamespace "
                "WHERE n.nspname = 'public' AND r.relname = :t ORDER BY c.contype, c.conname"
            ),
            {"t": _GRANT},
        )
    ).all()
    return {
        "columns": [tuple(row) for row in columns],
        "indexes": [tuple(row) for row in indexes],
        "constraints": [tuple(row) for row in constraints],
    }


def _schema_differences(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """What differs between two catalog snapshots, empty when they are the same schema.

    Columns are compared as a set and everything else exactly. The reason is in
    the docstring of the test that builds the second snapshot: ``Base`` declares
    ``id``, ``created_at`` and ``updated_at``, and an inherited column is stored
    after the subclass's own, so ``create_all`` puts those three last and a
    revision that declares them in reading order puts them first. Every other
    fact about a column has to match - name, type, width, nullability, default -
    and so does every index and constraint *definition*, which is the part a
    name-only comparison cannot see.
    """
    differences: dict[str, Any] = {}
    if sorted(before["columns"]) != sorted(after["columns"]):
        differences["columns"] = {"before": before["columns"], "after": after["columns"]}
    if before["indexes"] != after["indexes"]:
        differences["indexes"] = {"before": before["indexes"], "after": after["indexes"]}
    if before["constraints"] != after["constraints"]:
        differences["constraints"] = {"before": before["constraints"], "after": after["constraints"]}
    return differences


async def _table_exists(session, table: str) -> bool:  # noqa: ANN001
    return bool(
        await session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = :t)"
            ),
            {"t": table},
        )
    )


async def _drop_grant_table(session) -> None:  # noqa: ANN001
    """Remove what the revision creates, so ``upgrade()`` has something to build.

    The session's schema arrives from ``create_all``, so the table exists before
    a test starts. Dropping it is what makes the revision the thing under test
    rather than a no-op that passes.
    """
    await session.execute(text(f'DROP TABLE IF EXISTS "{_GRANT}" CASCADE'))


class _Install:
    """A populated database: two companies, three people, a project, a grant."""

    def __init__(self) -> None:
        self.session: Any = None
        #: Owns the project, and so owns the authority to grant on it.
        self.owner_user = ""
        #: The person who wrote the grant row. Deliberately not the owner: the
        #: cascade test deletes this user, and deleting the owner would take the
        #: project - and with it the grant - through a different foreign key.
        self.author_user = ""
        #: A member of the grantee company, so the install has a person the grant
        #: authorizes and a membership row the downgrade must leave alone.
        self.grantee_user = ""
        self.owner_org = ""
        self.grantee_org = ""
        self.membership = ""
        self.project = ""
        self.grant = ""


async def _populate(session) -> _Install:  # noqa: ANN001, ANN201
    """Build an install that holds grants, in the shape a live one has them.

    Raw SQL for every row, so nothing here depends on a Python-side default the
    ORM would have filled in: a migration runs against rows written by whatever
    client wrote them, and a test that only inserts rows the model would accept
    is testing the model.

    Which columns that means was found by asking the schema, not by reading the
    models - ``information_schema.columns`` for ``is_nullable = 'NO' AND
    column_default IS NULL``, which is the question "what must this INSERT
    name". On ``oe_projects_project`` the answer is nine columns, and four of
    them (``description``, ``region``, ``classification_standard``, ``locale``)
    are filled by the ORM and not by the database, so a first run of this test
    found them the expensive way.
    """
    state = _Install()
    state.session = session

    state.owner_user = str(uuid.uuid4())
    state.author_user = str(uuid.uuid4())
    state.grantee_user = str(uuid.uuid4())
    for user_id, email in (
        (state.owner_user, f"owner-{uuid.uuid4().hex[:8]}@grants.test"),
        (state.author_user, f"author-{uuid.uuid4().hex[:8]}@grants.test"),
        (state.grantee_user, f"grantee-{uuid.uuid4().hex[:8]}@grants.test"),
    ):
        await session.execute(
            text(
                f'INSERT INTO "{_USER}" (id, email, hashed_password, full_name, role, locale, is_active, metadata) '
                "VALUES (:id, :email, 'not-a-real-hash', 'Grant test', 'admin', 'en', true, '{}')"
            ),
            {"id": user_id, "email": email},
        )

    state.owner_org = str(uuid.uuid4())
    state.grantee_org = str(uuid.uuid4())
    for org_id, slug in (
        (state.owner_org, f"grant-owner-{uuid.uuid4().hex[:8]}"),
        (state.grantee_org, f"grant-grantee-{uuid.uuid4().hex[:8]}"),
    ):
        await session.execute(
            text(f"INSERT INTO \"{_ORGANIZATION}\" (id, name, slug, status) VALUES (:id, :name, :slug, 'active')"),
            {"id": org_id, "name": slug, "slug": slug},
        )

    state.membership = str(uuid.uuid4())
    await session.execute(
        text(
            'INSERT INTO "oe_users_membership" (id, user_id, organization_id, role, status, is_default) '
            "VALUES (:id, :user, :org, 'editor', 'active', true)"
        ),
        {"id": state.membership, "user": state.grantee_user, "org": state.grantee_org},
    )

    state.project = str(uuid.uuid4())
    await session.execute(
        text(
            f'INSERT INTO "{_PROJECT}" (id, name, description, region, classification_standard, currency, '
            "locale, status, owner_id, organization_id, metadata) "
            "VALUES (:id, :name, 'A project a second company participates in', 'international', 'none', "
            "'EUR', 'en', 'active', :owner, :org, '{}')"
        ),
        {
            "id": state.project,
            "name": f"Grant project {state.project[:6]}",
            "owner": state.owner_user,
            "org": state.owner_org,
        },
    )

    state.grant = await _insert_grant(
        session,
        project_id=state.project,
        grantee_organization_id=state.grantee_org,
        granted_by_user_id=state.author_user,
        granted_on_behalf_of_organization_id=state.owner_org,
    )
    return state


async def _insert_grant(
    session,  # noqa: ANN001
    *,
    project_id: str,
    grantee_organization_id: str,
    granted_by_user_id: str | None,
    granted_on_behalf_of_organization_id: str,
    scope: str = "view",
    status: str = "active",
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> str:
    """One grant row by raw SQL. Returns its id.

    The window ends are ``datetime`` values and not ISO strings, because the
    driver binds parameters by Python type before the server sees them: asyncpg
    refuses a ``str`` for a ``timestamp with time zone`` argument whatever the
    SQL around it says, and a ``CAST`` in the statement does not reach a value
    the client library already rejected.
    """
    grant_id = str(uuid.uuid4())
    await session.execute(
        text(
            f'INSERT INTO "{_GRANT}" (id, project_id, grantee_organization_id, granted_by_user_id, '
            "granted_on_behalf_of_organization_id, scope, status, valid_from, valid_until, metadata) "
            "VALUES (:id, :project, :grantee, :by, :behalf, :scope, :status, :valid_from, :valid_until, '{}')"
        ),
        {
            "id": grant_id,
            "project": project_id,
            "grantee": grantee_organization_id,
            "by": granted_by_user_id,
            "behalf": granted_on_behalf_of_organization_id,
            "scope": scope,
            "status": status,
            "valid_from": valid_from,
            "valid_until": valid_until,
        },
    )
    return grant_id


# ── the revision against the schema create_all already built ────────────────


async def test_a_database_create_all_built_reaches_the_revision_and_does_nothing(pg_session) -> None:  # noqa: ANN001
    """The install shape this product actually has: the table is already there.

    ``postgres_auto_migrate`` creates missing tables and stamps head, so a
    database booted from this release reaches the revision holding the table.
    The revision must then be inert - not merely quiet, but inert: no second
    index, no second constraint, no dropped row.
    """
    before = await _catalog(pg_session)
    rows_before = await pg_session.scalar(text(f'SELECT count(*) FROM "{_GRANT}"'))

    await _run_revision(pg_session, "upgrade")

    after = await _catalog(pg_session)
    rows_after = await pg_session.scalar(text(f'SELECT count(*) FROM "{_GRANT}"'))
    facts = await _role_facts(pg_session)

    assert after == before, "the revision changed a schema create_all had already built"
    assert rows_after == rows_before
    # Stated rather than assumed: the DDL runs as the connecting superuser, and
    # ``oe_app`` could not run it. A reader who sees rolsuper=True here is seeing
    # the truth about migrations and not a hole in the test.
    assert facts["rolsuper"] is True, facts
    assert facts["current_user"] != APP_ROLE, facts


async def test_the_revision_builds_the_same_table_create_all_built(pg_session) -> None:  # noqa: ANN001
    """The two install shapes are indistinguishable, measured against the catalog.

    This is the assertion the rest of the file depends on. A migration that built
    a *similar* table would pass every test that only asks whether a column
    exists, and would leave the boot heal unable to recognise the constraints the
    database already has - which is how a constraint gets added twice, once per
    boot, on every installation that took the migration path.
    """
    created = await _catalog(pg_session)
    expected = _model_columns()
    assert [name for name, *_ in created["columns"]] == expected, (
        f"create_all did not build the columns the model declares, in the order it declares them.\n"
        f"  model:  {expected}\n"
        f"  server: {[name for name, *_ in created['columns']]}"
    )

    await _drop_grant_table(pg_session)
    assert not await _table_exists(pg_session, _GRANT)

    await _run_revision(pg_session, "upgrade")
    migrated = await _catalog(pg_session)
    facts = await _role_facts(pg_session)

    # Columns compared as a set, and the reason is worth stating rather than
    # hiding behind a ``sorted()``: ``Base`` declares ``id``, ``created_at`` and
    # ``updated_at``, and an inherited column is appended after the subclass's
    # own ones, so ``create_all`` stores those three LAST while a revision that
    # declares them in reading order stores them first. Every other fact about a
    # column - name, type, width, nullability, default - has to match exactly,
    # and does. Ordinal position matches nothing in this product: every raw
    # INSERT in the tree names its columns, alembic's autogenerate compares
    # columns by name, and the boot heal asks whether a column exists. Writing
    # the three inherited columns last in the revision would make the two paths
    # byte-identical and would also make this the only one of 430 revisions that
    # declares a primary key after the columns it keys, so the difference is
    # documented here instead of removed there.
    assert sorted(migrated["columns"]) == sorted(created["columns"]), (
        f"columns differ.\n  create_all: {created['columns']}\n  revision:   {migrated['columns']}"
    )
    assert {name for name, *_ in migrated["columns"]} == set(expected)
    assert not _schema_differences(created, migrated), _schema_differences(created, migrated)
    assert facts["rolsuper"] is True, facts


async def test_every_identifier_the_revision_writes_fits_in_63_characters(pg_session) -> None:  # noqa: ANN001
    """PostgreSQL's limit, checked against what the server stored.

    ``tests/unit/test_migration_identifier_length.py`` scans the revision's
    source for long literals, which catches a long name before release. This
    catches the other half: a name that is short in the source and long in the
    database, because the metadata naming convention wrapped it. The three check
    constraints here carry the table name twice for exactly that reason, and the
    wrapped forms are 59 and 60 characters - under the limit, with a margin
    worth knowing the size of.
    """
    await _run_revision(pg_session, "upgrade")
    catalog = await _catalog(pg_session)

    names = [name for name, *_ in catalog["indexes"]]
    names += [name for name, *_ in catalog["constraints"]]
    facts = await _role_facts(pg_session)

    over = [(name, len(name)) for name in names if len(name) > 63]
    assert not over, f"PostgreSQL would have truncated or hash-mangled: {over}"
    # And the names are the ones the revision declares, not generated ones: a
    # hash-mangled identifier is also under 63 characters, so length alone does
    # not prove the name is the name this file asked for.
    assert all("_b8d8" not in name and len(name) < 63 for name in names), names
    assert facts["rolsuper"] is True, facts


async def test_upgrade_run_twice_builds_the_same_schema_once(pg_session) -> None:  # noqa: ANN001
    """Idempotence, which is what makes a boot-time revision safe to re-run."""
    await _drop_grant_table(pg_session)
    await _run_revision(pg_session, "upgrade")
    once = await _catalog(pg_session)

    await _run_revision(pg_session, "upgrade")
    twice = await _catalog(pg_session)
    facts = await _role_facts(pg_session)

    assert twice == once, "the second upgrade() added or replaced something the first one built"
    assert facts["rolsuper"] is True, facts


# ── what the constraints do on a real server ────────────────────────────────


async def test_one_live_grant_per_company_per_project_and_a_revoked_one_does_not_block_the_next(
    pg_session,  # noqa: ANN001
) -> None:
    """The partial unique index, which is the constraint the design rests on.

    Two halves, because they pull in opposite directions and a plain unique
    constraint would get one of them wrong: a second *live* grant for the same
    company on the same project is refused, and a *revoked* grant does not block
    the re-grant that replaces it. The second half is what keeps the history the
    ADR promises - revocation is an event, not a deletion - without leaving the
    live set ambiguous.
    """
    install = await _populate(pg_session)

    # Inside a savepoint. ``pg_session`` joins the fixture's outer transaction
    # with one of its own, so a bare rollback would take the populated install
    # with the refused statement, and the second half of this test would be
    # asserting about a database that no longer holds the first grant.
    with pytest.raises(IntegrityError) as refused:
        async with pg_session.begin_nested():
            await _insert_grant(
                pg_session,
                project_id=install.project,
                grantee_organization_id=install.grantee_org,
                granted_by_user_id=install.author_user,
                granted_on_behalf_of_organization_id=install.owner_org,
            )
    assert "uq_projects_participant_grant_live" in str(refused.value), str(refused.value)

    # Revoke the first, and the same company can be granted again: a new row, not
    # a resurrection of the old one, so both stay readable.
    await pg_session.execute(
        text(f"UPDATE \"{_GRANT}\" SET status = 'revoked', revoked_at = now() WHERE id = :id"),
        {"id": install.grant},
    )
    replacement = await _insert_grant(
        pg_session,
        project_id=install.project,
        grantee_organization_id=install.grantee_org,
        granted_by_user_id=install.author_user,
        granted_on_behalf_of_organization_id=install.owner_org,
        scope="contribute",
    )
    rows = (
        await pg_session.execute(
            text(f'SELECT id, status, scope FROM "{_GRANT}" ORDER BY created_at'),
        )
    ).all()
    facts = await _role_facts(pg_session)

    assert [(row.id, row.status, row.scope) for row in rows] == [
        (install.grant, "revoked", "view"),
        (replacement, "active", "contribute"),
    ], rows
    assert facts["rolsuper"] is True, facts


async def test_a_suspended_grant_also_occupies_the_live_slot(pg_session) -> None:  # noqa: ANN001
    """Suspended is not revoked, and the index treats it as still live.

    Owner decision 4 suspends grants when a project changes owner, pending
    review. A suspension has to be reversible without anybody re-deciding the
    grant, which means the row keeps its place: if a suspended grant freed the
    slot, the review would end with two rows for one company and the predicate
    would have to choose between them.
    """
    install = await _populate(pg_session)
    await pg_session.execute(
        text(f"UPDATE \"{_GRANT}\" SET status = 'suspended' WHERE id = :id"), {"id": install.grant}
    )

    with pytest.raises(IntegrityError) as refused:
        async with pg_session.begin_nested():
            await _insert_grant(
                pg_session,
                project_id=install.project,
                grantee_organization_id=install.grantee_org,
                granted_by_user_id=install.author_user,
                granted_on_behalf_of_organization_id=install.owner_org,
            )
    facts = await _role_facts(pg_session)

    assert "uq_projects_participant_grant_live" in str(refused.value), str(refused.value)
    assert facts["rolsuper"] is True, facts


async def test_the_vocabulary_and_the_window_are_refused_by_the_database_not_only_by_the_service(
    pg_session,  # noqa: ANN001
) -> None:
    """Three refusals, each named by the constraint that refused it.

    A scope outside ``view`` / ``contribute`` / ``manage`` is a grant no reader
    can interpret; a status outside the three is a state no screen can draw; a
    window that ends before it starts is a grant that is never live and never
    expiring. The service refuses all three with a 422, and the database refuses
    them too, because a write path nobody thought of - a repair, a script, an
    import - reaches the table without going through the service.
    """
    install = await _populate(pg_session)
    refusals: dict[str, str] = {}

    for label, kwargs in (
        ("scope", {"scope": "read"}),  # the vocabulary ADR 006 first proposed; decision 7 replaced it
        ("status", {"status": "offered"}),  # the accept step decision 2 removed
        (
            "window",
            {"valid_from": datetime(2026, 6, 1, tzinfo=UTC), "valid_until": datetime(2026, 1, 1, tzinfo=UTC)},
        ),
    ):
        with pytest.raises(IntegrityError) as refused:
            async with pg_session.begin_nested():
                await _insert_grant(
                    pg_session,
                    project_id=install.project,
                    grantee_organization_id=str(uuid.uuid4()),  # a fresh grantee, so only the value is wrong
                    granted_by_user_id=install.author_user,
                    granted_on_behalf_of_organization_id=install.owner_org,
                    **kwargs,
                )
        refusals[label] = str(refused.value)

    facts = await _role_facts(pg_session)

    assert "ck_participant_grant_scope" in refusals["scope"], refusals["scope"]
    assert "ck_participant_grant_status" in refusals["status"], refusals["status"]
    assert "ck_participant_grant_window" in refusals["window"], refusals["window"]
    assert facts["rolsuper"] is True, facts


async def test_the_foreign_keys_cascade_where_the_design_says_they_do(pg_session) -> None:  # noqa: ANN001
    """Deleting a project takes its grants; deleting a person does not.

    Two different rules and both are load-bearing. A grant on a project that no
    longer exists authorizes access to nothing, so it goes with the project. A
    grant whose author has been deleted is still a fact about two companies, so
    the row stays and only the name of the person is lost - deleting a user must
    not delete the record that a company was given access to a project.
    """
    install = await _populate(pg_session)

    await pg_session.execute(text(f'DELETE FROM "{_USER}" WHERE id = :id'), {"id": install.author_user})
    author = await pg_session.scalar(
        text(f'SELECT granted_by_user_id FROM "{_GRANT}" WHERE id = :id'), {"id": install.grant}
    )
    still_there = await pg_session.scalar(
        text(f'SELECT count(*) FROM "{_GRANT}" WHERE id = :id'), {"id": install.grant}
    )

    await pg_session.execute(text(f'DELETE FROM "{_PROJECT}" WHERE id = :id'), {"id": install.project})
    # Counted for *this* project rather than over the table. The lane shares one
    # database across every file in ``tests/pg`` and isolates by rolling back, so a
    # global count is an assertion about every other test's housekeeping as well as
    # about this cascade - and the claim here is only that a grant on a deleted
    # project went with it.
    after_project = await pg_session.scalar(
        text(f'SELECT count(*) FROM "{_GRANT}" WHERE project_id = :id'), {"id": install.project}
    )
    facts = await _role_facts(pg_session)

    assert author is None, "deleting the author should null the reference, not remove the grant"
    assert still_there == 1
    assert after_project == 0, "a grant on a deleted project should have gone with it"
    assert facts["rolsuper"] is True, facts


# ── the downgrade, on a database that has something to lose ─────────────────


async def test_downgrade_removes_the_grant_table_and_leaves_everything_else_standing(
    pg_session,  # noqa: ANN001
) -> None:
    """Reversibility, on a populated database, with the collateral counted.

    The grant rows are lost and that is the named limit of this downgrade: there
    is no ledger to replay because nothing was rewritten on the way up, and the
    table is the data. What has to survive is everything the table pointed *at* -
    the project, the two organizations, the two users - and the audit row that
    records the grant, which is what makes re-granting a reconstruction from a
    record rather than a guess. A ``DROP TABLE`` that took any of them with it
    would be a downgrade that destroys an installation instead of stepping it
    back.
    """
    install = await _populate(pg_session)
    await pg_session.execute(
        text(
            f'INSERT INTO "{_ACTIVITY}" (id, entity_type, entity_id, action, module, metadata, created_at, updated_at) '
            "VALUES (:id, 'project_participant_grant', :entity, 'granted', 'projects', '{}', now(), now())"
        ),
        {"id": str(uuid.uuid4()), "entity": install.grant},
    )
    audit_rows = await pg_session.scalar(text(f'SELECT count(*) FROM "{_ACTIVITY}"'))
    # Counted before as well as after, and compared with itself rather than with a
    # literal. This lane builds one database for the whole of ``tests/pg`` and
    # isolates each test by rolling its transaction back, so "the projects table
    # holds one row" is a claim about every test that ran before this one as much
    # as about this downgrade - and it is the wrong claim to make. What the
    # downgrade has to leave alone is what was there when it started, so that is
    # what is measured, and the rows this install owns are then asked for by id:
    # a count that did not move says nothing was destroyed, and an id that still
    # resolves says *these* rows are the ones that survived.
    survived = {
        _PROJECT: (install.project,),
        _ORGANIZATION: (install.owner_org, install.grantee_org),
        _USER: (install.owner_user, install.author_user, install.grantee_user),
        "oe_users_membership": (install.membership,),
    }
    before = {table: await pg_session.scalar(text(f'SELECT count(*) FROM "{table}"')) for table in survived}

    await _run_revision(pg_session, "downgrade")
    facts = await _role_facts(pg_session)

    assert not await _table_exists(pg_session, _GRANT), "the downgrade left the table behind"
    after = {table: await pg_session.scalar(text(f'SELECT count(*) FROM "{table}"')) for table in survived}
    assert after == before, f"the downgrade took collateral with it: {before} -> {after}"
    for table, ids in survived.items():
        for row_id in ids:
            present = await pg_session.scalar(text(f'SELECT count(*) FROM "{table}" WHERE id = :id'), {"id": row_id})
            assert present == 1, f"{table} {row_id} did not survive the downgrade"
    assert await pg_session.scalar(text(f'SELECT count(*) FROM "{_ACTIVITY}"')) == audit_rows, (
        "the audit trail is the record that survives a downgrade; it must not go with the table"
    )
    assert facts["rolsuper"] is True, facts


async def test_downgrade_then_upgrade_returns_an_empty_table_and_a_working_one(
    pg_session,  # noqa: ANN001
) -> None:
    """The round trip, and what it costs.

    Downgrading and upgrading again has to leave a database that works: the
    table comes back with the same shape, empty, and a grant can be written into
    it. Empty is the honest result and the reason the audit trail matters - the
    grant that was there before the downgrade is not restored, and pretending
    otherwise in a test would be pretending otherwise in a runbook.
    """
    install = await _populate(pg_session)
    before = await _catalog(pg_session)

    await _run_revision(pg_session, "downgrade")
    await _run_revision(pg_session, "upgrade")
    after = await _catalog(pg_session)

    assert await pg_session.scalar(text(f'SELECT count(*) FROM "{_GRANT}"')) == 0
    assert not _schema_differences(before, after), _schema_differences(before, after)

    # And it is a working table, not only a present one: the same install can
    # grant again, which is what an operator does after stepping back and forward.
    new_grant = await _insert_grant(
        pg_session,
        project_id=install.project,
        grantee_organization_id=install.grantee_org,
        granted_by_user_id=install.author_user,
        granted_on_behalf_of_organization_id=install.owner_org,
        scope="manage",
    )
    row = (
        await pg_session.execute(text(f'SELECT scope, status FROM "{_GRANT}" WHERE id = :id'), {"id": new_grant})
    ).one()
    facts = await _role_facts(pg_session)

    assert (row.scope, row.status) == ("manage", "active")
    assert facts["rolsuper"] is True, facts


async def test_downgrade_on_a_database_that_never_had_the_table_is_not_an_error(pg_session) -> None:  # noqa: ANN001
    """A downgrade is run by an operator under pressure, on an install of unknown shape."""
    await _drop_grant_table(pg_session)
    assert not await _table_exists(pg_session, _GRANT)

    await _run_revision(pg_session, "downgrade")
    facts = await _role_facts(pg_session)

    assert not await _table_exists(pg_session, _GRANT)
    assert facts["rolsuper"] is True, facts


async def test_the_grant_table_is_not_in_the_row_level_security_surface(pg_session) -> None:  # noqa: ANN001
    """No ``tenant_id`` column, so no policy - and that is the design, not a gap.

    A grant is a statement about the relation between two tenants, not a row
    inside one. Giving the table a ``tenant_id`` would put it in
    ``tenant_tables()`` and install a policy comparing the table's own tenant
    with the caller's, which would hide every grant from the grantee it names:
    the one reader that has to see it. This asserts the consequence rather than
    the intention, so that adding the column later fails here and gets decided
    rather than silently re-shaping the RLS surface.
    """
    from app.core.rls_setup import tenant_tables
    from app.database import Base

    tables = tenant_tables(Base)
    columns = [name for name, *_ in (await _catalog(pg_session))["columns"]]
    facts = await _role_facts(pg_session)

    assert _GRANT not in tables, "the grant table entered the policied surface; read this test's docstring first"
    assert "tenant_id" not in columns, columns
    assert facts["rolsuper"] is True, facts
