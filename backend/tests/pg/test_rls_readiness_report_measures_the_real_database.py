"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The RLS readiness report counts what a strict policy would do, on PostgreSQL.

Probe tables stand in for the tenant tables so the counts do not depend on any
one model's NOT NULL columns, and everything happens inside a transaction that
is rolled back, so no other suite sees them.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.rls_setup import _policy_statements, rls_readiness_report

pytestmark = pytest.mark.asyncio

_USERS = "_rls_ready_users"
_SHARED = "_rls_ready_shared"
_LEGACY = "_rls_ready_legacy"


async def test_the_report_finds_user_tenants_and_rows_without_a_tenant(pg_engine) -> None:
    async with pg_engine.connect() as conn:
        trans = await conn.begin()
        try:
            await conn.execute(text(f'CREATE TABLE "{_USERS}" (id varchar(36) PRIMARY KEY)'))
            await conn.execute(text(f"INSERT INTO \"{_USERS}\" VALUES ('user-a'), ('user-b')"))
            for name in (_SHARED, _LEGACY):
                await conn.execute(text(f'CREATE TABLE "{name}" (id serial PRIMARY KEY, tenant_id varchar(36))'))
            # Two users' rows, each stamped with its creator: the tenant == user shape.
            await conn.execute(text(f"INSERT INTO \"{_SHARED}\" (tenant_id) VALUES ('user-a'), ('user-a'), ('user-b')"))
            # Legacy rows with no tenant, and one with an organisation-style tenant.
            await conn.execute(text(f"INSERT INTO \"{_LEGACY}\" (tenant_id) VALUES (NULL), (NULL), ('org-1')"))
            for sql in _policy_statements(_SHARED):
                await conn.execute(text(sql))

            report = await rls_readiness_report(conn, [_SHARED, _LEGACY, "_rls_ready_missing"], users_table=_USERS)
        finally:
            await trans.rollback()

    assert report["dialect"] == "postgresql"
    assert report["enforced"] is False
    assert report["users"] == 2
    tables = {t["table"]: t for t in report["tables"]}
    assert set(tables) == {_SHARED, _LEGACY}, "a table this database does not have is skipped"
    assert tables[_SHARED] == {
        "table": _SHARED,
        "rows": 3,
        "null_tenant_rows": 0,
        "tenants": 2,
        "rows_with_user_tenant": 3,
        "rls_enabled": True,
        "policy_installed": True,
    }
    assert tables[_LEGACY]["null_tenant_rows"] == 2
    assert tables[_LEGACY]["rows_with_user_tenant"] == 0
    assert tables[_LEGACY]["policy_installed"] is False
    assert report["blockers"] == [
        {"code": "tenant_is_user", "rows": 3, "users": 2, "tables": [_SHARED]},
        {"code": "null_tenant_rows", "table": _LEGACY, "rows": 2},
    ]
    assert report["ready_for_strict"] is False


async def test_organisation_tenants_with_no_gaps_are_ready(pg_engine) -> None:
    async with pg_engine.connect() as conn:
        trans = await conn.begin()
        try:
            await conn.execute(text(f'CREATE TABLE "{_USERS}" (id varchar(36) PRIMARY KEY)'))
            await conn.execute(text(f"INSERT INTO \"{_USERS}\" VALUES ('user-a')"))
            await conn.execute(text(f'CREATE TABLE "{_SHARED}" (id serial PRIMARY KEY, tenant_id varchar(36))'))
            await conn.execute(text(f"INSERT INTO \"{_SHARED}\" (tenant_id) VALUES ('org-1'), ('org-2')"))

            report = await rls_readiness_report(conn, [_SHARED], users_table=_USERS)
        finally:
            await trans.rollback()

    assert report["blockers"] == []
    assert report["ready_for_strict"] is True


async def test_a_table_that_cannot_be_read_is_reported_not_raised(pg_engine) -> None:
    """One unreadable table is named in the report; the others are still measured."""
    async with pg_engine.connect() as conn:
        trans = await conn.begin()
        try:
            await conn.execute(text(f'CREATE TABLE "{_USERS}" (id varchar(36) PRIMARY KEY)'))
            await conn.execute(text(f'CREATE TABLE "{_SHARED}" (id serial PRIMARY KEY, tenant_id varchar(36))'))
            await conn.execute(text(f"INSERT INTO \"{_SHARED}\" (tenant_id) VALUES ('org-1')"))
            # Listed as a tenant table but has no tenant column: the count fails.
            await conn.execute(text(f'CREATE TABLE "{_LEGACY}" (id serial PRIMARY KEY)'))

            report = await rls_readiness_report(conn, [_SHARED, _LEGACY], users_table=_USERS)
        finally:
            await trans.rollback()

    assert [t["table"] for t in report["tables"]] == [_SHARED]
    assert report["blockers"] == [{"code": "unmeasured_table", "table": _LEGACY, "error": "ProgrammingError"}]
    assert report["ready_for_strict"] is False
