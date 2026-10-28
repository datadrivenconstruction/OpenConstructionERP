# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The two properties ``tests/_pg.py`` exists to provide, asserted directly.

Both are expensive enough to be tempting to weaken, and both fail silently when
weakened, which is why they are pinned here rather than trusted to the suite.

**Every test database is bounded against producing no verdict.** A test that
hangs returns nothing at all: nothing passes, nothing fails, nothing turns red,
and the silence reads exactly like health. It hangs in one of two shapes and
they need different bounds. A statement that runs too long is caught by
``statement_timeout``. A transaction left open with nothing running is invisible
to it, because no statement is executing, and is caught by
``idle_in_transaction_session_timeout``. That one TERMINATES the session rather
than cancelling a statement, and the difference matters to whoever reads the
failure: PostgreSQL names the reason in its own log, but the client is simply
disconnected, so under asyncpg the test reports ``connection is closed`` and
nothing more. It converts a hang into a failure; it does not convert it into an
explanation. ``lock_timeout`` covers neither: it bounds waiting for a lock. Above all three sits a per-test
kill that takes the process without naming statement or session, and only in CI:
``addopts`` carries no ``--timeout``, so a local run has nothing above these
bounds at all.

The idle bound is here because measurement showed the existing one was aimed
elsewhere. ``conftest._bound_idle_transactions`` reads ``DATABASE_SYNC_URL``,
which names the maintenance database, so its 300s landed there - correctly, and
usefully, since ``app.database.engine`` is bound to that same URL - while
``oe_test_unit`` and every clone read ``0``. That is worth stating plainly
because the function is careful in every other respect: it even reads its value
back, and it correctly verified a bound that was in force on the wrong database
for this suite's purposes.

A bound nobody reads back is not a bound, so these tests ask the server for both
values, over each of the four ways ``_pg.py`` hands out a connection, rather
than trusting the ``ALTER DATABASE`` to have landed.

**A throwaway database is genuinely throwaway.** ``isolated_engine`` clones a
database per call, which is the dominant cost of the suites that use it, so
"just widen the fixture scope" is a standing proposal. It is unsafe, and
measurably so: pointing all 16 ``isolated_engine`` unit files at one shared
database (and, separately, at one per module) failed the same 7 tests in
``test_erpchat_feedback``, ``test_match_analytics`` and
``test_partner_pack_full_install_stream``, every one of them on a count that had
absorbed a previous test's rows - ``assert 8 == 4``, ``assert 3 == 1``,
``assert 0 == 15``. Every leak was inside a single file, so module scope is no
safer than session scope. ``test_postgres_migrator_indexes`` raises the stakes
past rows: it drops indexes to simulate an old install, so what leaks there is
the schema.

A suite passing after such a change would not have proved anything - the tests
would simply never have read each other's leftovers. So the check below reads
them on purpose, and carries its own teeth: it asserts the leftovers ARE visible
when the database is reused, so the isolation half cannot pass by being blind.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests._pg import (
    IDLE_IN_TRANSACTION_TIMEOUT_S,
    LOCK_TIMEOUT_S,
    STATEMENT_TIMEOUT_S,
    isolated_database_url,
    isolated_engine,
    schema_inspection_engine,
    transactional_session,
)

#: ``pg_settings`` reports these in milliseconds, which is the only reading with
#: no unit to get wrong: ``SHOW`` renders 60 seconds as the string ``'1min'``.
#: Both bounds are read in one round trip so that no entry point can be checked
#: for one of them and quietly skipped for the other.
_READ_BOUNDS_MS = (
    "SELECT (SELECT setting::bigint FROM pg_settings WHERE name = 'statement_timeout'),"
    " (SELECT setting::bigint FROM pg_settings WHERE name = 'idle_in_transaction_session_timeout')"
)

_EXPECTED_MS = (STATEMENT_TIMEOUT_S * 1000, IDLE_IN_TRANSACTION_TIMEOUT_S * 1000)

#: Backend CI runs ``tests/unit`` with ``--timeout=300 --timeout-method=signal``
#: (``ci.yml``). Every bound this file defends has to fire below that, or the
#: process is killed without naming the statement or the session and the guard
#: has bought nothing. Read off the workflow rather than remembered, because the
#: value differs per lane and a folded YAML block hides it from a line-oriented
#: grep.
_BACKEND_CI_PER_TEST_KILL_S = 300


@pytest_asyncio.fixture(scope="module")
async def engine():
    """One throwaway database for the read-only checks - cloning one is not free."""
    async with isolated_engine() as eng:
        yield eng


async def test_isolated_engine_databases_bound_both_ways(engine) -> None:
    """Both bounds are in force on the connection a test actually gets."""
    async with engine.connect() as conn:
        observed = tuple((await conn.execute(text(_READ_BOUNDS_MS))).one())
    assert observed == _EXPECTED_MS, (
        f"(statement_timeout, idle_in_transaction_session_timeout) on {engine.url.database} "
        f"reads {observed}ms, expected {_EXPECTED_MS}ms"
    )


