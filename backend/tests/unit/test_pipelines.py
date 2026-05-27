# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Baseline unit tests for the Pipeline Builder module.

Covers the three workflow touch-points the module owns end-to-end:

1. **create** — :meth:`PipelineService.create` persists a graph + policy
   on the ``oe_pipeline`` row and lands ``created_by`` so the IDOR guard
   has something to compare against.
2. **run** — :meth:`PipelineService.submit_run` validates the graph,
   snapshots it onto an ``oe_pipeline_run`` row, enqueues a ``JobRun``
   of ``kind="pipeline.run"`` with the run id wired into the payload,
   and the registered handler drives the graph through ``execute_run``.
3. **result fetch** — :meth:`PipelineService.run_read_model` assembles
   the run-detail envelope (status, progress, per-node states) the
   router serialises for ``GET /pipelines/runs/{run_id}``.

External I/O (Celery dispatch, embedding lookups) is mocked: the
executor walks the in-process registry and writes to a file-backed
temp SQLite. The prod ``openestimate.db`` is never touched (the strict
``feedback_test_isolation.md`` rule).

A fourth test pins the recent hardening: the pipeline-execution per-run
node-count cap (``DEFAULT_MAX_NODES_PER_RUN``) refuses to start a graph
that would otherwise let a malicious / buggy author spin the worker.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Importing pipeline_nodes registers the 6 Phase-1 node types so
# validate_graph / execute_run can resolve them.
import app.modules.pipelines.pipeline_nodes  # noqa: F401
from app.core.job_run import JobRun
from app.core.pipeline.executor import (
    GraphValidationError,
    execute_run,
)
from app.core.pipeline.registry import NodeContext, register_node
from app.database import Base
from app.modules.pipelines.models import (
    Pipeline,
    PipelineNodeState,
    PipelineRun,
)
from app.modules.pipelines.service import PipelineService
from app.modules.projects.models import Project
from app.modules.users.models import User

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _register_builtin_rules() -> None:
    """Idempotently load validation rules so ``gate.validation`` runs."""
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()


@pytest.fixture
async def session_factory(tmp_path):
    """File-backed async SQLite scoped to just the tables we touch."""
    db_path = tmp_path / "pipelines_unit.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                User.__table__,
                Project.__table__,
                JobRun.__table__,
                Pipeline.__table__,
                PipelineRun.__table__,
                PipelineNodeState.__table__,
            ],
        )
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield maker
    await engine.dispose()


def _mock_graph() -> dict:
    """A two-node graph that exercises the executor without external I/O.

    Both nodes are registered as no-side-effect runners that return small
    envelopes — no DB lookups, no embeddings, no validation engine calls
    beyond what registration guarantees.
    """
    return {
        "nodes": [
            {"id": "t", "type": "trigger.manual", "params": {}},
            {"id": "echo", "type": "test.unit_echo", "params": {"msg": "hi"}},
        ],
        "edges": [{"id": "e1", "source": "t", "target": "echo"}],
    }


@pytest.fixture(autouse=True)
def _register_echo_node() -> None:
    """Register a tiny, deterministic node type used by the unit tests."""

    async def _echo(ctx: NodeContext) -> dict:
        return {
            "summary": f"echo {ctx.params.get('msg', '')}",
            "count": 1,
        }

    register_node(
        type="test.unit_echo",
        module="oe_pipelines",
        category="transform",
        label="Unit echo",
        description="No-IO test node — returns a small envelope.",
        runner=_echo,
    )


# ── 1. create ────────────────────────────────────────────────────────────


async def test_create_pipeline_persists_graph_and_creator(session_factory):
    """``service.create`` writes the graph, defaults unpublished, sets created_by."""
    creator = uuid.uuid4()
    async with session_factory() as db:
        svc = PipelineService(db)
        pipeline = await svc.create(
            name="unit-pipeline",
            description="baseline test",
            project_id=None,
            graph=_mock_graph(),
            policy={"retry": 1},
            created_by=str(creator),
        )
    assert pipeline.id is not None
    assert pipeline.name == "unit-pipeline"
    assert pipeline.is_published is False
    assert pipeline.version == 1
    assert pipeline.created_by == creator
    assert (pipeline.graph or {}).get("nodes")
    assert pipeline.policy == {"retry": 1}


# ── 2. run ───────────────────────────────────────────────────────────────


