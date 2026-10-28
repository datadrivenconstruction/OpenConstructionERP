"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The read-only schema checker must report clean, and must name what is absent.

A checker that only ever reports clean is indistinguishable from a broken one, so every
test here strips something first and demands the checker names it. DDL is transactional
in PostgreSQL, so each strip happens inside a transaction that is rolled back and the
shared session schema is left untouched.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from app.scripts.check_schema_constraints import find_missing

pytestmark = pytest.mark.asyncio


async def _report(conn):
    from app.database import Base

    return await conn.run_sync(lambda sync_conn: find_missing(sync_conn, Base))


async def _inspect(conn, fn):
    return await conn.run_sync(lambda sync_conn: fn(inspect(sync_conn)))


async def test_reports_clean_against_a_fresh_create_all_schema(pg_engine) -> None:
    """The other direction: on a schema create_all just built, nothing is missing."""
    async with pg_engine.connect() as conn:
        report = await _report(conn)

    assert report.missing_unique == [], report.missing_unique
    assert report.missing_check == [], report.missing_check
    assert report.missing_fk == [], report.missing_fk
    assert report.nullable_mismatch == [], report.nullable_mismatch
    assert report.total == 0


async def test_names_a_stripped_unique_constraint(pg_engine) -> None:
    async with pg_engine.connect() as conn:
        trans = await conn.begin()
        try:
            live = await _inspect(conn, lambda i: i.get_unique_constraints("oe_ncr_ncr"))
            name, cols = live[0]["name"], tuple(live[0]["column_names"])
            await conn.execute(text(f'ALTER TABLE "oe_ncr_ncr" DROP CONSTRAINT "{name}"'))

            report = await _report(conn)
        finally:
            await trans.rollback()

    hits = [r for r in report.missing_unique if r[0] == "oe_ncr_ncr"]
    assert hits, f"checker did not name the dropped unique constraint; got {report.missing_unique}"
    assert set(hits[0][2]) == set(cols)


async def test_names_a_stripped_foreign_key(pg_engine) -> None:
    async with pg_engine.connect() as conn:
        trans = await conn.begin()
        try:
            live = await _inspect(conn, lambda i: i.get_foreign_keys("oe_projects_project"))
            name = next(fk["name"] for fk in live if fk["constrained_columns"] == ["owner_id"])
            await conn.execute(text(f'ALTER TABLE "oe_projects_project" DROP CONSTRAINT "{name}"'))

            report = await _report(conn)
        finally:
            await trans.rollback()

    hits = [r for r in report.missing_fk if r[0] == "oe_projects_project" and "owner_id" in r[2]]
    assert hits, f"checker did not name the dropped foreign key; got {report.missing_fk}"


async def test_names_a_stripped_check_constraint(pg_engine) -> None:
    async with pg_engine.connect() as conn:
        trans = await conn.begin()
        try:
            live = await _inspect(conn, lambda i: i.get_check_constraints("oe_progress_entry"))
            name = live[0]["name"]
            await conn.execute(text(f'ALTER TABLE "oe_progress_entry" DROP CONSTRAINT "{name}"'))

            report = await _report(conn)
        finally:
            await trans.rollback()

    assert any(r[0] == "oe_progress_entry" for r in report.missing_check), (
        f"checker did not name the dropped check constraint; got {report.missing_check}"
    )


async def test_names_a_column_downgraded_to_nullable(pg_engine) -> None:
    """The shape postgres_auto_migrate produces for a NOT NULL column with no default."""
    async with pg_engine.connect() as conn:
        trans = await conn.begin()
        try:
            await conn.execute(
                text('ALTER TABLE "oe_projects_project" ALTER COLUMN "owner_id" DROP NOT NULL'),
            )
            report = await _report(conn)
        finally:
            await trans.rollback()

    assert ("oe_projects_project", "owner_id") in report.nullable_mismatch, report.nullable_mismatch
