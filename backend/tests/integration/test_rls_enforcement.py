"""Database-level row-level-security enforcement (RLS Phase 2+).

The suite in ``test_tenant_isolation.py`` pins the *app-layer* tenant guards at
the HTTP boundary. This suite pins the *database* backstop underneath them: when
``settings.rls_enforce`` is on, a query that runs as the non-superuser runtime
role ``oe_app`` cannot see, change or delete another tenant's rows even when it
carries no ``WHERE tenant_id`` filter at all. That is the whole point of RLS -
it catches the forgotten filter the app layer relies on.

Why a probe table instead of a real model
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The isolation guarantee lives in two reusable pieces of production code:

* the runtime role + grants created by ``provision_rls`` / ``apply_rls``;
* the exact policy SQL emitted by ``rls_setup._policy_statements``.

This suite provisions the real roles, then applies that same real policy SQL to
a throwaway ``_rls_probe`` table and drives raw SQL against it. That exercises
the genuine role mechanism and the genuine policy predicate without coupling the
assertions to any one model's NOT NULL columns, and without leaving RLS enabled
on a real table for later suites. The app's ``after_begin`` listener (installed
on the shared session factory) does the ``SET LOCAL ROLE oe_app`` + GUC stamp
exactly as it does in a real request.

Boot context
~~~~~~~~~~~~~
``conftest`` binds the engine to a PostgreSQL cluster whose connecting role is
the superuser ``postgres`` (embedded ``initdb -U postgres``; the CI service
container likewise). A superuser bypasses every policy, so the policies this
module installs stay inert for every other suite - which is exactly why RLS is
safe to enable globally only behind the flag + an explicit role downgrade.
"""

from __future__ import annotations

import contextlib

import pytest
import pytest_asyncio
from sqlalchemy import text

# ── Flag + provisioning fixture ─────────────────────────────────────────────

_PROBE_TABLE = "_rls_probe"
_TENANT_A = "tenant-aaaa"
_TENANT_B = "tenant-bbbb"

# A second probe whose tenant column is a *native* ``uuid`` (not varchar). It
# pins the ``::text`` cast in the policy predicate: current_setting returns
# text, so without the cast the predicate is ``uuid = text``, which PostgreSQL
# rejects ("operator does not exist: uuid = text") and every read/write 500s.
# The uuids are canonical lowercase so ``str(uuid.UUID)`` round-trips exactly.
_PROBE_TABLE_UUID = "_rls_probe_uuid"
_TENANT_A_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_TENANT_B_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _set_flag(value: bool) -> None:
    """Force ``settings.rls_enforce`` by env + cache reset, both directions."""
    import os

    from app.config import get_settings

    if value:
        os.environ["OE_RLS_ENFORCE"] = "1"
    else:
        os.environ.pop("OE_RLS_ENFORCE", None)
    get_settings.cache_clear()


@pytest_asyncio.fixture(scope="module")
async def rls_probe():
    """Enable RLS, provision the real roles, and stand up a policied probe table.

    Yields the engine. Tears down by dropping the probe table and reverting the
    flag so later suites see the default (disabled) behaviour again.
    """
    _set_flag(True)
    from app.config import get_settings

    assert get_settings().rls_enforce is True, "flag did not take effect"

    from app.core.rls_setup import _policy_statements, apply_rls
    from app.database import Base, engine

    # Provision the real runtime roles + grants + policies on every real tenant
    # table. We only need the roles/grants here; the probe table gets the same
    # policy SQL applied explicitly below.
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        await apply_rls(conn, Base)

    # Throwaway table with a tenant column, then the *production* policy SQL.
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP TABLE IF EXISTS "{_PROBE_TABLE}"'))
        await conn.execute(text(f'CREATE TABLE "{_PROBE_TABLE}" (id serial PRIMARY KEY, tenant_id varchar(36))'))
        # Make sure the runtime role can reach the probe table AND its serial
        # sequence even if default privileges did not apply (belt and braces).
        # Granting the sequence matters for the INSERT test: without it the
        # cross-tenant INSERT would fail on a missing-privilege error instead of
        # the row-level-security WITH CHECK we mean to exercise.
        await conn.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{_PROBE_TABLE}" TO "oe_app"'))
        await conn.execute(text('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "oe_app"'))
        for sql in _policy_statements(_PROBE_TABLE):
            await conn.execute(text(sql))
        # Seed as superuser (no request context -> RLS bypassed): one row per
        # tenant plus a shared NULL-tenant row.
        await conn.execute(
            text(f'INSERT INTO "{_PROBE_TABLE}" (tenant_id) VALUES (:a), (:b), (NULL)'),
            {"a": _TENANT_A, "b": _TENANT_B},
        )

    # Second probe with a native ``uuid`` tenant column, exercising the policy's
    # ``::text`` cast against a non-text column type. Same production policy SQL.
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP TABLE IF EXISTS "{_PROBE_TABLE_UUID}"'))
        await conn.execute(text(f'CREATE TABLE "{_PROBE_TABLE_UUID}" (id serial PRIMARY KEY, tenant_id uuid)'))
        await conn.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{_PROBE_TABLE_UUID}" TO "oe_app"'))
        await conn.execute(text('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "oe_app"'))
        for sql in _policy_statements(_PROBE_TABLE_UUID):
            await conn.execute(text(sql))
        # Cast the bound text params to uuid server-side so asyncpg does not have
        # to infer the column type from a bare string.
        await conn.execute(
            text(
                f'INSERT INTO "{_PROBE_TABLE_UUID}" (tenant_id) VALUES (CAST(:a AS uuid)), (CAST(:b AS uuid)), (NULL)'
            ),
            {"a": _TENANT_A_UUID, "b": _TENANT_B_UUID},
        )

    try:
        yield engine
    finally:
        with contextlib.suppress(Exception):
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP TABLE IF EXISTS "{_PROBE_TABLE}"'))
                await conn.execute(text(f'DROP TABLE IF EXISTS "{_PROBE_TABLE_UUID}"'))
        _set_flag(False)


