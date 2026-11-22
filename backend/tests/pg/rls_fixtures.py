"""Shared builders for the row-level-security tests in the PostgreSQL lane.

These tests are the only place in the suite where the tenant policy is observed
rather than reasoned about. A faked connection can prove what SQL
:mod:`app.core.rls_setup` *emits*; it cannot prove what PostgreSQL *does* with
it, and the difference is the whole security claim: whether a policy installed
by this code actually hides one tenant's rows from another when the query runs
as the restricted role.

Everything here therefore runs against the lane's real embedded PostgreSQL 16
cluster, and every read or write that is meant to be policied is issued on a
connection that has done ``SET LOCAL ROLE "oe_app"``, which is how the
application itself enters the policied role in :mod:`app.core.rls`. The
cluster's session user is the ``postgres`` superuser, so each helper also
reports ``current_user`` and that user's ``rolsuper`` flag: an assertion about
isolation is only worth reading if it also shows the reader which role produced
it, and a superuser bypasses every policy silently.

Probe tables are used instead of the application's own. The cluster and its
schema are shared by every test in the lane, so enabling row-level security on a
real table would be visible to unrelated suites, and the six reference tables in
``_NEVER_POLICY`` are deliberately never policied at all. Probe tables are
created committed (a separate connection has to see them), dropped in teardown,
and named so they cannot collide with a model.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from app.core.rls import APP_ROLE, GRANTED_GUC_NAME, GUC_NAME, SYSTEM_ROLE
from app.core.rls_setup import (
    _GRANT_POLICY_NAME,
    _POLICY_NAME,
    _role_setup_statements,
    policy_is_strict,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

#: Tenant-owned probe table. Stands in for any model carrying ``tenant_id``.
PROBE_TENANT = "oe_rls_probe_tenant_row"
#: Second tenant-owned probe table, so a policy decision can be shown to apply
#: per table rather than once for the database.
PROBE_SECOND = "oe_rls_probe_second_row"
#: Probe stand-in for ``oe_users_user``, so a tenant value can be recognised as
#: a user id without writing to the application's real user table.
PROBE_USERS = "oe_rls_probe_users"
#: Project-scoped probe tables: a ``tenant_id`` *and* a ``project_id``, which is
#: the shape a participant grant can widen (ADR 006). Two of them, for the same
#: reason there are two tenant probes - a policy decision has to be shown to
#: apply per table rather than once for the database.
PROBE_PROJECT = "oe_rls_probe_project_row"
PROBE_PROJECT_SECOND = "oe_rls_probe_project_second_row"

#: Project identifiers, and deliberately not UUID-shaped for the same reason the
#: tenant identifiers are not: a value that reads as a project rather than as a
#: person keeps the two confusions ADR 005 and ADR 006 each exist to prevent
#: from being reproduced inside the test that guards them.
PROJECT_ALPHA = "project-alpha-probe"
PROJECT_BETA = "project-beta-probe"

#: Tenant identifiers. Deliberately not UUID-shaped: the readiness report treats
#: a tenant value that matches a row in the users table as the ``tenant_is_user``
#: blocker, and these must be readable as organisations rather than as people.
TENANT_A = "tenant-alpha-probe"
TENANT_B = "tenant-beta-probe"
#: The label given to a row whose ``tenant_id`` is NULL: a legacy record with no
#: owner, which is exactly what the two policy modes disagree about.
UNOWNED_LABEL = "legacy-unowned"


@dataclass(frozen=True)
class RoleOutcome:
    """What one statement did when issued as the restricted role.

    ``current_user`` and ``rolsuper`` travel with the result so a test can assert
    which role actually ran the statement. ``error`` holds the first line of a
    raised database error, because a refusal is a result worth asserting on and
    not something to let escape as an exception.
    """

    rows: list[Any] | None
    rowcount: int
    error: str | None
    current_user: str
    session_user: str
    rolsuper: bool


class _ProbeTable:
    """The smallest thing :func:`app.core.rls_setup.tenant_tables` will accept.

    It reads ``table.name`` and asks whether ``tenant_id`` is in
    ``table.columns``, so a name and a column-name container are enough. Using a
    stand-in rather than the real ``Base`` is what keeps row-level security off
    the application's own tables in a cluster the whole lane shares.
    """

    def __init__(self, name: str, *, tenant: bool = True) -> None:
        self.name = name
        self.columns = {"tenant_id": None, "id": None, "label": None} if tenant else {"id": None, "label": None}


def probe_base(*names: str) -> SimpleNamespace:
    """A fake declarative ``Base`` carrying probe tables with a ``tenant_id``."""
    tables = [_ProbeTable(name) for name in names]
    return SimpleNamespace(metadata=SimpleNamespace(sorted_tables=tables, tables={t.name: t for t in tables}))


class _ProjectProbeTable(_ProbeTable):
    """A probe table that :func:`app.core.rls_setup.both_column_tables` accepts.

    That function asks for ``tenant_id`` and ``project_id`` in ``table.columns``,
    so the stand-in carries both. Inheriting the tenant probe's shape rather than
    writing a second one keeps the two arms of the predicate being tested against
    the same kind of table, which is the point: the grant arm is an addition to
    the tenant arm and not a different mechanism.
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.columns = {**self.columns, "project_id": None}


