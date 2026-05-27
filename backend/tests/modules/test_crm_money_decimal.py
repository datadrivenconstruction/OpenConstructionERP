"""CRM money/Decimal precision unit tests (R7 audit).

Ensures the pure aggregation helpers + weighted-value computation never
silently coerce to float — a single ``Decimal × float`` ladders into
sub-cent drift across an entire forecast.

Also locks in the model-level guarantee: every money column on Opportunity
/ Account / Forecast is declared ``Numeric`` (not ``Float``).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import Float as SAFloat
from sqlalchemy import Numeric as SANumeric

from app.modules.crm.models import (
    Forecast,
    Opportunity,
)
from app.modules.crm.service import (
    _q2,
    compute_pipeline_metrics,
    compute_stage_weighted_forecast,
    compute_weighted_value,
    convert_opportunity_to_project_payload,
)


def _opp(
    *,
    estimated_value: str = "0",
    weighted_value: str | None = None,
    status: str = "open",
    probability_percent: int = 0,
    stage_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        estimated_value=Decimal(estimated_value),
        weighted_value=Decimal(weighted_value) if weighted_value else None,
        status=status,
        probability_percent=probability_percent,
        stage_id=stage_id or uuid.uuid4(),
        owner_user_id=None,
        won_at=None,
        lost_at=None,
        lost_reason_code=None,
        currency="EUR",
    )


# ── No Float columns on money tables ──────────────────────────────────────


@pytest.mark.parametrize(
    ("model", "column_name"),
    [
        (Opportunity, "estimated_value"),
        (Opportunity, "weighted_value"),
        (Forecast, "pipeline_value"),
        (Forecast, "weighted_value"),
        (Forecast, "won_value"),
        (Forecast, "committed_value"),
    ],
)
def test_money_column_is_numeric_not_float(model, column_name):
    col = model.__table__.columns[column_name]
    assert isinstance(col.type, SANumeric), (
        f"{model.__name__}.{column_name} must be Numeric, got {type(col.type).__name__}"
    )
    assert not isinstance(col.type, SAFloat), f"{model.__name__}.{column_name} must NOT be Float"


# ── Pure helpers ─────────────────────────────────────────────────────────


def test_q2_quantises_to_two_decimal_places_half_up():
    assert _q2(Decimal("1.005")) == Decimal("1.01")
    assert _q2(Decimal("1.004")) == Decimal("1.00")
    assert _q2(Decimal("0")) == Decimal("0.00")


def test_compute_weighted_value_clamps_probability():
    # value=100, prob clamped to 100 → weighted=100
    assert compute_weighted_value(Decimal("100"), 200) == Decimal("100.00")
    assert compute_weighted_value(Decimal("100"), -50) == Decimal("0.00")


def test_compute_weighted_value_returns_decimal():
    """Float input must not poison the output type."""
    result = compute_weighted_value(123.45, 50)
    assert isinstance(result, Decimal)
    # 123.45 × 0.5 = 61.725 → rounds half-up to 61.73
    # (the input float carries inexactness so we tolerate ±1 cent)
    assert Decimal("61.72") <= result <= Decimal("61.73")


def test_compute_weighted_value_exact_decimal_round_trip():
    assert compute_weighted_value(Decimal("250.00"), 40) == Decimal("100.00")
    assert compute_weighted_value(Decimal("999.99"), 50) == Decimal("500.00")


# ── Aggregation correctness ──────────────────────────────────────────────


def test_pipeline_metrics_sums_decimal_exactly():
    """Three open opps at $0.10 each → exact $0.30, no float drift."""
    opps = [
        _opp(estimated_value="0.10", probability_percent=100, status="open"),
        _opp(estimated_value="0.10", probability_percent=100, status="open"),
        _opp(estimated_value="0.10", probability_percent=100, status="open"),
    ]
    metrics = compute_pipeline_metrics(opps)
    assert metrics["open_count"] == 3
    assert metrics["total_value"] == Decimal("0.30")


def test_pipeline_metrics_won_lost_excluded_from_open_totals():
    opps = [
        _opp(estimated_value="100.00", status="open"),
        _opp(estimated_value="500.00", status="won"),
        _opp(estimated_value="200.00", status="lost"),
    ]
    metrics = compute_pipeline_metrics(opps)
    assert metrics["open_count"] == 1
    assert metrics["total_value"] == Decimal("100.00")


def test_stage_weighted_forecast_returns_decimal_only():
    stage_id = uuid.uuid4()
    stage = SimpleNamespace(
        id=stage_id,
        name="Proposal",
        code="proposal",
        default_probability_percent=50,
    )
    opps = [
        _opp(
            estimated_value="1000.00",
            weighted_value="500.00",
            probability_percent=50,
            status="open",
            stage_id=stage_id,
        ),
        _opp(
            estimated_value="2000.00",
            weighted_value="1000.00",
            probability_percent=50,
            status="open",
            stage_id=stage_id,
        ),
    ]
    forecast = compute_stage_weighted_forecast(opps, {stage_id: stage})
    sid = str(stage_id)
    bucket = forecast["by_stage"][sid]
    assert isinstance(bucket["total"], Decimal)
    assert isinstance(bucket["weighted"], Decimal)
    assert bucket["total"] == Decimal("3000.00")
    assert bucket["weighted"] == Decimal("1500.00")
    assert forecast["grand_total"] == Decimal("3000.00")


# ── Project-payload serialisation must keep value as a string ────────────


def test_convert_opportunity_emits_string_money_not_float():
    """v4.3.0 fix: ``estimated_value`` is serialised as ``str(Decimal)`` so the
    downstream Projects subscriber casts back to Decimal without the
    float→binary→Decimal lossy hop.
    """
    opp = _opp(estimated_value="10000000.01")
    opp.title = "Big deal"
    opp.description = ""
    opp.account_id = uuid.uuid4()
    opp.owner_user_id = uuid.uuid4()
    opp.primary_contact_id = None
    opp.project_id = None
    payload = convert_opportunity_to_project_payload(opp)
    assert payload["estimated_value"] == "10000000.01"
    # Critical: must NOT be a float (which would drop the trailing cent).
    assert isinstance(payload["estimated_value"], str)
