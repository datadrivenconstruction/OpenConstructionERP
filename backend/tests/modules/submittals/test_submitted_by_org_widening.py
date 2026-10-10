"""The upgrade path for the submitting company column that was too narrow.

``submitted_by_org`` is now ``String(255)``, which fixes a fresh installation
outright. It does not fix an existing one: module tables here are built by
``create_all`` and topped up by an auto-migrator that only ever adds columns,
and the Alembic revision that lengthens the column is stamped rather than run
on an installation upgraded in place. ``widen_submitted_by_org`` is what closes
that, and this is the test that it does.

Three states are covered: the table as ``create_all`` builds it, where the
repair must find nothing to do; the 36 character column of a database built
before this version, with a row in it; and the boot after the repair.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

import app.modules.submittals.models  # noqa: F401

pytestmark = pytest.mark.asyncio

_TABLE = "oe_submittals_submittal"
_COLUMN = "submitted_by_org"
_SCRATCH = "oe_test_submitted_by_org_shape"


async def _length_of(conn, table: str, column: str) -> int | None:
    """Ask the database, not the model, how many characters a column holds."""
    row = await conn.execute(
        text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    return row.scalar_one()


async def test_widening_is_a_no_op_then_detected_applied_and_a_no_op_again():
    """A fresh column is left alone; a narrow one is widened once and then left alone."""
    from app.database import Base, engine
    from app.modules.submittals.org_width_repair import widen_submitted_by_org

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # The column as create_all builds it: the first boot of a new
        # installation must not report a repair.
        assert await _length_of(conn, _TABLE, _COLUMN) == 255
        assert await widen_submitted_by_org(conn) == 0

    # DDL is transactional in PostgreSQL, so the narrowing below and everything
    # after it is rolled back: the schema the other tests share is never left
    # narrow, whatever fails here.
    async with engine.connect() as conn:
        transaction = await conn.begin()
        try:
            # Put the column back the way a database built before this version
            # has it. This is the state the repair exists to find. A value only
            # a widened column can hold is cut to fit, so the narrowing does not
            # depend on what other tests left in the table.
            await conn.execute(
                text(
                    f'ALTER TABLE "{_TABLE}" ALTER COLUMN "{_COLUMN}" '  # noqa: S608
                    f'TYPE VARCHAR(36) USING left("{_COLUMN}", 36)'
                )
            )
            assert await _length_of(conn, _TABLE, _COLUMN) == 36

            assert await widen_submitted_by_org(conn) == 1
            assert await _length_of(conn, _TABLE, _COLUMN) == 255

            # Idempotent: the boot after the upgrade must not touch the column again.
            assert await widen_submitted_by_org(conn) == 0
            assert await _length_of(conn, _TABLE, _COLUMN) == 255
        finally:
            await transaction.rollback()


async def test_widening_keeps_the_stored_value_and_admits_a_long_name():
    """A stored contact id survives, and a company name longer than a UUID then fits."""
    from app.database import engine
    from app.modules.submittals.org_width_repair import _WIDEN

    contact_id = "7b0d6c1e-52a4-4a53-9f0e-3c1f0a9d2b11"
    long_name = "Mechanical and Electrical Installations Joint Venture, Northern Region Branch Office"
    assert len(contact_id) == 36
    assert len(long_name) > 36
    widen_scratch = _WIDEN.replace(_TABLE, _SCRATCH)
    assert _SCRATCH in widen_scratch, "the statement under test names its own table"

    async with engine.begin() as conn:
        await conn.execute(text(f'DROP TABLE IF EXISTS "{_SCRATCH}"'))
        await conn.execute(text(f'CREATE TABLE "{_SCRATCH}" ("{_COLUMN}" VARCHAR(36))'))
        await conn.execute(
            text(f'INSERT INTO "{_SCRATCH}" ("{_COLUMN}") VALUES (:v)'),  # noqa: S608
            {"v": contact_id},
        )

        await conn.execute(text(widen_scratch))

        await conn.execute(
            text(f'INSERT INTO "{_SCRATCH}" ("{_COLUMN}") VALUES (:v)'),  # noqa: S608
            {"v": long_name},
        )
        stored = (
            await conn.execute(
                text(f'SELECT "{_COLUMN}" FROM "{_SCRATCH}" ORDER BY char_length("{_COLUMN}")')  # noqa: S608
            )
        ).scalars()
        assert list(stored) == [contact_id, long_name]
        await conn.execute(text(f'DROP TABLE IF EXISTS "{_SCRATCH}"'))
