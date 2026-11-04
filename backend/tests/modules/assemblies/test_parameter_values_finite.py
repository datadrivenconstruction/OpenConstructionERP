"""Input-parameter overrides must be finite: NaN / Infinity never reach the engine."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.assemblies.parametric import _to_decimal, resolve_parameters
from app.modules.assemblies.schemas import ApplyToBOQRequest, ExpandPreviewRequest


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), 1e300])
def test_apply_and_expand_reject_non_finite_overrides(bad: float) -> None:
    with pytest.raises(ValidationError):
        ApplyToBOQRequest(boq_id=uuid.uuid4(), quantity=1, parameter_values={"w": bad})
    with pytest.raises(ValidationError):
        ExpandPreviewRequest(parameter_values={"w": bad})


def test_finite_overrides_accepted() -> None:
    req = ExpandPreviewRequest(parameter_values={"w": 2.5})
    assert req.parameter_values == {"w": 2.5}


@pytest.mark.parametrize("raw", ["nan", "NaN", "Infinity", "-inf"])
def test_non_finite_override_falls_back_to_stored_default(raw: str) -> None:
    assert _to_decimal(raw) is None
    scope, errors = resolve_parameters([{"name": "w", "kind": "input", "value": "3"}], {"w": raw})
    assert scope["w"] == Decimal(3)
    assert not errors
