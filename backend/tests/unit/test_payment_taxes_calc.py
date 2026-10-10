# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The shared payment tax calculation.

Every rate, fraction, threshold and cap in this file is synthetic and belongs
to the invented country ``XX``. A statutory value never enters a test: that is
how a number nobody verified ends up looking verified.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.currency_registry import money_quantum
from app.core.payment_taxes import (
    Choice,
    Figure,
    Override,
    PaymentTaxInput,
    PaymentTaxResult,
    RateRow,
    allocate,
    compute_payment_taxes,
)
from app.core.payment_taxes.calc import FIGURE_KINDS, REASON_KEYS

D = Decimal
ON = date(2024, 6, 1)
UNSET = Choice("unset")
NA = Choice("not_applicable", reason="Buyer is outside the withholding regime")


def _row(**changes: object) -> RateRow:
    base = RateRow(
        country_code="XX",
        kind="vat_withholding",
        code="W1",
        labels={"tr": "Deneme işi", "en": "Test work"},
        base="vat",
        rate_pct=None,
        numerator=4,
        denominator=10,
        threshold_amount=None,
        threshold_currency="",
        threshold_scope="",
        threshold_measure="",
        cap_amount=None,
        effective_from=date(2020, 1, 1),
        effective_to=None,
        legal_reference="Synthetic VAT Act art. 9",
        source_url="https://example.invalid/vat",
        read_date="2026-01-01",
        review_status="confirmed",
    )
    return replace(base, **changes)


def _pct_row(kind: str, code: str, rate: str, **changes: object) -> RateRow:
    defaults: dict[str, object] = {
        "kind": kind,
        "code": code,
        "base": "net",
        "rate_pct": D(rate),
        "numerator": None,
        "denominator": None,
        "legal_reference": f"Synthetic {kind} rule",
    }
    defaults.update(changes)
    return _row(**defaults)


ROWS: tuple[RateRow, ...] = (
    _row(),
    _pct_row("income_withholding", "I1", "5"),
    _pct_row("stamp_duty", "S1", "0.948"),
)


def _inp(net: str | Decimal = "100000.00", **changes: object) -> PaymentTaxInput:
    base = PaymentTaxInput(
        country_code="XX",
        currency="TRY",
        on=ON,
        net_amount=D(net),
        vat_rate_pct=D("20"),
        vat_withholding=Choice("selected", "W1"),
        income_withholding=Choice("selected", "I1"),
        stamp_duty=Choice("selected", "S1"),
    )
    return replace(base, **changes)


def _assert_shape(result: PaymentTaxResult) -> None:
    """Invariants every result must satisfy, whatever the inputs were."""
    assert tuple(figure.kind for figure in result.figures()) == FIGURE_KINDS
    for figure in result.figures():
        assert figure.reason_key in REASON_KEYS, figure
        assert figure.status in ("value", "not_applicable", "held")
        # An amount exists exactly when the figure is a value. Held is not zero.
        assert (figure.amount is not None) == (figure.status == "value"), figure
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in figure.reason_params.items())
        if figure.status == "held":
            assert figure.reason_key != ""
    assert result.complete == all(figure.status != "held" for figure in result.figures())


# ── The three VAT figures ────────────────────────────────────────────────────


def test_the_three_vat_figures_and_the_two_deductions() -> None:
    result = compute_payment_taxes(_inp(), ROWS)

    _assert_shape(result)
    assert result.complete
    assert result.vat_computed.amount == D("20000.00")
    assert result.vat_withheld.amount == D("8000.00")
    assert result.vat_payable.amount == D("12000.00")
    assert result.income_withheld.amount == D("5000.00")
    assert result.stamp_duty.amount == D("948.00")
    assert all(figure.reason_key == "" and not figure.overridden for figure in result.figures())


def test_each_figure_shows_its_basis() -> None:
    row = _row(review_status="unconfirmed", effective_from=date(2021, 3, 1))
    result = compute_payment_taxes(_inp(), (row, *ROWS[1:]))

    vat = result.vat_computed
    assert (vat.base, vat.rate_pct, vat.code, vat.legal_reference) == (D("100000.00"), D("20"), "", "")
    assert (vat.numerator, vat.denominator, vat.review_status, vat.effective_from) == (None, None, "", None)

    withheld = result.vat_withheld
    assert withheld.base == D("20000.00")
    assert (withheld.numerator, withheld.denominator, withheld.rate_pct) == (4, 10, None)
    assert (withheld.code, withheld.legal_reference) == ("W1", "Synthetic VAT Act art. 9")
    assert withheld.effective_from == date(2021, 3, 1)
    # An unconfirmed row still computes. The doubt travels with the number.
    assert withheld.status == "value"
    assert withheld.review_status == "unconfirmed"

    payable = result.vat_payable
    assert (payable.base, payable.code, payable.review_status) == (D("20000.00"), "W1", "unconfirmed")

    income = result.income_withheld
    assert (income.base, income.rate_pct, income.code) == (D("100000.00"), D("5"), "I1")
    assert income.review_status == "confirmed"


def test_withheld_vat_is_taken_from_the_rounded_vat_not_from_the_exact_one() -> None:
    # VAT 1.12 x 20% = 0.224 -> 0.22. Seven tenths of 0.22 is 0.154 -> 0.15.
    # Seven tenths of the unrounded 0.224 would be 0.1568 -> 0.16, a figure
    # that does not follow from the VAT printed one line above it.
    rows = (_row(numerator=7),)
    result = compute_payment_taxes(_inp("1.12", income_withholding=NA, stamp_duty=NA), rows)

    assert result.vat_computed.amount == D("0.22")
    assert result.vat_withheld.amount == D("0.15")
    assert result.vat_payable.amount == D("0.07")


def test_payable_is_a_subtraction_so_a_half_never_rounds_twice() -> None:
    # VAT 0.05, half of it is 0.025. Rounding both halves up would give
    # 0.03 + 0.03 = 0.06 against a VAT of 0.05.
    rows = (_row(numerator=5),)
    result = compute_payment_taxes(_inp("0.25", income_withholding=NA, stamp_duty=NA), rows)

    assert result.vat_computed.amount == D("0.05")
    assert result.vat_withheld.amount == D("0.03")
    assert result.vat_payable.amount == D("0.02")


@pytest.mark.parametrize(
    ("currency", "net", "vat", "withheld"),
    [
        ("TRY", "0.25", "0.03", "0.02"),  # 0.025 -> 0.03, half of it 0.015 -> 0.02
        ("EUR", "1000.25", "100.03", "50.02"),
        ("USD", "1000.25", "100.03", "50.02"),
        ("HUF", "1005", "101", "51"),  # 100.5 -> 101, half 50.5 -> 51
        ("JPY", "1005", "101", "51"),
        ("KWD", "1.005", "0.101", "0.051"),  # 0.1005 -> 0.101, half 0.0505 -> 0.051
    ],
)
def test_rounding_is_half_up_to_the_quantum_of_the_currency(currency: str, net: str, vat: str, withheld: str) -> None:
    rows = (_row(numerator=5),)
    inp = _inp(net, currency=currency, vat_rate_pct=D("10"), income_withholding=NA, stamp_duty=NA)

    result = compute_payment_taxes(inp, rows)

    assert result.vat_computed.amount == D(vat)
    assert result.vat_withheld.amount == D(withheld)
    assert result.vat_payable.amount == D(vat) - D(withheld)
    for figure in (result.vat_computed, result.vat_withheld, result.vat_payable):
        assert figure.amount == figure.amount.quantize(money_quantum(currency))


