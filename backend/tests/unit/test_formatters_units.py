# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for Wave 24 unit-system formatting / validation helpers.

Covers:
    - BOQUnitSystemConsistencyRule (pure async, no DB)
    - _METRIC_BOQ_UNITS / _IMPERIAL_BOQ_UNITS constants from takeoff.service

No database — all tests use plain Python objects or ValidationContext
constructed in-memory.
"""

from __future__ import annotations

import pytest

from app.core.validation.engine import RuleCategory, Severity, ValidationContext
from app.core.validation.rules import BOQUnitSystemConsistencyRule

# ── Helpers ──────────────────────────────────────────────────────────────────


def _ctx(positions: list[dict], unit_system: str | None = None) -> ValidationContext:
    """Build a minimal ValidationContext for the rule."""
    data: dict = {"positions": positions}
    if unit_system is not None:
        data["project_unit_system"] = unit_system
    return ValidationContext(data=data)


async def _run(positions: list[dict], unit_system: str | None = None):
    """Run the rule and return the list of RuleResult."""
    rule = BOQUnitSystemConsistencyRule()
    ctx = _ctx(positions, unit_system)
    return await rule.validate(ctx)


# ── Test: no unit_system supplied ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skips_when_no_unit_system_supplied():
    """No project_unit_system → the rule emits NO result at all (E-VAL-008:
    an otherwise-empty BOQ must stay SKIPPED, not synthetically passed)."""
    positions = [{"ordinal": "01.001", "unit": "m3", "description": "Concrete"}]
    results = await _run(positions, unit_system=None)
    assert results == []


@pytest.mark.asyncio
async def test_passes_when_unit_system_unknown():
    """Rule skips when unit_system is an unrecognised value."""
    positions = [{"ordinal": "01.001", "unit": "m2"}]
    results = await _run(positions, unit_system="furlong")
    assert results[0].passed is True


# ── Test: empty positions ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_passes_empty_positions_metric():
    results = await _run([], unit_system="metric")
    assert results[0].passed is True


@pytest.mark.asyncio
async def test_passes_empty_positions_imperial():
    results = await _run([], unit_system="imperial")
    assert results[0].passed is True


# ── Test: metric project, metric units → PASS ─────────────────────────────────


@pytest.mark.asyncio
async def test_metric_project_with_metric_units_passes():
    positions = [
        {"ordinal": "01.001", "unit": "m2"},
        {"ordinal": "01.002", "unit": "m3"},
        {"ordinal": "01.003", "unit": "kg"},
        {"ordinal": "01.004", "unit": "m"},
        {"ordinal": "01.005", "unit": "lm"},
        {"ordinal": "01.006", "unit": "pcs"},  # neutral unit → pass
    ]
    results = await _run(positions, unit_system="metric")
    assert results[0].passed is True


# ── Test: imperial project, imperial units → PASS ─────────────────────────────


@pytest.mark.asyncio
async def test_imperial_project_with_imperial_units_passes():
    positions = [
        {"ordinal": "01.001", "unit": "sqft"},
        {"ordinal": "01.002", "unit": "ft"},
        {"ordinal": "01.003", "unit": "lb"},
        {"ordinal": "01.004", "unit": "cy"},
    ]
    results = await _run(positions, unit_system="imperial")
    assert results[0].passed is True


# ── Test: imperial project, metric units → WARNING ────────────────────────────


@pytest.mark.asyncio
async def test_imperial_project_with_metric_units_warns():
    """Core assertion: m³ in an imperial project triggers a WARNING."""
    positions = [
        {"ordinal": "01.001", "unit": "m3", "description": "Concrete pour"},
    ]
    results = await _run(positions, unit_system="imperial")
    assert len(results) == 1
    result = results[0]
    assert result.passed is False
    assert result.severity == Severity.WARNING
    assert result.category == RuleCategory.CONSISTENCY
    assert "imperial" in result.message
    assert "metric" in result.message
    assert "m3" in result.message or "01.001" in result.message


@pytest.mark.asyncio
async def test_imperial_project_multiple_metric_positions():
    """Multiple mismatched positions are all captured."""
    positions = [
        {"ordinal": "01.001", "unit": "m2"},
        {"ordinal": "01.002", "unit": "m3"},
        {"ordinal": "01.003", "unit": "kg"},
        {"ordinal": "01.004", "unit": "ft"},  # correct imperial → not flagged
    ]
    results = await _run(positions, unit_system="imperial")
    result = results[0]
    assert result.passed is False
    assert result.details["mismatch_count"] == 3


# ── Test: metric project, imperial units → WARNING ────────────────────────────


@pytest.mark.asyncio
async def test_metric_project_with_imperial_units_warns():
    positions = [
        {"ordinal": "01.001", "unit": "sqft"},
        {"ordinal": "01.002", "unit": "lb"},
    ]
    results = await _run(positions, unit_system="metric")
    result = results[0]
    assert result.passed is False
    assert result.severity == Severity.WARNING


# ── Test: zero values, large BOQ, fractional units ───────────────────────────


@pytest.mark.asyncio
async def test_zero_quantity_position_still_checked():
    """Zero-quantity position with wrong unit should still trigger warning."""
    positions = [{"ordinal": "01.001", "unit": "m3", "quantity": 0}]
    results = await _run(positions, unit_system="imperial")
    assert results[0].passed is False


@pytest.mark.asyncio
async def test_large_boq_detects_any_mismatch():
    """A large BOQ with one mismatched unit out of 100 positions still warns."""
    positions = [{"ordinal": f"01.{i:03d}", "unit": "ft"} for i in range(99)]
    positions.append({"ordinal": "01.100", "unit": "m3"})  # the one bad unit
    results = await _run(positions, unit_system="imperial")
    assert results[0].passed is False
    assert results[0].details["mismatch_count"] == 1


@pytest.mark.asyncio
async def test_neutral_units_never_flagged():
    """Neutral/unknown units (pcs, hrs, lsum) are not in either set."""
    positions = [
        {"ordinal": "01.001", "unit": "pcs"},
        {"ordinal": "01.002", "unit": "hrs"},
        {"ordinal": "01.003", "unit": "lsum"},
        {"ordinal": "01.004", "unit": "ea"},
    ]
    results = await _run(positions, unit_system="imperial")
    assert results[0].passed is True  # none of these are metric


@pytest.mark.asyncio
async def test_missing_unit_field_does_not_crash():
    """Positions without a 'unit' key must not raise."""
    positions = [
        {"ordinal": "01.001"},  # no unit key at all
        {"ordinal": "01.002", "unit": None},
        {"ordinal": "01.003", "unit": ""},
    ]
    results = await _run(positions, unit_system="imperial")
    assert results[0].passed is True  # empty/missing units are neutral


# ── Test: rule metadata ───────────────────────────────────────────────────────


def test_rule_metadata():
    """Static metadata must be correct for the registry and UI."""
    rule = BOQUnitSystemConsistencyRule()
    assert rule.rule_id == "boq_quality.unit_system_consistency"
    assert rule.standard == "boq_quality"
    assert rule.severity == Severity.WARNING
    assert rule.category == RuleCategory.CONSISTENCY


# ── Test: suggestion and details structure ────────────────────────────────────


@pytest.mark.asyncio
async def test_warning_result_has_suggestion_and_details():
    positions = [{"ordinal": "01.001", "unit": "m2"}]
    results = await _run(positions, unit_system="imperial")
    result = results[0]
    assert result.passed is False
    assert result.suggestion is not None
    assert len(result.suggestion) > 0
    assert "project_unit_system" in result.details
    assert result.details["project_unit_system"] == "imperial"