async def _rows_visible_as(tenant: str | None, *, table: str = _PROBE_TABLE) -> set[str | None]:
    """Return the ``tenant_id`` set ``table`` shows in a request context.

    Opens a session through the app's factory with the tenant bound, so the
    ``after_begin`` listener downgrades to ``oe_app`` and stamps the GUC exactly
    as a real request would. Non-null ids are normalised to ``str`` so a native
    ``uuid`` column (the driver hands back ``uuid.UUID``) and a ``varchar``
    column can be asserted the same way.
    """
    from app.core import rls
    from app.database import async_session_factory

    token = rls.set_request_tenant(tenant)
    try:
        async with async_session_factory() as session:
            result = await session.execute(text(f'SELECT tenant_id FROM "{table}"'))
            return {None if v is None else str(v) for v in result.scalars().all()}
    finally:
        rls.reset_request_tenant(token)


# ── Read isolation ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_a_sees_only_own_and_shared_rows(rls_probe):
    """Tenant A sees its own row and the shared NULL row, never tenant B's."""
    visible = await _rows_visible_as(_TENANT_A)
    assert _TENANT_A in visible, f"tenant A cannot see its own row: {visible!r}"
    assert None in visible, f"tenant A cannot see the shared NULL-tenant row: {visible!r}"
    assert _TENANT_B not in visible, f"LEAK: tenant A can see tenant B's row: {visible!r}"


@pytest.mark.asyncio
async def test_tenant_b_sees_only_own_and_shared_rows(rls_probe):
    """Tenant B sees its own row and the shared NULL row, never tenant A's."""
    visible = await _rows_visible_as(_TENANT_B)
    assert _TENANT_B in visible, f"tenant B cannot see its own row: {visible!r}"
    assert None in visible, f"tenant B cannot see the shared NULL-tenant row: {visible!r}"
    assert _TENANT_A not in visible, f"LEAK: tenant B can see tenant A's row: {visible!r}"


@pytest.mark.asyncio
async def test_anonymous_sees_only_shared_rows(rls_probe):
    """An anonymous request (empty tenant) sees only shared NULL-tenant rows."""
    visible = await _rows_visible_as(None)
    assert visible == {None}, f"anonymous request saw tenant-owned rows: {visible!r}"


@pytest.mark.asyncio
async def test_uuid_tenant_column_compares_via_text_cast(rls_probe):
    """A native ``uuid`` tenant column is isolated via the policy's ``::text`` cast.

    The GUC is always text (``current_setting`` returns text), so the predicate
    must cast a non-text tenant column: ``tenant_id::text = current_setting(...)``.
    Drop that cast and the uuid predicate becomes ``uuid = text``, which
    PostgreSQL rejects with ``operator does not exist: uuid = text`` - the uuid
    probe then turns red (verified by temporarily reverting the cast), so this is
    the regression guard for it. Tenant A (bound as its uuid string) sees its own
    uuid row and the shared NULL row, never tenant B's.
    """
    visible = await _rows_visible_as(_TENANT_A_UUID, table=_PROBE_TABLE_UUID)
    assert _TENANT_A_UUID in visible, f"uuid tenant A cannot see its own row: {visible!r}"
    assert None in visible, f"uuid tenant A cannot see the shared NULL row: {visible!r}"
    assert _TENANT_B_UUID not in visible, f"LEAK: uuid tenant A can see tenant B's row: {visible!r}"


