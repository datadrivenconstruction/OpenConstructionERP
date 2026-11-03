"""Takeoff carry-over onto a new drawing revision: the pure parts.

* Only a page's own calibration counts as a checked scale.
* Same scale keeps the value; a changed scale recomputes it from the same points.
* Per-position deltas net deductions and count unreviewed copies.
* ``boq.drawing.carried_unconfirmed`` is an info finding per position.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.boq.validators import CarriedLowConfidencePending, CarriedMeasurementUnconfirmed
from app.modules.takeoff import carry_over as co


def test_page_scale_reads_only_the_page_entry():
    scales = {"defaultScale": {"pixelsPerUnit": 50}, "byPage": {"2": {"pixelsPerUnit": 40, "unitLabel": "m"}}}
    assert co.page_scale(scales, 2) == 40.0
    assert co.page_scale(scales, 1) is None
    assert co.page_scale(None, 1) is None
    assert co.page_scale({"byPage": {"1": {"pixelsPerUnit": "bad"}}}, 1) is None


@pytest.mark.parametrize(
    ("mtype", "old", "new", "verdict"),
    [
        ("area", 40.0, 40.1, co.SCALE_SAME),
        ("area", 40.0, 20.0, co.SCALE_CHANGED),
        ("distance", 40.0, None, co.SCALE_UNVERIFIED),
        ("distance", None, 40.0, co.SCALE_CHANGED),
        ("count", 40.0, 20.0, co.SCALE_NONE),
    ],
)
def test_scale_verdict(mtype, old, new, verdict):
    assert co.scale_verdict(mtype, old, new) == verdict


def _old(**kw):
    base = {
        "type": "distance",
        "points": [{"x": 0, "y": 0}, {"x": 100, "y": 0}],
        "scale_pixels_per_unit": 10.0,
        "measurement_value": Decimal("10"),
        "count_value": None,
        "depth": None,
        "volume": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_carried_values_keep_or_recompute_from_the_same_points():
    assert co.carried_values(_old(), 10.0)["measurement_value"] == pytest.approx(10.0)
    rescaled = co.carried_values(_old(), 20.0)
    assert rescaled["measurement_value"] == pytest.approx(5.0)
    assert rescaled["scale_pixels_per_unit"] == 20.0
    # No calibration on the new sheet: the old scale is kept, the quantity reads the same.
    kept = co.carried_values(_old(), None)
    assert kept["scale_pixels_per_unit"] == 10.0
    assert kept["measurement_value"] == pytest.approx(10.0)


def test_carry_status_reads_metadata():
    pending = SimpleNamespace(metadata_={co.CARRY_KEY: {"status": co.NEEDS_REVIEW, "scale_check": "same"}})
    assert co.is_carried_pending(pending)
    assert co.carry_status(pending) == (co.NEEDS_REVIEW, "same")
    assert co.carry_status(SimpleNamespace(metadata_={})) == (None, None)
    assert not co.is_carried_pending(SimpleNamespace(metadata_=None))


def test_position_deltas_net_deductions_and_count_pending():
    rows = [
        {"linked_boq_position_id": "p1", "old_value": 50.0, "new_value": 55.0, "cost_impact": "100.00"},
        {
            "linked_boq_position_id": "p1",
            "old_value": 4.0,
            "new_value": 6.0,
            "is_deduction": True,
            "carry_status": co.NEEDS_REVIEW,
            "cost_impact": "-40.00",
        },
        {"linked_boq_position_id": None, "old_value": 1.0, "new_value": 2.0},
    ]
    out = co.position_deltas(rows, {"p1": {"ordinal": "01.001", "unit": "m2", "quantity": "46"}})
    assert len(out) == 1
    d = out[0]
    assert (d["old_quantity"], d["new_quantity"], d["delta_quantity"]) == (46.0, 49.0, 3.0)
    assert d["cost_impact"] == "60.00"
    assert d["carried_pending"] == 1
    assert d["boq_quantity"] == "46"


@pytest.mark.asyncio
async def test_unconfirmed_carry_rule_is_info_per_position():
    rule = CarriedMeasurementUnconfirmed()
    data = {
        "positions": [{"id": "p1", "ordinal": "01.001", "unit": "m2", "type": "position"}],
        "drawing_refs": {"p1": {"carried_unconfirmed": 2, "refs": []}},
    }
    results = await rule.validate(ValidationContext(data=data))
    assert len(results) == 1
    assert results[0].severity == Severity.INFO
    assert "01.001" in results[0].message and "2" in results[0].message
    data["drawing_refs"]["p1"]["carried_unconfirmed"] = 0
    assert await rule.validate(ValidationContext(data=data)) == []


@pytest.mark.asyncio
async def test_low_confidence_carry_rule_counts_only_the_unsure_ones():
    rule = CarriedLowConfidencePending()
    data = {
        "positions": [{"id": "p1", "ordinal": "01.001", "unit": "m2", "type": "position"}],
        "drawing_refs": {"p1": {"carried_unconfirmed": 3, "carried_low_confidence": 1, "refs": []}},
    }
    results = await rule.validate(ValidationContext(data=data))
    assert len(results) == 1 and results[0].severity == Severity.WARNING
    data["drawing_refs"]["p1"]["carried_low_confidence"] = 0
    assert await rule.validate(ValidationContext(data=data)) == []


def test_low_confidence_is_counted_from_the_carry_metadata():
    from app.modules.boq.drawing_refs import PositionDrawingRefs

    entry = PositionDrawingRefs(position_id="p1", ordinal="1")
    assert entry.as_dict()["carried_low_confidence"] == 0
