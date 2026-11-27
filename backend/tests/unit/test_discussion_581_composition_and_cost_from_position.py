"""Position composition check and position-to-cost-item mapping (discussion 581)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.boq.composition_check import (
    ISSUE_MISSING_NAME,
    ISSUE_NON_POSITIVE_QUANTITY,
    ISSUE_TOTAL_MISMATCH,
    ISSUE_UNPRICED,
    inspect_composition,
)
from app.modules.costs.from_position import (
    DEFAULT_REGION,
    PositionNotSavableError,
    components_from_resources,
    cost_item_fields_from_position,
    default_code,
    resolve_region,
)


def _row(name="Mason", qty="2", rate="40", unit="h", **extra):
    return {"name": name, "quantity": qty, "unit_rate": rate, "unit": unit, **extra}


def test_coherent_when_rows_sum_to_the_stored_rate() -> None:
    meta = {"resources": [_row(), _row("Cement", "0.5", "30", "kg")]}
    out = inspect_composition(unit_rate="95", quantity="10", metadata=meta)
    assert out["derived_unit_rate"] == "95.0000"
    assert Decimal(out["delta"]) == 0
    assert out["coherent"] is True
    assert all(c["issues"] == [] for c in out["components"])


def test_drift_is_reported_as_stored_minus_derived() -> None:
    out = inspect_composition(unit_rate="100", quantity="1", metadata={"resources": [_row()]})
    assert out["coherent"] is False
    assert Decimal(out["delta"]) == Decimal("20")


def test_position_without_rows_is_coherent() -> None:
    out = inspect_composition(unit_rate="55", quantity="3", metadata={})
    assert out["coherent"] is True
    assert out["components"] == []


def test_row_issues_are_named() -> None:
    meta = {"resources": [_row(name="", qty="0", rate="0", total="5")]}
    issues = inspect_composition(unit_rate="0", quantity="1", metadata=meta)["components"][0]["issues"]
    assert {ISSUE_MISSING_NAME, ISSUE_NON_POSITIVE_QUANTITY, ISSUE_UNPRICED, ISSUE_TOTAL_MISMATCH} <= set(issues)


def test_foreign_currency_without_fx_is_listed() -> None:
    meta = {"resources": [_row(currency="CHF")]}
    out = inspect_composition(unit_rate="80", quantity="1", metadata=meta, fx_rates_map={}, base_currency="EUR")
    assert out["fx_missing"] == ["CHF"]


def test_components_keep_decimal_cost_to_cents() -> None:
    comps = components_from_resources([_row(qty="0.333", rate="10.01", currency="EUR"), {"name": " "}, "junk"])
    assert len(comps) == 1
    assert comps[0]["cost"] == "3.33"
    assert comps[0]["currency"] == "EUR"


def test_fields_from_position_carry_provenance() -> None:
    pid = uuid.uuid4()
    f = cost_item_fields_from_position(
        position_id=pid,
        description="Brick wall",
        unit="m2",
        unit_rate="120.50",
        metadata={"resources": [_row()], "currency": "EUR"},
    )
    assert f["rate"] == Decimal("120.50")
    assert f["currency"] == "EUR"
    assert f["metadata"] == {"saved_from_boq_position": str(pid)}
    assert len(f["components"]) == 1


@pytest.mark.parametrize(("desc", "unit"), [("Section", ""), ("", "m2"), (None, None)])
def test_sections_and_blank_positions_are_refused(desc, unit) -> None:
    with pytest.raises(PositionNotSavableError):
        cost_item_fields_from_position(
            position_id=uuid.uuid4(), description=desc, unit=unit, unit_rate="1", metadata={}
        )


def test_code_is_stable_per_position_and_region_falls_back() -> None:
    pid = uuid.uuid4()
    assert default_code(pid) == default_code(pid)
    assert resolve_region("DE-BY", {"cost_item_region": "X"}) == "DE-BY"
    assert resolve_region(None, {"cost_item_region": "X"}) == "X"
    assert resolve_region(None, {}) == DEFAULT_REGION
