# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Background Jobs API routes - RFC 34 §4 W0.1.

Endpoints (all prefixed at ``/api/v1/jobs`` by the module loader):

    GET    /{id}            - Read a single JobRun row.
    GET    /                - Paginated list, filterable by kind & status.
    POST   /{id}/cancel     - Best-effort cancel (status to 'cancelled' if
                              still pending or started; revoke the Celery
                              task; no-op for already-finished jobs).

The router is intentionally read-mostly. Job *creation* happens via
:func:`app.core.job_runner.submit_job` from the modules that own the
work - exposing a generic POST /jobs would let callers request any
``kind`` they like, which is a footgun.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.job_run import JobRun
from app.dependencies import CurrentUserId, RequireRole
from app.modules.jobs.schemas import JobRunListResponse, JobRunRead

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Background Jobs"])

# How many rows we will return at most per ``GET /``. Caps prevent a
# pathological client from pulling the whole table in one request.
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200

# INTERIM SECURITY GATE (IDOR fix). The JobRun table is per-tenant but carries
# no created_by / owner column yet, so these introspection endpoints (read a
# single job, list/filter jobs, cancel a job) cannot enforce per-row ownership.
# Without a gate, any authenticated user could read or cancel ANY tenant's
# JobRun, whose result_jsonb / error_jsonb hold business payloads (closeout,
# finance connector pushes, CAD conversions, EAC). Until a per-row owner column
# and a migration land, we admin-gate these three endpoints via the existing
# RequireRole("admin") dependency so a non-admin cannot reach arbitrary jobs.
# Job submission stays untouched: creation happens through
# app.core.job_runner.submit_job in the owning modules, not via this router.
_require_admin = Depends(RequireRole("admin"))


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Resolve the platform's default async session factory.

    Wrapped in a function so tests can patch this symbol to swap in an
    in-memory SQLite factory without touching the global engine.
    """
    from app.database import async_session_factory

    return async_session_factory


# ── GET /{id} ─────────────────────────────────────────────────────────────


# Admin-gated (interim IDOR fix): no per-row owner column on JobRun yet, so a
# non-admin must not be able to read another tenant's job result/error blob.
@router.get("/{job_id}", response_model=JobRunRead, dependencies=[_require_admin])
async def get_job(job_id: uuid.UUID, _user_id: CurrentUserId) -> JobRunRead:
    """Return the current state of a JobRun by id.

    Returns:
        404 when the id is unknown.

    Authentication is required: the JobRun result/error blobs may carry
    business data (cost-estimation outputs, AI-classification results,
    exported files) that must not leak to anonymous callers. The table
    is per-tenant (``tenant_id`` column) but RLS isn't enabled yet - at
    minimum, anonymous reads are blocked here.
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


# Admin-gated (interim IDOR fix): listing/filtering returns rows across every
# tenant because JobRun has no per-row owner column yet. Both the "" alias and
# the "/" path are gated so a non-admin cannot enumerate other tenants' jobs.
@router.get("", response_model=JobRunListResponse, dependencies=[_require_admin])
@router.get("/", response_model=JobRunListResponse, dependencies=[_require_admin])
async def list_jobs(
    _user_id: CurrentUserId,
    kind: str | None = Query(default=None, description="Filter by JobRun.kind"),
    job_status: str | None = Query(
        default=None,
        alias="status",
        description=("Filter by JobRun.status (pending, started, success, failed, cancelled, retry)."),
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


# Admin-gated (interim IDOR fix): without a per-row owner column, an
# authenticated non-admin could cancel any tenant's active job by guessing its
# UUID. RequireRole("admin") closes that until per-row ownership lands.
@router.post("/{job_id}/cancel", response_model=JobRunRead, dependencies=[_require_admin])
async def cancel_job(job_id: uuid.UUID, _user_id: CurrentUserId) -> JobRunRead:
    """Best-effort cancel of a still-active JobRun.

    Behaviour:
        * If the JobRun is in ``pending`` or ``started``: status flips
          to ``cancelled``, ``completed_at`` is set, the Celery task
          is revoked (non-terminating; we don't kill mid-flight Python).
        * If the JobRun is already ``success`` / ``failed`` /
          ``cancelled``: returns the row unchanged.
        * If the id is unknown: 404.

    Authentication is required: the JobRun model carries no project_id
    or created_by linkage (RFC 34 §4 W0.1 keeps the table generic), so
    we cannot ownership-gate per-row - but we MUST keep anonymous callers
    out of the mutation surface to prevent third parties from cancelling
    any active job they can guess a UUID for.
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

            # Best-effort Celery revoke - never fatal. We have already
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


# Keys of ``JobRun.error_jsonb`` that are safe to expose over the API. The
# blob written by app.core.job_runner is ``{type, message, traceback, phase}``;
# ``traceback`` is a full Python stack trace (file paths, source lines, locals
# context) and must NEVER cross the API boundary - it is the canonical internal
# leak. We keep ``type`` + ``message`` (useful, bounded diagnostics) and drop
# everything else by allowlist so a future handler that stashes extra internal
# keys can't silently start leaking them.
_SAFE_ERROR_KEYS = frozenset({"type", "message", "phase"})


def _sanitize_error(error: dict | None) -> dict | None:
    """Strip the server-side traceback (and any non-allowlisted keys) from a
    JobRun error blob before it is returned through the API.

    The full traceback stays in ``JobRun.error_jsonb`` in the database for
    operators / server-side log correlation; only ``type`` / ``message`` /
    ``phase`` reach the client.
    """
    if not isinstance(error, dict):
        return error if error is None else None
    return {k: v for k, v in error.items() if k in _SAFE_ERROR_KEYS} or None


def _to_read_model(row: JobRun) -> JobRunRead:
    """Translate a JobRun ORM row into the public read model.

    The mapping is explicit (rather than ``model_validate(row)``) so we
    can rename ``result_jsonb`` → ``result`` / ``error_jsonb`` → ``error``
    without leaking internal column names through the API. The error blob is
    additionally sanitised to drop the captured Python traceback.
    """
    return JobRunRead(
        id=row.id,
        kind=row.kind,
        status=row.status,
        progress_percent=row.progress_percent,
        result=row.result_jsonb,
        error=_sanitize_error(row.error_jsonb),
        started_at=row.started_at,
        completed_at=row.completed_at,
        retry_count=row.retry_count,
        idempotency_key=row.idempotency_key,
        created_at=row.created_at,
        updated_at=row.updated_at,
        tenant_id=row.tenant_id,
    )
