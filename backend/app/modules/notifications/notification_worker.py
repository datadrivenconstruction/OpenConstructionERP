# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Background notification worker - periodic digest flush + cleanup.

Epic B / B4-B5: replaces the previous "manual /digest/flush endpoint
only" dispatch model with two recurring tasks that fire on a fixed
cadence:

* :func:`flush_email_digest_periodic`  - every 5 minutes flush every
  email digest row whose ``scheduled_for`` has elapsed.  Keeps the
  user inbox at most 5 minutes behind the requested cadence
  (``hourly`` / ``daily`` semantics live in the pref row; the worker
  is dialect-agnostic and just drains everything that has matured).

* :func:`flush_inapp_digest_periodic` - every 5 minutes flush the
  same way for the in-app channel so users on the "daily summary"
  cadence still get a roll-up without an admin click.

* :func:`cleanup_old_notifications`   - every 24 hours delete
  notifications older than the configured retention window
  (default 90 days).

Scheduler choice
----------------
The project's documented Celery+Redis is optional; many deployments
run without a broker.  This module ships a tiny in-process asyncio
loop that the FastAPI lifespan starts on app boot.  A future PR can
add a Celery shim that calls the same async helpers - they're shaped
as pure coroutines so swapping the driver is a one-file change.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

# Default cadences.  Pulled from the schedule registration block below
# rather than from settings so a quick override only needs a code edit
# in one place; environment-driven overrides can be added later.
_EMAIL_DIGEST_INTERVAL_SEC = 5 * 60  # 5 minutes
_INAPP_DIGEST_INTERVAL_SEC = 5 * 60  # 5 minutes
_CLEANUP_INTERVAL_SEC = 24 * 60 * 60  # 24 hours
_CLEANUP_RETENTION_DAYS = 90

# First retry after a transient failure; doubles on each consecutive one and
# never waits longer than the task's own interval.
_TRANSIENT_RETRY_BASE_SEC = 30.0


# ── Task bodies ────────────────────────────────────────────────────────────


async def flush_email_digest_periodic() -> int:
    """Flush all matured email digest rows.  Returns the row count."""
    from app.database import async_session_factory
    from app.modules.notifications.service import NotificationService

    async with async_session_factory() as session:
        svc = NotificationService(session)
        count = await svc.flush_digest_queue("email")
        await session.commit()
    if count:
        logger.info("notification_worker: flushed %d email digest rows", count)
    return count


async def flush_inapp_digest_periodic() -> int:
    """Flush all matured in-app digest rows.  Returns the row count."""
    from app.database import async_session_factory
    from app.modules.notifications.service import NotificationService

    async with async_session_factory() as session:
        svc = NotificationService(session)
        count = await svc.flush_digest_queue("inapp")
        await session.commit()
    if count:
        logger.info("notification_worker: flushed %d in-app digest rows", count)
    return count


async def flush_webhook_digest_periodic() -> int:
    """Flush all matured webhook digest rows.  Returns the row count."""
    from app.database import async_session_factory
    from app.modules.notifications.service import NotificationService

    async with async_session_factory() as session:
        svc = NotificationService(session)
        count = await svc.flush_digest_queue("webhook")
        await session.commit()
    if count:
        logger.info("notification_worker: flushed %d webhook digest rows", count)
    return count


async def cleanup_old_notifications(retention_days: int = _CLEANUP_RETENTION_DAYS) -> int:
    """Drop notifications older than ``retention_days``."""
    from app.database import async_session_factory
    from app.modules.notifications.service import NotificationService

    async with async_session_factory() as session:
        svc = NotificationService(session)
        count = await svc.delete_old(retention_days)
        await session.commit()
    if count:
        logger.info(
            "notification_worker: cleaned up %d notifications older than %d days",
            count,
            retention_days,
        )
    return count


# ── Scheduler ──────────────────────────────────────────────────────────────


_RUNNING_TASKS: list[asyncio.Task[None]] = []
_SHUTDOWN_EVENT: asyncio.Event | None = None


def _is_transient_db_error(exc: BaseException) -> bool:
    """True when ``exc`` means the database is not reachable yet, not a bug.

    During a slow boot (migrations, a first seed holding the pool) a flush can
    time out connecting or waiting for a pooled connection. That clears on its
    own and is worth one line, not a traceback every five minutes.
    """
    from sqlalchemy.exc import InterfaceError, OperationalError
    from sqlalchemy.exc import TimeoutError as PoolTimeoutError

    return isinstance(
        exc,
        OperationalError | InterfaceError | PoolTimeoutError | ConnectionError | OSError | TimeoutError,
    )


