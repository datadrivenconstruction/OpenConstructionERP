# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pipeline Builder Phase-1 spine tests.

Covers the three core contracts the design pins:

* **executor** — Kahn topo order incl. cycle rejection, per-node state
  persistence, stale-downstream on re-run, and "a run IS a JobRun".
* **registry** — register / lookup, unknown type rejected *before* the
  run (graph validation), not mid-run.
* **graph rule** — a side-effecting node with no gate on the path from a
  trigger fails the structural ``pipeline`` validation rule (ERROR).

All DB work uses a file-backed temp SQLite (never the prod DB) — the
hard test-isolation rule.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Importing pipeline_nodes registers the 6 Phase-1 node types.
import app.modules.pipelines.pipeline_nodes  # noqa: F401,E402
from app.core.job_run import JobRun
from app.core.pipeline.executor import (
    GraphValidationError,
    descendants,
    execute_run,
    topological_order,
    validate_graph,
)
from app.core.pipeline.registry import NodeContext, node_registry, register_node
from app.database import Base
from app.modules.pipelines.models import (
    Pipeline,
    PipelineNodeState,
    PipelineRun,
)
from app.modules.projects.models import Project
from app.modules.users.models import User


@pytest.fixture(autouse=True)
def _register_builtin_rules():
    """The gate.validation node runs the real engine — rules must exist."""
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()


@pytest.fixture
async def session_factory(tmp_path):
    """File-backed async SQLite scoped to the pipeline + job tables."""
    db_path = tmp_path / "pipeline_test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
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


# ── helpers ──────────────────────────────────────────────────────────────


def _linear_graph() -> dict:
    """trigger.manual → source.boq → gate.validation → action.export.excel."""
    return {
        "nodes": [
            {"id": "t", "type": "trigger.manual", "params": {}},
            {"id": "s", "type": "source.boq", "params": {}},
            {
                "id": "g",
                "type": "gate.validation",
                "params": {"rule_sets": ["boq_quality"]},
            },
            {"id": "x", "type": "action.export.excel", "params": {}},
        ],
        "edges": [
            {"id": "e1", "source": "t", "target": "s"},
            {"id": "e2", "source": "s", "target": "g"},
            {"id": "e3", "source": "g", "target": "x"},
        ],
    }


async def _make_run(maker, graph: dict) -> uuid.UUID:
    async with maker() as db:
        pipeline = Pipeline(name="t", graph=graph)
        db.add(pipeline)
        await db.flush()
        run = PipelineRun(
            pipeline_id=pipeline.id,
            graph_snapshot=graph,
            trigger={"type": "manual"},
        )
        db.add(run)
        await db.commit()
        return run.id


# ── topo order + cycle rejection ─────────────────────────────────────────


def test_topological_order_is_dependency_respecting():
    order = topological_order(_linear_graph())
    assert order.index("t") < order.index("s")
    assert order.index("s") < order.index("g")
    assert order.index("g") < order.index("x")


def test_topological_order_rejects_a_cycle():
    cyclic = {
        "nodes": [
            {"id": "a", "type": "trigger.manual"},
            {"id": "b", "type": "transform.filter"},
            {"id": "c", "type": "transform.filter"},
        ],
        "edges": [
            {"id": "1", "source": "a", "target": "b"},
            {"id": "2", "source": "b", "target": "c"},
            {"id": "3", "source": "c", "target": "b"},  # cycle b↔c
        ],
    }
    with pytest.raises(GraphValidationError, match="cycle"):
        topological_order(cyclic)


def test_descendants_returns_topo_descendants():
    g = _linear_graph()
    assert descendants(g, "s") == {"g", "x"}
    assert descendants(g, "x") == set()


# ── registry: unknown type rejected BEFORE the run ───────────────────────


def test_validate_graph_rejects_unregistered_node_type():
    bad = {
        "nodes": [{"id": "n", "type": "does.not.exist"}],
        "edges": [],
    }
    with pytest.raises(GraphValidationError, match="unregistered node types"):
        validate_graph(bad)


def test_validate_graph_accepts_registered_types():
    # All six Phase-1 types are registered at import — no raise.
    assert validate_graph(_linear_graph()) == topological_order(_linear_graph())


def test_register_node_and_lookup_roundtrip():
    async def _runner(ctx: NodeContext) -> dict:
        return {"ok": True}

    spec = register_node(
        type="test.echo",
        module="oe_pipelines",
        category="transform",
        label="Echo",
        description="test node",
        runner=_runner,
    )
    assert node_registry.get("test.echo") is spec
    assert spec.public_dict()["type"] == "test.echo"
    assert "runner" not in spec.public_dict()


# ── per-node persistence + run==JobRun + stale-downstream ────────────────


