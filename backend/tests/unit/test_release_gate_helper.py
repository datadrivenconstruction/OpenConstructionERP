"""Tests for the pure parts of scripts/release_gate/gate.py.

The release gate decides whether a wheel installs and upgrades cleanly on
every platform, so a verdict function that cannot fail would wave a broken
release through. Each check here has a case that must fail next to the case
that must pass.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_GATE = Path(__file__).resolve().parents[3] / "scripts" / "release_gate" / "gate.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("release_gate_helper", _GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _healthy(**overrides):
    payload = {
        "status": "healthy",
        "database": "ok",
        "version": "18.7.0",
        "frontend_dist_present": True,
        "schema_heal_failed": False,
        "data_repairs_failed": False,
        "data_repair_ledger_failed": False,
        "schema_matches_models": True,
        "alembic_head_matches": True,
        "modules_enabled": 10,
        "modules_loaded": 10,
    }
    payload.update(overrides)
    return payload


def test_health_passes_a_healthy_payload(gate) -> None:
    assert gate.health_problems(_healthy(), "18.7.0", fresh=True) == []


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"status": "degraded"}, "status"),
        ({"database": "error"}, "database"),
        ({"version": "18.6.4"}, "version"),
        ({"frontend_dist_present": False}, "frontend_dist_present"),
        ({"schema_heal_failed": True}, "schema_heal_failed"),
        ({"data_repairs_failed": True}, "data_repairs_failed"),
        ({"schema_matches_models": False}, "schema_matches_models"),
        ({"alembic_head_matches": None}, "alembic_head_matches"),
        ({"modules_loaded": 9}, "modules loaded"),
    ],
)
def test_health_reports_each_problem(gate, overrides, needle) -> None:
    problems = gate.health_problems(_healthy(**overrides), "18.7.0", fresh=True)
    assert any(needle in p for p in problems), problems


def test_stale_stamp_is_not_a_failure_after_an_upgrade(gate) -> None:
    # The product does not advance an existing stamp; the schema is what counts.
    assert gate.health_problems(_healthy(alembic_head_matches=False), "18.7.0", fresh=False) == []


def test_log_scan_finds_tracebacks_and_error_levels(gate) -> None:
    log = "\n".join(
        [
            "INFO:     Started server process [1]",
            "2026-10-17 10:00:00 [info     ] module loaded name=oe_errors_catalog",
            "Traceback (most recent call last):",
            "ERROR:    Exception in ASGI application",
            "2026-10-17 10:00:01 [error    ] seed failed",
            "2026-10-17 10:00:02,123 ERROR app.main: boom",
            "STAGE:server:fail:OSError: port in use",
        ]
    )
    hits = gate.scan_log_for_errors(log)
    assert len(hits) == 5
    assert not any("oe_errors_catalog" in h for h in hits)


def test_log_scan_honours_the_allow_list(gate) -> None:
    log = "ERROR:    known noisy line\nERROR:    real problem"
    assert gate.scan_log_for_errors(log, [r"known noisy"]) == ["ERROR:    real problem"]


def _snapshot():
    return {
        "project_ids": ["p1", "p2"],
        "direct_cost_total": "35814.435",
        "positions": [
            {"ordinal": "01.001", "quantity": "125.5", "unit_rate": "285.37", "total": "35813.94"},
        ],
    }


def test_snapshot_survives_equal_decimals_in_another_spelling(gate) -> None:
    after = {
        "direct_cost_total": "35814.4350",
        "positions": [{"ordinal": "01.001", "quantity": "125.50", "unit_rate": "285.370", "total": "35813.940"}],
    }
    assert gate.compare_snapshot(_snapshot(), after, {"p1", "p2", "p3"}) == []


def test_snapshot_reports_changed_amounts_and_lost_rows(gate) -> None:
    after = {
        "direct_cost_total": "0",
        "positions": [{"ordinal": "01.001", "quantity": "125.5", "unit_rate": "285.36", "total": "35813.94"}],
    }
    problems = gate.compare_snapshot(_snapshot(), after, {"p1"})
    assert any("unit_rate" in p for p in problems)
    assert any("direct_cost_total" in p for p in problems)
    assert any("project(s)" in p for p in problems)


def test_snapshot_reports_a_missing_position(gate) -> None:
    after = {"direct_cost_total": "35814.435", "positions": []}
    problems = gate.compare_snapshot(_snapshot(), after, {"p1", "p2"})
    assert any("01.001 is gone" in p for p in problems)


def test_wheel_version_and_asset_refs(gate) -> None:
    assert gate.wheel_version(Path("openconstructionerp-18.7.0-py3-none-any.whl")) == "18.7.0"
    html = '<script type="module" src="/assets/index-abc.js"></script><link href="https://fonts.x/a.css">'
    assert gate.asset_refs(html) == ["/assets/index-abc.js"]