def test_the_quantum_helper_answers_as_this_module_assumes() -> None:
    assert money_quantum("TRY") == D("0.01")
    assert money_quantum("EUR") == D("0.01")
    assert money_quantum("USD") == D("0.01")
    assert money_quantum("HUF") == D("1")
    assert money_quantum("JPY") == D("1")
    assert money_quantum("KWD") == D("0.001")
    # The helper answers two decimals for a code it has never heard of. That
    # default is the reason the calculator checks the code itself.
    assert money_quantum("ZZZ") == D("0.01")
    assert money_quantum("") == D("0.01")


@pytest.mark.parametrize("currency", ["ZZZ", "", "  ", "TL"])
def test_an_unknown_currency_holds_every_figure_instead_of_rounding_to_cents(currency: str) -> None:
    result = compute_payment_taxes(_inp(currency=currency), ROWS)

    _assert_shape(result)
    assert not result.complete
    for figure in result.figures():
        assert (figure.status, figure.amount, figure.reason_key) == ("held", None, "currency_unknown")


def test_currency_code_is_matched_without_regard_to_case_or_padding() -> None:
    result = compute_payment_taxes(_inp("1005", currency=" jpy ", vat_rate_pct=D("10")), ROWS)

    assert result.vat_computed.amount == D("101")


# ── Value, not applicable, held ──────────────────────────────────────────────


def test_an_unset_choice_is_held_not_zero() -> None:
    result = compute_payment_taxes(_inp(vat_withholding=UNSET, income_withholding=UNSET, stamp_duty=UNSET), ROWS)

    _assert_shape(result)
    assert not result.complete
    assert result.vat_computed.amount == D("20000.00")
    for figure in (result.vat_withheld, result.vat_payable, result.income_withheld, result.stamp_duty):
        assert (figure.status, figure.amount, figure.reason_key) == ("held", None, "not_chosen")


def test_a_selected_choice_without_a_code_is_not_a_choice() -> None:
    result = compute_payment_taxes(_inp(income_withholding=Choice("selected", "  ")), ROWS)

    assert (result.income_withheld.status, result.income_withheld.reason_key) == ("held", "not_chosen")


def test_a_code_with_no_row_on_the_date_is_held_and_never_takes_the_nearest_row() -> None:
    rows = (
        _row(numerator=3, effective_from=date(2020, 1, 1), effective_to=date(2021, 2, 28)),
        _row(numerator=4, effective_from=date(2025, 1, 1)),
    )
    result = compute_payment_taxes(_inp(income_withholding=NA, stamp_duty=NA), rows)

    _assert_shape(result)
    held = result.vat_withheld
    assert (held.status, held.amount, held.reason_key) == ("held", None, "no_rate_on_date")
    assert held.reason_params == {"code": "W1", "on": "2024-06-01"}
    assert (held.code, held.numerator, held.denominator, held.legal_reference) == ("W1", None, None, "")
    assert (result.vat_payable.status, result.vat_payable.reason_key) == ("held", "no_rate_on_date")
    # The VAT itself does not depend on the withholding table.
    assert result.vat_computed.amount == D("20000.00")


def test_a_row_of_another_country_is_not_a_row() -> None:
    result = compute_payment_taxes(_inp(country_code="YY"), ROWS)

    assert result.vat_withheld.reason_key == "no_rate_on_date"
    assert result.income_withheld.reason_key == "no_rate_on_date"
    assert result.stamp_duty.reason_key == "no_rate_on_date"


def test_an_unknown_vat_rate_holds_every_vat_figure_and_is_never_read_as_zero() -> None:
    result = compute_payment_taxes(_inp(vat_rate_pct=None), ROWS)

    _assert_shape(result)
    for figure in (result.vat_computed, result.vat_withheld, result.vat_payable):
        assert (figure.status, figure.amount, figure.reason_key) == ("held", None, "vat_rate_unknown")
    # The row was found, so the reader still sees which fraction is waiting.
    assert (result.vat_withheld.numerator, result.vat_withheld.denominator) == (4, 10)
    # A percent of the net needs no VAT.
    assert result.income_withheld.amount == D("5000.00")
    assert result.stamp_duty.amount == D("948.00")


def test_not_applicable_carries_the_human_reason_and_no_amount() -> None:
    result = compute_payment_taxes(_inp(vat_withholding=NA, income_withholding=NA, stamp_duty=NA), ROWS)

    _assert_shape(result)
    assert result.complete
    for figure in (result.vat_withheld, result.income_withheld, result.stamp_duty):
        assert (figure.status, figure.amount, figure.reason_key) == ("not_applicable", None, "not_applicable_by_user")
        assert figure.reason_params == {"reason": "Buyer is outside the withholding regime"}
    # Nothing is withheld, so the whole VAT is payable.
    assert (result.vat_payable.status, result.vat_payable.amount) == ("value", D("20000.00"))


@pytest.mark.parametrize("reason", ["", "   "])
def test_not_applicable_without_a_reason_is_held(reason: str) -> None:
    choice = Choice("not_applicable", reason=reason)
    result = compute_payment_taxes(_inp(vat_withholding=choice, stamp_duty=choice), ROWS)

    _assert_shape(result)
    assert (result.vat_withheld.status, result.vat_withheld.reason_key) == ("held", "not_applicable_reason_missing")
    assert (result.vat_payable.status, result.vat_payable.reason_key) == ("held", "not_applicable_reason_missing")
    assert (result.stamp_duty.status, result.stamp_duty.reason_key) == ("held", "not_applicable_reason_missing")


def test_a_real_zero_is_a_value() -> None:
    result = compute_payment_taxes(_inp(vat_rate_pct=D("0")), ROWS)

    _assert_shape(result)
    for figure in (result.vat_computed, result.vat_withheld, result.vat_payable):
        assert (figure.status, figure.amount) == ("value", D("0.00"))


def test_a_zero_net_is_a_zero_value_for_every_selected_kind_even_under_a_threshold() -> None:
    rows = (
        _row(
            threshold_amount=D("1000"),
            threshold_currency="TRY",
            threshold_scope="per_document",
            threshold_measure="net_plus_vat",
        ),
        _pct_row(
            "income_withholding",
            "I1",
            "5",
            threshold_amount=D("1000"),
            threshold_currency="EUR",
            threshold_scope="per_payee_year",
            threshold_measure="net",
        ),
        _pct_row("stamp_duty", "S1", "0.948", cap_amount=D("10"), threshold_currency="EUR"),
    )
    result = compute_payment_taxes(_inp("0"), rows)

    _assert_shape(result)
    assert result.complete
    for figure in result.figures():
        assert (figure.status, figure.amount, figure.reason_key) == ("value", D("0.00"), ""), figure


