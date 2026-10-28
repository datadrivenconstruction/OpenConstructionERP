# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the progress-rigor Pydantic schemas (T3.2).

Pure (pydantic only) so they run on the local 3.11 runner without a DB.
"""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.schedule.progress_schemas import (
    PercentTypeRequest,
    PlannedValueResponse,
    StepCreate,
    TypedProgressRequest,
)


def test_typed_progress_defaults_are_all_optional() -> None:
    req = TypedProgressRequest()
    assert req.percent_complete_type is None
    assert req.percent is None
    assert req.remaining_duration is None


def test_typed_progress_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        TypedProgressRequest(unknown_field=1)


def test_typed_progress_percent_bounds() -> None:
    with pytest.raises(ValidationError):
        TypedProgressRequest(percent=150.0)
    with pytest.raises(ValidationError):
        TypedProgressRequest(percent=-1.0)
    assert TypedProgressRequest(percent=42.5).percent == 42.5


def test_typed_progress_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        TypedProgressRequest(percent_complete_type="bogus")
    assert TypedProgressRequest(percent_complete_type="duration").percent_complete_type == "duration"


def test_remaining_duration_must_be_non_negative() -> None:
    with pytest.raises(ValidationError):
        TypedProgressRequest(remaining_duration=-3)
    assert TypedProgressRequest(remaining_duration=0).remaining_duration == 0


def test_percent_type_request_literal() -> None:
    assert PercentTypeRequest(percent_complete_type="units").percent_complete_type == "units"
    with pytest.raises(ValidationError):
        PercentTypeRequest(percent_complete_type="weighted")


def test_step_create_validation() -> None:
    step = StepCreate(name="Pour slab", weight=Decimal("3"), percent_complete=Decimal("50"))
    assert step.weight == Decimal("3")
    with pytest.raises(ValidationError):
        StepCreate(name="x", percent_complete=Decimal("101"))
    with pytest.raises(ValidationError):
        StepCreate(name="x", weight=Decimal("-1"))
    with pytest.raises(ValidationError):
        StepCreate(name="")  # min_length=1


def test_planned_value_money_serialises_as_string() -> None:
    resp = PlannedValueResponse(
        schedule_id=uuid4(),
        as_of="2026-06-23",
        planned_value=Decimal("1234.56"),
        earned_value=Decimal("1000.00"),
        budget_at_completion=Decimal("5000.00"),
        activity_count=7,
    )
    payload = json.loads(resp.model_dump_json())
    # Money discipline: emitted as strings, not JSON numbers.
    assert payload["planned_value"] == "1234.56"
    assert isinstance(payload["planned_value"], str)
    assert isinstance(payload["earned_value"], str)
    assert isinstance(payload["budget_at_completion"], str)
    assert payload["activity_count"] == 7
