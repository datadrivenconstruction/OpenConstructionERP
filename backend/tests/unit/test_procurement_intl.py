"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure-function tests for the international procurement helpers (``intl.py``).

These pin the database-free, framework-free helpers that keep procurement money
and delivery math correct and clear for users worldwide. No DB, no fixtures, no
event loop, so they run locally and in CI regardless of the PostgreSQL harness.

Covered:
    * money math      - line_total, subtotal, price_breakdown, tax_and_gross
    * Decimal safety  - exactness, garbage / NaN / negative rejection
    * currency safety - ensure_single_currency never blends codes
    * delivery timing - expected_delivery_date (order date plus lead time)
    * coverage        - delivery_coverage with a division-by-zero guard
    * plain language  - explain() and the status-label describers
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.procurement.intl import (
    CONCEPTS,
    delivery_coverage,
    describe_delivery_status,
    describe_po_status,
    describe_requisition_status,
    ensure_single_currency,
    expected_delivery_date,
    explain,
    format_quantity,
    line_total,
    normalize_currency,
    price_breakdown,
    quantize_money,
    subtotal,
    subtotal_from_lines,
    tax_and_gross,
    to_decimal,
)

D = Decimal


# ── to_decimal (strict parse) ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("100", D("100")),
        ("100.50", D("100.50")),
        (Decimal("3.14"), D("3.14")),
        (5, D("5")),
        ("  42 ", D("42")),
    ],
)
def test_to_decimal_parses_valid(value: object, expected: Decimal) -> None:
    assert to_decimal(value) == expected


@pytest.mark.parametrize("bad", [None, "", "not-a-number", "NaN", "Infinity", "-inf", []])
def test_to_decimal_rejects_garbage_and_nonfinite(bad: object) -> None:
    with pytest.raises(ValueError, match="amount"):
        to_decimal(bad, "amount")


# ── line_total ────────────────────────────────────────────────────────────


def test_line_total_is_decimal_exact() -> None:
    # 0.1 * 3 must be exactly 0.3, no float drift.
    assert line_total("0.1", "3") == D("0.3")


def test_line_total_multiplies() -> None:
    assert line_total("12", "10.50") == D("126.00")


def test_line_total_zero_allowed_by_default() -> None:
    assert line_total("0", "10") == D("0")


def test_line_total_zero_rejected_when_disallowed() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        line_total("0", "10", allow_zero=False)


@pytest.mark.parametrize(
    ("qty", "rate"),
    [("-1", "10"), ("5", "-2")],
)
def test_line_total_rejects_negative(qty: str, rate: str) -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        line_total(qty, rate)


# ── subtotal ──────────────────────────────────────────────────────────────


def test_subtotal_sums_lines() -> None:
    assert subtotal(["100", "50.50", "0.50"]) == D("151.00")


def test_subtotal_empty_list_is_zero() -> None:
    assert subtotal([]) == D("0")


def test_subtotal_rejects_negative_entry() -> None:
    with pytest.raises(ValueError, match="line_totals"):
        subtotal(["100", "-1"])


def test_subtotal_from_lines_computes_each_line() -> None:
    assert subtotal_from_lines([("2", "10"), ("3", "5")]) == D("35")


def test_subtotal_from_lines_empty_is_zero() -> None:
    assert subtotal_from_lines([]) == D("0")


# ── price_breakdown ───────────────────────────────────────────────────────


def test_price_breakdown_no_rates_gross_equals_subtotal() -> None:
    out = price_breakdown("1000")
    assert out["net"] == "1000.00"
    assert out["tax_amount"] == "0.00"
    assert out["gross"] == "1000.00"


def test_price_breakdown_applies_tax() -> None:
    out = price_breakdown("1000", tax_rate_percent="19")
    assert out["net"] == "1000.00"
    assert out["tax_amount"] == "190.00"
    assert out["gross"] == "1190.00"


def test_price_breakdown_applies_discount_before_tax() -> None:
    # 1000 less 10 percent = 900 net, then 20 percent tax = 180, gross 1080.
    out = price_breakdown("1000", tax_rate_percent="20", discount_percent="10")
    assert out["discount_amount"] == "100.00"
    assert out["net"] == "900.00"
    assert out["tax_amount"] == "180.00"
    assert out["gross"] == "1080.00"


def test_price_breakdown_arbitrary_tax_rate_no_hardcoded_default() -> None:
    # A caller in any country supplies their own rate; nothing is assumed.
    out = price_breakdown("200", tax_rate_percent="7.5")
    assert out["tax_amount"] == "15.00"
    assert out["gross"] == "215.00"


def test_price_breakdown_rejects_discount_over_100() -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        price_breakdown("1000", discount_percent="150")


def test_price_breakdown_rejects_negative_tax() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        price_breakdown("1000", tax_rate_percent="-1")


def test_price_breakdown_custom_quantum_for_zero_decimal_currency() -> None:
    # A zero-decimal currency (whole units) rounds to integers.
    out = price_breakdown("1000", tax_rate_percent="8", quantum=Decimal("1"))
    assert out["tax_amount"] == "80"
    assert out["gross"] == "1080"


# ── tax_and_gross ─────────────────────────────────────────────────────────


