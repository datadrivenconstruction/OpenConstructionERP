"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pipeline Builder executor + node-runner + IDOR regression suite.

Two concerns, one file:

1. **Executor / node correctness** (PostgreSQL, no Celery): the
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

Test isolation: the executor tests run against a throwaway PostgreSQL
database (``isolated_engine``) so the seed-then-execute flow can see data
committed across separate sessions; the HTTP suite runs the app against the
session PostgreSQL cluster provisioned by ``conftest``.

Run:
    cd backend
    python -m pytest tests/integration/test_pipelines_executor.py -q
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

# The executor only ever calls *registered* node runners. Outside full
# app startup the module loader has not imported pipeline_nodes yet, so
# import it here for its registration side-effect (mirrors how
# conftest.py eagerly imports module models).
import app.modules.pipelines.pipeline_nodes  # noqa: F401
from tests._pg import isolated_engine

# ── PostgreSQL executor harness ─────────────────────────────────────────────


@pytest_asyncio.fixture
async def mem_factory():
    """Sessionmaker over a throwaway, schema-loaded PostgreSQL database.

    The executor flow seeds a run in one session, commits, then opens
    *separate* sessions to execute it and read back node states. Those
    cross-session reads require committed data to be visible on independent
    connections, so this binds to a real ``isolated_engine`` (dropped on
    teardown) rather than a single rolled-back transactional session.
    """
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)


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


# ── Per-node coverage: the wider working set ───────────────────────────────

# Rows without ``row_ids`` so aggregates/totals/gates use the wire sample and
# never touch the DB (``_resolve_full_rows`` falls back to ``rows``).
_SAMPLE_ROWS = [
    {"id": "1", "ordinal": "01", "unit": "m3", "quantity": "10", "unit_rate": "100"},
    {"id": "2", "ordinal": "02", "unit": "m3", "quantity": "2", "unit_rate": "50"},
    {"id": "3", "ordinal": "03", "unit": "m2", "quantity": "1", "unit_rate": "5"},
]


@pytest.mark.asyncio
async def test_node_transform_markup() -> None:
    from decimal import Decimal

    from app.modules.pipelines.pipeline_nodes import _run_transform_markup

    out = await _run_transform_markup(_ctx(params={"percent": 10}, inputs={"up": {"rows": _SAMPLE_ROWS, "count": 3}}))
    assert out["mutated"] is True
    first = out["rows"][0]
    assert Decimal(first["unit_rate"]) == Decimal("110")
    assert Decimal(first["total"]) == Decimal("1100")
    # A negative percent is a discount.
    disc = await _run_transform_markup(_ctx(params={"percent": -50}, inputs={"up": {"rows": _SAMPLE_ROWS}}))
    assert Decimal(disc["rows"][0]["unit_rate"]) == Decimal("50")


@pytest.mark.asyncio
async def test_node_transform_aggregate() -> None:
    from decimal import Decimal

    from app.modules.pipelines.pipeline_nodes import _run_transform_aggregate

    out = await _run_transform_aggregate(_ctx(params={"group_by": "unit"}, inputs={"up": {"rows": _SAMPLE_ROWS}}))
    assert out["count"] == 2  # m3 + m2
    assert Decimal(out["grand_total"]) == Decimal("1105")
    # Largest group first (m3 = 10*100 + 2*50 = 1100).
    assert out["rows"][0]["group"] == "m3"
    assert Decimal(out["rows"][0]["total"]) == Decimal("1100")


@pytest.mark.asyncio
async def test_node_transform_rollup() -> None:
    from decimal import Decimal

    from app.modules.pipelines.pipeline_nodes import _run_transform_rollup

    out = await _run_transform_rollup(_ctx(inputs={"up": {"rows": _SAMPLE_ROWS}}))
    assert out["count"] == 3
    assert out["priced"] == 3
    assert Decimal(out["total"]) == Decimal("1105")
    assert out["rows"][0]["metric"] == "Total"


@pytest.mark.asyncio
async def test_node_gate_budget_passes_and_blocks() -> None:
    from decimal import Decimal

    from app.modules.pipelines.pipeline_nodes import _run_gate_budget

    ok = await _run_gate_budget(_ctx(params={"max_total": 2000}, inputs={"up": {"rows": _SAMPLE_ROWS}}))
    assert Decimal(ok["total"]) == Decimal("1105")
    with pytest.raises(ValueError, match="Budget gate failed"):
        await _run_gate_budget(_ctx(params={"max_total": 1000}, inputs={"up": {"rows": _SAMPLE_ROWS}}))