async def test_the_bound_reaches_a_session_and_not_just_the_engine(engine) -> None:
    """Application code opens sessions, not connections - check the path it uses."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        observed = tuple((await session.execute(text(_READ_BOUNDS_MS))).one())
    assert observed == _EXPECTED_MS


async def test_the_bound_reaches_an_engine_built_from_a_handed_out_url() -> None:
    """``isolated_database_url`` hands out a URL, so nothing sets connect args for it.

    This is the entry point a ``connect_args`` on ``isolated_engine`` would have
    missed entirely: its callers build their own engine, one per event loop. The
    bound has to live on the database for this to hold.
    """
    with isolated_database_url() as url:
        own_engine = create_async_engine(url, future=True)
        try:
            async with own_engine.connect() as conn:
                observed = tuple((await conn.execute(text(_READ_BOUNDS_MS))).one())
        finally:
            await own_engine.dispose()
    assert observed == _EXPECTED_MS


async def test_the_bound_reaches_the_shared_transactional_database() -> None:
    """``transactional_session`` is the widest population of the four by far.

    Every unit and module fixture that needs a session goes through it, against
    the one long-lived ``oe_test_unit`` database. A guard that covered only the
    per-test clones would leave most of the suite unbounded while reading green.
    """
    async with transactional_session() as session:
        observed = tuple((await session.execute(text(_READ_BOUNDS_MS))).one())
    assert observed == _EXPECTED_MS


def test_the_bound_reaches_the_schema_inspection_engine() -> None:
    """The fourth entry point, and the only synchronous one."""
    sync_engine = schema_inspection_engine()
    try:
        with sync_engine.connect() as conn:
            observed = tuple(conn.execute(text(_READ_BOUNDS_MS)).one())
    finally:
        sync_engine.dispose()
    assert observed == _EXPECTED_MS


async def test_an_overrunning_statement_fails_by_name(engine) -> None:
    """The point of the bound: a hang becomes a named failure, not silence.

    Lowered for this one transaction so the test costs a fraction of a second
    rather than :data:`STATEMENT_TIMEOUT_S`. That a session-level value wins over
    the per-database one is itself part of the contract - it is the escape hatch
    a test with a legitimately long statement uses.

    ``SET LOCAL`` and an explicit rollback, not a bare ``SET``. This engine
    pools its connections, so a bare ``SET`` would ride back into the pool and
    hand the next test in this file a 250ms bound it never asked for. In a file
    whose subject is state leaking between tests, leaving that behind would be
    a poor joke.
    """
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            await conn.execute(text("SET LOCAL statement_timeout = '250ms'"))
            with pytest.raises(DBAPIError) as caught:
                await conn.execute(text("SELECT pg_sleep(5)"))
        finally:
            await trans.rollback()
    assert "statement timeout" in str(caught.value).lower(), str(caught.value)

    # And the connection came back clean.
    async with engine.connect() as conn:
        assert tuple((await conn.execute(text(_READ_BOUNDS_MS))).one()) == _EXPECTED_MS


async def test_an_idle_transaction_is_killed_rather_than_left_to_hang() -> None:
    """The other half of "no verdict": a transaction open and issuing nothing.

    ``statement_timeout`` cannot see this. It runs only while a statement does,
    and this session has none - it is holding a transaction open and waiting,
    which is exactly the shape ``transactional_session`` keeps every test in and
    the shape a cross-loop wait produces under ``isolated_database_url``.

    The idle is a Python sleep, not ``pg_sleep``: ``pg_sleep`` is a running
    statement and would be caught by the other bound, proving nothing about this
    one.

    **What the caller actually sees is NOT the server's message.** PostgreSQL
    logs "terminating connection due to idle-in-transaction timeout", but it
    then closes the socket, and asyncpg reports the next statement as
    ``InterfaceError: connection is closed``. Measured, not assumed - this test
    was first written to assert the server's wording and failed against a bound
    that had worked perfectly. So the reason lives in the PostgreSQL log, and
    what reaches pytest is only that the connection died.

    That makes a message assertion worthless on its own: any dropped connection
    produces it. So causation is established by a CONTROL instead. The same
    connection, the same open transaction and the same two-second idle are run
    twice, and the only difference between them is the bound. Under a bound the
    idle does not exceed, the statement must succeed; under one it does exceed,
    the statement must fail. Without the control half, this test would pass on a
    machine that simply drops connections.

    Its own engine, with ``NullPool``, disposed at the end. This bound
    TERMINATES the session rather than cancelling one statement, so the
    connection comes back dead rather than clean, and the ``SET LOCAL`` plus
    rollback that the statement test uses cannot apply - there is nothing left
    to roll back on. Handing that corpse to another test through a shared pool
    would be the same leak this file exists to catch.
    """
    idle_seconds = 2

    with isolated_database_url() as url:
        own_engine = create_async_engine(url, future=True, poolclass=NullPool)
        try:
            # Control: the identical idle, under a bound it does not exceed.
            conn = await own_engine.connect()
            try:
                await conn.begin()
                await conn.execute(text("SET LOCAL idle_in_transaction_session_timeout = '30s'"))
                await asyncio.sleep(idle_seconds)
                survived = (await conn.execute(text("SELECT 1"))).scalar_one()
            finally:
                with contextlib.suppress(Exception):
                    await conn.close()

            # Same again, changing only the bound.
            conn = await own_engine.connect()
            try:
                await conn.begin()
                await conn.execute(text("SET LOCAL idle_in_transaction_session_timeout = '250ms'"))
                await asyncio.sleep(idle_seconds)
                with pytest.raises(DBAPIError) as caught:
                    await conn.execute(text("SELECT 1"))
            finally:
                with contextlib.suppress(Exception):
                    await conn.close()
        finally:
            await own_engine.dispose()

    assert survived == 1, (
        "a 2s idle inside a transaction did not survive a 30s bound, so the failing half below "
        "proves nothing about the bound"
    )
    message = str(caught.value).lower()
    assert "closed" in message or "idle-in-transaction" in message, str(caught.value)


def test_the_bounds_stay_ordered() -> None:
    """Which timeout fires first is a design decision, not an accident.

    Three bounds, and the order they fire in decides which message a developer
    reads. ``lock_timeout`` is shortest so that a statement stuck waiting for a
    lock still reports the clearer "lock timeout". ``statement_timeout`` catches
    what that cannot, a statement running rather than waiting. The idle bound is
    longest of the three because a session doing nothing inside a transaction is
    the least urgent of the failures and the easiest to mistake for a slow test.

    All three must stay under the per-test kill, or the process dies unnamed and
    the bounds have bought nothing. That is the assertion that would have caught
    the number this file originally shipped with: 300 was copied from
    ``conftest`` and ties Backend CI's own 300s kill exactly, which is a race
    rather than a bound.

    ``conftest``'s value is deliberately NOT asserted equal to ours. It bounds
    the maintenance database, which is where ``app.database.engine`` lives; ours
    bound the databases this file hands out. They are separate nets over
    separate populations and a future reader should not "fix" the difference.
    It is read out of the already-imported module through :data:`sys.modules`,
    because importing ``conftest`` by name a second time would boot a second
    PostgreSQL cluster.
    """
    assert LOCK_TIMEOUT_S < STATEMENT_TIMEOUT_S < IDLE_IN_TRANSACTION_TIMEOUT_S
    assert IDLE_IN_TRANSACTION_TIMEOUT_S < _BACKEND_CI_PER_TEST_KILL_S, (
        f"idle bound {IDLE_IN_TRANSACTION_TIMEOUT_S}s must fire before Backend CI's "
        f"{_BACKEND_CI_PER_TEST_KILL_S}s kill, or the process dies without naming the session"
    )

    conftest = sys.modules.get("tests.conftest")
    assert conftest is not None, "tests/conftest.py should already be imported under this name by pytest"
    assert conftest._IDLE_IN_TRANSACTION_TIMEOUT_S > STATEMENT_TIMEOUT_S


async def test_two_isolated_engines_share_neither_schema_nor_rows() -> None:
    """Widening the fixture scope would break the 7 tests named in the docstring.

    Asserted in both directions on purpose. The first half checks that a second
    clone cannot see what the first one wrote. On its own that would also pass if
    the write never landed or the read were aimed at nothing, which is the shape
    of green that means nothing. So the second half re-reads the first database
    through a fresh engine and requires the leftovers to be right there - if they
    are not, the isolation assertion above had no teeth and this test says so.

    Both a table and a row, because the two suites at risk lose different things:
    the counting tests leak rows, ``test_postgres_migrator_indexes`` leaks a
    schema change.
    """
    probe = "fixture_isolation_probe"

    async with isolated_engine() as first:
        first_url = first.url
        async with first.begin() as conn:
            await conn.execute(text(f"CREATE TABLE {probe} (note text)"))
            await conn.execute(text(f"INSERT INTO {probe} (note) VALUES ('left behind')"))

        async with isolated_engine() as second:
            assert second.url.database != first_url.database
            async with second.connect() as conn:
                leaked = (await conn.execute(text("SELECT to_regclass(:name)"), {"name": probe})).scalar_one()
            assert leaked is None, (
                f"{probe} created on {first_url.database} is visible on {second.url.database}: "
                "the fixture is handing out a shared database"
            )

        # Teeth: the same read, aimed at the database that WAS written to.
        witness = create_async_engine(first_url, future=True)
        try:
            async with witness.connect() as conn:
                rows = (await conn.execute(text(f"SELECT note FROM {probe}"))).scalars().all()
        finally:
            await witness.dispose()
        assert rows == ["left behind"], (
            "the probe row is not readable even on its own database, so the isolation assertion above proved nothing"
        )
