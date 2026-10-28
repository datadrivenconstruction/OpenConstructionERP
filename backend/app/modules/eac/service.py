# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠High-level service layer for EAC v2 (RFC 35 §1.7, task #221).

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
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.validation.engine import validation_engine
from app.modules.eac.engine import api as engine_api
from app.modules.eac.engine.api import (
    CompiledPlan,
    RunDiff,
    RunStatus,
)
from app.modules.eac.models import GRAPH_VALIDATION_STATUSES, EacBlockGraph, EacRun
from app.modules.eac.repository import replace_graph_body
from app.modules.eac.schemas_graph import (
    BlockWrite,
    ConnectionWrite,
    GraphFinding,
    GraphValidationReport,
)
from app.modules.eac.validators import EAC_GRAPH_RULE_SET

logger = logging.getLogger(__name__)


# ── Compile + describe ─────────────────────────────────────────────────


async def compile_plan(
    rule_definition: dict[str, Any],
    *,
    session: AsyncSession,
    tenant_id: uuid.UUID | None,
) -> CompiledPlan:
    """Validate + plan a rule definition. Read-only - no events."""
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
    """Snapshot of a run's state - used by the run-detail header."""
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
            # Event publishing must never break the request - the cancel
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


# ── Block graphs ───────────────────────────────────────────────────────
#
# The visual editor's own working document: blocks on a canvas, wired
# together. Everything below is pure enough to test without a database
# except the two functions that take a session.


def normalise_graph_body(
    blocks: Sequence[BlockWrite],
    connections: Sequence[ConnectionWrite],
) -> tuple[list[BlockWrite], list[ConnectionWrite]]:
    """Collapse the duplicates the canvas itself would never have produced.

    Two normalisations, both mirroring what ``useBlockCanvasStore`` does:

    * A block id appearing twice keeps its first occurrence. The editor
      generates ids from a monotonic counter plus randomness, so a repeat is
      a client bug or a hand-rolled payload, and the unique constraint would
      refuse the write anyway.
    * A second wire between the same slot pair is dropped. ``addConnection``
      returns the existing edge instead of adding a duplicate, so accepting
      one here would store a graph the editor cannot reproduce.

    What this deliberately does **not** do is drop a wire whose endpoint is
    missing. That is a real defect in the estimator's methodology, and
    deleting the evidence would let a broken graph report a clean validation.
    It is stored as sent and reported by ``eac_graph.block_reference_exists``.

    Args:
        blocks: Blocks as received, in canvas order.
        connections: Wires as received, in canvas order.

    Returns:
        The de-duplicated blocks and wires, order preserved.
    """
    seen_blocks: set[str] = set()
    kept_blocks: list[BlockWrite] = []
    for block in blocks:
        if block.client_id in seen_blocks:
            continue
        seen_blocks.add(block.client_id)
        kept_blocks.append(block)

    seen_conn_ids: set[str] = set()
    seen_pairs: set[tuple[str, str, str, str]] = set()
    kept_connections: list[ConnectionWrite] = []
    for conn in connections:
        pair = (
            conn.source_block_client_id,
            conn.source_slot_id,
            conn.target_block_client_id,
            conn.target_slot_id,
        )
        if conn.client_id in seen_conn_ids or pair in seen_pairs:
            continue
        seen_conn_ids.add(conn.client_id)
        seen_pairs.add(pair)
        kept_connections.append(conn)

    return kept_blocks, kept_connections


def graph_body_to_validation_data(
    blocks: Sequence[BlockWrite],
    connections: Sequence[ConnectionWrite],
) -> dict[str, Any]:
    """Render a graph body as the plain dict the ``eac_graph`` rules read."""
    return {
        "blocks": [
            {
                "client_id": block.client_id,
                "kind": block.kind,
                "color": block.color,
                "title": block.title,
                "slots": [slot.model_dump(exclude_none=True) for slot in block.slots],
                "params": dict(block.params),
            }
            for block in blocks
        ],
        "connections": [
            {
                "client_id": conn.client_id,
                "source_block_client_id": conn.source_block_client_id,
                "source_slot_id": conn.source_slot_id,
                "target_block_client_id": conn.target_block_client_id,
                "target_slot_id": conn.target_slot_id,
                "data_type": conn.data_type,
            }
            for conn in connections
        ],
    }


