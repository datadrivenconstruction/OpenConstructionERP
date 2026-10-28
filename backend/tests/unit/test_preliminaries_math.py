# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-free unit tests for the preliminaries pricing math.

These pin the pure behaviour the module exists for, with no database, session or
fixtures:

* :func:`app.modules.preliminaries.prelim_math.line_total` - time-related lines
  price as ``rate_per_period * periods`` and fixed lines as ``fixed_amount``,
  quantized to 2dp half-up, with bad / missing input coercing to zero.
* :func:`app.modules.preliminaries.prelim_math.rollup_by_category` - the
  per-category split (time-related vs fixed), the grand total, and the invariant
  that the grand total equals the sum of the category totals.
* the ``normalize_*`` helpers that keep an unknown item type or blank category safe.

The starter checklist is asserted to be non-empty and well formed.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.preliminaries.prelim_math import (
    FIXED,
    TIME_RELATED,
    line_total,
    normalize_category,
    normalize_item_type,
    rollup_by_category,
)
from app.modules.preliminaries.seed import starter_checklist

# ── Banned characters, built from code points (never a literal string) ─────────
# em / en dash, curly quotes and the zero-width family. Assembled from chr() so
# this source file itself stays free of them, matching the house rule.
_BANNED_CODE_POINTS = (
    0x2014,  # em dash
    0x2013,  # en dash
    0x2018,  # left single quotation mark
    0x2019,  # right single quotation mark
    0x201C,  # left double quotation mark
    0x201D,  # right double quotation mark
    0x200B,  # zero width space
    0x200C,  # zero width non-joiner
    0x200D,  # zero width joiner
    0x2060,  # word joiner
    0xFEFF,  # zero width no-break space
)
_BANNED_CHARS = frozenset(chr(cp) for cp in _BANNED_CODE_POINTS)


def _item(**kw: object) -> dict[str, object]:
    """Build a line mapping with the fields line_total / rollup read."""
    base: dict[str, object] = {
        "label": "",
        "category": "general",
        "item_type": TIME_RELATED,
        "rate_per_period": "0",
        "periods": "0",
        "fixed_amount": "0",
    }
    base.update(kw)
    return base


# ── line_total ────────────────────────────────────────────────────────────────


def test_time_related_line_is_rate_times_periods() -> None:
    total = line_total(_item(item_type=TIME_RELATED, rate_per_period="3500.00", periods="12"))
    assert total == Decimal("42000.00")


def test_time_related_line_supports_fractional_periods() -> None:
    total = line_total(_item(item_type=TIME_RELATED, rate_per_period="800", periods="12.5"))
    assert total == Decimal("10000.00")


def test_fixed_line_is_fixed_amount_and_ignores_rate_and_periods() -> None:
    total = line_total(
        _item(item_type=FIXED, fixed_amount="15000.00", rate_per_period="999", periods="99"),
    )
    assert total == Decimal("15000.00")


def test_line_total_is_quantized_two_places_half_up() -> None:
    # 100.005 * 1 rounds half-up to 100.01 (never truncated, never a float).
    total = line_total(_item(item_type=TIME_RELATED, rate_per_period="100.005", periods="1"))
    assert total == Decimal("100.01")


def test_line_total_returns_two_decimal_places_exactly() -> None:
    total = line_total(_item(item_type=FIXED, fixed_amount="500"))
    assert total == Decimal("500.00")
    assert total.as_tuple().exponent == -2


def test_missing_and_bad_numbers_coerce_to_zero() -> None:
    assert line_total(_item(item_type=TIME_RELATED, rate_per_period=None, periods="5")) == Decimal("0.00")
    assert line_total(_item(item_type=TIME_RELATED, rate_per_period="abc", periods="5")) == Decimal("0.00")
    assert line_total(_item(item_type=FIXED, fixed_amount=None)) == Decimal("0.00")


def test_unknown_item_type_prices_as_time_related() -> None:
    # An unknown type must not crash - it falls back to time-related pricing.
    total = line_total(_item(item_type="mystery", rate_per_period="10", periods="3"))
    assert total == Decimal("30.00")


# ── normalize helpers ─────────────────────────────────────────────────────────


