# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every connection the app opens must carry a bound on abandoned transactions.

A session that opens a transaction and then stops talking keeps every lock it
took until its connection closes. The fuse this tree already had is
``lock_timeout``, and it is on the wrong side of that: it makes each VICTIM of
an abandoned transaction give up faster while the culprit stays open and waits
for the next victim. ``idle_in_transaction_session_timeout`` is the one that
removes the culprit, and until now no application connection carried it - the
only place it existed was ``tests/conftest.py``, which sets it on the test
DATABASE and therefore says nothing about production.

These tests are built so that only the new mechanism can make them pass. The
test database already carries a 300s database-level default, so a connection
reporting "some non-zero value" would prove nothing. Every assertion here is
made against a budget no database default supplies, which can only have arrived
as the startup parameter the engine now sends.

There are two engines and therefore two halves: connections from
``create_engine_from_settings`` (2 seconds here), and the per-dispatch engine
background jobs build for themselves (7 seconds here), which cannot come through
that factory because it needs NullPool and carries a far larger budget.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

# Short enough to keep the suite fast, long enough that a loaded machine cannot
# reach it between two adjacent statements.
_TIGHT_S = 2
# The control's budget. Far above the idle both connections actually spend, so
# the only difference between the two legs is the number, not the waiting.
_ROOMY_S = 120
# Longer than _TIGHT_S, far shorter than _ROOMY_S: one shared idle period that
# one budget forbids and the other permits.
_IDLE_S = 3.5


def _engine_with(seconds: int):
    """Build an engine through the real factory, with this idle budget."""
    import app.database as database_module
    from app.config import get_settings

    settings = get_settings().model_copy(update={"database_idle_in_transaction_timeout": seconds})
    original = database_module.get_settings
    database_module.get_settings = lambda: settings
    try:
        return database_module.create_engine_from_settings()
    finally:
        database_module.get_settings = original


async def _skip_unless_postgres() -> None:
    from app.database import engine

    if engine.dialect.name != "postgresql":
        pytest.skip("idle_in_transaction_session_timeout is PostgreSQL-specific")


@pytest.mark.asyncio
async def test_the_budget_reaches_the_server_on_a_live_connection() -> None:
    """Ask the server, not the settings object: a config read proves nothing.

    ``ALTER DATABASE`` in conftest already puts 300s on this database, so the
    value asserted here is deliberately one no default supplies.
    """
    await _skip_unless_postgres()

    engine = _engine_with(_TIGHT_S)
    try:
        async with engine.connect() as conn:
            observed = (await conn.exec_driver_sql("SHOW idle_in_transaction_session_timeout")).scalar()
    finally:
        await engine.dispose()

    assert observed in ("2s", "2000ms"), (
        f"the connection reports idle_in_transaction_session_timeout={observed!r}; "
        "the engine's startup parameter did not reach the server"
    )


