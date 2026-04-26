# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Celery task definitions — RFC 34 §4 W0.1.

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


@celery_app.task(name="oe.dispatch_job", bind=True)
def dispatch_job(self, job_run_id: str) -> dict[str, str]:  # noqa: ANN001 — Celery's bind=True
    """Generic dispatch task — runs the handler registered for JobRun.kind.

    Returns a small dict with the outcome so Celery's own result
    backend has something useful to log. The authoritative outcome is
    written to the JobRun row by the lifecycle helpers in
    :mod:`app.core.job_runner`.
    """
    import uuid as _uuid

    from app.core.job_runner import _dispatch_job_sync

    job_uuid = _uuid.UUID(job_run_id)
    factory = _get_session_factory()

    # Celery tasks are sync, but our DB layer is async. We must NOT
    # call ``asyncio.run`` if a loop is already running on this thread
    # (which is the case in eager-mode tests that run inside pytest's
    # asyncio loop). The portable bridge is to spin up a dedicated
    # thread whose only job is to drive a fresh event loop.
    _run_async_in_dedicated_thread(
        _dispatch_job_sync(job_uuid, session_factory=factory),
    )
    return {"job_run_id": job_run_id, "status": "dispatched"}


def _run_async_in_dedicated_thread(coro) -> None:  # noqa: ANN001 — coroutine
    """Run a coroutine to completion on its own thread + event loop.

    Required by the Celery dispatch task because:
      * Celery tasks are sync.
      * In production, the worker thread has no event loop, so
        ``asyncio.run`` would Just Work.
      * In eager-mode tests, the calling thread already has a loop
        (pytest-asyncio's), so ``asyncio.run`` raises
        ``RuntimeError: asyncio.run() cannot be called from a
        running event loop``.

    Spinning up a thread side-steps both cases uniformly.
    """
    import threading

    exception_holder: list[BaseException] = []

    def _runner() -> None:
        try:
            asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 — re-raise on caller thread
            exception_holder.append(exc)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if exception_holder:
        raise exception_holder[0]
