"""Background Jobs API routes — RFC 34 §4 W0.1.

Endpoints (all prefixed at ``/api/v1/jobs`` by the module loader):

    GET    /{id}            — Read a single JobRun row.
    GET    /                — Paginated list, filterable by kind & status.
    POST   /{id}/cancel     — Best-effort cancel (status to 'cancelled' if
                              still pending or started; revoke the Celery
                              task; no-op for already-finished jobs).

The router is intentionally read-mostly. Job *creation* happens via
:func:`app.core.job_runner.submit_job` from the modules that own the
work — exposing a generic POST /jobs would let callers request any
``kind`` they like, which is a footgun.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.job_run import JobRun
from app.modules.jobs.schemas import JobRunListResponse, JobRunRead

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Background Jobs"])

# How many rows we will return at most per ``GET /``. Caps prevent a
# pathological client from pulling the whole table in one request.
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Resolve the platform's default async session factory.

    Wrapped in a function so tests can patch this symbol to swap in an
    in-memory SQLite factory without touching the global engine.
    """
    from app.database import async_session_factory

    return async_session_factory


# ── GET /{id} ─────────────────────────────────────────────────────────────


@router.get("/{job_id}", response_model=JobRunRead)
async def get_job(job_id: uuid.UUID) -> JobRunRead:
    """Return the current state of a JobRun by id.

    Returns:
        404 when the id is unknown.
    """
    factory = _get_session_factory()
    async with factory() as session:
        row = await session.get(JobRun, job_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"JobRun {job_id} not found",
            )
        return _to_read_model(row)


# ── GET / ─────────────────────────────────────────────────────────────────


@router.get("", response_model=JobRunListResponse)
@router.get("/", response_model=JobRunListResponse)
async def list_jobs(
    kind: str | None = Query(default=None, description="Filter by JobRun.kind"),
    job_status: str | None = Query(
        default=None,
        alias="status",
        description=(
            "Filter by JobRun.status (pending, started, success, failed, "
            "cancelled, retry)."
        ),
    ),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=10_000),
    offset: int = Query(default=0, ge=0),
) -> JobRunListResponse:
    """List JobRun rows newest-first with optional filters.

    ``limit`` is silently clamped to :data:`_MAX_LIMIT` so a misbehaving
    client cannot pull the whole table in one request.
    """
    effective_limit = min(limit, _MAX_LIMIT)

    factory = _get_session_factory()
    async with factory() as session:
        base = select(JobRun)
        count_query = select(func.count()).select_from(JobRun)

        if kind is not None:
            base = base.where(JobRun.kind == kind)
            count_query = count_query.where(JobRun.kind == kind)

        if job_status is not None:
            base = base.where(JobRun.status == job_status)
            count_query = count_query.where(JobRun.status == job_status)

        base = base.order_by(JobRun.created_at.desc()).limit(effective_limit).offset(offset)

        total = (await session.execute(count_query)).scalar_one()
        rows = (await session.execute(base)).scalars().all()

    items = [_to_read_model(r) for r in rows]
    return JobRunListResponse(
        items=items,
        total=int(total),
        limit=effective_limit,
        offset=offset,
        has_more=offset + len(items) < int(total),
    )


# ── POST /{id}/cancel ─────────────────────────────────────────────────────


@router.post("/{job_id}/cancel", response_model=JobRunRead)
async def cancel_job(job_id: uuid.UUID) -> JobRunRead:
    """Best-effort cancel of a still-active JobRun.

    Behaviour:
        * If the JobRun is in ``pending`` or ``started``: status flips
          to ``cancelled``, ``completed_at`` is set, the Celery task
          is revoked (non-terminating; we don't kill mid-flight Python).
        * If the JobRun is already ``success`` / ``failed`` /
          ``cancelled``: returns the row unchanged.
        * If the id is unknown: 404.
    """
    factory = _get_session_factory()
    async with factory() as session:
        row = await session.get(JobRun, job_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"JobRun {job_id} not found",
            )

        if row.status in ("pending", "started"):
            row.status = "cancelled"
            row.completed_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)

            # Best-effort Celery revoke — never fatal. We have already
            # marked the row cancelled, which is the source of truth
            # the UI cares about; a Celery worker that has already
            # picked up the task may still finish, but the result will
            # be ignored when it sees the row is cancelled.
            celery_task_id = row.celery_task_id
            if celery_task_id:
                try:
                    from app.core.jobs import get_celery_app

                    get_celery_app().control.revoke(celery_task_id, terminate=False)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Best-effort Celery revoke failed for task %s",
                        celery_task_id,
                    )

        return _to_read_model(row)


# ── Helpers ───────────────────────────────────────────────────────────────


def _to_read_model(row: JobRun) -> JobRunRead:
    """Translate a JobRun ORM row into the public read model.

    The mapping is explicit (rather than ``model_validate(row)``) so we
    can rename ``result_jsonb`` → ``result`` / ``error_jsonb`` → ``error``
    without leaking internal column names through the API.
    """
    return JobRunRead(
        id=row.id,
        kind=row.kind,
        status=row.status,
        progress_percent=row.progress_percent,
        result=row.result_jsonb,
        error=row.error_jsonb,
        started_at=row.started_at,
        completed_at=row.completed_at,
        retry_count=row.retry_count,
        idempotency_key=row.idempotency_key,
        created_at=row.created_at,
        updated_at=row.updated_at,
        tenant_id=row.tenant_id,
    )
