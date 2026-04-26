# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""High-level helpers around the JobRun row — RFC 34 §4 W0.1.

This module is the API surface every other Wave (CDE upload pipeline,
BIM diff engine, EAC validator, QTO export, …) talks to:

* ``register_handler(kind, handler)`` — module bootstrap registers its
  background work by ``kind`` here.
* ``submit_job(kind, payload, idempotency_key=...)`` — endpoint code
  enqueues a background task and gets back a JobRun row whose ``id``
  the client can poll.
* ``update_progress(job_run_id, percent, message)`` — handlers report
  progress as they run.

The split keeps the Celery transport (``app.core.jobs``,
``app.core.jobs_tasks``) decoupled from business code — handlers never
import Celery directly.

Idempotency contract
--------------------
``idempotency_key`` is a UNIQUE column on ``oe_job_run``. We enforce
de-duplication in two layers:

1. Optimistic SELECT first: lookup by key, return existing row if found.
2. Pessimistic INSERT: race losers will trip the UNIQUE constraint, and
   we then re-read to return the winner's row.

This double-check pattern handles the inevitable race between two
concurrent callers without a serialisable transaction.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.job_run import JobRun

logger = logging.getLogger(__name__)


# Handlers may be either sync or async — we await whichever they are.
type JobHandler = Callable[[JobRun, dict[str, Any]], Any]


# ── Handler registry ─────────────────────────────────────────────────────


_HANDLERS: dict[str, JobHandler] = {}


def register_handler(kind: str, handler: JobHandler) -> None:
    """Register a handler for a JobRun ``kind``.

    Re-registering the same kind silently overrides — useful in tests,
    matches the Pythonic "last write wins" convention, and avoids
    surprising registration ordering bugs at module-load time.
    """
    _HANDLERS[kind] = handler
    logger.debug("Registered job handler: kind=%s handler=%s", kind, handler.__name__)


def unregister_handler(kind: str) -> None:
    """Remove a handler from the registry. No-op if absent."""
    _HANDLERS.pop(kind, None)


def get_handler(kind: str) -> JobHandler | None:
    """Return the registered handler for a kind, or None."""
    return _HANDLERS.get(kind)


# ── Session factory plumbing ─────────────────────────────────────────────


def _default_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the platform's default async session factory.

    Imported lazily to avoid pulling in the global engine during
    test collection (the in-memory SQLite tests inject their own
    factory directly).
    """
    from app.database import async_session_factory

    return async_session_factory


# ── Celery dispatch shim ─────────────────────────────────────────────────


def _dispatch_to_celery(job_run_id: uuid.UUID) -> str:
    """Hand the JobRun to a Celery worker and return Celery's task id.

    Carved out as a standalone helper so unit tests can patch it without
    starting a real Celery app. The patch target is the symbol exported
    here, not the underlying Celery method, which keeps the test
    contract stable across Celery version bumps.
    """
    from app.core.jobs_tasks import dispatch_job

    async_result = dispatch_job.apply_async(args=[str(job_run_id)])
    return str(async_result.id)


# ── Public API: submit_job ────────────────────────────────────────────────


async def submit_job(
    kind: str,
    payload: dict[str, Any],
    *,
    idempotency_key: str | None = None,
    tenant_id: uuid.UUID | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> JobRun:
    """Create (or reuse) a JobRun row and queue the dispatch task.

    Args:
        kind: Handler key registered via :func:`register_handler`.
        payload: JSON-serialisable input for the handler.
        idempotency_key: Optional UNIQUE token — if present and matches
            an existing row, that row is returned and no new Celery
            dispatch is queued.
        tenant_id: Optional tenant scope (RLS placeholder for now —
            indexed but not enforced).
        session_factory: Override for testing. Defaults to the global
            async session factory.

    Returns:
        The created (or existing) JobRun, expunged from the session so
        callers can read attributes without a refresh.
    """
    factory = session_factory or _default_session_factory()

    # ── 1. Fast path: return the existing row when the key matches.
    if idempotency_key is not None:
        existing = await _find_by_idempotency_key(idempotency_key, factory)
        if existing is not None:
            return existing

    # ── 2. Insert. Race-loser branch falls into the IntegrityError below.
    new_id = uuid.uuid4()
    async with factory() as session:
        row = JobRun(
            id=new_id,
            tenant_id=tenant_id,
            kind=kind,
            status="pending",
            progress_percent=0,
            payload_jsonb=dict(payload),
            idempotency_key=idempotency_key,
        )
        session.add(row)
        try:
            await session.commit()
        except IntegrityError:
            # A concurrent caller already inserted the same idempotency_key.
            # Roll back, then re-fetch to return the winner.
            await session.rollback()
            if idempotency_key is None:
                # Should never happen, but re-raise so we don't silently swallow.
                raise
            existing = await _find_by_idempotency_key(idempotency_key, factory)
            if existing is not None:
                return existing
            # Truly impossible at this point, but be loud if it happens.
            raise

        await session.refresh(row)
        # Detach so callers can read attributes without an active session.
        session.expunge(row)

    # ── 3. Dispatch to Celery and record the task id on the row.
    try:
        celery_task_id = _dispatch_to_celery(row.id)
    except Exception as exc:  # noqa: BLE001
        # Dispatch failed — mark the row failed so the UI doesn't spin
        # waiting for a worker that will never run. Keep the original
        # exception for the caller; this is a real error path.
        logger.exception("Celery dispatch failed for job_run_id=%s", row.id)
        await _mark_dispatch_failed(row.id, exc, factory)
        raise

    if celery_task_id:
        await _attach_celery_task_id(row.id, celery_task_id, factory)
        row.celery_task_id = celery_task_id

    return row


async def _find_by_idempotency_key(
    idempotency_key: str,
    factory: async_sessionmaker[AsyncSession],
) -> JobRun | None:
    async with factory() as session:
        existing = (
            await session.execute(
                select(JobRun).where(JobRun.idempotency_key == idempotency_key),
            )
        ).scalar_one_or_none()
        if existing is None:
            return None
        session.expunge(existing)
        return existing


async def _attach_celery_task_id(
    job_run_id: uuid.UUID,
    celery_task_id: str,
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        row = await session.get(JobRun, job_run_id)
        if row is None:
            return
        row.celery_task_id = celery_task_id
        await session.commit()


async def _mark_dispatch_failed(
    job_run_id: uuid.UUID,
    exc: BaseException,
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        row = await session.get(JobRun, job_run_id)
        if row is None:
            return
        row.status = "failed"
        row.completed_at = datetime.now(UTC)
        row.error_jsonb = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
            "phase": "dispatch",
        }
        await session.commit()


# ── Public API: update_progress ──────────────────────────────────────────


async def update_progress(
    job_run_id: uuid.UUID,
    *,
    percent: int,
    message: str | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Atomically advance ``progress_percent`` (and optional message).

    Behaviour:
        * percent is clamped into [0, 100].
        * Updates that would *decrease* progress are silently dropped —
          stale progress events from retried tasks must not roll back
          the UI's progress bar.
        * ``message=None`` keeps the previous progress message intact;
          pass an empty string explicitly if you want to clear it.
        * Unknown ``job_run_id`` is a no-op (best-effort semantics —
          the handler must not crash if its row was deleted by tests).
    """
    factory = session_factory or _default_session_factory()
    clamped = max(0, min(100, int(percent)))

    async with factory() as session:
        row = await session.get(JobRun, job_run_id)
        if row is None:
            return

        # Monotonic — never regress.
        if clamped > row.progress_percent:
            row.progress_percent = clamped

        if message is not None:
            current = dict(row.result_jsonb or {})
            current["progress_message"] = message
            row.result_jsonb = current

        await session.commit()