def test_normalize_item_type() -> None:
    assert normalize_item_type("fixed") == FIXED
    assert normalize_item_type("FIXED") == FIXED
    assert normalize_item_type("time_related") == TIME_RELATED
    assert normalize_item_type("") == TIME_RELATED
    assert normalize_item_type(None) == TIME_RELATED
    assert normalize_item_type("anything-else") == TIME_RELATED


def test_normalize_category_defaults_when_blank() -> None:
    assert normalize_category("") == "general"
    assert normalize_category(None) == "general"
    assert normalize_category("  site_staff  ") == "site_staff"


# ── rollup_by_category ────────────────────────────────────────────────────────


def test_empty_rollup_is_all_zero() -> None:
    rollup = rollup_by_category([])
    assert rollup.categories == []
    assert rollup.time_related_total == Decimal("0.00")
    assert rollup.fixed_total == Decimal("0.00")
    assert rollup.grand_total == Decimal("0.00")
    assert rollup.item_count == 0


def test_rollup_splits_time_related_and_fixed_and_totals() -> None:
    items = [
        _item(category="site_staff", item_type=TIME_RELATED, rate_per_period="5000", periods="10"),
        _item(category="site_staff", item_type=TIME_RELATED, rate_per_period="4000", periods="10"),
        _item(category="site_establishment", item_type=FIXED, fixed_amount="20000"),
        _item(category="site_establishment", item_type=TIME_RELATED, rate_per_period="1500", periods="10"),
    ]
    rollup = rollup_by_category(items)

    # Categories are sorted by label for stable output.
    assert [c.category for c in rollup.categories] == ["site_establishment", "site_staff"]

    establishment = rollup.categories[0]
    assert establishment.time_related_total == Decimal("15000.00")
    assert establishment.fixed_total == Decimal("20000.00")
    assert establishment.total == Decimal("35000.00")
    assert establishment.item_count == 2

    staff = rollup.categories[1]
    assert staff.time_related_total == Decimal("90000.00")
    assert staff.fixed_total == Decimal("0.00")
    assert staff.total == Decimal("90000.00")
    assert staff.item_count == 2

    assert rollup.time_related_total == Decimal("105000.00")
    assert rollup.fixed_total == Decimal("20000.00")
    assert rollup.grand_total == Decimal("125000.00")
    assert rollup.item_count == 4


def test_grand_total_equals_sum_of_category_totals() -> None:
    items = [
        _item(category="a", item_type=TIME_RELATED, rate_per_period="100.33", periods="3"),
        _item(category="b", item_type=FIXED, fixed_amount="250.50"),
        _item(category="a", item_type=FIXED, fixed_amount="99.99"),
    ]
    rollup = rollup_by_category(items)
    assert sum((c.total for c in rollup.categories), Decimal("0")) == rollup.grand_total
    # And the grand total splits exactly into the two type totals.
    assert rollup.time_related_total + rollup.fixed_total == rollup.grand_total


def test_blank_category_rolls_into_general() -> None:
    rollup = rollup_by_category([_item(category="", item_type=FIXED, fixed_amount="10")])
    assert [c.category for c in rollup.categories] == ["general"]
    assert rollup.grand_total == Decimal("10.00")


# ── starter checklist ─────────────────────────────────────────────────────────


def test_starter_checklist_is_non_empty_and_well_formed() -> None:
    checklist = starter_checklist()
    assert len(checklist) >= 5
    labels = {row["label"] for row in checklist}
    # The labels the spec calls out are present.
    assert any("office" in label.lower() for label in labels)
    assert any("supervision" in label.lower() for label in labels)
    assert any("power" in label.lower() for label in labels)
    assert any("scaffold" in label.lower() for label in labels)
    assert any("clean" in label.lower() for label in labels)
    for row in checklist:
        assert set(row) == {"label", "category", "item_type"}
        assert row["item_type"] in (TIME_RELATED, FIXED)
        # Suggestions carry no amounts - the user enters them.
        assert "rate_per_period" not in row
        assert "fixed_amount" not in row


def test_starter_checklist_labels_avoid_banned_characters() -> None:
    for row in starter_checklist():
        assert not (_BANNED_CHARS & set(row["label"])), f"banned char in {row['label']!r}"
