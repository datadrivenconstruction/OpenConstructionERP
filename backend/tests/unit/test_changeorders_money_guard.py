# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Money-field hardening for change orders (audit wave-2).

A change order's monetary inputs must reject non-finite (NaN / Infinity) and
absurd-magnitude values:

* a stored ``NaN`` poisons the project-wide cost rollup - the summary sums every
  CO's ``cost_impact`` and ``quantize(NaN)`` stays ``NaN``, so one bad CO makes
  the whole project's total_cost_impact / total_approved_amount serialize as
  ``"NaN"``;
* a huge-but-finite value such as ``1e1000`` breaks the service's ``quantize()``
  with an uncaught ``InvalidOperation`` (a 500 on otherwise-"valid" input).

These are pure Pydantic-schema tests - no database needed.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.modules.changeorders.schemas import (
    ChangeOrderCreate,
    ChangeOrderItemCreate,
    ChangeOrderUpdate,
    SimulateImpactRequest,
)

_PID = uuid.uuid4()

_BAD_SIGNED = ["NaN", "nan", "Infinity", "-Infinity", "inf", "1e1000", "-1e1000"]


@pytest.mark.parametrize("bad", _BAD_SIGNED)
def test_create_cost_impact_rejects_non_finite_and_overflow(bad: str) -> None:
    with pytest.raises(ValidationError):
        ChangeOrderCreate(project_id=_PID, title="x", cost_impact=bad)


@pytest.mark.parametrize("ok", ["0", "1250.50", "-500.25", "1000000000"])
def test_create_cost_impact_accepts_valid_signed_decimals(ok: str) -> None:
    # cost_impact can be a credit (negative), so signed decimals are valid.
    assert ChangeOrderCreate(project_id=_PID, title="x", cost_impact=ok).cost_impact == ok


def test_create_cost_impact_is_optional() -> None:
    assert ChangeOrderCreate(project_id=_PID, title="x").cost_impact is None


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "1e1000"])
def test_update_cost_impact_rejects_non_finite_and_overflow(bad: str) -> None:
    with pytest.raises(ValidationError):
        ChangeOrderUpdate(cost_impact=bad)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "1e1000", "-5"])
def test_item_quantities_reject_bad_values(bad: str) -> None:
    # Item quantities/rates are non-negative AND must be finite + in range.
    with pytest.raises(ValidationError):
        ChangeOrderItemCreate(description="x", new_quantity=bad)


def test_item_accepts_valid_quantities() -> None:
    item = ChangeOrderItemCreate(description="x", new_quantity="5", new_rate="12.50")
    assert item.new_quantity == "5"


@pytest.mark.parametrize("bad", ["NaN", "1e1000"])
def test_simulate_request_rejects_bad_cost_impact(bad: str) -> None:
    with pytest.raises(ValidationError):
        SimulateImpactRequest(cost_impact=bad)
