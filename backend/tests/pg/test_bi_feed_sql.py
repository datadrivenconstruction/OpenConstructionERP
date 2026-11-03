# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""``bi enable`` / ``bi disable`` against a live PostgreSQL cluster (PG lane only).

The reader role is exercised over its own connection: it can SELECT the views, and
nothing else (no writes, no DDL, no table outside the feeds).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.modules.bi_feed import sqlview
from app.modules.bi_feed.feeds import FEEDS, SQL_ROLE, SQL_SCHEMA
from app.modules.bi_feed.validators import view_mismatches


async def _enable(engine, *, single_tenant: bool = True) -> sqlview.EnableResult:
    async with engine.begin() as conn:
        return await conn.run_sync(lambda c: sqlview.enable(c, single_tenant=single_tenant))


async def _disable(engine) -> bool:
    async with engine.begin() as conn:
        return await conn.run_sync(sqlview.disable)


async def _status(engine) -> dict:
    async with engine.connect() as conn:
        return await conn.run_sync(sqlview.status)


def _reader_engine(admin_url: str, password: str):
    url = make_url(admin_url).set(username=SQL_ROLE, password=password)
    return create_async_engine(url, poolclass=NullPool)


@pytest.fixture
async def enabled(pg_engine):
    result = await _enable(pg_engine)
    try:
        yield result
    finally:
        await _disable(pg_engine)


async def test_enable_creates_one_view_per_feed_with_identical_columns(pg_engine, enabled) -> None:
    async with pg_engine.connect() as conn:
        columns = await conn.run_sync(sqlview.view_columns)
    assert set(columns) == set(FEEDS)
    assert view_mismatches(FEEDS, columns) == []  # R6
    assert (await _status(pg_engine))["enabled"] is True


async def test_reader_can_select_the_views_and_nothing_else(pg_engine, pg_async_url, enabled) -> None:
    assert enabled.password
    reader = _reader_engine(pg_async_url, enabled.password)
    try:
        async with reader.connect() as conn:
            for feed_id in FEEDS:
                await conn.execute(text(f'SELECT * FROM {SQL_SCHEMA}."{feed_id}" LIMIT 1'))
        forbidden = [
            "SELECT 1 FROM public.oe_users_user LIMIT 1",
            "SELECT hashed_password FROM public.oe_users_user LIMIT 1",
            "SELECT key_hash FROM public.oe_users_api_key LIMIT 1",
            "SELECT notes FROM public.oe_finance_invoice LIMIT 1",
            f'INSERT INTO {SQL_SCHEMA}."projects" (id) VALUES (gen_random_uuid())',
            f"UPDATE {SQL_SCHEMA}.\"projects\" SET name = 'x'",
            f'DELETE FROM {SQL_SCHEMA}."projects"',
            "UPDATE public.oe_projects_project SET name = 'x'",
            "DELETE FROM public.oe_projects_project",
            f"CREATE TABLE {SQL_SCHEMA}.leak (x int)",
            "CREATE TABLE public.leak (x int)",
        ]
        for statement in forbidden:
            async with reader.connect() as conn:
                with pytest.raises((ProgrammingError, DBAPIError)):
                    await conn.execute(text(statement))
    finally:
        await reader.dispose()


async def test_run_twice_is_idempotent_and_keeps_the_password(pg_engine, enabled) -> None:
    again = await _enable(pg_engine)
    assert again.role_created is False and again.password is None
    assert sorted(again.views) == sorted(FEEDS)


async def test_disable_removes_schema_and_role_and_is_repeatable(pg_engine) -> None:
    await _enable(pg_engine)
    assert await _disable(pg_engine) is True
    async with pg_engine.connect() as conn:
        assert (await conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": SQL_ROLE})).first() is None
        assert (
            await conn.execute(text("SELECT 1 FROM pg_namespace WHERE nspname = :s"), {"s": SQL_SCHEMA})
        ).first() is None
    assert (await _status(pg_engine))["enabled"] is False
    assert await _disable(pg_engine) is False


async def test_enable_refuses_without_row_level_security_unless_single_tenant(pg_engine) -> None:
    with pytest.raises(sqlview.BiSqlError) as info:
        await _enable(pg_engine, single_tenant=False)
    assert info.value.code == "BI_RLS_REQUIRED"
    assert (await _status(pg_engine))["enabled"] is False