def test_complete_is_false_as_soon_as_one_figure_is_held() -> None:
    assert compute_payment_taxes(_inp(), ROWS).complete
    assert compute_payment_taxes(_inp(vat_withholding=NA), ROWS).complete
    assert not compute_payment_taxes(_inp(stamp_duty=UNSET), ROWS).complete
    assert not compute_payment_taxes(_inp(vat_rate_pct=None), ROWS).complete


def test_two_rows_in_force_on_one_date_hold_the_figure() -> None:
    rows = (_row(numerator=3), _row(numerator=4))
    result = compute_payment_taxes(_inp(income_withholding=NA, stamp_duty=NA), rows)

    _assert_shape(result)
    assert (result.vat_withheld.status, result.vat_withheld.reason_key) == ("held", "rate_ambiguous")
    assert result.vat_payable.reason_key == "rate_ambiguous"


@pytest.mark.parametrize(
    "rows",
    [
        (_row(numerator=None),),
        (_row(denominator=0),),
        (_row(numerator=11),),
        (_row(base="net"),),
        (_row(threshold_amount=D("5"), threshold_currency="TRY", threshold_scope="", threshold_measure="net"),),
    ],
)
def test_a_malformed_withholding_row_holds_the_figure(rows: tuple[RateRow, ...]) -> None:
    result = compute_payment_taxes(_inp(income_withholding=NA, stamp_duty=NA), rows)

    _assert_shape(result)
    assert (result.vat_withheld.status, result.vat_withheld.reason_key) == ("held", "rate_row_invalid")


def test_a_percent_row_without_a_rate_holds_the_figure() -> None:
    rows = (_pct_row("income_withholding", "I1", "5", rate_pct=None),)
    result = compute_payment_taxes(_inp(vat_withholding=NA, stamp_duty=NA), rows)

    assert (result.income_withheld.status, result.income_withheld.reason_key) == ("held", "rate_row_invalid")


# ── Bases of the percent kinds ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("base", "expected_base", "expected"),
    [("net", "100000.00", "5000.00"), ("net_plus_vat", "120000.00", "6000.00"), ("vat", "20000.00", "1000.00")],
)
def test_a_percent_is_taken_from_the_base_the_row_names(base: str, expected_base: str, expected: str) -> None:
    rows = (_pct_row("income_withholding", "I1", "5", base=base),)
    result = compute_payment_taxes(_inp(vat_withholding=NA, stamp_duty=NA), rows)

    assert result.income_withheld.base == D(expected_base)
    assert result.income_withheld.amount == D(expected)


@pytest.mark.parametrize("base", ["net_plus_vat", "vat"])
def test_a_base_that_needs_vat_is_held_while_the_vat_rate_is_unknown(base: str) -> None:
    rows = (_pct_row("stamp_duty", "S1", "1", base=base),)
    result = compute_payment_taxes(_inp(vat_rate_pct=None, vat_withholding=NA, income_withholding=NA), rows)

    assert (result.stamp_duty.status, result.stamp_duty.amount) == ("held", None)
    assert result.stamp_duty.reason_key == "withholding_needs_vat"


def test_a_per_mille_rate_is_written_as_a_percent_and_rounded_once() -> None:
    rows = (_pct_row("stamp_duty", "S1", "0.948"),)
    result = compute_payment_taxes(_inp("1234.56", vat_withholding=NA, income_withholding=NA), rows)

    # 1234.56 x 0.948 / 100 = 11.7036288
    assert result.stamp_duty.amount == D("11.70")


# ── Thresholds ───────────────────────────────────────────────────────────────


def _threshold_rows(scope: str = "per_document", measure: str = "net", currency: str = "TRY") -> tuple[RateRow, ...]:
    return (
        _row(threshold_amount=D("1000"), threshold_currency=currency, threshold_scope=scope, threshold_measure=measure),
    )


def _vat_only(net: str, **changes: object) -> PaymentTaxInput:
    return _inp(net, income_withholding=NA, stamp_duty=NA, **changes)


def test_below_a_per_document_threshold_the_tax_does_not_apply() -> None:
    result = compute_payment_taxes(_vat_only("999.99"), _threshold_rows())

    _assert_shape(result)
    withheld = result.vat_withheld
    assert (withheld.status, withheld.amount, withheld.reason_key) == ("not_applicable", None, "below_threshold")
    assert withheld.reason_params == {"threshold": "1000", "currency": "TRY", "measure": "net", "measured": "999.99"}
    assert (withheld.numerator, withheld.denominator, withheld.legal_reference) == (4, 10, "Synthetic VAT Act art. 9")
    assert (result.vat_payable.status, result.vat_payable.amount) == ("value", D("200.00"))


def test_at_and_above_the_threshold_the_tax_applies_to_the_whole_amount() -> None:
    at = compute_payment_taxes(_vat_only("1000.00"), _threshold_rows())
    above = compute_payment_taxes(_vat_only("1000.01"), _threshold_rows())

    assert (at.vat_withheld.status, at.vat_withheld.amount) == ("value", D("80.00"))
    assert (above.vat_withheld.status, above.vat_withheld.amount) == ("value", D("80.00"))


def test_a_threshold_can_be_measured_on_net_plus_vat() -> None:
    rows = _threshold_rows(measure="net_plus_vat")

    # 833.33 + 166.67 = 1000.00 reaches the threshold, 833.32 + 166.66 does not.
    assert compute_payment_taxes(_vat_only("833.33"), rows).vat_withheld.status == "value"
    below = compute_payment_taxes(_vat_only("833.32"), rows).vat_withheld
    assert (below.status, below.reason_key) == ("not_applicable", "below_threshold")
    assert below.reason_params["measured"] == "999.98"


def test_a_threshold_in_another_currency_is_never_compared() -> None:
    result = compute_payment_taxes(_vat_only("50.00", currency="EUR"), _threshold_rows(currency="TRY"))

    _assert_shape(result)
    withheld = result.vat_withheld
    assert (withheld.status, withheld.amount, withheld.reason_key) == ("held", None, "threshold_currency_mismatch")
    assert withheld.reason_params == {"threshold_currency": "TRY", "document_currency": "EUR"}
    assert result.vat_payable.reason_key == "threshold_currency_mismatch"


def test_a_threshold_currency_is_matched_without_regard_to_case() -> None:
    result = compute_payment_taxes(_vat_only("5000.00", currency="try"), _threshold_rows(currency="TRY"))

    assert result.vat_withheld.status == "value"


@pytest.mark.parametrize("net", ["50.00", "5000000.00"])
def test_a_yearly_threshold_cannot_be_proved_by_one_payment(net: str) -> None:
    rows = (
        _pct_row(
            "income_withholding",
            "I1",
            "5",
            threshold_amount=D("1000"),
            threshold_currency="TRY",
            threshold_scope="per_payee_year",
            threshold_measure="net",
        ),
    )
    result = compute_payment_taxes(_inp(net, vat_withholding=NA, stamp_duty=NA), rows)

    _assert_shape(result)
    income = result.income_withheld
    assert (income.status, income.amount, income.reason_key) == ("held", None, "threshold_needs_year_total")


