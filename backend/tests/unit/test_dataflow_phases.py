"""Dataflow phases and edge labels: the platform map's columns come from data."""

from __future__ import annotations

from types import SimpleNamespace

from app.core.data_paths import DataPath, DataPaths
from app.modules.dataflow.phases import PHASE_OF, PHASES, phase_of


def test_table_maps_only_known_phases():
    assert set(PHASE_OF.values()) <= set(PHASES)


def test_estimating_spine_reads_in_project_order():
    order = [PHASES.index(phase_of(m, None)) for m in ("oe_takeoff", "oe_tendering", "oe_schedule", "oe_costmodel")]
    assert order == sorted(order)
    assert phase_of("oe_boq", None) == "estimate"


def test_declaration_phase_wins_over_table():
    manifest = SimpleNamespace(data_paths=DataPaths(reason="x", phase="finance"))
    assert phase_of("oe_boq", manifest) == "finance"


def test_unknown_declared_phase_falls_back_to_table():
    manifest = SimpleNamespace(data_paths=DataPaths(reason="x", phase="nowhere"))
    assert phase_of("oe_boq", manifest) == "estimate"


def test_unlisted_module_sits_in_platform():
    assert phase_of("oe_users", None) == "platform"


def test_edge_label_defaults_empty():
    assert DataPath("oe_tendering", "TenderPackage", via="TenderPackage.boq_id").edge == ""
    assert DataPath("oe_x", "X", via="X.id", edge="data_paths.edge.x").edge == "data_paths.edge.x"
