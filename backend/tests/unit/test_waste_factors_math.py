"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure net-to-gross waste-factor engine.

Stdlib + pytest only: imports just the pure engine and the import-safe default
factor data, so it runs on the local test runner without a database or
SQLAlchemy on the path. Quantities are exercised with Decimal literals and
asserted for 4 dp, half-up rounding, and float-free exactness.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.waste_factors.seed import DEFAULT_WASTE_FACTORS
from app.modules.waste_factors.waste_math import (
    DEFAULT_FACTOR,
    FACTOR_MIN,
    QTY_PLACES,
    GrossLine,
    NetLine,
    apply,
    batch_net_to_gross,
    normalize_category,
    quantize_qty,
    resolve_factor,
)

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------


def test_constants() -> None:
    assert Decimal("0.0001") == QTY_PLACES
    assert Decimal("1") == FACTOR_MIN
    assert Decimal("1.0") == DEFAULT_FACTOR


# ---------------------------------------------------------------------------
# quantize_qty
# ---------------------------------------------------------------------------


def test_quantize_qty_half_up() -> None:
    assert quantize_qty(Decimal("1.00005")) == Decimal("1.0001")
    assert quantize_qty(Decimal("1.00004")) == Decimal("1.0000")


def test_quantize_qty_is_four_places() -> None:
    assert quantize_qty(Decimal("2")).as_tuple().exponent == -4


# ---------------------------------------------------------------------------
# normalize_category
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Rebar ", "rebar"),
        ("STRUCTURAL Steel", "structural steel"),
        ("concrete", "concrete"),
    ],
)
def test_normalize_category(raw: str, expected: str) -> None:
    assert normalize_category(raw) == expected


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("net", "factor", "expected"),
    [
        (Decimal("100"), Decimal("1.10"), Decimal("110.0000")),
        (Decimal("12.5"), Decimal("1.03"), Decimal("12.8750")),
        (Decimal("340"), Decimal("1"), Decimal("340.0000")),
        (Decimal("0"), Decimal("1.5"), Decimal("0.0000")),
        (Decimal("200"), Decimal("1.03"), Decimal("206.0000")),
    ],
)
def test_apply(net: Decimal, factor: Decimal, expected: Decimal) -> None:
    assert apply(net, factor) == expected


def test_apply_result_is_four_places() -> None:
    assert apply(Decimal("1"), Decimal("1.1")).as_tuple().exponent == -4


def test_apply_rounds_half_up() -> None:
    # 5th decimal place is a 5 -> rounds the 4th place away from zero.
    assert apply(Decimal("1.00005"), Decimal("1")) == Decimal("1.0001")


def test_apply_no_float_drift() -> None:
    # 0.1 summed three times drifts in float; Decimal stays exact.
    total = sum((apply(Decimal("0.1"), Decimal("1")) for _ in range(3)), Decimal("0"))
    assert total == Decimal("0.3000")


# ---------------------------------------------------------------------------
# resolve_factor
# ---------------------------------------------------------------------------


def test_resolve_factor_matches_case_insensitively() -> None:
    factors = {"Concrete": Decimal("1.03"), "rebar": Decimal("1.10")}
    assert resolve_factor("concrete", factors) == (Decimal("1.03"), True)
    assert resolve_factor("  REBAR ", factors) == (Decimal("1.10"), True)


def test_resolve_factor_default_when_unmatched() -> None:
    assert resolve_factor("granite", {}) == (Decimal("1.0"), False)
    assert resolve_factor("granite", {}, default=Decimal("1.2")) == (Decimal("1.2"), False)


# ---------------------------------------------------------------------------
# batch_net_to_gross
# ---------------------------------------------------------------------------


def test_batch_matches_and_falls_back() -> None:
    factors = {"concrete": Decimal("1.03"), "rebar": Decimal("1.10")}
    lines = [
        NetLine("concrete", Decimal("100")),
        NetLine("rebar", Decimal("340")),
        NetLine("unknown", Decimal("50")),
    ]
    out = batch_net_to_gross(lines, factors)
    assert [(g.category, g.gross_qty, g.matched) for g in out] == [
        ("concrete", Decimal("103.0000"), True),
        ("rebar", Decimal("374.0000"), True),
        ("unknown", Decimal("50.0000"), False),
    ]
    # The unmatched line passes through with the default multiplier.
    assert out[2].factor == Decimal("1.0")


def test_batch_preserves_order_for_duplicate_categories() -> None:
    lines = [
        NetLine("concrete", Decimal("10")),
        NetLine("concrete", Decimal("20")),
    ]
    out = batch_net_to_gross(lines, {"concrete": Decimal("1.03")})
    assert [g.net_qty for g in out] == [Decimal("10.0000"), Decimal("20.0000")]
    assert [g.gross_qty for g in out] == [Decimal("10.3000"), Decimal("20.6000")]


def test_batch_quantizes_net_qty_to_four_places() -> None:
    out = batch_net_to_gross([NetLine("c", Decimal("1.5"))], {})
    assert out[0].net_qty == Decimal("1.5000")


def test_batch_empty_input() -> None:
    assert batch_net_to_gross([], {"concrete": Decimal("1.03")}) == []


def test_batch_lines_are_frozen() -> None:
    out = batch_net_to_gross([NetLine("x", Decimal("1"))], {})
    assert isinstance(out[0], GrossLine)
    with pytest.raises(AttributeError):
        out[0].gross_qty = Decimal("0")  # type: ignore[misc]


def test_batch_is_deterministic() -> None:
    factors = {"concrete": Decimal("1.03")}
    lines = [NetLine("concrete", Decimal("100")), NetLine("steel", Decimal("5"))]
    assert batch_net_to_gross(lines, factors) == batch_net_to_gross(lines, factors)


# ---------------------------------------------------------------------------
# default library data (import-safe, no DB)
# ---------------------------------------------------------------------------


def test_default_factors_all_at_least_one() -> None:
    for row in DEFAULT_WASTE_FACTORS:
        assert Decimal(str(row["factor"])) >= FACTOR_MIN


def test_default_factors_cover_core_categories() -> None:
    cats = {normalize_category(str(r["category"])) for r in DEFAULT_WASTE_FACTORS}
    assert {"concrete", "rebar", "tiling", "blockwork"} <= cats


def test_default_factors_categories_are_unique() -> None:
    cats = [normalize_category(str(r["category"])) for r in DEFAULT_WASTE_FACTORS]
    assert len(cats) == len(set(cats))


def test_default_factors_apply_cleanly() -> None:
    factors = {str(r["category"]): Decimal(str(r["factor"])) for r in DEFAULT_WASTE_FACTORS}
    out = batch_net_to_gross([NetLine("concrete", Decimal("200"))], factors)
    assert out[0].matched is True
    assert out[0].gross_qty == Decimal("206.0000")  # 200 * 1.03