def test_a_threshold_on_net_plus_vat_is_held_while_the_vat_rate_is_unknown() -> None:
    rows = (
        _pct_row(
            "income_withholding",
            "I1",
            "5",
            threshold_amount=D("1000"),
            threshold_currency="TRY",
            threshold_scope="per_document",
            threshold_measure="net_plus_vat",
        ),
    )
    result = compute_payment_taxes(_inp(vat_rate_pct=None, vat_withholding=NA, stamp_duty=NA), rows)

    assert (result.income_withheld.status, result.income_withheld.reason_key) == ("held", "withholding_needs_vat")


# ── Who the buyer is ─────────────────────────────────────────────────────────


def _buyer_rows(scope: str, **changes: object) -> tuple[RateRow, ...]:
    if scope == "designated_or_work_value":
        changes.setdefault("work_value_threshold", D("5000"))
        changes.setdefault("threshold_currency", "TRY")
    return (_row(buyer_scope=scope, **changes),)


def _withheld(rows: tuple[RateRow, ...], net: str = "1000.00", **changes: object) -> Figure:
    result = compute_payment_taxes(_vat_only(net, **changes), rows)
    _assert_shape(result)
    if result.vat_withheld.status == "not_applicable":
        # Nothing withheld, so the seller collects the whole VAT.
        assert result.vat_payable.amount == result.vat_computed.amount
    return result.vat_withheld


@pytest.mark.parametrize("scope", ["", "any"])
def test_a_row_without_a_buyer_condition_does_not_ask_who_the_buyer_is(scope: str) -> None:
    for designated in (None, True, False):
        figure = _withheld(_buyer_rows(scope), buyer_is_designated=designated)
        assert (figure.status, figure.amount) == ("value", D("80.00"))


def test_designated_only_never_assumes_the_buyer_class() -> None:
    rows = _buyer_rows("designated_only")

    unknown = _withheld(rows)
    assert (unknown.status, unknown.amount, unknown.reason_key) == ("held", None, "buyer_class_unknown")
    # The row is known, so the reader sees which fraction is waiting on the answer.
    assert (unknown.numerator, unknown.denominator) == (4, 10)

    ordinary = _withheld(rows, buyer_is_designated=False)
    assert (ordinary.status, ordinary.amount, ordinary.reason_key) == ("not_applicable", None, "buyer_not_designated")

    designated = _withheld(rows, buyer_is_designated=True)
    assert (designated.status, designated.amount, designated.reason_key) == ("value", D("80.00"), "")


def test_designated_only_ignores_the_value_of_the_work() -> None:
    figure = _withheld(_buyer_rows("designated_only"), buyer_is_designated=False, work_value_incl_vat=D("9999999"))

    assert (figure.status, figure.reason_key) == ("not_applicable", "buyer_not_designated")


def test_a_designated_buyer_withholds_whatever_the_value_of_the_work() -> None:
    rows = _buyer_rows("designated_or_work_value")

    for work_value in (None, D("1"), D("5000"), D("9999999")):
        figure = _withheld(rows, buyer_is_designated=True, work_value_incl_vat=work_value)
        assert (figure.status, figure.amount) == ("value", D("80.00"))


def test_an_ordinary_buyer_withholds_only_from_the_work_value_upwards() -> None:
    rows = _buyer_rows("designated_or_work_value")

    below = _withheld(rows, buyer_is_designated=False, work_value_incl_vat=D("4999.99"))
    assert (below.status, below.amount, below.reason_key) == ("not_applicable", None, "below_work_value")
    assert below.reason_params == {"threshold": "5000", "currency": "TRY", "work_value": "4999.99"}

    # "Or more": the limit itself is inside.
    at = _withheld(rows, buyer_is_designated=False, work_value_incl_vat=D("5000"))
    assert (at.status, at.amount) == ("value", D("80.00"))
    above = _withheld(rows, buyer_is_designated=False, work_value_incl_vat=D("5000.01"))
    assert (above.status, above.amount) == ("value", D("80.00"))


def test_the_work_value_is_the_contract_not_the_document() -> None:
    rows = _buyer_rows("designated_or_work_value")

    # A small certificate under a large contract is withheld,
    small = _withheld(rows, net="10.00", buyer_is_designated=False, work_value_incl_vat=D("6000"))
    assert (small.status, small.amount) == ("value", D("0.80"))
    # and a large document under a small contract value is not judged by its own size.
    large = _withheld(rows, net="900000.00", buyer_is_designated=False, work_value_incl_vat=D("100"))
    assert (large.status, large.reason_key) == ("not_applicable", "below_work_value")


def test_an_ordinary_buyer_with_no_work_value_is_held() -> None:
    figure = _withheld(_buyer_rows("designated_or_work_value"), buyer_is_designated=False)

    assert (figure.status, figure.amount, figure.reason_key) == ("held", None, "work_value_unknown")


def test_an_unknown_buyer_class_is_held_unless_the_work_value_settles_it() -> None:
    rows = _buyer_rows("designated_or_work_value")

    assert _withheld(rows).reason_key == "buyer_class_unknown"
    # Below the limit the answer depends on who the buyer is.
    below = _withheld(rows, work_value_incl_vat=D("100"))
    assert (below.status, below.reason_key) == ("held", "buyer_class_unknown")
    # At or above the limit both kinds of buyer withhold, so nothing is assumed.
    above = _withheld(rows, work_value_incl_vat=D("5000"))
    assert (above.status, above.amount) == ("value", D("80.00"))


def test_a_work_value_limit_in_another_currency_is_never_compared() -> None:
    rows = _buyer_rows("designated_or_work_value")

    figure = _withheld(rows, currency="EUR", buyer_is_designated=False, work_value_incl_vat=D("9999999"))
    assert (figure.status, figure.reason_key) == ("held", "threshold_currency_mismatch")
    assert figure.reason_params == {"threshold_currency": "TRY", "document_currency": "EUR"}
    # A designated buyer needs no comparison, so the currency does not matter.
    assert _withheld(rows, currency="EUR", buyer_is_designated=True).status == "value"


def test_the_buyer_condition_applies_to_a_credit_note_as_to_an_invoice() -> None:
    rows = _buyer_rows("designated_only")

    assert _withheld(rows, net="-1000.00", buyer_is_designated=False).reason_key == "buyer_not_designated"
    assert _withheld(rows, net="-1000.00").reason_key == "buyer_class_unknown"
    assert _withheld(rows, net="-1000.00", buyer_is_designated=True).amount == D("-80.00")


def test_the_buyer_condition_is_judged_before_the_document_threshold() -> None:
    rows = _buyer_rows(
        "designated_only",
        threshold_amount=D("1000"),
        threshold_currency="TRY",
        threshold_scope="per_document",
        threshold_measure="net",
    )

    assert _withheld(rows, net="10.00").reason_key == "buyer_class_unknown"
    assert _withheld(rows, net="10.00", buyer_is_designated=False).reason_key == "buyer_not_designated"
    assert _withheld(rows, net="10.00", buyer_is_designated=True).reason_key == "below_threshold"
    assert _withheld(rows, net="1000.00", buyer_is_designated=True).status == "value"