# ── Write isolation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_a_cannot_update_tenant_b_row(rls_probe):
    """An UPDATE from A targeting B's row must touch zero rows and change nothing."""
    from app.core import rls
    from app.database import async_session_factory, engine

    token = rls.set_request_tenant(_TENANT_A)
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                text(f"UPDATE \"{_PROBE_TABLE}\" SET tenant_id = 'hijacked' WHERE tenant_id = :b"),
                {"b": _TENANT_B},
            )
            await session.commit()
            assert result.rowcount == 0, f"LEAK: tenant A updated {result.rowcount} of tenant B's rows"
    finally:
        rls.reset_request_tenant(token)

    # Confirm from the superuser side that tenant B's row is intact.
    async with engine.begin() as conn:
        remaining = (
            await conn.execute(
                text(f'SELECT count(*) FROM "{_PROBE_TABLE}" WHERE tenant_id = :b'),
                {"b": _TENANT_B},
            )
        ).scalar()
    assert remaining == 1, "tenant B's row was mutated by tenant A's UPDATE"


@pytest.mark.asyncio
async def test_tenant_a_cannot_delete_tenant_b_row(rls_probe):
    """A DELETE from A targeting B's row must touch zero rows and leave it intact."""
    from app.core import rls
    from app.database import async_session_factory, engine

    token = rls.set_request_tenant(_TENANT_A)
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                text(f'DELETE FROM "{_PROBE_TABLE}" WHERE tenant_id = :b'),
                {"b": _TENANT_B},
            )
            await session.commit()
            assert result.rowcount == 0, f"LEAK: tenant A deleted {result.rowcount} of tenant B's rows"
    finally:
        rls.reset_request_tenant(token)

    async with engine.begin() as conn:
        remaining = (
            await conn.execute(
                text(f'SELECT count(*) FROM "{_PROBE_TABLE}" WHERE tenant_id = :b'),
                {"b": _TENANT_B},
            )
        ).scalar()
    assert remaining == 1, "tenant B's row was deleted by tenant A's DELETE"


@pytest.mark.asyncio
async def test_tenant_a_cannot_insert_as_tenant_b(rls_probe):
    """An INSERT from A stamping B's tenant id must be refused by the WITH CHECK."""
    from sqlalchemy.exc import DBAPIError

    from app.core import rls
    from app.database import async_session_factory

    token = rls.set_request_tenant(_TENANT_A)
    try:
        async with async_session_factory() as session:
            # The INSERT runs eagerly, so the WITH CHECK violation raises here.
            with pytest.raises(DBAPIError):
                await session.execute(
                    text(f'INSERT INTO "{_PROBE_TABLE}" (tenant_id) VALUES (:b)'),
                    {"b": _TENANT_B},
                )
    finally:
        rls.reset_request_tenant(token)


# ── Table selection ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_tables_selects_tenant_columns_only(rls_probe):
    """``tenant_tables`` selects tables with a tenant_id column, never globals."""
    from app.core.rls_setup import tenant_tables
    from app.database import Base

    selected = set(tenant_tables(Base))

    # Every selected table really carries a tenant_id column.
    for name in selected:
        table = Base.metadata.tables[name]
        assert "tenant_id" in table.columns, f"{name} was selected without a tenant_id column"

    # Global reference tables are never selected.
    assert "oe_costs_item" not in selected, "global cost catalog must never be tenant-policied"


# ── Disabled path stays a pure bypass ───────────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_flag_bypasses_policies(rls_probe):
    """With the flag off, a request-context session sees every row (superuser).

    Proves the off-switch: the ``after_begin`` listener returns before any role
    downgrade, so the connection keeps its superuser role and RLS is bypassed -
    the behaviour every non-RLS suite depends on. Restores the flag afterwards
    so the rest of this module keeps enforcing.
    """
    _set_flag(False)
    try:
        visible = await _rows_visible_as(_TENANT_A)
        assert {_TENANT_A, _TENANT_B, None} <= visible, (
            f"flag off should bypass RLS and show all rows, saw: {visible!r}"
        )
    finally:
        _set_flag(True)
