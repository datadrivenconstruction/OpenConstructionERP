# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure CVR / cashflow aggregation math (DB-free, float-free).

Kept out of the service so the unit suite can assert the margin roll-up and the
cumulative cashflow S-curve without a database. Every function takes plain
attribute-bearing objects (ORM rows or ``SimpleNamespace`` in tests) and returns
2dp-quantized ``decimal.Decimal`` money. The schema layer serialises those
Decimals to strings on the wire (money is never a float), so the arithmetic here
stays in pure Decimal and never formats a string itself.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.modules.cvr.validators import forecast_flags

_CENTS = Decimal("0.01")


def to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    """Coerce *value* to Decimal, returning *default* on any bad input."""
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def q2(value: Decimal) -> Decimal:
    """Quantize a money Decimal to 2 places, half-up (the accounting default)."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Percentage ``numerator / denominator * 100`` (0 when denominator <= 0)."""
    if denominator <= 0:
        return Decimal("0")
    return numerator / denominator * Decimal("100")


def summarise_lines(lines: list[Any]) -> dict[str, Any]:
    """Roll a report's lines up into total cost/value/forecast and margins.

    Returns a dict of 2dp Decimal figures plus a ``warnings`` list that carries
    the per-line advisory forecast flags (prefixed with the cost code).

    ``margin_to_date  = value_to_date - cost_to_date``
    ``forecast_margin = forecast_value - forecast_cost``
    Percentages are margin over the corresponding value base (0 when the base is
    non-positive, so a value-less report never divides by zero).
    """
    total_cost = Decimal("0")
    total_value = Decimal("0")
    total_accruals = Decimal("0")
    total_fcost = Decimal("0")
    total_fvalue = Decimal("0")
    total_budget = Decimal("0")
    total_committed = Decimal("0")
    warnings: list[str] = []

    for line in lines:
        cost = to_decimal(getattr(line, "cost_to_date", 0))
        value = to_decimal(getattr(line, "value_to_date", 0))
        accruals = to_decimal(getattr(line, "accruals", 0))
        fcost = to_decimal(getattr(line, "forecast_cost", 0))
        fvalue = to_decimal(getattr(line, "forecast_value", 0))

        total_cost += cost
        total_value += value
        total_accruals += accruals
        total_fcost += fcost
        total_fvalue += fvalue
        total_budget += to_decimal(getattr(line, "budget_cost", 0) or 0)
        total_committed += to_decimal(getattr(line, "committed_cost", 0) or 0)

        code = str(getattr(line, "cost_code", "") or "")
        for flag in forecast_flags(
            cost_to_date=cost,
            value_to_date=value,
            forecast_cost=fcost,
            forecast_value=fvalue,
        ):
            warnings.append(f"{code}:{flag}" if code else flag)

    margin = total_value - total_cost
    forecast_margin = total_fvalue - total_fcost

    return {
        "total_cost_to_date": q2(total_cost),
        "total_value_to_date": q2(total_value),
        "total_budget_cost": q2(total_budget),
        "total_committed_cost": q2(total_committed),
        "total_accruals": q2(total_accruals),
        "total_forecast_cost": q2(total_fcost),
        "total_forecast_value": q2(total_fvalue),
        "margin_to_date": q2(margin),
        "forecast_margin": q2(forecast_margin),
        "margin_to_date_pct": q2(_pct(margin, total_value)),
        "forecast_margin_pct": q2(_pct(forecast_margin, total_fvalue)),
        "warnings": warnings,
    }


def cumulative_series(points: list[Any]) -> dict[str, Any]:
    """Turn ordered cashflow points into a cumulative S-curve.

    *points* must already be sorted by period ascending. Produces per-period
    and running-cumulative cash-in / cash-out / net, plus the totals and the
    closing net position. Every money value is a 2dp Decimal.
    """
    entries: list[dict[str, Any]] = []
    cum_in = Decimal("0")
    cum_out = Decimal("0")

    for point in points:
        cash_in = to_decimal(getattr(point, "cash_in", 0))
        cash_out = to_decimal(getattr(point, "cash_out", 0))
        cum_in += cash_in
        cum_out += cash_out
        entries.append(
            {
                "period": str(getattr(point, "period", "") or ""),
                "cash_in": q2(cash_in),
                "cash_out": q2(cash_out),
                "net": q2(cash_in - cash_out),
                "cumulative_cash_in": q2(cum_in),
                "cumulative_cash_out": q2(cum_out),
                "cumulative_net": q2(cum_in - cum_out),
            }
        )

    return {
        "points": entries,
        "total_cash_in": q2(cum_in),
        "total_cash_out": q2(cum_out),
        "net_position": q2(cum_in - cum_out),
    }


def net_of_retention(gross_value: Any, retention: Any) -> Decimal:
    """Net payable = gross - retention, clamped at zero and quantized to 2dp."""
    net = to_decimal(gross_value) - to_decimal(retention)
    if net < 0:
        net = Decimal("0")
    return q2(net)