async def test_execute_run_persists_every_node_state(session_factory):
    """Each node gets a persisted row; a clean run ends all 'done'."""
    run_id = await _make_run(session_factory, _linear_graph())
    async with session_factory() as db:
        summary = await execute_run(db, run_id)

    assert summary["node_count"] == 4
    assert summary["done"] == 4
    assert summary["error"] == 0

    async with session_factory() as db:
        states = (await db.execute(select(PipelineNodeState).where(PipelineNodeState.run_id == run_id))).scalars().all()
    by_node = {s.node_id: s for s in states}
    assert set(by_node) == {"t", "s", "g", "x"}
    assert all(s.status == "done" for s in states)
    # took_ms captured on every node (generalised run_stage contract).
    assert all(s.took_ms is not None for s in states)


async def test_rerun_marks_downstream_stale(session_factory):
    """Re-running an upstream node flips done descendants to 'stale'."""
    run_id = await _make_run(session_factory, _linear_graph())
    async with session_factory() as db:
        await execute_run(db, run_id)

    # Re-run ONLY the source node — its descendants (g, x) were 'done'
    # and must become 'stale' (the match_elements run_stage behaviour).
    from app.core.pipeline.executor import run_node

    graph = _linear_graph()
    src_node = next(n for n in graph["nodes"] if n["id"] == "s")
    async with session_factory() as db:
        await run_node(
            db,
            run_id,
            src_node,
            upstream={},
            graph=graph,
        )
        states = (await db.execute(select(PipelineNodeState).where(PipelineNodeState.run_id == run_id))).scalars().all()
    by_node = {s.node_id: s.status for s in states}
    assert by_node["s"] == "done"
    assert by_node["g"] == "stale"
    assert by_node["x"] == "stale"


async def test_run_is_a_jobrun(session_factory):
    """submit_run enqueues exactly one JobRun of kind=pipeline.run."""
    from unittest.mock import patch

    from app.modules.pipelines.service import PipelineService

    graph = _linear_graph()
    async with session_factory() as db:
        svc = PipelineService(db)
        pipeline = await svc.create(
            name="p",
            description=None,
            project_id=None,
            graph=graph,
            policy={},
            created_by=None,
        )
        # submit_job uses the platform default session factory; point it at
        # the test DB so the JobRun row lands in the same SQLite file.
        with (
            patch(
                "app.core.job_runner._dispatch_to_celery",
                return_value="celery-1",
            ),
            patch(
                "app.core.job_runner._default_session_factory",
                return_value=session_factory,
            ),
        ):
            run, job = await svc.submit_run(pipeline, trigger={"type": "manual"}, actor_id=None)

    assert job.kind == "pipeline.run"
    assert run.job_run_id == job.id
    assert job.payload_jsonb["run_id"] == str(run.id)

    # The handler is registered and actually drives the graph.
    async with session_factory() as db:
        from app.core.pipeline.executor import _run_pipeline_job

        result = await _run_pipeline_job(job, {"run_id": str(run.id)}, session_factory=session_factory)
    assert result["done"] == 4


async def test_failing_node_skips_its_descendants(session_factory):
    """A node error skips every dependent node (no partial writes)."""
    # gate.validation will raise because the boq_quality rule set finds a
    # blocking error in the injected bad row.
    graph = {
        "nodes": [
            {"id": "t", "type": "trigger.manual"},
            {"id": "src", "type": "test.bad_rows"},
            {
                "id": "g",
                "type": "gate.validation",
                "params": {"rule_sets": ["boq_quality"]},
            },
            {"id": "x", "type": "action.export.excel"},
        ],
        "edges": [
            {"id": "1", "source": "t", "target": "src"},
            {"id": "2", "source": "src", "target": "g"},
            {"id": "3", "source": "g", "target": "x"},
        ],
    }

    async def _bad_rows(ctx: NodeContext) -> dict:
        # Zero quantity + zero rate + missing description → boq_quality
        # ERROR-severity findings, so the gate raises.
        return {
            "rows": [
                {
                    "id": "p1",
                    "ordinal": "01",
                    "description": "",
                    "unit": "m3",
                    "quantity": 0,
                    "unit_rate": 0,
                    "classification": {},
                }
            ]
        }

    register_node(
        type="test.bad_rows",
        module="oe_pipelines",
        category="source",
        label="Bad rows",
        description="emits a failing row",
        runner=_bad_rows,
    )

    run_id = await _make_run(session_factory, graph)
    async with session_factory() as db:
        summary = await execute_run(db, run_id)

    assert summary["error"] == 1  # the gate
    assert summary["skipped"] == 1  # the export, skipped after gate error
    async with session_factory() as db:
        states = {
            s.node_id: s.status
            for s in (await db.execute(select(PipelineNodeState).where(PipelineNodeState.run_id == run_id)))
            .scalars()
            .all()
        }
    assert states["g"] == "error"
    assert states["x"] == "skipped"