@pytest.mark.asyncio
async def test_an_abandoned_transaction_is_killed_by_its_budget_not_by_idling() -> None:
    """The behaviour, with the controls that separate the explanations.

    Three connections open a transaction and then idle for the same wall-clock
    period. The only thing that differs is the budget each was built with: 2s,
    120s, and none at all. The 2s one is gone afterwards and the other two are
    still sitting in their transactions, so neither "idling kills connections
    here" nor "something else cut it" survives the result. The third leg is the
    connection this tree opened before the change, idling long enough to have
    been killed - it is the red half of the proof, kept in the test.
    """
    await _skip_unless_postgres()

    from app.database import engine as app_engine

    tight = _engine_with(_TIGHT_S)
    roomy = _engine_with(_ROOMY_S)
    # 0 means the factory sends no startup parameter at all - the connection
    # this tree opened before this change. It is the red half of the proof:
    # it idles exactly as long as the one that dies.
    unbounded = _engine_with(0)
    tight_conn = await tight.connect()
    roomy_conn = await roomy.connect()
    unbounded_conn = await unbounded.connect()
    try:
        # A statement is what puts a session INTO a transaction: SQLAlchemy's
        # BEGIN is lazy, and a connection that has executed nothing is `idle`,
        # not `idle in transaction`, so the server would never touch it.
        tight_pid = (await tight_conn.execute(text("SELECT pg_backend_pid()"))).scalar()
        roomy_pid = (await roomy_conn.execute(text("SELECT pg_backend_pid()"))).scalar()
        unbounded_pid = (await unbounded_conn.execute(text("SELECT pg_backend_pid()"))).scalar()

        await asyncio.sleep(_IDLE_S)

        # Ask a third connection what the server did with the other two. The
        # victim's own error does not name the cause - asyncpg only reports
        # that its socket is closed - so read the verdict where it is written.
        async with app_engine.connect() as observer:
            states = dict(
                (
                    await observer.execute(
                        text("SELECT pid, state FROM pg_stat_activity WHERE pid IN (:tight, :roomy, :off)"),
                        {"tight": tight_pid, "roomy": roomy_pid, "off": unbounded_pid},
                    )
                ).all()
            )

        assert tight_pid not in states, (
            f"the backend on a {_TIGHT_S}s budget is still there after {_IDLE_S}s "
            f"idle in transaction (state {states.get(tight_pid)!r}); nothing removed it"
        )
        assert states.get(roomy_pid) == "idle in transaction", (
            f"the control backend on a {_ROOMY_S}s budget reports "
            f"{states.get(roomy_pid)!r}; it was supposed to still be sitting in "
            "its transaction, which is what makes the kill above about the budget"
        )
        assert states.get(unbounded_pid) == "idle in transaction", (
            f"the backend built with the parameter switched off reports "
            f"{states.get(unbounded_pid)!r}; it is the connection this tree used to "
            "open, and it has to survive the idle that killed the bounded one - "
            "otherwise something other than this setting is doing the killing"
        )

        # And the consequence the application sees: the victim's connection is
        # gone, the control's still answers.
        with pytest.raises(DBAPIError):
            await tight_conn.execute(text("SELECT 1"))
        assert (await roomy_conn.execute(text("SELECT 1"))).scalar() == 1
    finally:
        for conn in (tight_conn, roomy_conn, unbounded_conn):
            with contextlib.suppress(Exception):  # the tight one is already gone
                await conn.close()
        for eng in (tight, roomy, unbounded):
            await eng.dispose()


def test_the_shipped_default_is_not_zero() -> None:
    """The tests above run on a budget they set themselves; this is the one
    that speaks for what a real install gets. 0 would mean unbounded."""
    from app.config import Settings

    default = Settings.model_fields["database_idle_in_transaction_timeout"].default

    assert isinstance(default, int) and default > 0, (
        f"database_idle_in_transaction_timeout defaults to {default!r}; a default of 0 "
        "leaves every abandoned transaction holding its locks until the connection closes"
    )


# ── Background job dispatch ──────────────────────────────────────────────
# Job dispatch builds its own engine instead of coming through the factory,
# because it needs NullPool: a pooled connection opened on one dispatch's event
# loop and reused from the next one's makes asyncpg raise "attached to a
# different loop". So it carries the bound itself, on its own budget - a handler
# parsing a large file or calling an external service is legitimately idle
# inside its transaction for that whole time.

# A value no default anywhere supplies: not the request-side 300s, not the 300s
# this test database carries, not the shipped jobs default. Only the jobs path
# reading its own setting can produce it.
_JOBS_BUDGET_S = 7

# The dispatch helper these two tests drive lives in the Celery worker module,
# which imports ``celery`` at module scope because that is what it is for.
# Celery is the optional ``server`` extra, so on a base install the import
# fails and both tests error out rather than reporting anything about the
# engine. They are not skipped everywhere: ci-postgres installs
# ``.[dev,server]`` and runs them for real, which is the lane that gates a
# release. What this guard removes is a base install reporting a missing
# optional dependency as a failure of the thing under test.
#
# Named on the extra rather than on the module so the reason a reader sees is
# the one they can act on: install the extra, or read the result in the lane
# that has it.
_requires_the_server_extra = pytest.mark.skipif(
    importlib.util.find_spec("celery") is None,
    reason="needs the optional 'server' extra (celery); ci-postgres installs .[dev,server] and runs these",
)


