"""Demo cost allocations identify their origin without changing pricing or planning."""

from decimal import Decimal

import pytest

from app.core.demo_projects import (
    _enrich_position_metadata,
    _resource_breakdown_rollup,
    _resources_for_position,
)
from app.modules.schedule.service import _calc_duration_from_resources


@pytest.mark.parametrize("explicit", [None, [("general_labor", "labor", "hr", 2, 50)]])
def test_provenance_distinguishes_generated_and_explicit_without_certifying_either(explicit):
    meta = _enrich_position_metadata("Unclassified scope", "m2", 100, {}, explicit_resources=explicit)
    rows = meta["resources"]
    expected = "template_explicit_build_up" if explicit else "synthetic_cost_allocation"
    assert {r["demo_provenance"]["source"] for r in rows} == {expected}
    assert all(r["demo_provenance"]["productivity_verified"] is False for r in rows)
    assert sum(Decimal(str(r["quantity"])) * Decimal(str(r["unit_rate"])) for r in rows) == Decimal("100")
    if explicit:
        assert (rows[0]["quantity"], rows[0]["unit_rate"], rows[0]["total"]) == (2, 50, 100)
    else:
        assert {r["demo_provenance"]["quantity_basis"] for r in rows} == {
            "allowance",
            "price_share_divided_by_hourly_rate",
        }
    stripped = [{k: v for k, v in r.items() if k != "demo_provenance"} for r in rows]
    assert _resource_breakdown_rollup(rows) == _resource_breakdown_rollup(stripped)
    args = (100, "m2", 10000, 10000, 365)
    kwargs = {"hours_per_day": 8, "work_days_per_week": 5, "assumed_workers": 3}
    assert _calc_duration_from_resources({"resources": rows}, *args, **kwargs) == _calc_duration_from_resources(
        {"resources": stripped}, *args, **kwargs
    )


def test_rejected_explicit_build_up_retains_synthetic_origin_and_values():
    baseline = _enrich_position_metadata("Concrete", "m3", 100, {})
    rejected = _enrich_position_metadata(
        "Concrete", "m3", 100, {}, explicit_resources=[("general_labor", "labor", "hr", 1, 1)]
    )
    assert rejected == baseline
    assert all(r["demo_provenance"]["source"] == "synthetic_cost_allocation" for r in rejected["resources"])


def test_budget_allowances_have_origin_but_are_not_verified_hour_norms():
    rows = _resources_for_position("Unclassified scope", "m2", 200, 100)
    assert len(rows) == 3
    assert sum(Decimal(str(r["quantity"])) * Decimal(r["unit_rate"]) for r in rows) == Decimal("100")
    assert all(r["quantity"] == 1 and r["unit"] == "m2" and r["estimated"] for r in rows)
    assert all(
        r["demo_provenance"]
        == {"source": "synthetic_cost_allocation", "quantity_basis": "allowance", "productivity_verified": False}
        for r in rows
    )
    assert _resources_for_position("Unclassified scope", "m2", 0, 100) == []