@pytest.mark.asyncio
async def test_node_gate_completeness_warn_and_block() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_gate_completeness

    rows = [
        {"ordinal": "01", "quantity": "10", "unit_rate": "100"},
        {"ordinal": "02", "quantity": "0", "unit_rate": "0"},
    ]
    warn = await _run_gate_completeness(_ctx(params={"mode": "warn"}, inputs={"up": {"rows": rows}}))
    assert warn["complete"] is False
    assert warn["missing_quantity"] == 1
    assert warn["missing_unit_rate"] == 1
    with pytest.raises(ValueError, match="Completeness gate failed"):
        await _run_gate_completeness(_ctx(params={"mode": "block"}, inputs={"up": {"rows": rows}}))


@pytest.mark.asyncio
async def test_node_flow_merge_dedupes() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_flow_merge

    out = await _run_flow_merge(
        _ctx(
            inputs={
                "a": {"rows": [{"id": "1"}, {"id": "2"}], "row_ids": ["1", "2"], "count": 2},
                "b": {"rows": [{"id": "2"}, {"id": "3"}], "row_ids": ["2", "3"], "count": 2},
            }
        )
    )
    assert out["inputs_merged"] == 2
    assert out["count"] == 3  # id "2" deduped
    ids = {r["id"] for r in out["rows"]}
    assert ids == {"1", "2", "3"}


@pytest.mark.asyncio
async def test_node_transform_sort() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_transform_sort

    hi = await _run_transform_sort(
        _ctx(params={"field": "unit_rate", "descending": True}, inputs={"u": {"rows": _SAMPLE_ROWS}})
    )
    assert [r["id"] for r in hi["rows"]] == ["1", "2", "3"]  # 100, 50, 5
    lo = await _run_transform_sort(_ctx(params={"field": "unit_rate"}, inputs={"u": {"rows": _SAMPLE_ROWS}}))
    assert [r["id"] for r in lo["rows"]] == ["3", "2", "1"]


@pytest.mark.asyncio
async def test_node_transform_limit() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_transform_limit

    out = await _run_transform_limit(_ctx(params={"count": 2}, inputs={"u": {"rows": _SAMPLE_ROWS}}))
    assert out["count"] == 2
    assert [r["id"] for r in out["rows"]] == ["1", "2"]


@pytest.mark.asyncio
async def test_node_transform_dedupe() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_transform_dedupe

    rows = [{"id": "1", "unit": "m3"}, {"id": "1", "unit": "m3"}, {"id": "2", "unit": "m2"}]
    out = await _run_transform_dedupe(_ctx(inputs={"u": {"rows": rows}}))
    assert out["count"] == 2
    assert out["dropped"] == 1


@pytest.mark.asyncio
async def test_node_gate_count() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_gate_count

    ok = await _run_gate_count(
        _ctx(params={"min_rows": 1, "max_rows": 10}, inputs={"u": {"rows": _SAMPLE_ROWS, "count": 3}})
    )
    assert ok["count"] == 3
    with pytest.raises(ValueError, match="Count gate failed"):
        await _run_gate_count(_ctx(params={"min_rows": 5}, inputs={"u": {"rows": _SAMPLE_ROWS, "count": 3}}))


@pytest.mark.asyncio
async def test_node_action_export_csv() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_action_export_csv

    rows = [{"ordinal": "01", "description": "X", "unit": "m3", "quantity": "1", "unit_rate": "2"}]
    out = await _run_action_export_csv(_ctx(params={"filename": "o.csv"}, inputs={"u": {"rows": rows}}))
    assert out["file"]["filename"] == "o.csv"
    assert out["file"]["row_count"] == 1
    assert out["file"]["size_bytes"] > 0