async def _build_dispatch_engine(budget_s: int):
    """Return the engine one job dispatch builds, with this jobs budget.

    Drives the real ``_dispatch_job_via_dedicated_engine`` and intercepts the
    engine it constructs, so what is asserted below is the engine background
    jobs actually get - not a re-creation of it in the test.
    """
    import uuid
    from unittest.mock import patch

    import sqlalchemy.ext.asyncio as sa_asyncio

    import app.config as config_module
    import app.core.job_runner as job_runner_module
    from app.core.jobs_tasks import _dispatch_job_via_dedicated_engine
    from app.database import async_session_factory

    settings = config_module.get_settings().model_copy(update={"database_jobs_idle_in_transaction_timeout": budget_s})
    captured = {}
    real_create = sa_asyncio.create_async_engine

    def _capture(*args, **kwargs):
        engine = real_create(*args, **kwargs)
        captured["engine"] = engine
        return engine

    async def _no_dispatch(*_args, **_kwargs):
        """The dispatch itself is not what is under test here."""

    with (
        patch.object(config_module, "get_settings", lambda: settings),
        patch.object(sa_asyncio, "create_async_engine", _capture),
        patch.object(job_runner_module, "_dispatch_job_sync", _no_dispatch),
    ):
        await _dispatch_job_via_dedicated_engine(uuid.uuid4(), async_session_factory)

    assert "engine" in captured, "the dispatch did not build an engine to inspect"
    return captured["engine"]


@_requires_the_server_extra
@pytest.mark.asyncio
async def test_a_job_dispatch_connection_carries_the_jobs_budget() -> None:
    """Ask the server what the dispatch's connection got, not the settings.

    The engine is disposed by the dispatch's own ``finally``; under NullPool
    that pools nothing, so connecting again here opens a fresh connection
    through the very ``connect_args`` the dispatch built.
    """
    await _skip_unless_postgres()

    engine = await _build_dispatch_engine(_JOBS_BUDGET_S)
    try:
        async with engine.connect() as conn:
            observed = (await conn.exec_driver_sql("SHOW idle_in_transaction_session_timeout")).scalar()
    finally:
        await engine.dispose()

    assert observed in ("7s", "7000ms"), (
        f"a background job's connection reports idle_in_transaction_session_timeout={observed!r}; "
        "it did not get the jobs budget"
    )


@_requires_the_server_extra
@pytest.mark.asyncio
async def test_the_jobs_engine_still_pools_nothing() -> None:
    """The bound must not have arrived by routing dispatch through the factory.

    ``create_engine_from_settings`` returns a sized pool, and a pooled
    connection cannot survive one event loop per dispatch. This asserts the
    thing that would silently break if someone consolidated the two paths.
    """
    from sqlalchemy.pool import NullPool

    engine = await _build_dispatch_engine(_JOBS_BUDGET_S)
    try:
        assert isinstance(engine.pool, NullPool), (
            f"a job dispatch got a {type(engine.pool).__name__}; it needs NullPool, because a "
            "connection opened on one dispatch's event loop cannot be reused from the next one's"
        )
    finally:
        await engine.dispose()


def test_the_jobs_budget_is_far_larger_than_the_request_one() -> None:
    """A handler doing non-database work inside a transaction is legitimately
    idle for far longer than any gap between two statements of one request. If
    these two ever converge, the jobs budget has become a deadline on that work
    rather than a fuse against an abandoned one."""
    from app.config import Settings

    jobs = Settings.model_fields["database_jobs_idle_in_transaction_timeout"].default
    request = Settings.model_fields["database_idle_in_transaction_timeout"].default

    assert isinstance(jobs, int) and jobs > 0, (
        f"database_jobs_idle_in_transaction_timeout defaults to {jobs!r}; 0 leaves a wedged "
        "worker holding its locks until the connection closes"
    )
    assert jobs >= request * 4, (
        f"the jobs budget ({jobs}s) is not meaningfully larger than the request one ({request}s); "
        "it would cut legitimate handler work instead of only abandoned transactions"
    )
