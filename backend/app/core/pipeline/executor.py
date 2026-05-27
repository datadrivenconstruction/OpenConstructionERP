# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Graph DAG executor — generalises ``match_elements.pipeline.run_stage``.

The match-elements pipeline runs a *fixed* seven-stage tuple. This module
runs a *user-authored DAG*: the node order is a Kahn topological sort (the
same cycle-detection guarantee as ``module_loader.resolve_order``, but
Kahn rather than DFS so an explicit cycle is reported as a clear error),
and the per-node runner is the generalised ``run_stage`` body:

    load/create node-state row
      → flip ``running`` + commit (concurrent polls see it; the runner
        starts from a clean transaction boundary)
      → run the registered runner in a fresh txn boundary
      → capture ``took_ms``
      → write the terminal state (done | error)
      → mark every topological descendant ``stale``

The whole run is ONE ``JobRun`` of ``kind="pipeline.run"`` (§3.3). This
module registers itself as that JobRun handler at import time, exactly
like ``boq.events`` / ``costs.events`` register theirs.

Three hard rules from §3.2 are enforced by convention here: node runners
return small envelopes (IDs + previews, never the element universe),
which protects the 2 GB-RAM / SQLite deploy target; Pydantic validates
node params at the boundary; dicts go on the wire.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.pipeline.registry import NodeContext, node_registry

logger = logging.getLogger(__name__)

PIPELINE_JOB_KIND = "pipeline.run"

# ── Resource caps (DoS / memory-bomb protection) ─────────────────────────
# A user-authored DAG runs in-process; without an upper bound a buggy /
# malicious graph could spin a worker forever or balloon node-state JSON.
# Both caps are env-tunable so a self-host with bigger boxes can raise
# them, but the defaults keep the SQLite / 2 GB-RAM deploy safe.
DEFAULT_MAX_NODES_PER_RUN = int(os.environ.get("PIPELINE_MAX_NODES", "256"))
DEFAULT_NODE_TIMEOUT_S = float(os.environ.get("PIPELINE_NODE_TIMEOUT_S", "300"))

# Terminal + transient node statuses (clone of MatchStageState's set, plus
# the DAG-only "paused" for Phase-2 human-approval gates).
NODE_STATUSES = (
    "pending",
    "running",
    "done",
    "error",
    "skipped",
    "stale",
    "paused",
)


class GraphValidationError(ValueError):
    """‌⁠‍Raised when a graph cannot be executed (cycle, unknown type, …).

    The router converts this into a 400 so a malformed graph never
    silently produces a half-finished run.
    """


# ── Graph helpers ────────────────────────────────────────────────────────


def _adjacency(
    graph: dict[str, Any],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, list[str]],
    dict[str, list[str]],
]:
    """‌⁠‍Return ``(nodes_by_id, out_edges, in_edges)`` from a graph dict.

    ``out_edges[src] = [dst, …]`` and ``in_edges[dst] = [src, …]``.
    Edges whose endpoints are not declared nodes are dropped (defensive —
    a stale edge must not crash the topo sort).
    """
    raw_nodes = graph.get("nodes") or []
    raw_edges = graph.get("edges") or []
    nodes_by_id: dict[str, dict[str, Any]] = {}
    for n in raw_nodes:
        nid = str(n.get("id") or "")
        if nid:
            nodes_by_id[nid] = n

    out_edges: dict[str, list[str]] = defaultdict(list)
    in_edges: dict[str, list[str]] = defaultdict(list)
    for e in raw_edges:
        src = str(e.get("source") or "")
        dst = str(e.get("target") or "")
        if src in nodes_by_id and dst in nodes_by_id:
            out_edges[src].append(dst)
            in_edges[dst].append(src)
    return nodes_by_id, dict(out_edges), dict(in_edges)


def topological_order(graph: dict[str, Any]) -> list[str]:
    """Kahn topological sort of node ids; raises on a cycle.

    Kahn (not the loader's DFS) so a genuine cycle surfaces as a precise
    :class:`GraphValidationError` listing the stuck nodes — that error is
    shown to the user before any node runs.
    """
    nodes_by_id, out_edges, in_edges = _adjacency(graph)
    indegree: dict[str, int] = dict.fromkeys(nodes_by_id, 0)
    for dst, srcs in in_edges.items():
        indegree[dst] = len(srcs)

    # Deterministic order: process zero-indegree nodes in declaration order.
    queue: deque[str] = deque(nid for nid in nodes_by_id if indegree.get(nid, 0) == 0)
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for nxt in out_edges.get(node, []):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(nodes_by_id):
        stuck = sorted(set(nodes_by_id) - set(order))
        raise GraphValidationError(f"Pipeline graph has a cycle (unresolved nodes: {stuck})")
    return order