async def _run_periodically(
    name: str,
    coro_factory: Callable[[], Awaitable[int]],
    interval_sec: float,
    shutdown: asyncio.Event,
    retry_base_sec: float = _TRANSIENT_RETRY_BASE_SEC,
) -> None:
    """Run ``coro_factory()`` every ``interval_sec`` until ``shutdown`` is set.

    Errors inside the periodic body are logged and swallowed so a
    single bad iteration cannot kill the schedule.  The first run
    happens after the first interval - no startup race-condition with
    half-mounted modules.

    A database that is not reachable yet is retried sooner, backing off
    from ``retry_base_sec`` up to ``interval_sec``, and logged once per
    streak without a traceback; any other error is still logged in full.
    """
    delay = interval_sec
    failures = 0
    while not shutdown.is_set():
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=delay)
            # If wait returned without timeout, shutdown was requested.
            return
        except TimeoutError:
            pass
        try:
            await coro_factory()
        except Exception as exc:  # noqa: BLE001
            if not _is_transient_db_error(exc):
                failures = 0
                delay = interval_sec
                logger.exception("notification_worker: %s iteration failed", name)
                continue
            failures += 1
            delay = min(retry_base_sec * 2 ** (failures - 1), interval_sec)
            if failures == 1:
                logger.warning(
                    "notification_worker: %s could not reach the database (%s), retrying in %.0fs",
                    name,
                    type(exc).__name__,
                    delay,
                )
            else:
                logger.debug("notification_worker: %s still waiting for the database (attempt %d)", name, failures)
            continue
        if failures:
            logger.info("notification_worker: %s reached the database after %d attempts", name, failures + 1)
        failures = 0
        delay = interval_sec


def _is_scheduler_running() -> bool:
    return bool(_RUNNING_TASKS) and any(not t.done() for t in _RUNNING_TASKS)


def start_scheduler() -> None:
    """Boot the in-process worker.

    Idempotent: a second call while tasks are already running is a
    no-op.  Used from the FastAPI lifespan ``on_startup`` hook.
    """
    global _SHUTDOWN_EVENT
    if _is_scheduler_running():
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("notification_worker: no running loop, scheduler will start lazily")
        return

    _SHUTDOWN_EVENT = asyncio.Event()
    schedule: list[tuple[str, Callable[[], Awaitable[int]], float]] = [
        ("email_digest", flush_email_digest_periodic, _EMAIL_DIGEST_INTERVAL_SEC),
        ("inapp_digest", flush_inapp_digest_periodic, _INAPP_DIGEST_INTERVAL_SEC),
        ("webhook_digest", flush_webhook_digest_periodic, _EMAIL_DIGEST_INTERVAL_SEC),
        ("cleanup", cleanup_old_notifications, _CLEANUP_INTERVAL_SEC),
    ]
    for name, factory, interval in schedule:
        task = loop.create_task(
            _run_periodically(name, factory, interval, _SHUTDOWN_EVENT),
            name=f"notification_worker.{name}",
        )
        _RUNNING_TASKS.append(task)
    logger.info(
        "notification_worker: scheduler started (%d periodic tasks)",
        len(_RUNNING_TASKS),
    )


async def stop_scheduler() -> None:
    """Signal shutdown and wait for every task to finish.  Used in tests."""
    global _SHUTDOWN_EVENT
    if _SHUTDOWN_EVENT is not None:
        _SHUTDOWN_EVENT.set()
    if _RUNNING_TASKS:
        # return_exceptions=True result is deliberately discarded: every task
        # here only ever stops by observing _SHUTDOWN_EVENT inside
        # _run_periodically, which never raises (its own except Exception
        # already logs and swallows per-iteration failures), and nothing in
        # this module ever calls .cancel() on a running task. Safe only as
        # long as both of those stay true - the moment something starts
        # cancelling these tasks, or the result here starts being read, a
        # cancelled task's CancelledError is a BaseException that would need
        # its own check, not a plain isinstance(x, Exception) one.
        await asyncio.gather(*_RUNNING_TASKS, return_exceptions=True)
    _RUNNING_TASKS.clear()
    _SHUTDOWN_EVENT = None


def next_scheduled_runs() -> dict[str, str]:
    """Return a human-readable map of task → next-run timestamp.

    Used by the admin UI / health probe; the actual scheduler does not
    track this state (it's a wait-loop), so we approximate from the
    interval table.  Good enough for ops; not load-bearing.
    """
    now = datetime.now(UTC)
    return {
        "email_digest": (now + timedelta(seconds=_EMAIL_DIGEST_INTERVAL_SEC)).isoformat(),
        "inapp_digest": (now + timedelta(seconds=_INAPP_DIGEST_INTERVAL_SEC)).isoformat(),
        "webhook_digest": (now + timedelta(seconds=_EMAIL_DIGEST_INTERVAL_SEC)).isoformat(),
        "cleanup": (now + timedelta(seconds=_CLEANUP_INTERVAL_SEC)).isoformat(),
    }


__all__ = [
    "cleanup_old_notifications",
    "flush_email_digest_periodic",
    "flush_inapp_digest_periodic",
    "flush_webhook_digest_periodic",
    "next_scheduled_runs",
    "start_scheduler",
    "stop_scheduler",
]
