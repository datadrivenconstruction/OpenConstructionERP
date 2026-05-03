"""Admin API routes.

Endpoints:
    POST /qa-reset                   — reset the demo dataset (triple-gated)
    POST /cost-vector-reindex        — rebuild the ``oe_cost_items`` collection
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.dependencies import SessionDep
from app.modules.admin.service import GateError, check_gates, reset_demo_data

router = APIRouter()
logger = logging.getLogger(__name__)


# Background-task registry for the cost-vector reindex.  Tracks one-shot
# reindex runs by an opaque task_id so the operator can poll progress
# from the same admin process. Stored in-memory only — restarting the
# process drops the history, which is fine for an operator endpoint.
_REINDEX_TASKS: dict[str, dict[str, object]] = {}
_REINDEX_TASKS_LOCK = asyncio.Lock()
# Gate threshold: above this row count we run as a background task and
# return 202 immediately; at or below we run inline and return the full
# result synchronously. The brief sets the threshold at 1000.
_REINDEX_INLINE_LIMIT = 1000


class QAResetRequest(BaseModel):
    """Body for POST /qa-reset.

    ``confirm_token`` must equal ``os.environ['QA_RESET_TOKEN']`` server-side.
    ``tenant`` must equal ``"demo"`` — the only resettable tenant.
    """

    tenant: str = Field(default="demo", description="Tenant to reset; only 'demo' is allowed.")
    confirm_token: str = Field(min_length=1, description="Shared secret matching QA_RESET_TOKEN env.")


class QAResetResponse(BaseModel):
    reset: bool
    demo_users: list[str]
    deleted_projects: int
    seeded_projects: int
    seeded_demo_ids: list[str]
    took_ms: int


@router.post(
    "/qa-reset",
    response_model=QAResetResponse,
    summary="Reset demo dataset (QA crawler baseline)",
    description=(
        "Hard-deletes all projects owned by the demo accounts and re-seeds the "
        "canonical 5 demo projects. Idempotent — safe to call repeatedly. "
        "Triple-gated by env (QA_RESET_ALLOWED=1), shared-secret token, and "
        "hostname check (refuses production). Use only against dev/staging."
    ),
)
async def qa_reset(
    body: QAResetRequest,
    request: Request,
    session: SessionDep,
) -> QAResetResponse:
    hostname = request.url.hostname
    try:
        check_gates(
            hostname=hostname,
            confirm_token=body.confirm_token,
            tenant=body.tenant,
        )
    except GateError as exc:
        logger.warning(
            "qa-reset rejected: code=%s host=%s", exc.code, hostname,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    try:
        result = await reset_demo_data(session)
    except GateError as exc:
        # Sanity-cap gate fires inside the service after the cheaper checks
        # so the error path is the same shape.
        logger.warning(
            "qa-reset aborted by service gate: code=%s host=%s", exc.code, hostname,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except Exception:
        logger.exception("qa-reset failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "qa_reset_internal_error", "message": "Unexpected failure during reset."},
        )

    return QAResetResponse(**result)


# ── Cost-vector reindex ──────────────────────────────────────────────────


class CostVectorReindexRequest(BaseModel):
    """Body for ``POST /cost-vector-reindex``.

    Same triple-gate model as qa-reset:
        * ``QA_RESET_ALLOWED=1`` env var (the existing operator flag is
          reused to keep the surface area small — operators who already
          opted in for qa-reset get the reindex endpoint too)
        * ``confirm_token`` body field == ``QA_RESET_TOKEN`` env var
        * Hostname must look dev/staging — never production
    """

    confirm_token: str = Field(
        min_length=1, description="Shared secret matching QA_RESET_TOKEN env."
    )
    force: bool = Field(
        default=False,
        description=(
            "When True, reindex every active row even if the collection "
            "already has at least as many vectors. When False, the call "
            "is a no-op once the indexed count matches the live count."
        ),
    )
    batch_size: int = Field(
        default=500,
        ge=1,
        le=5000,
        description="Embedding batch size — tune down on memory-tight hosts.",
    )


class CostVectorReindexResponse(BaseModel):
    """Result of a cost-vector reindex.

    ``task_id`` is non-null when the row count exceeded the inline
    threshold and the reindex was scheduled as a background task; the
    operator can poll ``GET /cost-vector-reindex/status/{task_id}``
    (not yet implemented in this phase — see backlog) to track
    completion. For inline runs ``task_id`` is None and ``indexed`` /
    ``took_ms`` carry the final result.
    """

    indexed: int
    took_ms: int
    collection: str
    task_id: str | None = None
    background: bool = False
    live_rows: int


async def _run_cost_reindex(
    *, batch_size: int, force: bool, task_id: str | None
) -> dict[str, object]:
    """Execute the reindex pass.

    Runs in either inline (when called from the request handler) or
    background (when scheduled via FastAPI BackgroundTasks) mode.
    Failures are logged and surfaced through the task registry so the
    operator can see them on the status endpoint instead of vanishing
    silently into the worker pool.
    """
    started = time.monotonic()
    from app.database import async_session_factory
    from app.modules.costs import vector_adapter as cost_vector
    from app.modules.costs.models import CostItem

    if task_id is not None:
        async with _REINDEX_TASKS_LOCK:
            entry = _REINDEX_TASKS.get(task_id)
            if entry is not None:
                entry["status"] = "running"

    try:
        if not force:
            indexed_count = await cost_vector.collection_count()
            async with async_session_factory() as session:
                live_total = (
                    await session.execute(
                        select(func.count())
                        .select_from(CostItem)
                        .where(CostItem.is_active.is_(True))
                    )
                ).scalar_one() or 0
            if indexed_count >= live_total > 0:
                # Already in sync — bail out cheaply.
                summary = {
                    "indexed": 0,
                    "took_ms": int((time.monotonic() - started) * 1000),
                    "collection": cost_vector.COLLECTION_COSTS,
                    "live_rows": int(live_total),
                    "skipped": True,
                }
                if task_id is not None:
                    async with _REINDEX_TASKS_LOCK:
                        _REINDEX_TASKS[task_id] = {
                            "status": "completed",
                            **summary,
                        }
                return summary

        # Pull rows in batches — never materialise the entire table.
        indexed = 0
        async with async_session_factory() as session:
            offset = 0
            while True:
                stmt = (
                    select(CostItem)
                    .where(CostItem.is_active.is_(True))
                    .order_by(CostItem.id)
                    .offset(offset)
                    .limit(batch_size)
                )
                rows = list((await session.execute(stmt)).scalars().all())
                if not rows:
                    break
                indexed += await cost_vector.upsert(rows)
                if len(rows) < batch_size:
                    break
                offset += batch_size

        summary = {
            "indexed": indexed,
            "took_ms": int((time.monotonic() - started) * 1000),
            "collection": cost_vector.COLLECTION_COSTS,
        }
        if task_id is not None:
            async with _REINDEX_TASKS_LOCK:
                _REINDEX_TASKS[task_id] = {"status": "completed", **summary}
        return summary
    except Exception as exc:
        logger.exception("cost-vector reindex failed")
        if task_id is not None:
            async with _REINDEX_TASKS_LOCK:
                _REINDEX_TASKS[task_id] = {
                    "status": "failed",
                    "error": str(exc),
                    "took_ms": int((time.monotonic() - started) * 1000),
                }
        raise


@router.post(
    "/cost-vector-reindex",
    response_model=CostVectorReindexResponse,
    summary="Reindex the cost catalog into the oe_cost_items vector collection",
    description=(
        "Rebuilds the ``oe_cost_items`` LanceDB / Qdrant collection from "
        "every active row in ``oe_costs_item``. Triple-gated by env "
        "(QA_RESET_ALLOWED=1), shared-secret token, and hostname check "
        "(refuses production). Above 1000 live rows the reindex is "
        "scheduled as a background task and the response returns "
        "``task_id`` immediately."
    ),
)
async def cost_vector_reindex(
    body: CostVectorReindexRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> CostVectorReindexResponse:
    """Trigger a cost-vector reindex pass."""
    hostname = request.url.hostname
    try:
        check_gates(
            hostname=hostname,
            confirm_token=body.confirm_token,
            tenant="demo",  # tenant is irrelevant here; pass the gate sentinel
        )
    except GateError as exc:
        logger.warning(
            "cost-vector reindex rejected: code=%s host=%s", exc.code, hostname,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    # Vector backend probe — fail fast if the optional extra is missing
    # so the operator gets a clear error instead of a silent zero-op.
    try:
        import importlib.util  # noqa: PLC0415

        if importlib.util.find_spec("lancedb") is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "vector_extra_missing",
                    "message": (
                        "lancedb not installed; install the [vector] extra "
                        "(pip install openconstructionerp[vector])."
                    ),
                },
            )
    except HTTPException:
        raise
    except Exception:
        logger.exception("cost-vector reindex backend probe failed")

    # Decide inline vs background based on live row count.
    from app.modules.costs.models import CostItem

    live_rows = (
        await session.execute(
            select(func.count())
            .select_from(CostItem)
            .where(CostItem.is_active.is_(True))
        )
    ).scalar_one() or 0
    live_rows = int(live_rows)

    # Defensive: ensure QA_RESET_ALLOWED really is set even if check_gates
    # was monkeypatched in a test. The endpoint is destructive enough
    # to warrant a redundant check.
    if os.environ.get("QA_RESET_ALLOWED", "").strip() != "1":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "qa_reset_disabled",
                "message": "Set QA_RESET_ALLOWED=1 to enable.",
            },
        )

    if live_rows > _REINDEX_INLINE_LIMIT:
        task_id = str(uuid.uuid4())
        async with _REINDEX_TASKS_LOCK:
            _REINDEX_TASKS[task_id] = {
                "status": "queued",
                "live_rows": live_rows,
            }

        async def _run() -> None:
            try:
                await _run_cost_reindex(
                    batch_size=body.batch_size,
                    force=body.force,
                    task_id=task_id,
                )
            except Exception:
                # Already logged + recorded by _run_cost_reindex
                pass

        background_tasks.add_task(_run)
        from app.modules.costs.vector_adapter import COLLECTION_COSTS

        return CostVectorReindexResponse(
            indexed=0,
            took_ms=0,
            collection=COLLECTION_COSTS,
            task_id=task_id,
            background=True,
            live_rows=live_rows,
        )

    try:
        summary = await _run_cost_reindex(
            batch_size=body.batch_size,
            force=body.force,
            task_id=None,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "cost_reindex_failed",
                "message": f"Reindex failed: {exc}",
            },
        ) from exc

    return CostVectorReindexResponse(
        indexed=int(summary["indexed"]),
        took_ms=int(summary["took_ms"]),
        collection=str(summary["collection"]),
        task_id=None,
        background=False,
        live_rows=live_rows,
    )


@router.get(
    "/cost-vector-reindex/status/{task_id}",
    summary="Poll status of a background cost-vector reindex task",
)
async def cost_vector_reindex_status(task_id: str) -> dict[str, object]:
    """Return the current status of a previously scheduled reindex.

    Returns 404 if the task_id is unknown — the operator typically
    polls this from a script that already has the id from the original
    POST response. The registry is in-memory, so a process restart
    drops history.
    """
    async with _REINDEX_TASKS_LOCK:
        entry = _REINDEX_TASKS.get(task_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "task_not_found",
                "message": "No such cost-vector reindex task in this process.",
            },
        )
    return {"task_id": task_id, **entry}