def test_tax_and_gross_default_rate_is_zero() -> None:
    out = tax_and_gross("500")
    assert out["tax_amount"] == "0.00"
    assert out["gross"] == "500.00"


def test_tax_and_gross_applies_rate() -> None:
    out = tax_and_gross("500", "10")
    assert out["tax_amount"] == "50.00"
    assert out["gross"] == "550.00"


# ── quantize_money ────────────────────────────────────────────────────────


def test_quantize_money_half_up() -> None:
    assert quantize_money(Decimal("1.005")) == Decimal("1.01")


# ── currency safety ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [("eur", "EUR"), ("  usd ", "USD"), (None, ""), ("", "")],
)
def test_normalize_currency(value: str | None, expected: str) -> None:
    assert normalize_currency(value) == expected


def test_ensure_single_currency_returns_the_shared_code() -> None:
    assert ensure_single_currency(["EUR", "eur", " EUR "]) == "EUR"


def test_ensure_single_currency_ignores_unstated() -> None:
    assert ensure_single_currency(["USD", "", None]) == "USD"


def test_ensure_single_currency_empty_is_unstated() -> None:
    assert ensure_single_currency([None, "", ""]) == ""


def test_ensure_single_currency_rejects_a_mix() -> None:
    with pytest.raises(ValueError, match="different currencies"):
        ensure_single_currency(["EUR", "USD"])


# ── format_quantity (units always explicit) ───────────────────────────────


def test_format_quantity_with_unit() -> None:
    assert format_quantity("100", "m3") == "100 m3"


def test_format_quantity_strips_trailing_zeros() -> None:
    assert format_quantity("100.50", "kg") == "100.5 kg"


def test_format_quantity_missing_unit_keeps_number() -> None:
    assert format_quantity("42", None) == "42"


# ── expected_delivery_date (order date plus lead time) ─────────────────────


def test_expected_delivery_date_adds_lead_time() -> None:
    assert expected_delivery_date("2026-05-10", 10) == "2026-05-20"


def test_expected_delivery_date_crosses_month_boundary() -> None:
    assert expected_delivery_date("2026-04-25", 10) == "2026-05-05"


def test_expected_delivery_date_zero_lead_is_same_day() -> None:
    assert expected_delivery_date("2026-05-10", 0) == "2026-05-10"


@pytest.mark.parametrize("order_date", [None, "", "not-a-date", "2026/05/10"])
def test_expected_delivery_date_none_on_bad_date(order_date: str | None) -> None:
    assert expected_delivery_date(order_date, 10) is None


def test_expected_delivery_date_rejects_negative_lead() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        expected_delivery_date("2026-05-10", -5)


def test_expected_delivery_date_rejects_fractional_lead() -> None:
    with pytest.raises(ValueError, match="whole number"):
        expected_delivery_date("2026-05-10", "2.5")


# ── delivery_coverage (division-by-zero guarded) ──────────────────────────


def test_delivery_coverage_partial() -> None:
    out = delivery_coverage("60", "100")
    assert out["coverage"] == "0.6000"
    assert out["coverage_percent"] == "60.00"
    assert out["outstanding"] == "40"
    assert out["over_delivered"] == "0"
    assert out["is_complete"] == "false"


def test_delivery_coverage_complete() -> None:
    out = delivery_coverage("100", "100")
    assert out["coverage"] == "1.0000"
    assert out["outstanding"] == "0"
    assert out["is_complete"] == "true"


def test_delivery_coverage_over_delivered_caps_at_one() -> None:
    out = delivery_coverage("120", "100")
    assert out["coverage"] == "1.0000"
    assert out["over_delivered"] == "20"
    assert out["outstanding"] == "0"
    assert out["is_complete"] == "true"


def test_delivery_coverage_zero_ordered_is_guarded() -> None:
    # Nothing ordered: no division by zero, coverage defined as fully met.
    out = delivery_coverage("0", "0")
    assert out["coverage"] == "1.0000"
    assert out["outstanding"] == "0"
    assert out["is_complete"] == "true"


def test_delivery_coverage_nothing_delivered() -> None:
    out = delivery_coverage("0", "100")
    assert out["coverage"] == "0.0000"
    assert out["outstanding"] == "100"
    assert out["is_complete"] == "false"


def test_delivery_coverage_rejects_negative() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        delivery_coverage("-1", "100")


# ── plain-language explainers ─────────────────────────────────────────────


@pytest.mark.parametrize("concept", sorted(CONCEPTS))
def test_explain_returns_nonempty_for_every_concept(concept: str) -> None:
    text = explain(concept)
    assert isinstance(text, str)
    assert text.strip()


def test_explain_unknown_concept_raises() -> None:
    with pytest.raises(ValueError, match="Unknown procurement concept"):
        explain("no-such-concept")


def test_describe_po_status_known() -> None:
    assert describe_po_status("issued") == "Issued to the supplier"


def test_describe_po_status_unknown_is_humanised_not_blank() -> None:
    assert describe_po_status("on_hold_special") == "On hold special"


def test_describe_po_status_empty_is_unknown() -> None:
    assert describe_po_status(None) == "Unknown"


def test_describe_delivery_status_known() -> None:
    assert describe_delivery_status("confirmed") == "Delivery confirmed and counted"


def test_describe_requisition_status_known() -> None:
    assert describe_requisition_status("consumed") == "Used up on the works"