# ── Public API: synchronous dispatch (used by Celery task body) ──────────


async def _dispatch_job_sync(
    job_run_id: uuid.UUID,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Run a JobRun through its lifecycle on the calling thread.

    Called from the Celery worker task body. Loads the row, flips it
    to ``started``, dispatches to the registered handler, then writes
    back ``success`` / ``failed`` based on the outcome.

    Exposed at module scope (rather than nested in the Celery task) so
    unit tests can verify the lifecycle without spinning up a worker.
    """
    factory = session_factory or _default_session_factory()

    async with factory() as session:
        row = await session.get(JobRun, job_run_id)
        if row is None:
            logger.warning("dispatch_job: JobRun id=%s not found", job_run_id)
            return

        # Cancelled-before-start: respect the cancellation, do nothing.
        if row.status == "cancelled":
            return

        row.status = "started"
        row.started_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(row)
        kind = row.kind
        payload = dict(row.payload_jsonb or {})
        # Snapshot for the handler — we don't want to hold the session
        # open while the handler runs (which may take minutes).
        snapshot = row
        session.expunge(snapshot)

    handler = get_handler(kind)
    if handler is None:
        await _record_failure(
            job_run_id,
            RuntimeError(f"No handler registered for kind={kind!r}"),
            factory,
        )
        return

    try:
        result = handler(snapshot, payload)
        if isinstance(result, Awaitable):
            result = await result
        result_dict: dict[str, Any] = result if isinstance(result, dict) else {"result": result}
    except Exception as exc:  # noqa: BLE001 — record + return; do not raise.
        logger.exception("Job handler raised: kind=%s job_run_id=%s", kind, job_run_id)
        await _record_failure(job_run_id, exc, factory)
        return

    await _record_success(job_run_id, result_dict, factory)


async def _record_success(
    job_run_id: uuid.UUID,
    result: dict[str, Any],
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        row = await session.get(JobRun, job_run_id)
        if row is None:
            return
        row.status = "success"
        row.completed_at = datetime.now(UTC)
        # Merge with any progress_message already on the row.
        merged = dict(row.result_jsonb or {})
        merged.update(result)
        row.result_jsonb = merged
        await session.commit()


async def _record_failure(
    job_run_id: uuid.UUID,
    exc: BaseException,
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        row = await session.get(JobRun, job_run_id)
        if row is None:
            return
        row.status = "failed"
        row.completed_at = datetime.now(UTC)
        row.error_jsonb = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        await session.commit()


# ── Sync convenience wrapper for Celery task body ────────────────────────


def run_dispatch_blocking(job_run_id: uuid.UUID) -> None:
    """Synchronous entry point usable from a Celery worker process.

    Celery tasks run in a sync context; this wraps the async dispatch
    in an event loop so the task body itself can stay one-liner simple.
    """
    asyncio.run(_dispatch_job_sync(job_run_id))