@pytest.mark.asyncio
async def test_node_source_cost_catalog(mem_factory) -> None:
    from app.modules.costs.models import CostItem
    from app.modules.pipelines.pipeline_nodes import _run_source_cost_catalog

    async with mem_factory() as db:
        db.add(CostItem(code="C-001", description="Concrete C30/37", unit="m3", rate="120"))
        db.add(CostItem(code="S-001", description="Structural steel", unit="t", rate="1500"))
        await db.commit()

        out = await _run_source_cost_catalog(_ctx(db=db))
        assert out["count"] == 2
        assert out["row_ids"]

        filtered = await _run_source_cost_catalog(_ctx(db=db, params={"query": "concrete"}))
        assert filtered["count"] == 1
        assert filtered["rows"][0]["code"] == "C-001"
        assert filtered["rows"][0]["unit_rate"] == "120"


# ── Per-node coverage: the newer working set ───────────────────────────────


@pytest.mark.asyncio
async def test_node_transform_round() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_transform_round

    rows = [{"id": "1", "unit_rate": "10.126"}, {"id": "2", "unit_rate": "5"}]
    out = await _run_transform_round(_ctx(params={"field": "unit_rate", "places": 2}, inputs={"u": {"rows": rows}}))
    assert out["mutated"] is True
    assert out["rows"][0]["unit_rate"] == "10.13"
    assert out["rows"][1]["unit_rate"] == "5.00"
    # A separate target leaves the source untouched.
    tgt = await _run_transform_round(
        _ctx(params={"field": "unit_rate", "places": 0, "target": "rounded"}, inputs={"u": {"rows": rows}})
    )
    assert tgt["rows"][0]["rounded"] == "10"
    assert tgt["rows"][0]["unit_rate"] == "10.126"


@pytest.mark.asyncio
async def test_node_transform_currency_convert() -> None:
    from decimal import Decimal

    from app.modules.pipelines.pipeline_nodes import _run_transform_currency_convert

    rows = [{"id": "1", "quantity": "2", "unit_rate": "100"}]
    out = await _run_transform_currency_convert(
        _ctx(params={"rate": "1.1", "currency": "USD"}, inputs={"u": {"rows": rows}})
    )
    assert Decimal(out["rows"][0]["unit_rate"]) == Decimal("110.0")
    # unit_rate conversion recomputes the line total.
    assert Decimal(out["rows"][0]["total"]) == Decimal("220.0")
    assert out["rows"][0]["currency"] == "USD"
    # No rate → pass-through.
    noop = await _run_transform_currency_convert(_ctx(params={}, inputs={"u": {"rows": rows}}))
    assert noop["rows"][0]["unit_rate"] == "100"


@pytest.mark.asyncio
async def test_node_transform_map_values() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_transform_map_values

    rows = [{"id": "1", "unit": "m3"}, {"id": "2", "unit": "sqm"}, {"id": "3", "unit": "m3"}]
    out = await _run_transform_map_values(
        _ctx(params={"field": "unit", "mapping": {"sqm": "m2"}}, inputs={"u": {"rows": rows}})
    )
    # sqm remapped, unmapped m3 kept.
    assert [r["unit"] for r in out["rows"]] == ["m3", "m2", "m3"]
    # keep_unmapped=False blanks the miss.
    dropped = await _run_transform_map_values(
        _ctx(
            params={"field": "unit", "mapping": {"sqm": "m2"}, "keep_unmapped": False},
            inputs={"u": {"rows": rows}},
        )
    )
    assert dropped["rows"][0]["unit"] is None


@pytest.mark.asyncio
async def test_node_transform_split() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_transform_split

    rows = [{"id": "1", "unit": "m3"}, {"id": "2", "unit": "m2"}, {"id": "3", "unit": "m3"}]
    out = await _run_transform_split(
        _ctx(params={"field": "unit", "op": "eq", "value": "m3"}, inputs={"u": {"rows": rows}})
    )
    assert out["count"] == 2
    assert out["unmatched_count"] == 1
    assert {r["id"] for r in out["rows"]} == {"1", "3"}
    assert out["unmatched_rows"][0]["id"] == "2"


@pytest.mark.asyncio
async def test_node_transform_join() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_transform_join

    left = [{"id": "1", "code": "C-1"}, {"id": "2", "code": "C-2"}]
    right = [{"code": "C-1", "rate": "100"}]
    out = await _run_transform_join(
        _ctx(
            params={"key": "code", "how": "inner"},
            inputs={"a": {"rows": left}, "b": {"rows": right}},
        )
    )
    assert out["count"] == 1  # inner: only C-1 matched
    assert out["rows"][0]["rate"] == "100"
    # left join keeps the unmatched left row.
    lj = await _run_transform_join(
        _ctx(
            params={"key": "code", "how": "left"},
            inputs={"a": {"rows": left}, "b": {"rows": right}},
        )
    )
    assert lj["count"] == 2


