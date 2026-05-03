# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""High-level service layer for EAC v2 (RFC 35 §1.7, task #221).

This is the seam between the HTTP router and the engine internals.
Routers get the auth/tenant guard, the service composes the engine
calls and publishes events on state-changing operations so other
modules (audit, notifications, scheduling) can react without coupling.

All public methods are ``async def``. Read-only methods do not publish
events; state-changing methods (``cancel``, ``rerun``) do.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.eac.engine import api as engine_api
from app.modules.eac.engine.api import (
    CompiledPlan,
    RunDiff,
    RunStatus,
)
from app.modules.eac.models import EacRun

logger = logging.getLogger(__name__)


# ── Compile + describe ─────────────────────────────────────────────────


async def compile_plan(
    rule_definition: dict[str, Any],
    *,
    session: AsyncSession,
    tenant_id: uuid.UUID | None,
) -> CompiledPlan:
    """Validate + plan a rule definition. Read-only — no events."""
    return await engine_api.compile_plan(
        rule_definition,
        session=session,
        tenant_id=tenant_id,
    )


def describe_plan(compiled: CompiledPlan) -> dict[str, Any]:
    """Render a :class:`CompiledPlan` as a JSON-serialisable dict."""
    payload = engine_api.describe_plan(compiled.plan)
    payload["valid"] = compiled.valid
    payload["issues"] = list(compiled.issues)
    return payload


# ── Status + listing ───────────────────────────────────────────────────


async def get_run_status(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID,
) -> RunStatus | None:
    """Snapshot of a run's state — used by the run-detail header."""
    return await engine_api.status(session, run_id, tenant_id=tenant_id)


async def list_runs(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    ruleset_id: uuid.UUID | None = None,
    run_status: str | None = None,
    triggered_by: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[EacRun]:
    """Tenant-scoped run listing with simple filters."""
    return await engine_api.list_runs(
        session,
        tenant_id=tenant_id,
        ruleset_id=ruleset_id,
        run_status=run_status,
        triggered_by=triggered_by,
        limit=limit,
        offset=offset,
    )


# ── State-changing: cancel / rerun ─────────────────────────────────────


async def cancel_run(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID,
    user_id: str | None = None,
) -> bool:
    """Request cancellation of ``run_id``.

    Publishes ``eac.run.cancelled`` when accepted so subscribers
    (audit log, notifications) can react. Idempotent: a second call
    against an already-cancelled run still returns ``True`` but does
    not publish a duplicate event.
    """
    # Read pre-state so we can avoid double-publishing.
    pre = await session.get(EacRun, run_id)
    pre_status = pre.status if pre is not None else None

    accepted = await engine_api.cancel(session, run_id, tenant_id=tenant_id)
    if accepted and pre_status not in {"cancelled", "success", "failed"}:
        try:
            event_bus.publish_detached(
                "eac.run.cancelled",
                {
                    "run_id": str(run_id),
                    "tenant_id": str(tenant_id),
                    "user_id": user_id,
                },
            )
        except Exception:  # noqa: BLE001
            # Event publishing must never break the request — the cancel
            # itself already succeeded. Log and move on.
            logger.exception("Failed to publish eac.run.cancelled")
    return accepted


async def rerun(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID,
    elements: list[dict[str, Any]],
    triggered_by: str = "manual",
    user_id: str | None = None,
) -> EacRun:
    """Replay ``run_id`` against ``elements`` and publish an event.

    The new run is a fresh row with its own ``id``; the source run is
    untouched. ``eac.run.rerun_started`` carries both IDs so a subscriber
    can correlate the lineage.
    """
    new_run = await engine_api.rerun(
        session,
        run_id,
        tenant_id=tenant_id,
        elements=elements,
        triggered_by=triggered_by,
    )
    try:
        event_bus.publish_detached(
            "eac.run.rerun_started",
            {
                "run_id": str(new_run.id),
                "source_run_id": str(run_id),
                "tenant_id": str(tenant_id),
                "user_id": user_id,
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to publish eac.run.rerun_started")
    return new_run


# ── Diff ───────────────────────────────────────────────────────────────


async def diff_runs(
    session: AsyncSession,
    run_id_a: uuid.UUID,
    run_id_b: uuid.UUID,
    *,
    tenant_id: uuid.UUID,
) -> RunDiff:
    """Compare two runs of the same ruleset (read-only)."""
    return await engine_api.diff(session, run_id_a, run_id_b, tenant_id=tenant_id)


__all__ = [
    "cancel_run",
    "compile_plan",
    "describe_plan",
    "diff_runs",
    "get_run_status",
    "list_runs",
    "rerun",
]