def test_an_override_supplies_the_amount_while_the_buyer_class_is_unknown() -> None:
    overrides = {"vat_withheld": Override(D("80.00"), "Buyer confirmed by letter", "user-1")}
    result = compute_payment_taxes(_vat_only("1000.00", overrides=overrides), _buyer_rows("designated_only"))

    assert (result.vat_withheld.status, result.vat_withheld.amount) == ("value", D("80.00"))
    assert result.vat_withheld.overridden


def test_a_work_value_row_without_its_limit_holds_the_figure() -> None:
    rows = (_row(buyer_scope="designated_or_work_value"),)

    assert _withheld(rows, buyer_is_designated=False, work_value_incl_vat=D("1")).reason_key == "rate_row_invalid"
    assert _withheld((_row(buyer_scope="everyone"),)).reason_key == "rate_row_invalid"


def test_buyer_inputs_of_the_wrong_type_are_rejected() -> None:
    with pytest.raises(TypeError, match="work_value_incl_vat"):
        compute_payment_taxes(_inp(work_value_incl_vat=5000.0), ROWS)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="buyer_is_designated"):
        compute_payment_taxes(_inp(buyer_is_designated="yes"), ROWS)  # type: ignore[arg-type]


# ── Caps ─────────────────────────────────────────────────────────────────────


def _cap_rows(cap: str = "500.00", currency: str = "TRY") -> tuple[RateRow, ...]:
    return (_pct_row("stamp_duty", "S1", "1", cap_amount=D(cap), threshold_currency=currency),)


def _duty_only(net: str, **changes: object) -> PaymentTaxInput:
    return _inp(net, vat_withholding=NA, income_withholding=NA, **changes)


def test_a_cap_clamps_the_amount_and_says_so() -> None:
    result = compute_payment_taxes(_duty_only("100000.00"), _cap_rows())

    _assert_shape(result)
    duty = result.stamp_duty
    assert (duty.status, duty.amount, duty.reason_key) == ("value", D("500.00"), "capped")
    assert duty.reason_params == {"cap": "500.00", "currency": "TRY", "computed": "1000.00"}
    assert (duty.base, duty.rate_pct) == (D("100000.00"), D("1"))


def test_an_amount_at_or_under_the_cap_is_left_alone() -> None:
    at = compute_payment_taxes(_duty_only("50000.00"), _cap_rows()).stamp_duty
    under = compute_payment_taxes(_duty_only("49999.00"), _cap_rows()).stamp_duty

    assert (at.amount, at.reason_key) == (D("500.00"), "")
    assert (under.amount, under.reason_key) == (D("499.99"), "")


def test_a_cap_in_another_currency_is_never_applied_or_ignored() -> None:
    result = compute_payment_taxes(_duty_only("10.00", currency="EUR"), _cap_rows(currency="TRY"))

    _assert_shape(result)
    duty = result.stamp_duty
    assert (duty.status, duty.amount, duty.reason_key) == ("held", None, "cap_currency_mismatch")
    assert duty.reason_params == {"cap_currency": "TRY", "document_currency": "EUR"}


def test_a_cap_is_rounded_to_the_currency_like_any_amount() -> None:
    result = compute_payment_taxes(_duty_only("100000", currency="JPY"), _cap_rows(cap="500.40", currency="JPY"))

    assert result.stamp_duty.amount == D("500")


# ── Overrides ────────────────────────────────────────────────────────────────


def _override(amount: str, reason: str = "Agreed with the accountant") -> Override:
    return Override(amount=D(amount), reason=reason, by="user-1")


def test_an_override_of_withheld_vat_recomputes_payable_by_subtraction() -> None:
    result = compute_payment_taxes(_inp(overrides={"vat_withheld": _override("7999.99")}), ROWS)

    _assert_shape(result)
    withheld = result.vat_withheld
    assert (withheld.status, withheld.amount, withheld.overridden) == ("value", D("7999.99"), True)
    # The computed basis stays on the figure so the reader sees what was replaced.
    assert (withheld.base, withheld.numerator, withheld.denominator) == (D("20000.00"), 4, 10)
    assert (withheld.code, withheld.legal_reference) == ("W1", "Synthetic VAT Act art. 9")
    assert withheld.reason_params == {"reason": "Agreed with the accountant", "by": "user-1", "computed": "8000.00"}
    assert result.vat_payable.amount == D("12000.01")
    assert not result.vat_payable.overridden
    assert not result.vat_computed.overridden


def test_an_override_of_computed_vat_flows_into_withheld_and_payable() -> None:
    result = compute_payment_taxes(_inp(overrides={"vat_computed": _override("20000.10")}), ROWS)

    _assert_shape(result)
    assert (result.vat_computed.amount, result.vat_computed.overridden) == (D("20000.10"), True)
    assert (result.vat_computed.base, result.vat_computed.rate_pct) == (D("100000.00"), D("20"))
    assert result.vat_withheld.amount == D("8000.04")
    assert result.vat_withheld.base == D("20000.10")
    assert result.vat_payable.amount == D("12000.06")


def test_overrides_of_income_withholding_and_stamp_duty() -> None:
    overrides = {"income_withheld": _override("4000.00"), "stamp_duty": _override("0.00")}
    result = compute_payment_taxes(_inp(overrides=overrides), ROWS)

    _assert_shape(result)
    assert (result.income_withheld.amount, result.income_withheld.overridden) == (D("4000.00"), True)
    assert (result.income_withheld.base, result.income_withheld.rate_pct) == (D("100000.00"), D("5"))
    assert (result.stamp_duty.status, result.stamp_duty.amount) == ("value", D("0.00"))
    assert result.vat_withheld.amount == D("8000.00")


def test_overrides_may_be_keyed_by_the_row_kind_as_well_as_the_figure_kind() -> None:
    overrides = {"vat_withholding": _override("1.00"), "income_withholding": _override("2.00")}
    result = compute_payment_taxes(_inp(overrides=overrides), ROWS)

    assert result.vat_withheld.amount == D("1.00")
    assert result.income_withheld.amount == D("2.00")


def test_one_figure_overridden_under_both_of_its_names_is_an_error() -> None:
    overrides = {"vat_withholding": _override("1.00"), "vat_withheld": _override("2.00")}

    with pytest.raises(ValueError, match="vat_withheld"):
        compute_payment_taxes(_inp(overrides=overrides), ROWS)


def test_an_override_under_an_unknown_key_is_an_error_not_a_silent_no_op() -> None:
    with pytest.raises(ValueError, match="withholding"):
        compute_payment_taxes(_inp(overrides={"withholding": _override("1.00")}), ROWS)