def project_probe_base(*names: str) -> SimpleNamespace:
    """A fake declarative ``Base`` carrying probe tables with both columns."""
    tables = [_ProjectProbeTable(name) for name in names]
    return SimpleNamespace(metadata=SimpleNamespace(sorted_tables=tables, tables={t.name: t for t in tables}))


async def ensure_roles(conn: AsyncConnection) -> None:
    """Create and grant the RLS roles exactly as provisioning does.

    Runs the repository's own statements rather than a test-local approximation,
    so the attributes and grants under test are the shipped ones. Idempotent: the
    role creation is guarded on ``pg_roles`` and the grants are re-runnable.
    """
    for statement in _role_setup_statements():
        await conn.execute(text(statement))


async def create_probe_tables(conn: AsyncConnection, *names: str) -> None:
    """Create committed probe tables the restricted role can reach.

    Committed rather than rolled back, because the assertions are issued on a
    second connection that has to see both the tables and their policies. A
    ``varchar`` primary key is used on purpose: no sequence, so nothing here
    depends on sequence grants and a refusal can only mean the policy refused.
    """
    for name in names:
        await conn.execute(
            text(f'CREATE TABLE IF NOT EXISTS "{name}" (id varchar(64) PRIMARY KEY, tenant_id varchar(36), label text)')
        )
        await conn.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{name}" TO "{APP_ROLE}", "{SYSTEM_ROLE}"'))


async def create_project_probe_tables(conn: AsyncConnection, *names: str) -> None:
    """Create committed project-scoped probe tables the restricted role can reach.

    Same reasoning as :func:`create_probe_tables`, with a ``project_id`` beside
    the ``tenant_id`` and an index on each: the grant arm matches a project id
    against a list, and a table with no index on either column would measure a
    sequential scan rather than the plan a real project-scoped table gets.
    """
    for name in names:
        await conn.execute(
            text(
                f'CREATE TABLE IF NOT EXISTS "{name}" ('
                "id varchar(64) PRIMARY KEY, tenant_id varchar(36), project_id varchar(36), label text)"
            )
        )
        await conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{name}_tenant_ix" ON "{name}" (tenant_id)'))
        await conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{name}_project_ix" ON "{name}" (project_id)'))
        await conn.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{name}" TO "{APP_ROLE}", "{SYSTEM_ROLE}"'))


async def seed_project(conn: AsyncConnection, table: str, rows: tuple[str, str | None, str | None, str]) -> None:
    """Insert one project-scoped row, ``rows`` being ``(id, tenant_id, project_id, label)``."""
    row_id, tenant_id, project_id, label = rows
    await conn.execute(
        text(
            f'INSERT INTO "{table}" (id, tenant_id, project_id, label) VALUES (:i, :t, :p, :l) '
            "ON CONFLICT (id) DO UPDATE SET tenant_id = EXCLUDED.tenant_id, "
            "project_id = EXCLUDED.project_id, label = EXCLUDED.label"
        ),
        {"i": row_id, "t": tenant_id, "p": project_id, "l": label},
    )


async def create_probe_users(conn: AsyncConnection, *user_ids: str) -> None:
    """Create the probe stand-in for the users table, holding ``user_ids``."""
    await conn.execute(text(f'CREATE TABLE IF NOT EXISTS "{PROBE_USERS}" (id varchar(36) PRIMARY KEY)'))
    for user_id in user_ids:
        await conn.execute(
            text(f'INSERT INTO "{PROBE_USERS}" (id) VALUES (:i) ON CONFLICT DO NOTHING'),
            {"i": user_id},
        )


async def drop_probe_tables(conn: AsyncConnection, *names: str) -> None:
    """Remove probe tables, their policies and the probe users table.

    ``DROP TABLE`` takes the policy with it, so no ``DROP POLICY`` is needed and
    a test that fails halfway leaves nothing behind for the next one.
    """
    for name in (*names, PROBE_USERS):
        await conn.execute(text(f'DROP TABLE IF EXISTS "{name}" CASCADE'))


async def seed(conn: AsyncConnection, table: str, rows: tuple[str, str | None, str]) -> None:
    """Insert one row, ``rows`` being ``(id, tenant_id, label)``."""
    row_id, tenant_id, label = rows
    await conn.execute(
        text(
            f'INSERT INTO "{table}" (id, tenant_id, label) VALUES (:i, :t, :l) ON CONFLICT (id) DO UPDATE SET '
            "tenant_id = EXCLUDED.tenant_id, label = EXCLUDED.label"
        ),
        {"i": row_id, "t": tenant_id, "l": label},
    )


