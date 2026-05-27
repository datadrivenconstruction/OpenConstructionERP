# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Structural ``pipeline`` validation rule — "AI proposes, human confirms".

A side-effecting (write) node MUST have a ``gate.validation`` or
``gate.human_approval`` on every path from a trigger/AI node to it. A
graph that violates this fails the rule with an ERROR (which blocks
publish in the service layer).
"""

from __future__ import annotations

import pytest

# Ensure Phase-1 nodes + the builtin rules are registered.
import app.modules.pipelines.pipeline_nodes  # noqa: F401,E402
from app.core.pipeline.registry import NodeContext, register_node
from app.core.validation.engine import validation_engine


@pytest.fixture(autouse=True)
def _register_builtin_rules():
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()


async def _make_side_effecting_node() -> str:
    """Register a throwaway side-effecting node and return its type."""

    async def _noop(ctx: NodeContext) -> dict:
        return {"ok": True}

    register_node(
        type="test.write_db",
        module="oe_pipelines",
        category="action",
        label="Write DB",
        description="a side-effecting test node",
        runner=_noop,
        side_effecting=True,
    )
    return "test.write_db"


async def test_side_effecting_without_gate_fails():
    wtype = await _make_side_effecting_node()
    graph = {
        "nodes": [
            {"id": "t", "type": "trigger.manual"},
            {"id": "w", "type": wtype},
        ],
        "edges": [{"id": "1", "source": "t", "target": "w"}],
    }
    report = await validation_engine.validate(
        data={"graph": graph},
        rule_sets=["pipeline"],
        target_type="pipeline",
    )
    assert report.has_errors
    assert any(r.rule_id == "pipeline.side_effecting_requires_gate" for r in report.errors)


async def test_side_effecting_with_validation_gate_passes():
    wtype = await _make_side_effecting_node()
    graph = {
        "nodes": [
            {"id": "t", "type": "trigger.manual"},
            {"id": "g", "type": "gate.validation"},
            {"id": "w", "type": wtype},
        ],
        "edges": [
            {"id": "1", "source": "t", "target": "g"},
            {"id": "2", "source": "g", "target": "w"},
        ],
    }
    report = await validation_engine.validate(
        data={"graph": graph},
        rule_sets=["pipeline"],
        target_type="pipeline",
    )
    assert not report.has_errors


async def test_side_effecting_with_human_approval_gate_passes():
    wtype = await _make_side_effecting_node()
    graph = {
        "nodes": [
            {"id": "t", "type": "trigger.manual"},
            {"id": "a", "type": "gate.human_approval"},
            {"id": "w", "type": wtype},
        ],
        "edges": [
            {"id": "1", "source": "t", "target": "a"},
            {"id": "2", "source": "a", "target": "w"},
        ],
    }
    report = await validation_engine.validate(
        data={"graph": graph},
        rule_sets=["pipeline"],
        target_type="pipeline",
    )
    assert not report.has_errors


async def test_one_gated_path_but_one_ungated_path_still_fails():
    """The gate must cover EVERY path, not just one."""
    wtype = await _make_side_effecting_node()
    graph = {
        "nodes": [
            {"id": "t", "type": "trigger.manual"},
            {"id": "g", "type": "gate.validation"},
            {"id": "w", "type": wtype},
        ],
        "edges": [
            {"id": "1", "source": "t", "target": "g"},
            {"id": "2", "source": "g", "target": "w"},
            # Second, UNGATED path straight from the trigger to the write.
            {"id": "3", "source": "t", "target": "w"},
        ],
    }
    report = await validation_engine.validate(
        data={"graph": graph},
        rule_sets=["pipeline"],
        target_type="pipeline",
    )
    assert report.has_errors


async def test_pipeline_with_no_side_effecting_nodes_passes():
    """The Phase-1 spine has no side-effecting node → no gate required."""
    graph = {
        "nodes": [
            {"id": "t", "type": "trigger.manual"},
            {"id": "s", "type": "source.boq"},
            {"id": "x", "type": "action.export.excel"},
        ],
        "edges": [
            {"id": "1", "source": "t", "target": "s"},
            {"id": "2", "source": "s", "target": "x"},
        ],
    }
    report = await validation_engine.validate(
        data={"graph": graph},
        rule_sets=["pipeline"],
        target_type="pipeline",
    )
    assert not report.has_errors