async def validate_graph_body(
    blocks: Sequence[BlockWrite],
    connections: Sequence[ConnectionWrite],
    *,
    target_id: str = "",
    project_id: uuid.UUID | None = None,
) -> GraphValidationReport:
    """Run the ``eac_graph`` rule set over a graph body.

    Validation is not optional here - this runs on every write, and the
    outcome is stored on the row so a list view can show whether a saved
    methodology is actually sound. What it does not do is *block* the write:
    a graph mid-edit is routinely incomplete, and refusing to save it would
    cost the estimator their work to enforce a rule about work in progress.

    Args:
        blocks: Blocks to check.
        connections: Wires to check.
        target_id: Graph id, for the report's target reference.
        project_id: Project scope, passed through for project-specific rules.

    Returns:
        The status, score and every failing finding.
    """
    report = await validation_engine.validate(
        data=graph_body_to_validation_data(blocks, connections),
        rule_sets=[EAC_GRAPH_RULE_SET],
        target_type="eac_block_graph",
        target_id=target_id,
        project_id=str(project_id) if project_id else None,
    )
    findings = [
        GraphFinding(
            rule_id=result.rule_id,
            severity=result.severity.value,
            message=result.message,
            element_ref=result.element_ref,
            suggestion=result.suggestion,
            details=dict(result.details or {}),
        )
        for result in report.results
        if not result.passed and not result.is_engine_error
    ]
    # report.score is deliberately not defaulted. The engine returns None when
    # no compliance result was produced, and it says in as many words that the
    # alternative - reporting 1.0 for a report that checked nothing - is
    # misleading. An estimator opening a blank canvas should not be told it
    # scores perfectly.
    return GraphValidationReport(
        status=report.status.value,
        score=report.score,
        findings=findings,
    )


def remap_graph_body(
    blocks: Sequence[BlockWrite],
    connections: Sequence[ConnectionWrite],
) -> tuple[list[BlockWrite], list[ConnectionWrite]]:
    """Give every block and wire a fresh client id, keeping the wiring intact.

    Used by duplicate. The trap this exists to avoid is copying the wires
    verbatim: a connection carries its endpoints as block *client ids*, so a
    copy that renames the blocks without rewriting the endpoints produces a
    graph whose every wire dangles. The remap is therefore done as one
    operation, and the endpoint rewrite reads from the same mapping that
    renamed the blocks.

    Args:
        blocks: Blocks to copy.
        connections: Wires to copy.

    Returns:
        Copies with new ids, wired exactly as the originals were.
    """
    id_map: dict[str, str] = {}
    new_blocks: list[BlockWrite] = []
    for index, block in enumerate(blocks):
        fresh = f"block_{index + 1}_{uuid.uuid4().hex[:8]}"
        id_map[block.client_id] = fresh
        new_blocks.append(block.model_copy(deep=True, update={"client_id": fresh}))

    new_connections: list[ConnectionWrite] = []
    for index, conn in enumerate(connections):
        new_connections.append(
            conn.model_copy(
                deep=True,
                update={
                    "client_id": f"conn_{index + 1}_{uuid.uuid4().hex[:8]}",
                    # A wire pointing at a block that was not copied keeps its
                    # original id, so the copy carries the same dangling
                    # reference the original had. Inventing an endpoint would
                    # hide a defect the estimator needs to see.
                    "source_block_client_id": id_map.get(
                        conn.source_block_client_id,
                        conn.source_block_client_id,
                    ),
                    "target_block_client_id": id_map.get(
                        conn.target_block_client_id,
                        conn.target_block_client_id,
                    ),
                },
            )
        )
    return new_blocks, new_connections


async def save_graph_body(
    session: AsyncSession,
    graph: EacBlockGraph,
    blocks: Sequence[BlockWrite],
    connections: Sequence[ConnectionWrite],
    *,
    user_id: uuid.UUID | None = None,
) -> GraphValidationReport:
    """Normalise, validate and persist a graph body, bumping the revision.

    Args:
        session: Active async session.
        graph: The graph being written; must already be persistent.
        blocks: New blocks, in canvas order.
        connections: New wires, in canvas order.
        user_id: Who saved, recorded on the row.

    Returns:
        The validation outcome, which is also stored on the graph.
    """
    kept_blocks, kept_connections = normalise_graph_body(blocks, connections)
    await replace_graph_body(session, graph, kept_blocks, kept_connections)
    report = await validate_graph_body(
        kept_blocks,
        kept_connections,
        target_id=str(graph.id),
        project_id=graph.project_id,
    )
    graph.validation_status = _graph_status(report.status)
    graph.validation_findings = [finding.model_dump() for finding in report.findings]
    graph.validation_score = report.score
    graph.revision = (graph.revision or 0) + 1
    if user_id is not None:
        graph.updated_by_user_id = user_id
    await session.flush()
    return report


def _graph_status(engine_status: str) -> str:
    """Collapse an engine status onto the four the graph row stores.

    ``skipped`` and ``unsupported`` both mean nothing actually ran, which must
    never be recorded as a pass - an empty canvas reads as ``pending``, the
    same as one that has not been checked yet.
    """
    if engine_status in GRAPH_VALIDATION_STATUSES:
        return engine_status
    return "pending"


__all__ = [
    "cancel_run",
    "compile_plan",
    "describe_plan",
    "diff_runs",
    "get_run_status",
    "graph_body_to_validation_data",
    "list_runs",
    "normalise_graph_body",
    "remap_graph_body",
    "rerun",
    "save_graph_body",
    "validate_graph_body",
]