async def as_app_role(
    engine: AsyncEngine,
    tenant: str | None,
    sql: str,
    *,
    fetch: bool = False,
    commit: bool = False,
    role: str = APP_ROLE,
    granted_projects: Sequence[str] | None = None,
) -> RoleOutcome:
    """Run one statement as the restricted role, with ``tenant`` bound.

    ``SET LOCAL ROLE`` and a transaction-local ``set_config`` are what
    :mod:`app.core.rls` does for a real request, so the statement is policied the
    same way.

    ``role`` defaults to the request role; pass :data:`app.core.rls.SYSTEM_ROLE`
    to observe the ``BYPASSRLS`` role the platform reserves for trusted system
    work, which is the difference between "policied" and "deliberately not".

    ``granted_projects`` binds the second GUC, ``app.granted_projects``, beside
    the tenant, which is what the grant arm of the predicate reads (ADR 006).
    Left as ``None`` the second GUC is not set at all, so a caller that does not
    care about grants observes exactly what it observed before the arm existed -
    including the fail-closed answer, because an unset GUC and an empty one match
    the same nothing. Pass ``()`` to bind an empty list on purpose, which is what
    a caller whose company holds no live grant gets.

    By default the transaction is rolled back, which is right for a visibility
    question. A write test passes ``commit=True`` instead, so what it asserts
    afterwards through :func:`admin_rows` is what the database really kept: a
    rolled-back ``DELETE`` and a refused one leave the same rows behind, and only
    a committed attempt distinguishes them.
    """
    async with engine.connect() as conn:
        await conn.execute(text(f'SET LOCAL ROLE "{role}"'))
        await conn.execute(
            text("SELECT set_config(:key, :value, true)"),
            {"key": GUC_NAME, "value": "" if tenant is None else tenant},
        )
        if granted_projects is not None:
            await conn.execute(
                text("SELECT set_config(:key, :value, true)"),
                {"key": GRANTED_GUC_NAME, "value": ",".join(granted_projects)},
            )
        identity = (
            await conn.execute(
                text("SELECT current_user, session_user, (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)")
            )
        ).one()
        rows: list[Any] | None = None
        rowcount = -1
        error: str | None = None
        try:
            result = await conn.execute(text(sql))
            rowcount = result.rowcount
            if fetch:
                rows = [tuple(r) for r in result.fetchall()]
        except Exception as exc:  # noqa: BLE001 - a refusal is an observation here
            error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
            await conn.rollback()
        else:
            if commit:
                await conn.commit()
            else:
                await conn.rollback()
    return RoleOutcome(
        rows=rows,
        rowcount=rowcount,
        error=error,
        current_user=str(identity[0]),
        session_user=str(identity[1]),
        rolsuper=bool(identity[2]),
    )


async def admin_rows(engine: AsyncEngine, sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    """Read as the connecting superuser, which sees every row regardless of policy."""
    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params or {})
        return [tuple(r) for r in result.fetchall()]


async def installed_grant_policy(conn: AsyncConnection, table: str) -> dict[str, Any]:
    """The grant arm's deparsed predicate, its command, and the table's RLS flags.

    Read separately from :func:`installed_policy` because the two policies are
    separate objects in the catalog and the interesting fact about this one is
    that it is ``FOR SELECT``: permissive ``WITH CHECK`` expressions are OR'd as
    well as ``USING`` ones, so a grant arm on writes would let a grantee insert a
    row carrying the owner's tenant into a project it was only invited to read.
    """
    row = (
        await conn.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity, p.qual, p.cmd "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "LEFT JOIN pg_policies p ON p.schemaname = 'public' AND p.tablename = c.relname "
                "AND p.policyname = :p "
                "WHERE n.nspname = 'public' AND c.relname = :t"
            ),
            {"t": table, "p": _GRANT_POLICY_NAME},
        )
    ).one()
    qual = row[2]
    return {
        "rls_enabled": bool(row[0]),
        "forced": bool(row[1]),
        "qual": qual,
        "cmd": row[3],
        "installed": qual is not None,
        "policy_name": _GRANT_POLICY_NAME,
    }


async def installed_policy(conn: AsyncConnection, table: str) -> dict[str, Any]:
    """The installed policy's deparsed predicate and the table's RLS flags."""
    row = (
        await conn.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity, "
                "(SELECT p.qual FROM pg_policies p WHERE p.schemaname = 'public' "
                "AND p.tablename = :t AND p.policyname = :p) AS qual "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = :t"
            ),
            {"t": table, "p": _POLICY_NAME},
        )
    ).one()
    qual = row[2]
    return {
        "rls_enabled": bool(row[0]),
        "forced": bool(row[1]),
        "qual": qual,
        "is_strict": policy_is_strict(qual if isinstance(qual, str) else None),
        "installed": qual is not None,
    }


async def role_attributes(conn: AsyncConnection, role: str = APP_ROLE) -> dict[str, Any]:
    """The catalog attributes that decide whether a role can bypass a policy."""
    row = (
        await conn.execute(
            text("SELECT rolsuper, rolbypassrls, rolcanlogin, rolinherit FROM pg_roles WHERE rolname = :r"),
            {"r": role},
        )
    ).one_or_none()
    if row is None:
        return {"exists": False}
    return {
        "exists": True,
        "rolsuper": bool(row[0]),
        "rolbypassrls": bool(row[1]),
        "rolcanlogin": bool(row[2]),
        "rolinherit": bool(row[3]),
    }