@pytest.mark.parametrize("reason", ["", "  \t"])
def test_an_override_without_a_reason_holds_the_figure(reason: str) -> None:
    result = compute_payment_taxes(_inp(overrides={"vat_withheld": _override("7000.00", reason)}), ROWS)

    _assert_shape(result)
    withheld = result.vat_withheld
    assert (withheld.status, withheld.amount, withheld.reason_key) == ("held", None, "override_reason_missing")
    assert not withheld.overridden
    assert (result.vat_payable.status, result.vat_payable.reason_key) == ("held", "override_reason_missing")
    assert result.vat_computed.status == "value"


def test_an_unreasoned_override_of_computed_vat_holds_what_depends_on_it() -> None:
    result = compute_payment_taxes(_inp(overrides={"vat_computed": _override("1.00", "")}), ROWS)

    _assert_shape(result)
    assert result.vat_computed.reason_key == "override_reason_missing"
    assert (result.vat_withheld.status, result.vat_withheld.reason_key) == ("held", "withholding_needs_vat")
    assert (result.vat_payable.status, result.vat_payable.reason_key) == ("held", "override_reason_missing")
    assert result.income_withheld.status == "value"


def test_an_override_finer_than_the_currency_is_held_not_rounded() -> None:
    result = compute_payment_taxes(_inp(overrides={"stamp_duty": _override("10.005")}), ROWS)

    _assert_shape(result)
    duty = result.stamp_duty
    assert (duty.status, duty.amount, duty.reason_key) == ("held", None, "override_precision")
    assert duty.reason_params == {"amount": "10.005", "currency": "TRY"}


def test_an_override_with_trailing_zeros_is_normalised_to_the_quantum() -> None:
    result = compute_payment_taxes(_inp(overrides={"stamp_duty": _override("10.5000")}), ROWS)

    assert result.stamp_duty.amount == D("10.50")
    assert result.stamp_duty.amount.as_tuple().exponent == -2


def test_payable_vat_cannot_be_overridden_because_it_is_a_difference() -> None:
    result = compute_payment_taxes(_inp(overrides={"vat_payable": _override("1.00")}), ROWS)

    _assert_shape(result)
    payable = result.vat_payable
    assert (payable.status, payable.amount, payable.reason_key) == ("held", None, "override_not_allowed")
    assert result.vat_withheld.amount == D("8000.00")


def test_an_override_supplies_the_amount_a_missing_row_could_not() -> None:
    result = compute_payment_taxes(_inp(overrides={"stamp_duty": _override("123.45")}), ROWS[:2])

    _assert_shape(result)
    duty = result.stamp_duty
    assert (duty.status, duty.amount, duty.overridden) == ("value", D("123.45"), True)
    assert (duty.code, duty.legal_reference, duty.rate_pct) == ("S1", "", None)


def test_an_override_supplies_vat_when_the_rate_is_unknown() -> None:
    result = compute_payment_taxes(_inp(vat_rate_pct=None, overrides={"vat_computed": _override("20000.00")}), ROWS)

    _assert_shape(result)
    assert result.complete
    assert (result.vat_computed.amount, result.vat_computed.rate_pct) == (D("20000.00"), None)
    assert result.vat_withheld.amount == D("8000.00")
    assert result.vat_payable.amount == D("12000.00")


def test_an_override_does_not_stand_in_for_a_decision_nobody_made() -> None:
    overrides = {"vat_withheld": _override("1.00"), "stamp_duty": _override("1.00")}
    result = compute_payment_taxes(_inp(vat_withholding=UNSET, stamp_duty=NA, overrides=overrides), ROWS)

    _assert_shape(result)
    assert (result.vat_withheld.status, result.vat_withheld.reason_key) == ("held", "not_chosen")
    # "Does not apply" and "the amount is 1.00" contradict each other. The
    # explicit statement that the tax does not apply wins and nothing is charged.
    assert (result.stamp_duty.status, result.stamp_duty.amount) == ("not_applicable", None)
    assert not result.stamp_duty.overridden


def test_an_override_is_not_clamped_by_the_cap() -> None:
    result = compute_payment_taxes(_duty_only("100000.00", overrides={"stamp_duty": _override("750.00")}), _cap_rows())

    assert (result.stamp_duty.amount, result.stamp_duty.reason_key) == (D("750.00"), "")


# ── Negative and zero amounts ────────────────────────────────────────────────


def _mirror(figure: Figure) -> tuple[object, ...]:
    amount = None if figure.amount is None else -figure.amount
    base = None if figure.base is None else -figure.base
    return (figure.kind, figure.status, amount, base, figure.rate_pct, figure.code, figure.reason_key)


def _plain(figure: Figure) -> tuple[object, ...]:
    return (figure.kind, figure.status, figure.amount, figure.base, figure.rate_pct, figure.code, figure.reason_key)


@pytest.mark.parametrize("net", ["0.25", "1.12", "33.33", "100000.00", "123456.78", "0.01"])
@pytest.mark.parametrize("currency", ["TRY", "JPY", "KWD"])
def test_a_credit_note_is_the_exact_mirror_of_the_document_it_reverses(net: str, currency: str) -> None:
    rows = (
        _row(numerator=7),
        _pct_row("income_withholding", "I1", "5", base="net_plus_vat"),
        _pct_row("stamp_duty", "S1", "0.948", cap_amount=D("200"), threshold_currency=currency),
    )
    amount = D(net).quantize(money_quantum(currency)) + money_quantum(currency)
    positive = compute_payment_taxes(_inp(amount, currency=currency), rows)
    negative = compute_payment_taxes(_inp(-amount, currency=currency), rows)

    _assert_shape(negative)
    # Half-up rounds away from zero on both sides, and a cap limits the size
    # of the amount, so every figure flips its sign and nothing else.
    assert [_plain(figure) for figure in negative.figures()] == [_mirror(figure) for figure in positive.figures()]
    assert negative.vat_computed.amount == negative.vat_withheld.amount + negative.vat_payable.amount


def test_a_negative_half_rounds_away_from_zero_like_a_positive_one() -> None:
    result = compute_payment_taxes(_vat_only("-0.25", vat_rate_pct=D("10")), (_row(numerator=5),))

    assert result.vat_computed.amount == D("-0.03")
    assert result.vat_withheld.amount == D("-0.02")
    assert result.vat_payable.amount == D("-0.01")


def test_an_amount_that_rounds_to_nothing_is_a_plain_zero_not_a_negative_one() -> None:
    result = compute_payment_taxes(_inp("-0.01", vat_rate_pct=D("1")), ROWS)

    for figure in result.figures():
        assert str(figure.amount) == "0.00", figure
    assert [str(part) for part in allocate(D("-0.01"), [D("1"), D("1")], "TRY")] == ["-0.01", "0.00"]


def test_a_per_document_threshold_is_not_applied_to_a_credit_note() -> None:
    # The threshold was tested on the document being corrected. A credit of
    # 50.00 against an invoice of 100000.00 reverses a share of a withholding
    # that did apply, so reading "50.00 is below 1000" as "no withholding"
    # would leave the reversal out.
    result = compute_payment_taxes(_vat_only("-50.00"), _threshold_rows())

    _assert_shape(result)
    assert (result.vat_withheld.status, result.vat_withheld.amount) == ("value", D("-4.00"))
    assert result.vat_payable.amount == D("-6.00")


