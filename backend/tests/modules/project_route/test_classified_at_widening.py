"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The upgrade path for the one timestamp column that was declared naive.

``classified_at`` is now ``DateTime(timezone=True)`` like the other 197 module
timestamps, which fixes a fresh installation outright. It does not fix an
existing one: module tables here are built by ``create_all`` and topped up by an
auto-migrator that only ever adds columns, so an upgraded database keeps the
naive column it was created with. ``widen_classified_at`` is what closes that,
and this is the test that it does.

The test is in two parts because the two risks are separable and one of them
cannot be reached through the real table. Retyping is cheap to verify against
the real table and the real function. Preserving the instant needs a stored
value, and storing one means satisfying a foreign key to a project and every
NOT NULL column beside it, which would test the projects module rather than this
one. So the instant is verified against a table of the same shape, under a
session time zone deliberately set away from UTC: with the ``USING ... AT TIME
ZONE 'UTC'`` clause the stored moment survives, and without it PostgreSQL reads
the naive value in the session's zone and the assertion moves by hours.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

import app.modules.project_route.models  # noqa: F401

pytestmark = pytest.mark.asyncio

_TABLE = "oe_project_route_assessment"
_SCRATCH = "oe_test_classified_at_shape"


async def _timezone_of(conn, table: str, column: str) -> bool:
    """Ask the database, not the model, whether a column carries a time zone."""
    row = await conn.execute(
        text("SELECT data_type FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
        {"t": table, "c": column},
    )
    data_type = row.scalar_one()
    return data_type == "timestamp with time zone"


async def test_widening_is_detected_applied_and_then_a_no_op():
    """A naive column is found, widened once, and left alone on every later boot."""
    from app.database import Base, engine
    from app.modules.project_route.tz_repair import widen_classified_at

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Put the column back the way a database built before this version has
        # it. This is the state the repair exists to find.
        await conn.execute(
            text(
                f'ALTER TABLE "{_TABLE}" ALTER COLUMN "classified_at" '  # noqa: S608
                "TYPE timestamp without time zone"
            )
        )
        assert await _timezone_of(conn, _TABLE, "classified_at") is False

    async with engine.begin() as conn:
        assert await widen_classified_at(conn) == 1
        assert await _timezone_of(conn, _TABLE, "classified_at") is True

    # Idempotent: the boot after the upgrade must not touch the column again.
    async with engine.begin() as conn:
        assert await widen_classified_at(conn) == 0
        assert await _timezone_of(conn, _TABLE, "classified_at") is True


async def test_widening_keeps_the_instant_under_a_non_utc_session():
    """The stored moment is relabelled, not shifted, whatever the session zone is."""
    from app.database import engine
    from app.modules.project_route.tz_repair import _WIDEN

    stamped = datetime(2026, 3, 14, 9, 26, 53, tzinfo=UTC)
    widen_scratch = _WIDEN.replace(_TABLE, _SCRATCH)
    assert _SCRATCH in widen_scratch, "the statement under test names its own table"

    async with engine.begin() as conn:
        # A zone with a large offset and a daylight-saving rule, so a missing
        # USING clause cannot accidentally agree with UTC.
        await conn.execute(text("SET LOCAL TIME ZONE 'America/Denver'"))
        await conn.execute(text(f'DROP TABLE IF EXISTS "{_SCRATCH}"'))
        await conn.execute(text(f'CREATE TABLE "{_SCRATCH}" (classified_at timestamp)'))
        await conn.execute(
            text(f'INSERT INTO "{_SCRATCH}" (classified_at) VALUES (:v)'),  # noqa: S608
            {"v": stamped.replace(tzinfo=None)},
        )

        await conn.execute(text(widen_scratch))

        read_back = (
            await conn.execute(text(f'SELECT classified_at FROM "{_SCRATCH}"'))  # noqa: S608
        ).scalar_one()
        assert read_back.tzinfo is not None, "the column came back naive"
        assert read_back.astimezone(UTC) == stamped
        await conn.execute(text(f'DROP TABLE IF EXISTS "{_SCRATCH}"'))
