# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Celery task definitions - RFC 34 §4 W0.1.

There is exactly one task: ``oe.dispatch_job``. Module-specific work
attaches via :func:`app.core.job_runner.register_handler`, NOT via
``@celery_app.task``. This keeps the worker entry point a single,
small, well-tested generic dispatcher.

The dispatcher loads the JobRun by id, looks up the handler registered
for ``JobRun.kind``, and invokes the lifecycle helpers in
:mod:`app.core.job_runner`. All persistence runs through SQLAlchemy
async sessions; the task body itself stays sync (Celery's contract)
and uses ``asyncio.run`` to bridge.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.core.jobs import celery_app

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the platform's default async session factory.

    Wrapped in a function so unit tests can patch this symbol to swap
    in an in-memory SQLite factory without monkey-patching the global
    ``app.database.async_session_factory``.
    """
    from app.database import async_session_factory

    return async_session_factory


async def _dispatch_job_via_dedicated_engine(
    job_uuid: uuid.UUID,
    base_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Run ``_dispatch_job_sync`` against a connection scoped to this call.

    ``_run_async_in_dedicated_thread`` gives every dispatch a brand-new
    event loop - a fresh ``asyncio.run()`` each time. ``base_factory`` is
    whatever ``_get_session_factory()`` currently resolves to (production,
    or a test's patched-in isolated database): an ``async_sessionmaker``
    bound to a pooled engine that outlives any single dispatch. A
    connection checked out on one loop and later reused from a *different*
    loop makes asyncpg raise ``RuntimeError: ... got Future ... attached to
    a different loop`` - deterministically from the second dispatch onward
    in any one worker process, since a connection returned to the pool at
    the end of one ``asyncio.run()`` is still sitting there, bound to a
    loop that no longer exists, when the next dispatch's loop starts.

    The fix builds a throwaway engine for this dispatch alone, pointed at
    the exact same database as ``base_factory`` (same URL, same
    localhost/SSL handling as ``app.database.create_engine_from_settings``)
    but with ``NullPool``, so no connection is ever held between checkouts
    to begin with - nothing can outlive the loop that opened it. Disposed
    in the ``finally`` below; under ``NullPool`` there is nothing left
    pooled to dispose of, but an explicit dispose keeps the engine's own
    bookkeeping tidy rather than relying on garbage collection for it.

    ``base_factory`` decides *which* database this dispatch talks to; this
    function only changes how connections to that database are pooled for
    the lifetime of one dispatch. It does not change what
    ``_dispatch_job_sync`` does with the session it is handed - only which
    engine that session comes from.
    """
    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
    from sqlalchemy.ext.asyncio import async_sessionmaker as _async_sessionmaker
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.job_runner import _dispatch_job_sync
    from app.database import _tolerant_json_loads

    base_engine = base_factory.kw.get("bind")
    if base_engine is None:
        raise RuntimeError("Session factory passed to job dispatch has no bound engine")

    # Mirrors app.database.create_engine_from_settings: asyncpg defaults to
    # sslmode "prefer" and eagerly builds an SSLContext even for loopback,
    # which crashes on the bundled OpenSSL in a frozen desktop build. Same
    # URL as base_engine, so this is always the same database, just with a
    # pool that cannot go stale across event loops.
    host = (base_engine.url.host or "").lower()
    connect_args: dict = {"ssl": False} if host in ("", "localhost", "127.0.0.1", "::1") else {}

    # Bound abandoned transactions here too, but on a budget of this path's own.
    #
    # A worker killed mid-dispatch leaves its transaction open and holding every
    # lock it took until the connection closes, and nothing on the waiting side
    # ends that. ``idle_in_transaction_session_timeout`` is what removes it. This
    # engine cannot simply come through ``create_engine_from_settings`` to get
    # the parameter: that factory returns a sized pool (measured:
    # AsyncAdaptedQueuePool, 24 + 10 overflow, pre-ping, recycle), and NullPool
    # is the whole point of building an engine here - a pooled connection opened
    # on one dispatch's event loop and reused from the next one's makes asyncpg
    # raise "attached to a different loop". The factory also reads
    # ``settings.database_url`` rather than ``base_engine.url``, which would
    # silently move a dispatch off the database ``base_factory`` chose. So the
    # parameter is passed here instead, and the duplication is deliberate.
    #
    # The budget is the jobs one, not the request one: a handler that parses a
    # large file or calls an external service is legitimately idle in its
    # transaction for that whole time, and the request-side value would cut it.
    # See ``Settings.database_jobs_idle_in_transaction_timeout`` for why the
    # number is an order of magnitude rather than a measurement. 0 disables it.
    from app.config import get_settings

    idle_ms = max(0, get_settings().database_jobs_idle_in_transaction_timeout) * 1000
    if idle_ms:
        # asyncpg requires string values here; PostgreSQL reads a bare number as
        # milliseconds.
        connect_args["server_settings"] = {"idle_in_transaction_session_timeout": str(idle_ms)}

    dedicated_engine = create_async_engine(
        base_engine.url,
        future=True,
        json_deserializer=_tolerant_json_loads,
        poolclass=NullPool,
        connect_args=connect_args,
    )
    dedicated_factory = _async_sessionmaker(dedicated_engine, class_=_AsyncSession, expire_on_commit=False)
    try:
        await _dispatch_job_sync(job_uuid, session_factory=dedicated_factory)
    finally:
        await dedicated_engine.dispose()


@celery_app.task(name="oe.dispatch_job", bind=True)
def dispatch_job(self, job_run_id: str) -> dict[str, str]:  # noqa: ANN001 - Celery's bind=True
    """Generic dispatch task - runs the handler registered for JobRun.kind.

    Returns a small dict with the outcome so Celery's own result
    backend has something useful to log. The authoritative outcome is
    written to the JobRun row by the lifecycle helpers in
    :mod:`app.core.job_runner`.
    """
    import uuid as _uuid

    job_uuid = _uuid.UUID(job_run_id)
    factory = _get_session_factory()

    # Celery tasks are sync, but our DB layer is async. We must NOT
    # call ``asyncio.run`` if a loop is already running on this thread
    # (which is the case in eager-mode tests that run inside pytest's
    # asyncio loop). The portable bridge is to spin up a dedicated
    # thread whose only job is to drive a fresh event loop. See
    # _dispatch_job_via_dedicated_engine for why that loop also gets its
    # own throwaway engine rather than reusing factory's pooled one.
    _run_async_in_dedicated_thread(
        _dispatch_job_via_dedicated_engine(job_uuid, factory),
    )
    return {"job_run_id": job_run_id, "status": "dispatched"}


def _run_async_in_dedicated_thread(coro) -> None:  # noqa: ANN001 - coroutine
    """Run a coroutine to completion on its own thread + event loop.

    Required by the Celery dispatch task because Celery tasks are sync
    while our DB layer is async, and ``asyncio.run`` cannot be called
    from a thread that already has a running loop. That is not just a
    test-only concern: eager mode (``task_always_eager = True``, the
    documented dev / lightweight-deployment default - see the stack
    table in the project CLAUDE.md) runs the task in-process on
    whatever thread called ``apply()``, and that thread is frequently
    the one driving the caller's own asyncio loop. A real, non-eager
    Celery worker thread usually has no loop of its own, so
    ``asyncio.run`` would work there without this helper - but this
    function does not special-case either mode. It always hands the
    coroutine to a brand-new thread, so the loop it runs on is always
    one this call created and nothing else could already be driving.

    That freshness is also why every dispatch is handed its own engine
    (see :func:`_dispatch_job_via_dedicated_engine`): a new loop here
    does not imply new connections unless the thing using it is built
    not to reuse old ones either.
    """
    import threading

    exception_holder: list[BaseException] = []

    def _runner() -> None:
        try:
            asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - re-raise on caller thread
            exception_holder.append(exc)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if exception_holder:
        raise exception_holder[0]