async def test_submit_run_enqueues_a_jobrun_and_drives_the_graph(
    session_factory,
):
    """``submit_run`` + the registered handler walk the graph to completion.

    Celery dispatch is mocked (no broker required); the JobRun lands in
    the same SQLite file as the pipeline so the test sees both sides.
    """
    async with session_factory() as db:
        svc = PipelineService(db)
        pipeline = await svc.create(
            name="run-me",
            description=None,
            project_id=None,
            graph=_mock_graph(),
            policy={},
            created_by=None,
        )

        with (
            patch(
                "app.core.job_runner._dispatch_to_celery",
                return_value="celery-mock",
            ),
            patch(
                "app.core.job_runner._default_session_factory",
                return_value=session_factory,
            ),
        ):
            run, job = await svc.submit_run(pipeline, trigger={"type": "manual"}, actor_id=None)

    # The contract: a run IS a JobRun of kind="pipeline.run".
    assert job is not None
    assert job.kind == "pipeline.run"
    assert run.job_run_id == job.id
    assert job.payload_jsonb["run_id"] == str(run.id)

    # The handler is registered at import — invoke it directly to drive the
    # graph (no Celery worker needed for a unit test).
    from app.core.pipeline.executor import _run_pipeline_job

    summary = await _run_pipeline_job(job, {"run_id": str(run.id)}, session_factory=session_factory)
    assert summary["node_count"] == 2
    assert summary["done"] == 2
    assert summary["error"] == 0
    # The duration-logging hardening pins a ``duration_ms`` key onto the
    # summary so observability has the outcome without poking the DB.
    assert isinstance(summary.get("duration_ms"), int)


# ── 3. result fetch ──────────────────────────────────────────────────────


async def test_run_read_model_returns_per_node_states(session_factory):
    """``run_read_model`` is the shape ``GET /pipelines/runs/{id}`` serialises."""
    async with session_factory() as db:
        svc = PipelineService(db)
        pipeline = await svc.create(
            name="read-model",
            description=None,
            project_id=None,
            graph=_mock_graph(),
            policy={},
            created_by=None,
        )
        with (
            patch(
                "app.core.job_runner._dispatch_to_celery",
                return_value="celery-mock",
            ),
            patch(
                "app.core.job_runner._default_session_factory",
                return_value=session_factory,
            ),
        ):
            run, _ = await svc.submit_run(pipeline, trigger={"type": "manual"}, actor_id=None)
        await execute_run(db, run.id)

        run_row = await svc.get_run(run.id)
        assert run_row is not None
        detail = await svc.run_read_model(run_row)

    assert detail["id"] == str(run.id)
    assert detail["pipeline_id"] == str(pipeline.id)
    # Two nodes, both done — the read model surfaces per-node statuses
    # plus the small envelope each runner returned.
    assert len(detail["nodes"]) == 2
    statuses = {n["node_id"]: n["status"] for n in detail["nodes"]}
    assert statuses == {"t": "done", "echo": "done"}
    # The echo node's envelope is threaded through unchanged.
    echo = next(n for n in detail["nodes"] if n["node_id"] == "echo")
    assert echo["output"]["summary"] == "echo hi"


# ── 4. hardening: max-nodes-per-run guard ────────────────────────────────


async def test_execute_run_rejects_graphs_exceeding_max_nodes(session_factory, monkeypatch):
    """A graph past ``DEFAULT_MAX_NODES_PER_RUN`` is refused before any node runs.

    Without this cap a malicious / buggy graph could ask the worker to
    walk arbitrary-N nodes, eating CPU and growing the node-state table
    unboundedly. We monkeypatch the cap down to 2 for a deterministic
    assertion that does not depend on the production default.
    """
    import app.core.pipeline.executor as executor_mod

    monkeypatch.setattr(executor_mod, "DEFAULT_MAX_NODES_PER_RUN", 2)

    # 3 nodes > cap of 2 — must raise before any state row is written.
    graph = {
        "nodes": [
            {"id": "a", "type": "trigger.manual"},
            {"id": "b", "type": "test.unit_echo"},
            {"id": "c", "type": "test.unit_echo"},
        ],
        "edges": [
            {"id": "1", "source": "a", "target": "b"},
            {"id": "2", "source": "b", "target": "c"},
        ],
    }
    async with session_factory() as db:
        pipeline = Pipeline(name="big", graph=graph)
        db.add(pipeline)
        await db.flush()
        run = PipelineRun(
            pipeline_id=pipeline.id,
            graph_snapshot=graph,
            trigger={"type": "manual"},
        )
        db.add(run)
        await db.commit()
        run_id = run.id

    async with session_factory() as db:
        with pytest.raises(GraphValidationError, match="exceeds the per-run limit"):
            await execute_run(db, run_id)