def descendants(graph: dict[str, Any], node_id: str) -> set[str]:
    """Return every node reachable from ``node_id`` (its topo-descendants)."""
    _, out_edges, _ = _adjacency(graph)
    seen: set[str] = set()
    stack = list(out_edges.get(node_id, []))
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(out_edges.get(cur, []))
    return seen


def validate_graph(graph: dict[str, Any]) -> list[str]:
    """Validate a graph for execution. Returns the topo order or raises.

    Checks: (1) acyclic (Kahn), (2) every node type is registered in the
    Node Capability Registry. An unregistered type is rejected here,
    BEFORE the run starts — never mid-run (§3.5).
    """
    order = topological_order(graph)
    nodes_by_id, _, _ = _adjacency(graph)
    unknown = sorted(
        {str(n.get("type") or "") for n in nodes_by_id.values() if node_registry.get(str(n.get("type") or "")) is None}
    )
    if unknown:
        raise GraphValidationError(f"Pipeline graph references unregistered node types: {unknown}")
    return order


# ── Per-node executor (generalised run_stage) ────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


async def _get_or_create_node_state(
    db: AsyncSession,
    run_id: uuid.UUID,
    node_id: str,
    node_type: str,
) -> Any:
    """Load (or create) the ``oe_pipeline_node_state`` row for a node.

    Imported lazily to avoid an import cycle (the executor is imported very
    early at module-load time; the ORM model imports the SQLAlchemy ``Base``
    which is fine, but keeping the import lazy mirrors the match-elements
    pattern and keeps this core file model-agnostic for tests).
    """
    from app.modules.pipelines.models import PipelineNodeState

    row = (
        await db.execute(
            select(PipelineNodeState).where(
                PipelineNodeState.run_id == run_id,
                PipelineNodeState.node_id == node_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = PipelineNodeState(
            run_id=run_id,
            node_id=node_id,
            node_type=node_type,
            status="pending",
            inputs={},
            output={},
        )
        db.add(row)
        await db.flush()
    return row


async def run_node(
    db: AsyncSession,
    run_id: uuid.UUID,
    node: dict[str, Any],
    *,
    upstream: dict[str, dict[str, Any]],
    graph: dict[str, Any],
    project_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    actor_id: str | None = None,
) -> dict[str, Any]:
    """Execute one node and persist its state — generalised ``run_stage``.

    The state machine is a 1:1 port of ``match_elements.pipeline.run_stage``:
    flip ``running`` + commit, run the registered runner in a fresh txn
    boundary, capture ``took_ms``, write the terminal state, then mark every
    topological descendant ``stale`` so the UI flags the gap on a re-run.

    Args:
        db: Live async session (the executor owns the txn boundary).
        run_id: ``oe_pipeline_run.id``.
        node: The graph node dict (``{id, type, params, position}``).
        upstream: ``{source_node_id: output_envelope}`` from predecessors.
        graph: The frozen graph snapshot (for descendant staleness).
        project_id / tenant_id / actor_id: Run scope passed to the runner.

    Returns:
        ``{node_id, node_type, status, output, error, took_ms}`` — a small
        envelope the executor threads into downstream nodes.
    """
    node_id = str(node.get("id") or "")
    node_type = str(node.get("type") or "")
    params = dict(node.get("params") or {})

    spec = node_registry.get(node_type)
    if spec is None:
        # Defensive — validate_graph already rejects this before the run.
        raise GraphValidationError(f"Unknown node type: {node_type!r}")

    state = await _get_or_create_node_state(db, run_id, node_id, node_type)
    state.status = "running"
    state.node_type = node_type
    state.error = None
    state.started_at = _now()
    state.took_ms = None
    state.inputs = {"params": params, "upstream_node_ids": sorted(upstream)}
    # Commit the running state so a concurrent poll sees it and so the
    # runner starts from a clean transaction boundary — exactly the
    # match-elements rationale.
    await db.commit()

    t0 = time.perf_counter()
    final_status = "done"
    final_output: dict[str, Any] = {}
    final_error: str | None = None
    try:
        ctx = NodeContext(
            db=db,
            node_id=node_id,
            node_type=node_type,
            params=params,
            inputs=upstream,
            project_id=project_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            run_id=run_id,
        )
        # Wall-clock cap so a stuck / runaway node cannot freeze the
        # worker forever. Tunable via PIPELINE_NODE_TIMEOUT_S.
        final_output = await asyncio.wait_for(spec.runner(ctx), timeout=DEFAULT_NODE_TIMEOUT_S)
        if not isinstance(final_output, dict):
            final_output = {"result": final_output}
    except TimeoutError as exc:
        logger.warning(
            "pipeline.executor: node %s (%s) timed out after %.1fs for run %s",
            node_id,
            node_type,
            DEFAULT_NODE_TIMEOUT_S,
            run_id,
        )
        final_status = "error"
        final_error = f"Node timed out after {DEFAULT_NODE_TIMEOUT_S:.0f}s"
        await db.rollback()
        # Suppress unused-variable warning while keeping the bind for grep.
        del exc
    except Exception as exc:  # noqa: BLE001 — surface error to the run row.
        logger.exception(
            "pipeline.executor: node %s (%s) failed for run %s",
            node_id,
            node_type,
            run_id,
        )
        final_status = "error"
        final_error = str(exc)
        # The session may be in a failed-transaction state — roll back
        # before we touch the DB again to write the error row.
        await db.rollback()

    took_ms = int((time.perf_counter() - t0) * 1000)

    # Re-fetch: a rollback (error path) or a runner that committed mid-flight
    # can detach the earlier instance — reload to write the terminal state
    # against a live row (same as run_stage).
    state = await _get_or_create_node_state(db, run_id, node_id, node_type)
    state.status = final_status
    state.output = final_output if final_status == "done" else {}
    state.error = final_error
    state.finished_at = _now()
    state.took_ms = took_ms

    if final_status == "done":
        # Mark downstream done-nodes stale so the UI flags the gap on a
        # re-run. Build the node-type index once instead of an O(N) scan
        # per descendant (was O(N²·E) across a whole run).
        type_by_id = {str(n.get("id") or ""): str(n.get("type") or "") for n in (graph.get("nodes") or [])}
        for ds_id in descendants(graph, node_id):
            ds = await _get_or_create_node_state(db, run_id, ds_id, type_by_id.get(ds_id, ""))
            if ds.status == "done":
                ds.status = "stale"

    await db.commit()
    return {
        "node_id": node_id,
        "node_type": node_type,
        "status": final_status,
        "output": dict(final_output or {}),
        "error": final_error,
        "took_ms": took_ms,
    }


# ── Whole-run orchestration ──────────────────────────────────────────────


async def execute_run(
    db: AsyncSession,
    run_id: uuid.UUID,
) -> dict[str, Any]:
    """Run an entire pipeline graph in topological order.

    Loads the ``oe_pipeline_run`` row, validates its frozen graph snapshot,
    then runs each node sequentially in topo order, threading each node's
    output envelope to its downstream consumers. A node ``error`` skips
    every node that depends on it (they are marked ``skipped``) but does
    NOT abort sibling branches — partial progress is preserved, matching
    the durable-execution philosophy.

    Returns a small run summary dict (counts + per-node statuses) that the
    JobRun handler stores as the job result.
    """
    from app.modules.pipelines.models import PipelineRun

    run = await db.get(PipelineRun, run_id)
    if run is None:
        raise LookupError(f"Pipeline run not found: {run_id}")

    graph = dict(run.graph_snapshot or {})
    order = validate_graph(graph)
    # Cap the number of nodes per run to defuse memory-bomb / DoS graphs.
    if len(order) > DEFAULT_MAX_NODES_PER_RUN:
        raise GraphValidationError(
            f"Pipeline graph has {len(order)} nodes, exceeds the per-run limit of {DEFAULT_MAX_NODES_PER_RUN}"
        )
    nodes_by_id, _, in_edges = _adjacency(graph)
    run_t0 = time.perf_counter()

    project_id = run.project_id
    tenant_id = run.tenant_id
    actor_id = str(run.created_by) if run.created_by else None
    job_run_id = run.job_run_id

    async def _report(done_count: int) -> None:
        """Push monotonic progress onto the owning JobRun.

        Without this the JobRun's ``progress_percent`` stays 0 for the
        whole run, so the UI progress bar never moves and the run-detail
        API always reports 0%. Best-effort: a progress write must never
        abort the run, and ``update_progress`` is monotonic + tolerates a
        missing row.
        """
        if job_run_id is None or not order:
            return
        pct = int(done_count * 100 / len(order))
        try:
            from app.core.job_runner import update_progress

            await update_progress(job_run_id, percent=pct)
        except Exception:  # noqa: BLE001 — progress is advisory only.
            logger.warning(
                "pipeline.executor: progress update failed for run %s",
                run_id,
                exc_info=True,
            )

    outputs: dict[str, dict[str, Any]] = {}
    failed: set[str] = set()
    statuses: dict[str, str] = {}

    for idx, node_id in enumerate(order):
        node = nodes_by_id[node_id]
        node_type = str(node.get("type") or "")
        preds = in_edges.get(node_id, [])

        # If any predecessor failed/was skipped, skip this node too.
        if any(p in failed for p in preds):
            state = await _get_or_create_node_state(db, run_id, node_id, node_type)
            state.status = "skipped"
            # Stamp started_at too: the run-detail read model orders node
            # states by started_at, so a skipped node with only
            # finished_at would jump out of topological order in the UI
            # timeline. Both timestamps = the moment it was evaluated.
            now = _now()
            state.started_at = now
            state.finished_at = now
            await db.commit()
            failed.add(node_id)
            statuses[node_id] = "skipped"
            await _report(idx + 1)
            continue

        upstream = {p: outputs.get(p, {}) for p in preds}
        result = await run_node(
            db,
            run_id,
            node,
            upstream=upstream,
            graph=graph,
            project_id=project_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
        )
        statuses[node_id] = result["status"]
        if result["status"] == "error":
            failed.add(node_id)
        else:
            outputs[node_id] = result["output"]
        await _report(idx + 1)

    n_done = sum(1 for s in statuses.values() if s == "done")
    n_error = sum(1 for s in statuses.values() if s == "error")
    n_skipped = sum(1 for s in statuses.values() if s == "skipped")
    duration_ms = int((time.perf_counter() - run_t0) * 1000)
    # Structured run-completion log so prod observability has the
    # outcome + wall-clock without poking the DB.
    logger.info(
        "pipeline.executor: run %s finished node_count=%d done=%d error=%d skipped=%d duration_ms=%d",
        run_id,
        len(order),
        n_done,
        n_error,
        n_skipped,
        duration_ms,
    )
    return {
        "run_id": str(run_id),
        "node_count": len(order),
        "done": n_done,
        "error": n_error,
        "skipped": n_skipped,
        "duration_ms": duration_ms,
        "statuses": statuses,
        "order": order,
    }


# ── JobRun handler registration (§3.3) ───────────────────────────────────


async def _run_pipeline_job(
    job_run: Any,
    payload: dict[str, Any],
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> dict[str, Any]:
    """JobRun handler for ``kind="pipeline.run"``.

    Resolves the ``oe_pipeline_run`` from the payload and drives the whole
    graph. Any exception propagates so ``_dispatch_job_sync`` records the
    failure on the JobRun row (the standard job-runner contract).
    """
    if session_factory is None:
        from app.database import async_session_factory

        session_factory = async_session_factory

    run_id = uuid.UUID(str(payload["run_id"]))
    async with session_factory() as db:
        return await execute_run(db, run_id)


def register_pipeline_job_handler() -> None:
    """Register the ``pipeline.run`` JobRun handler. Idempotent.

    Called at module import (below) and again from the module's
    ``on_startup`` so a fresh process always has the handler bound before
    the first ``POST /{id}/run`` enqueues a job.
    """
    from app.core.job_runner import register_handler

    register_handler(PIPELINE_JOB_KIND, _run_pipeline_job)


# Register at import so any importer (the module router, a test) gets the
# handler bound without an explicit bootstrap call — mirrors how
# ``boq.events`` self-registers at module import.
register_pipeline_job_handler()
