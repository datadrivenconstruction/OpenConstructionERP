"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the Cost Explorer pricing engine (substitution + price stats).

Like the ranking engine, ``app.modules.cost_explorer.pricing`` is pure (stdlib
only), so it is loaded here directly from its file path - independent of the
FastAPI dependency graph, and identical here and in CI.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

_PRICING_PATH = Path(__file__).resolve().parents[2] / "app" / "modules" / "cost_explorer" / "pricing.py"
_spec = importlib.util.spec_from_file_location("cost_explorer_pricing", _PRICING_PATH)
assert _spec and _spec.loader
pricing = importlib.util.module_from_spec(_spec)
sys.modules["cost_explorer_pricing"] = pricing
_spec.loader.exec_module(pricing)


# ── substitute: incremental delta, never a recompute ────────────────────────


def test_substitute_cheaper_material_lowers_rate() -> None:
    r = pricing.substitute("100", "2", "10", "6")  # line 20 -> 12, delta -8
    assert r.old_rate == Decimal("100")
    assert r.old_line_cost == Decimal("20")
    assert r.new_line_cost == Decimal("12")
    assert r.delta == Decimal("-8")
    assert r.new_rate == Decimal("92")
    assert r.clamped is False


def test_substitute_is_incremental_not_a_recompute() -> None:
    # Only the swapped line moves; the rate is old_rate + delta, so the other
    # (unmodelled) lines that make the authored rate != component sum stay put.
    r = pricing.substitute("100", "1", "0", "50")
    assert r.delta == Decimal("50")
    assert r.new_rate == Decimal("150")


def test_substitute_delta_pct() -> None:
    r = pricing.substitute("200", "4", "10", "5")  # delta -20 => -10% of 200
    assert r.delta == Decimal("-20")
    assert r.delta_pct == -10.0


def test_substitute_clamps_negative_rate_but_keeps_true_delta() -> None:
    r = pricing.substitute("10", "1", "50", "0")  # raw new -40 -> floored to 0
    assert r.clamped is True
    assert r.new_rate == Decimal("0")
    assert r.delta == Decimal("-50")


def test_substitute_zero_rate_does_not_divide() -> None:
    r = pricing.substitute("0", "1", "1", "2")
    assert r.delta_pct == 0.0
    assert r.new_rate == Decimal("1")


def test_substitute_degrades_on_garbage() -> None:
    r = pricing.substitute("abc", "x", None, "")
    assert r.old_rate == Decimal(0)
    assert r.new_rate == Decimal(0)
    assert r.delta == Decimal(0)


def test_substitute_clamps_absurd_catalog_price_without_overflow() -> None:
    # A malformed catalog base_price (huge exponent) parses to a valid Decimal
    # then overflows the multiply; the clamp keeps the engine total-safe rather
    # than raising an uncaught decimal.Overflow that would 500 the endpoint.
    r = pricing.substitute("100", "1", "0", "1E9999999")
    assert r.new_rate.is_finite()
    assert r.delta.is_finite()
    assert r.new_line_cost == pricing.MAX_ABS_PRICE


def test_substitute_clamps_absurd_quantity_and_negative_price() -> None:
    r = pricing.substitute("100", "1E9999999", "0", "5")
    assert r.new_line_cost.is_finite()
    r2 = pricing.substitute("100", "1", "0", "-1E9999999")
    assert r2.delta.is_finite()
    assert r2.new_line_cost == -pricing.MAX_ABS_PRICE


def test_clamp_price_bounds_and_nonfinite() -> None:
    assert pricing._clamp_price(Decimal("1E20")) == pricing.MAX_ABS_PRICE
    assert pricing._clamp_price(Decimal("-1E20")) == -pricing.MAX_ABS_PRICE
    assert pricing._clamp_price(Decimal("NaN")) == Decimal(0)
    assert pricing._clamp_price(Decimal("5")) == Decimal("5")


# ── price_stats: distribution across the rows that carry a price ────────────


def test_price_stats_basic() -> None:
    s = pricing.price_stats(["10", "20", "30", "40", "50"])
    assert s.count == 5
    assert s.min == Decimal("10")
    assert s.max == Decimal("50")
    assert s.median == Decimal("30")
    assert s.mean == Decimal("30")


def test_price_stats_drops_nonpositive_and_blanks() -> None:
    s = pricing.price_stats(["0", "", None, "5", "15"])
    assert s.count == 2
    assert s.min == Decimal("5")
    assert s.max == Decimal("15")
    assert s.median == Decimal("10")


def test_price_stats_percentiles_interpolate() -> None:
    s = pricing.price_stats(["10", "20", "30", "40"])
    assert s.p25 == Decimal("17.5")
    assert s.p75 == Decimal("32.5")


def test_price_stats_empty() -> None:
    s = pricing.price_stats([])
    assert s.count == 0
    assert s.min == Decimal(0)
    assert s.mean == Decimal(0)


def test_price_stats_single_value() -> None:
    s = pricing.price_stats(["42"])
    assert s.count == 1
    assert s.median == Decimal("42")
    assert s.p25 == Decimal("42")


def test_price_stats_mean_is_quantized_to_two_dp() -> None:
    # Regression: a repeating mean must render as a short money value, not a
    # 28-significant-digit Decimal.
    s = pricing.price_stats(["10", "20", "40"])
    assert s.mean == Decimal("23.33")
    assert str(s.mean) == "23.33"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"\n{len(fns)} pricing tests passed")
