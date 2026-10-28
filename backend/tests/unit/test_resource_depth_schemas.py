# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure unit tests for the resource-depth schemas (T3.1).

Schema-only (pydantic + stdlib), so they run on the local Python 3.11 runner
without importing the ORM / DB layer. The focus is the money-as-string
discipline and the curve/rate/unit validation contracts.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.resources.resource_depth_schemas import (
    AssignmentUnitsPatch,
    CurveUpsert,
    HistogramCellResponse,
    RateCreate,
    RateResponse,
    ResourceHistogramResponse,
)


def _now() -> datetime:
    return datetime(2026, 6, 23, tzinfo=UTC)


def test_rate_create_defaults() -> None:
    rc = RateCreate(resource_id=uuid4(), effective_from=date(2026, 1, 1))
    assert rc.rate == Decimal("0")
    assert rc.rate_type == "cost"
    assert rc.effective_to is None


def test_rate_create_rejects_negative_rate() -> None:
    with pytest.raises(ValidationError):
        RateCreate(resource_id=uuid4(), effective_from=date(2026, 1, 1), rate=Decimal("-1"))


def test_rate_create_rejects_unknown_rate_type() -> None:
    with pytest.raises(ValidationError):
        RateCreate(resource_id=uuid4(), effective_from=date(2026, 1, 1), rate_type="bogus")


def test_rate_response_serialises_money_as_string() -> None:
    rr = RateResponse(
        id=uuid4(),
        resource_id=uuid4(),
        rate=Decimal("123.4500"),
        rate_type="cost",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        currency="EUR",
        created_at=_now(),
        updated_at=_now(),
    )
    dumped = rr.model_dump(mode="json")
    assert isinstance(dumped["rate"], str)
    assert dumped["rate"] == "123.4500"


def test_rate_response_zero_rate_is_honoured_not_dropped() -> None:
    rr = RateResponse(
        id=uuid4(),
        resource_id=uuid4(),
        rate=Decimal("0"),
        rate_type="billing",
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
        currency="",
        created_at=_now(),
        updated_at=_now(),
    )
    assert rr.model_dump(mode="json")["rate"] == "0"


def test_curve_upsert_accepts_named_curves() -> None:
    for ctype in ("flat", "front_load", "back_load", "bell"):
        cu = CurveUpsert(curve_type=ctype)
        assert cu.curve_type == ctype
        assert cu.manual_weights == []


def test_curve_upsert_rejects_unknown_curve() -> None:
    with pytest.raises(ValidationError):
        CurveUpsert(curve_type="sawtooth")


def test_units_patch_optional_and_validated() -> None:
    empty = AssignmentUnitsPatch()
    assert empty.model_dump(exclude_unset=True) == {}
    patch = AssignmentUnitsPatch(units=3.0, unit_kind="equipment")
    assert patch.units == 3.0
    assert patch.unit_kind == "equipment"
    with pytest.raises(ValidationError):
        AssignmentUnitsPatch(units=-1.0)
    with pytest.raises(ValidationError):
        AssignmentUnitsPatch(unit_kind="ghost")


def test_histogram_cell_serialises_cost_as_string() -> None:
    cell = HistogramCellResponse(
        bucket_index=0,
        start=_now(),
        end=_now(),
        label="Jun 23",
        demand_units=2.5,
        demand_cost=Decimal("4000.00"),
        available=3.0,
        capacity_unknown=False,
        over_allocated=False,
        bookings=[],
    )
    dumped = cell.model_dump(mode="json")
    assert isinstance(dumped["demand_cost"], str)
    assert dumped["demand_cost"] == "4000.00"


def test_histogram_response_roundtrip() -> None:
    resp = ResourceHistogramResponse(
        resource_id=uuid4(),
        bucket="week",
        capacity_units=None,
        peak_demand=0.0,
        over_allocated_buckets=0,
        cells=[],
    )
    dumped = resp.model_dump(mode="json")
    assert dumped["capacity_units"] is None
    assert dumped["cells"] == []