@pytest.mark.asyncio
async def test_node_transform_running_total() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_transform_running_total

    rows = [{"id": "1", "q": "10"}, {"id": "2", "q": "5"}, {"id": "3", "q": "2"}]
    out = await _run_transform_running_total(_ctx(params={"field": "q", "target": "cum"}, inputs={"u": {"rows": rows}}))
    assert [r["cum"] for r in out["rows"]] == ["10", "15", "17"]
    assert out["final_total"] == "17"


@pytest.mark.asyncio
async def test_node_transform_percent_of_total() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_transform_percent_of_total

    # No row_ids → uses the wire sample; line totals 1000 + 100 + 5 = 1105.
    out = await _run_transform_percent_of_total(_ctx(params={"places": 2}, inputs={"u": {"rows": _SAMPLE_ROWS}}))
    assert out["grand_total"] == "1105"
    # First row 10*100 = 1000 → 90.50%.
    assert out["rows"][0]["pct_of_total"] == "90.50"


@pytest.mark.asyncio
async def test_node_transform_fill_missing() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_transform_fill_missing

    rows = [{"id": "1", "unit": "m3"}, {"id": "2", "unit": ""}, {"id": "3"}]
    out = await _run_transform_fill_missing(
        _ctx(params={"field": "unit", "value": "pcs"}, inputs={"u": {"rows": rows}})
    )
    assert [r["unit"] for r in out["rows"]] == ["m3", "pcs", "pcs"]


@pytest.mark.asyncio
async def test_node_transform_clamp() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_transform_clamp

    rows = [{"id": "1", "unit_rate": "5"}, {"id": "2", "unit_rate": "150"}, {"id": "3", "unit_rate": "50"}]
    out = await _run_transform_clamp(
        _ctx(params={"field": "unit_rate", "min": 10, "max": 100}, inputs={"u": {"rows": rows}})
    )
    assert [r["unit_rate"] for r in out["rows"]] == ["10", "100", "50"]


@pytest.mark.asyncio
async def test_node_transform_concat() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_transform_concat

    rows = [{"id": "1", "code": "C-1", "desc": "Concrete"}, {"id": "2", "code": "S-1", "desc": ""}]
    out = await _run_transform_concat(
        _ctx(
            params={"fields": ["code", "desc"], "target": "label", "separator": " - "},
            inputs={"u": {"rows": rows}},
        )
    )
    assert out["rows"][0]["label"] == "C-1 - Concrete"
    # Blank part is skipped, no dangling separator.
    assert out["rows"][1]["label"] == "S-1"


@pytest.mark.asyncio
async def test_node_source_constant() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_source_constant

    out = await _run_source_constant(_ctx(params={"rows": [{"code": "A"}, {"id": "keep", "code": "B"}]}))
    assert out["count"] == 2
    # A missing id is generated; a supplied one is kept.
    assert out["rows"][0]["id"] == "const-0"
    assert out["rows"][1]["id"] == "keep"
    assert out["row_ids"] == ["const-0", "keep"]


@pytest.mark.asyncio
async def test_node_enrich_lookup() -> None:
    from app.modules.pipelines.pipeline_nodes import _run_enrich_lookup

    rows = [{"id": "1", "code": "C-1"}, {"id": "2", "code": "C-9"}]
    table = {"C-1": {"rate": "100", "trade": "Concrete"}}
    out = await _run_enrich_lookup(_ctx(params={"key": "code", "table": table}, inputs={"u": {"rows": rows}}))
    assert out["matched"] == 1
    assert out["rows"][0]["rate"] == "100"
    assert out["rows"][0]["trade"] == "Concrete"
    # Unmatched row kept untouched by default.
    assert out["rows"][1].get("rate") is None
    # keep_unmatched=False drops the miss.
    dropped = await _run_enrich_lookup(
        _ctx(params={"key": "code", "table": table, "keep_unmatched": False}, inputs={"u": {"rows": rows}})
    )
    assert dropped["count"] == 1


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


@pytest.mark.tenant_isolation
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