def test_a_credit_note_still_cannot_prove_a_yearly_threshold() -> None:
    rows = (
        _pct_row(
            "income_withholding",
            "I1",
            "5",
            threshold_amount=D("1000"),
            threshold_currency="TRY",
            threshold_scope="per_payee_year",
            threshold_measure="net",
        ),
    )
    result = compute_payment_taxes(_inp("-50.00", vat_withholding=NA, stamp_duty=NA), rows)

    assert (result.income_withheld.status, result.income_withheld.reason_key) == ("held", "threshold_needs_year_total")


def test_a_cap_limits_the_size_of_a_negative_amount_and_keeps_its_sign() -> None:
    duty = compute_payment_taxes(_duty_only("-100000.00"), _cap_rows()).stamp_duty

    assert (duty.status, duty.amount, duty.reason_key) == ("value", D("-500.00"), "capped")


# ── Inputs that are programming errors ───────────────────────────────────────


def test_a_float_amount_is_rejected() -> None:
    with pytest.raises(TypeError, match="net_amount"):
        compute_payment_taxes(_inp(net_amount=100.0), ROWS)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="vat_rate_pct"):
        compute_payment_taxes(_inp(vat_rate_pct=20.0), ROWS)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="override"):
        compute_payment_taxes(_inp(overrides={"stamp_duty": Override(1.5, "x", "u")}), ROWS)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_amount_is_rejected(bad: str) -> None:
    with pytest.raises(ValueError, match="finite"):
        compute_payment_taxes(_inp(net_amount=D(bad)), ROWS)
    with pytest.raises(ValueError, match="finite"):
        compute_payment_taxes(_inp(vat_rate_pct=D(bad)), ROWS)


def test_a_negative_vat_rate_is_rejected() -> None:
    with pytest.raises(ValueError, match="vat_rate_pct"):
        compute_payment_taxes(_inp(vat_rate_pct=D("-1")), ROWS)


def test_an_unknown_choice_state_is_rejected() -> None:
    with pytest.raises(ValueError, match="state"):
        compute_payment_taxes(_inp(stamp_duty=Choice("maybe")), ROWS)  # type: ignore[arg-type]


# ── The reason vocabulary is closed ──────────────────────────────────────────


def _scenarios() -> list[tuple[PaymentTaxInput, tuple[RateRow, ...]]]:
    no_reason = _override("1.00", "")
    return [
        (_inp(), ROWS),
        (_inp("0"), ROWS),
        (_inp("-100.00"), ROWS),
        (_inp(vat_withholding=UNSET, income_withholding=UNSET, stamp_duty=UNSET), ROWS),
        (_inp(vat_withholding=NA, income_withholding=NA, stamp_duty=NA), ROWS),
        (_inp(stamp_duty=Choice("not_applicable")), ROWS),
        (_inp(vat_rate_pct=None), ROWS),
        (_inp(vat_rate_pct=None), (_pct_row("stamp_duty", "S1", "1", base="net_plus_vat"),)),
        (_inp(country_code="YY"), ROWS),
        (_inp(currency="ZZZ"), ROWS),
        (_inp(), (_row(numerator=3), _row(numerator=4))),
        (_inp(), (_row(numerator=None),)),
        (_vat_only("10.00"), _threshold_rows()),
        (_vat_only("10.00", currency="EUR"), _threshold_rows()),
        (_vat_only("10.00"), _threshold_rows(scope="per_payee_year")),
        (_duty_only("100000.00"), _cap_rows()),
        (_duty_only("100000.00", currency="EUR"), _cap_rows()),
        (_vat_only("10.00"), _buyer_rows("designated_only")),
        (_vat_only("10.00", buyer_is_designated=False), _buyer_rows("designated_only")),
        (_vat_only("10.00", buyer_is_designated=False), _buyer_rows("designated_or_work_value")),
        (
            _vat_only("10.00", buyer_is_designated=False, work_value_incl_vat=D("1")),
            _buyer_rows("designated_or_work_value"),
        ),
        (_inp(overrides={"vat_withheld": _override("5.00")}), ROWS),
        (_inp(overrides={"vat_withheld": no_reason}), ROWS),
        (_inp(overrides={"vat_computed": no_reason}), ROWS),
        (_inp(overrides={"vat_payable": _override("5.00")}), ROWS),
        (_inp(overrides={"stamp_duty": _override("5.005")}), ROWS),
    ]


def test_the_calculator_never_emits_a_reason_key_outside_the_vocabulary() -> None:
    emitted: set[str] = set()
    for inp, rows in _scenarios():
        result = compute_payment_taxes(inp, rows)
        _assert_shape(result)
        emitted.update(figure.reason_key for figure in result.figures())

    assert emitted <= set(REASON_KEYS)
    # Every key in the vocabulary is one the calculator can actually produce.
    # A key nobody emits is a translation nobody can ever see, and a sign that
    # a branch was removed without its key.
    assert emitted == set(REASON_KEYS)


def test_the_vocabulary_contains_the_keys_other_packages_translate() -> None:
    required = {
        "",
        "not_chosen",
        "no_rate_on_date",
        "vat_rate_unknown",
        "not_applicable_by_user",
        "below_threshold",
        "threshold_currency_mismatch",
        "threshold_needs_year_total",
        "capped",
        "override_reason_missing",
        "withholding_needs_vat",
    }

    assert required <= set(REASON_KEYS)
    assert len(REASON_KEYS) == len(set(REASON_KEYS))


# ── The exact-sum property over a grid ───────────────────────────────────────

_MANTISSAS = (1, 2, 3, 5, 7, 11, 15, 25, 33, 49, 50, 51, 99, 101, 125, 333, 505, 995, 1005, 12345, 99995, 123455)
_VAT_RATES = (D("0"), D("1"), D("10"), D("20"))
_BILLION = D(10) ** 9


def _grid_nets(currency: str) -> list[Decimal]:
    """Amounts from one quantum up to a billion, heavy in digits that end in 5."""
    quantum = money_quantum(currency)
    nets = {quantum, _BILLION, _BILLION - quantum}
    for mantissa in _MANTISSAS:
        value = mantissa * quantum
        while value <= _BILLION:
            nets.add(value)
            value *= 10
    return sorted(nets)


@pytest.mark.parametrize("currency", ["JPY", "TRY", "KWD"])
def test_vat_figures_sum_exactly_and_stay_on_the_quantum_over_a_grid(currency: str) -> None:
    quantum = money_quantum(currency)
    decimals = -quantum.as_tuple().exponent
    row_sets = [
        (_row(numerator=n), _pct_row("income_withholding", "I1", "5"), _pct_row("stamp_duty", "S1", "0.948"))
        for n in range(1, 11)
    ]
    nets = _grid_nets(currency)
    assert nets[0] == quantum
    assert nets[-1] == _BILLION
    assert len(nets) > 100

    checked = 0
    for net in nets:
        for rate in _VAT_RATES:
            for rows in row_sets:
                for signed in (net, -net):
                    result = compute_payment_taxes(_inp(signed, currency=currency, vat_rate_pct=rate), rows)
                    vat, withheld, payable = result.vat_computed, result.vat_withheld, result.vat_payable
                    assert vat.amount == withheld.amount + payable.amount, (signed, rate, rows[0].numerator)
                    for figure in result.figures():
                        assert figure.status == "value"
                        assert figure.amount.as_tuple().exponent == -decimals, (figure, signed)
                    # Withholding a fraction of the VAT never exceeds the VAT.
                    assert abs(withheld.amount) <= abs(vat.amount)
                    checked += 1
    assert checked == len(nets) * len(_VAT_RATES) * 10 * 2


