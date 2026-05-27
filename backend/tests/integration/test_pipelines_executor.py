"""Pipeline Builder executor + node-runner + IDOR regression suite.

Two concerns, one file:

1. **Executor / node correctness** (in-memory SQLite, no Celery): the
   DAG executor must topo-order deterministically, surface a node
   failure as an ``error`` state, skip every dependent of a failed node
   (without aborting sibling branches), and persist a small envelope per
   node. Plus a happy-path assertion for every Phase-1 node type
   (``trigger.manual``, ``source.project``, ``source.boq``,
   ``transform.filter``, ``gate.validation``, ``action.export.excel``).

2. **Access control (IDOR)** at the HTTP layer: an authenticated user
   must not be able to read / mutate / run / list another user's
   pipeline, nor read another user's run output (which embeds project
   BOQ rows). Pre-fix every pipeline endpoint authenticated but never
   authorized.

Test isolation (``feedback_test_isolation.md``): a per-module temp
SQLite file is registered BEFORE any ``from app...`` import; the
production ``openestimate.db`` is never touched.

Run:
    cd backend
    python -m pytest tests/integration/test_pipelines_executor.py -q
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-pipelines-exec-"))
_TMP_DB = _TMP_DIR / "pipelines_exec.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    async_sessionmaker,
    create_async_engine,
)

# The executor only ever calls *registered* node runners. Outside full
# app startup the module loader has not imported pipeline_nodes yet, so
# import it here for its registration side-effect (mirrors how
# conftest.py eagerly imports module models).
import app.modules.pipelines.pipeline_nodes  # noqa: E402,F401

# ── In-memory executor harness ─────────────────────────────────────────────


@pytest_asyncio.fixture
async def mem_factory():
    """Fresh in-memory DB with every table the executor path touches."""
    from app.core.job_run import JobRun  # noqa: F401
    from app.database import Base
    from app.modules.boq import models as _boq  # noqa: F401
    from app.modules.pipelines import models as _pl  # noqa: F401
    from app.modules.projects import models as _proj  # noqa: F401
    from app.modules.users import models as _users  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


async def _seed_run(maker, graph: dict) -> uuid.UUID:
    """Create a PipelineRun row carrying ``graph`` as its snapshot."""
    from app.modules.pipelines.models import Pipeline, PipelineRun

    async with maker() as s:
        p = Pipeline(name="t", graph=graph, policy={})
        s.add(p)
        await s.flush()
        run = PipelineRun(pipeline_id=p.id, graph_snapshot=graph, trigger={"type": "manual"})
        s.add(run)
        await s.commit()
        return run.id


@pytest.mark.asyncio
async def test_executor_linear_spine_runs_every_node(mem_factory) -> None:
    """trigger → filter → export: all three nodes reach ``done``."""
    from app.core.pipeline.executor import execute_run

    graph = {
        "nodes": [
            {"id": "a", "type": "trigger.manual", "params": {}},
            {"id": "b", "type": "transform.filter", "params": {}},
            {
                "id": "c",
                "type": "action.export.excel",
                "params": {"filename": "x.xlsx"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "a", "target": "b"},
            {"id": "e2", "source": "b", "target": "c"},
        ],
    }
    run_id = await _seed_run(mem_factory, graph)
    async with mem_factory() as db:
        summary = await execute_run(db, run_id)

    assert summary["order"] == ["a", "b", "c"], "topo order must be stable"
    assert summary["done"] == 3
    assert summary["error"] == 0
    assert summary["statuses"] == {"a": "done", "b": "done", "c": "done"}


@pytest.mark.asyncio
async def test_executor_node_failure_skips_only_dependents(mem_factory) -> None:
    """A failing node errors; its dependents skip; a sibling still runs."""
    from app.core.pipeline.executor import execute_run
    from app.core.pipeline.registry import node_registry, register_node

    async def _boom(_ctx):
        raise RuntimeError("intentional node failure")

    register_node(
        type="test.boom",
        module="test",
        category="action",
        label="Boom",
        description="always fails",
        runner=_boom,
    )
    try:
        graph = {
            "nodes": [
                {"id": "root", "type": "trigger.manual", "params": {}},
                {"id": "bad", "type": "test.boom", "params": {}},
                {"id": "after_bad", "type": "transform.filter", "params": {}},
                {"id": "sibling", "type": "transform.filter", "params": {}},
            ],
            "edges": [
                {"id": "e1", "source": "root", "target": "bad"},
                {"id": "e2", "source": "bad", "target": "after_bad"},
                {"id": "e3", "source": "root", "target": "sibling"},
            ],
        }
        run_id = await _seed_run(mem_factory, graph)
        async with mem_factory() as db:
            summary = await execute_run(db, run_id)

        assert summary["statuses"]["root"] == "done"
        assert summary["statuses"]["bad"] == "error"
        assert summary["statuses"]["after_bad"] == "skipped"
        # The failure must NOT abort the independent branch.
        assert summary["statuses"]["sibling"] == "done"
    finally:
        node_registry._specs.pop("test.boom", None)


@pytest.mark.asyncio
async def test_executor_rejects_cycle_before_running(mem_factory) -> None:
    """A cyclic graph raises GraphValidationError — no partial run."""
    from app.core.pipeline.executor import GraphValidationError, execute_run

    graph = {
        "nodes": [
            {"id": "a", "type": "transform.filter", "params": {}},
            {"id": "b", "type": "transform.filter", "params": {}},
        ],
        "edges": [
            {"id": "e1", "source": "a", "target": "b"},
            {"id": "e2", "source": "b", "target": "a"},
        ],
    }
    run_id = await _seed_run(mem_factory, graph)
    async with mem_factory() as db:
        with pytest.raises(GraphValidationError):
            await execute_run(db, run_id)


@pytest.mark.asyncio
async def test_node_states_persist_small_envelope(mem_factory) -> None:
    """Every node writes a PipelineNodeState row with its output."""
    from app.core.pipeline.executor import execute_run
    from app.modules.pipelines.repository import PipelineRepository

    graph = {
        "nodes": [{"id": "a", "type": "trigger.manual", "params": {}}],
        "edges": [],
    }
    run_id = await _seed_run(mem_factory, graph)
    async with mem_factory() as db:
        await execute_run(db, run_id)
    async with mem_factory() as db:
        states = await PipelineRepository(db).list_node_states(run_id)
    assert len(states) == 1
    assert states[0].node_id == "a"
    assert states[0].status == "done"
    assert states[0].output.get("trigger") == "manual"
    assert states[0].started_at is not None


# ── Per-node happy-path coverage ───────────────────────────────────────────


def _ctx(**kw):
    from app.core.pipeline.registry import NodeContext

    base = dict(
        db=None,
        node_id="n",
        node_type="t",
        params={},
        inputs={},
    )
    base.update(kw)
    return NodeContext(**base)


@pytest.mark.asyncio
async def test_node_trigger_manual() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_trigger_manual

    out = await _run_trigger_manual(_ctx(actor_id="u1"))
    assert out["trigger"] == "manual"
    assert out["actor_id"] == "u1"


@pytest.mark.asyncio
async def test_node_source_project_and_boq(mem_factory) -> None:
    from app.modules.boq.models import BOQ, Position
    from app.modules.pipelines.pipeline_nodes import (
        _run_source_boq,
        _run_source_project,
    )
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    async with mem_factory() as db:
        owner = User(
            email=f"owner-{uuid.uuid4().hex[:8]}@pl.io",
            hashed_password="x",
            full_name="Owner",
        )
        db.add(owner)
        await db.flush()
        proj = Project(name="Proj X", owner_id=owner.id, status="active")
        db.add(proj)
        await db.flush()
        boq = BOQ(project_id=proj.id, name="B1")
        db.add(boq)
        await db.flush()
        db.add(
            Position(
                boq_id=boq.id,
                ordinal="01",
                description="Concrete",
                unit="m3",
                quantity="10",
                unit_rate="100",
                sort_order=0,
            )
        )
        await db.commit()
        pid = proj.id

        proj_out = await _run_source_project(_ctx(db=db, project_id=pid))
        assert proj_out["project"]["name"] == "Proj X"

        boq_out = await _run_source_boq(_ctx(db=db, project_id=pid))
        assert boq_out["count"] == 1
        assert boq_out["rows"][0]["description"] == "Concrete"
        assert boq_out["row_ids"]


@pytest.mark.asyncio
async def test_node_transform_filter() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_transform_filter

    rows = [
        {"id": "1", "unit": "m3"},
        {"id": "2", "unit": "m2"},
        {"id": "3", "unit": "m3"},
    ]
    out = await _run_transform_filter(
        _ctx(
            params={"field": "unit", "op": "eq", "value": "m3"},
            inputs={"up": {"rows": rows}},
        )
    )
    assert out["count"] == 2
    assert out["dropped"] == 1
    # Empty predicate is identity pass-through.
    out2 = await _run_transform_filter(_ctx(params={}, inputs={"up": {"rows": rows}}))
    assert out2["count"] == 3


@pytest.mark.asyncio
async def test_node_gate_validation_passes_clean_rows() -> None:
    from app.core.validation.rules import register_builtin_rules
    from app.modules.pipelines.pipeline_nodes import _run_gate_validation

    register_builtin_rules()
    rows = [
        {
            "id": "1",
            "ordinal": "01",
            "description": "Concrete C30/37",
            "unit": "m3",
            "quantity": "10",
            "unit_rate": "100",
        }
    ]
    out = await _run_gate_validation(_ctx(params={"rule_sets": ["boq_quality"]}, inputs={"up": {"rows": rows}}))
    assert out["count"] == 1
    assert "validation" in out


@pytest.mark.asyncio
async def test_node_gate_validation_blocks_on_errors() -> None:
    """A row with zero quantity + empty description must raise (gate stops)."""
    from app.core.validation.rules import register_builtin_rules
    from app.modules.pipelines.pipeline_nodes import _run_gate_validation

    register_builtin_rules()
    rows = [
        {
            "id": "1",
            "ordinal": "01",
            "description": "",
            "quantity": "0",
            "unit_rate": "0",
        }
    ]
    with pytest.raises(ValueError, match="Validation gate failed"):
        await _run_gate_validation(
            _ctx(
                params={"rule_sets": ["boq_quality"]},
                inputs={"up": {"rows": rows}},
            )
        )


@pytest.mark.asyncio
async def test_node_action_export_excel() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_action_export_excel

    rows = [{"ordinal": "01", "description": "X", "quantity": "1"}]
    out = await _run_action_export_excel(
        _ctx(
            params={"filename": "out.xlsx"},
            inputs={"up": {"rows": rows}},
        )
    )
    assert out["file"]["filename"] == "out.xlsx"
    assert out["file"]["row_count"] == 1
    assert out["file"]["size_bytes"] > 0


# ── HTTP IDOR regression ───────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def http_client():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def _activate(email: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True))
        await s.commit()


async def _register_login(client, tag: str) -> dict[str, str]:
    email = f"{tag}-{uuid.uuid4().hex[:8]}@pl-idor.io"
    pw = f"PlIdor{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": pw, "full_name": tag},
    )
    assert reg.status_code in (200, 201), reg.text
    await _activate(email)
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": pw})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_pipeline_idor_owner_isolation(http_client) -> None:
    """User B must not read / mutate / delete / run A's pipeline."""
    a = await _register_login(http_client, "a")
    b = await _register_login(http_client, "b")

    created = await http_client.post(
        "/api/v1/pipelines/",
        headers=a,
        json={"name": "A secret", "graph": {"nodes": [], "edges": []}},
    )
    assert created.status_code == 201, created.text
    pid = created.json()["id"]

    # B sees it in neither the global list nor by id.
    b_list = await http_client.get("/api/v1/pipelines/", headers=b)
    assert b_list.status_code == 200
    assert all(p["id"] != pid for p in b_list.json()), "B must not enumerate A's pipeline"

    for method, path, body in [
        ("GET", f"/api/v1/pipelines/{pid}", None),
        ("PUT", f"/api/v1/pipelines/{pid}", {"name": "hijacked"}),
        ("GET", f"/api/v1/pipelines/{pid}/runs/", None),
        ("POST", f"/api/v1/pipelines/{pid}/run", {}),
        ("DELETE", f"/api/v1/pipelines/{pid}", None),
    ]:
        r = await http_client.request(method, path, headers=b, json=body)
        assert r.status_code in (403, 404), f"B {method} {path} must be denied, got {r.status_code}"

    # A still has full access (pipeline was not mutated/deleted by B).
    a_get = await http_client.get(f"/api/v1/pipelines/{pid}", headers=a)
    assert a_get.status_code == 200
    assert a_get.json()["name"] == "A secret"