@pytest.mark.parametrize("currency", ["JPY", "TRY", "KWD"])
def test_allocate_sums_to_its_total_over_a_grid(currency: str) -> None:
    quantum = money_quantum(currency)
    weight_sets = [
        [D("1")],
        [D("1"), D("1"), D("1")],
        [D("1"), D("2"), D("3"), D("4")],
        [D("0.01"), D("999999.99")],
        [D("0"), D("5"), D("0"), D("5"), D("5")],
        [D("100"), D("-30"), D("7.5")],
        [D("33.33")] * 7,
        [D(n) for n in range(1, 30)],
    ]
    for total in _grid_nets(currency):
        for weights in weight_sets:
            for signed in (total, -total):
                parts = allocate(signed, weights, currency)
                assert len(parts) == len(weights)
                assert sum(parts, D("0")) == signed, (signed, weights)
                assert all(part == part.quantize(quantum) for part in parts)
                assert all(part.as_tuple().exponent == quantum.as_tuple().exponent for part in parts)


# ── allocate ─────────────────────────────────────────────────────────────────


def test_allocate_gives_the_spare_units_to_the_largest_remainders() -> None:
    # 100.00 over 1:1:1 is 33.333.. each. One cent is left and goes to the first row.
    assert allocate(D("100.00"), [D("1"), D("1"), D("1")], "TRY") == [D("33.34"), D("33.33"), D("33.33")]
    # Exact shares 0.025, 0.035, 0.04: floors 0.02, 0.03, 0.04 leave one cent
    # short, and the two halves tie, so the earlier row takes it.
    assert allocate(D("0.10"), [D("25"), D("35"), D("40")], "TRY") == [D("0.03"), D("0.03"), D("0.04")]
    # Remainders 0.6, 0.6, 0.8: the largest first, then row order.
    assert allocate(D("0.02"), [D("3"), D("3"), D("4")], "TRY") == [D("0.01"), D("0.00"), D("0.01")]


def test_allocate_follows_the_weights_exactly_when_they_divide_evenly() -> None:
    assert allocate(D("8000.00"), [D("25000"), D("75000")], "TRY") == [D("2000.00"), D("6000.00")]
    assert allocate(D("101"), [D("1"), D("1")], "JPY") == [D("51"), D("50")]
    assert allocate(D("0.100"), [D("1"), D("2")], "KWD") == [D("0.033"), D("0.067")]


def test_a_zero_weight_gets_nothing_not_even_a_spare_unit() -> None:
    parts = allocate(D("0.05"), [D("0"), D("1"), D("0"), D("1"), D("1")], "TRY")

    assert parts == [D("0.00"), D("0.02"), D("0.00"), D("0.02"), D("0.01")]


def test_a_negative_total_is_the_mirror_of_the_positive_one() -> None:
    weights = [D("1"), D("1"), D("1")]

    assert allocate(D("-100.00"), weights, "TRY") == [-part for part in allocate(D("100.00"), weights, "TRY")]
    assert allocate(D("-100.00"), weights, "TRY") == [D("-33.34"), D("-33.33"), D("-33.33")]


def test_a_credit_line_among_the_weights_takes_a_negative_share() -> None:
    # Shares of 10.00 over 100 : -30 : 30 are 10.00, -3.00 and 3.00.
    assert allocate(D("10.00"), [D("100"), D("-30"), D("30")], "TRY") == [D("10.00"), D("-3.00"), D("3.00")]
    parts = allocate(D("10.00"), [D("100"), D("-30"), D("7")], "TRY")
    assert sum(parts, D("0")) == D("10.00")
    assert parts[1] < 0


def test_a_zero_total_is_all_zeros_whatever_the_weights() -> None:
    assert allocate(D("0"), [D("1"), D("2")], "TRY") == [D("0.00"), D("0.00")]
    assert allocate(D("0.00"), [D("0"), D("0")], "TRY") == [D("0.00"), D("0.00")]
    assert allocate(D("0"), [], "TRY") == []
    assert allocate(D("0"), [D("1"), D("-1")], "JPY") == [D("0"), D("0")]


@pytest.mark.parametrize("weights", [[], [D("0"), D("0")], [D("1"), D("-1")], [D("0")]])
def test_a_total_that_no_weight_can_carry_is_an_error(weights: list[Decimal]) -> None:
    # Putting the whole amount on the first row, or splitting it evenly, would
    # print a figure against a line that did not earn it.
    with pytest.raises(ValueError, match="weights"):
        allocate(D("10.00"), weights, "TRY")


def test_a_total_finer_than_the_currency_is_an_error() -> None:
    with pytest.raises(ValueError, match="quantum"):
        allocate(D("10.005"), [D("1"), D("1")], "TRY")
    with pytest.raises(ValueError, match="quantum"):
        allocate(D("10.5"), [D("1")], "JPY")


def test_allocate_refuses_an_unknown_currency_and_non_decimal_input() -> None:
    with pytest.raises(ValueError, match="currency"):
        allocate(D("10.00"), [D("1")], "ZZZ")
    with pytest.raises(ValueError, match="currency"):
        allocate(D("10.00"), [D("1")], "")
    with pytest.raises(TypeError):
        allocate(10.0, [D("1")], "TRY")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        allocate(D("10.00"), [1.5], "TRY")  # type: ignore[list-item]
    with pytest.raises(ValueError, match="finite"):
        allocate(D("10.00"), [D("NaN")], "TRY")


def test_per_line_values_from_allocate_sum_to_the_group_figures() -> None:
    lines = [D("333.33"), D("333.33"), D("333.34"), D("0.01"), D("4999.99")]
    result = compute_payment_taxes(_inp(sum(lines, D("0"))), ROWS)

    for figure in result.figures():
        parts = allocate(figure.amount, lines, "TRY")
        assert sum(parts, D("0")) == figure.amount


# ── The module stays in the core layer ───────────────────────────────────────


def test_importing_the_package_pulls_in_no_module_layer_and_no_database() -> None:
    backend = Path(__file__).resolve().parents[2]
    probe = (
        "import sys\n"
        "import app.core.payment_taxes\n"
        "import app.core.payment_taxes.data_tr\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('sqlalchemy', 'pydantic', 'fastapi')"
        " or m.startswith('app.modules'))\n"
        "print(','.join(bad))\n"
    )

    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", probe], cwd=backend, capture_output=True, text=True, timeout=120, check=False
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == ""
