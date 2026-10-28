# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Money inside a module's validation message is rendered, never interpolated raw.

The core rules were fixed first. The module rule sets carried the same defect:
a ``Decimal`` dropped straight into the sentence reaches the reader as
``1234567.89`` with no thousands separator and no currency, or as ``1E+3`` once
the Decimal has normalised itself. ``_fmt_money`` is the house renderer and
these tests assert the *rendered sentence*, so putting the raw value back turns
them red.

Two boundaries are pinned here as hard as the fixes are:

* **A quantity is not money.** Hours worked, planned quantities, reuse counts
  and performance indices stay bare numbers. Every pin uses a four-digit
  figure, because a pin on ``5`` cannot tell a conversion from a no-op while a
  pin on ``1234`` catches both the grouping and the added decimals.
* **A currency is taken from the record in hand or not written at all.** Where
  the payload carries no currency the amount is grouped and left uncoded rather
  than given an invented one, and that no-code rendering is pinned too.

No database: every rule here reads a plain dict out of ``ValidationContext``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.currency_registry import sentence_amount
from app.core.validation.engine import ValidationContext
from app.core.validation.rules import _fmt_money
from app.modules.certified_payroll.validators import (
    FringeElectionUnstatedRule,
    OvertimeBaseIncludesFringeRule,
    RateBelowDeterminationRule,
)
from app.modules.einvoice.cii import EInvoice, EInvoiceLine, Party, TaxSubtotal
from app.modules.einvoice.rules import _check_breakdown_basis
from app.modules.formwork.validators import FormworkBoqPositionLinked
from app.modules.full_evm.validators import (
    BaselineBacPositive,
    BaselinePvMatchesBac,
    BaselinePvMonotonic,
    BaselineQuantityMonotonic,
    MeasureEvWithinBac,
    MeasureTcpiAchievable,
)
from app.modules.payment_clock.clock import format_money
from app.modules.payment_clock.validators import PaymentClockStatutoryInterest
from app.modules.rfq_bidding.validators import RFQAwardFollowsRanking, RFQQuoteLinesMatchTotal
from app.modules.tax_withholding.validators import TaxableBaseIsCorrect, WithheldWithinBase
from app.modules.variations.validators import VariationBOQTotalMatchesEstimate

#: Four digits and two decimals: enough to need a grouping separator, and a
#: figure ``str()`` renders without one.
PROBE = Decimal("1234.50")


async def _messages(rule: Any, data: Any, **metadata: Any) -> list[str]:
    """Every message the rule produces for this payload, in order."""
    context = ValidationContext(data=data, metadata={"locale": "en", **metadata})
    return [result.message for result in await rule.validate(context)]


async def _only(rule: Any, data: Any, **metadata: Any) -> str:
    messages = await _messages(rule, data, **metadata)
    assert len(messages) == 1, f"expected exactly one result, got {messages}"
    return messages[0]


# ── the one spelling, asserted as one ───────────────────────────────────────


#: A two-decimal currency, two with no subunit and one with three, plus the
#: blank. A second spelling of a money format never disagrees on the currency
#: its author tested with, so a currency of each shape has to be in the list.
CURRENCY_SHAPES = ("EUR", "JPY", "IDR", "KWD", "")


class TestEveryRendererIsTheSameRenderer:
    """``_fmt_money`` is a name for ``sentence_amount``, and has to stay one.

    Every fix in this file routes through ``_fmt_money``, and the two
    standard-library-only validator modules route through ``sentence_amount``
    directly because they cannot import the rules module. That is safe only
    while the two are the same function. Re-inlining
    ``f"{value:,.{minor_units(currency)}f} {currency}"`` into ``_fmt_money``
    would pass every other test here and every test in the stdlib-only file,
    and would quietly re-create the divergence the split was made to remove.
    """

    def test_fmt_money_still_delegates_rather_than_spelling_it_out_again(self) -> None:
        probe = Decimal("1234567.891")
        for currency in CURRENCY_SHAPES:
            assert _fmt_money(probe, currency) == sentence_amount(probe, currency), currency

    def test_they_agree_on_a_float_as_well_as_a_decimal(self) -> None:
        """``_fmt_money`` accepts float, so the delegation has to carry that too."""
        for currency in CURRENCY_SHAPES:
            assert _fmt_money(1234.5, currency) == sentence_amount(1234.5, currency), currency


# ── certified_payroll: the currency is on the line, glued on by hand ────────


def _payroll_line(**overrides: Any) -> dict[str, Any]:
    """One payroll line underpaying against its determination."""
    line = {
        "worker_name": "Dana Ruiz",
        "currency": "USD",
        "determination_identifier": "WD-2026-014",
        "straight_hours": "1234",
        "overtime_hours": "0",
        "paid_basic_rate": "1000.00",
        "paid_fringe_rate": "234.50",
        "required_basic_rate": "1500.00",
        "required_fringe_rate": "1000.00",
    }
    line.update(overrides)
    return line


class TestCertifiedPayrollRateBelowDetermination:
    async def test_every_amount_is_grouped_and_coded_and_the_hours_stay_bare(self) -> None:
        message = await _only(RateBelowDeterminationRule(), {"lines": [_payroll_line()]})
        assert message == (
            "Dana Ruiz was paid a total package of 1,234.50 USD an hour "
            "(1,000.00 USD basic plus 234.50 USD fringe) against the 2,500.00 USD required "
            "by determination WD-2026-014, a shortfall of 1,265.50 USD for every one of "
            "1234 hours."
        )

    async def test_the_hand_rolled_suffix_does_not_double_the_code(self) -> None:
        """The rule glued ``f" {currency}"`` on itself; the code must appear once per amount."""
        message = await _only(RateBelowDeterminationRule(), {"lines": [_payroll_line()]})
        assert "USD USD" not in message
        # Five amounts in the sentence: package paid, its basic and fringe
        # halves, the package required, and the shortfall.
        assert message.count("USD") == 5

    async def test_a_line_without_a_currency_is_grouped_but_never_coded(self) -> None:
        message = await _only(RateBelowDeterminationRule(), {"lines": [_payroll_line(currency="")]})
        assert message == (
            "Dana Ruiz was paid a total package of 1,234.50 an hour "
            "(1,000.00 basic plus 234.50 fringe) against the 2,500.00 required "
            "by determination WD-2026-014, a shortfall of 1,265.50 for every one of "
            "1234 hours."
        )

    async def test_a_zero_decimal_currency_keeps_no_cents(self) -> None:
        """The renderer asks the currency how many decimals it has, not the caller."""
        line = _payroll_line(
            currency="JPY",
            paid_basic_rate="1000",
            paid_fringe_rate="234",
            required_basic_rate="1500",
            required_fringe_rate="1000",
        )
        message = await _only(RateBelowDeterminationRule(), {"lines": [line]})
        assert "a total package of 1,234 JPY an hour" in message
        assert "1,234.00" not in message


class TestCertifiedPayrollOvertimeBase:
    async def test_the_overtime_base_sentence_codes_each_amount_once(self) -> None:
        line = _payroll_line(
            overtime_hours="1234",
            overtime_base_rate="1234.50",
            paid_basic_rate="1000.00",
            paid_fringe_rate="234.50",
            required_basic_rate="1000.00",
            required_fringe_rate="234.50",
        )
        message = await _only(OvertimeBaseIncludesFringeRule(), {"lines": [line]})
        assert message == (
            "Dana Ruiz has 1234 overtime hours computed on a base of 1,234.50 USD "
            "while the basic wage is 1,000.00 USD and the fringe rate is 234.50 USD. "
            "The overtime multiplier has been applied to 234.50 USD an hour of fringe "
            "benefit money, which is not part of the overtime base."
        )


class TestCertifiedPayrollFringeElection:
    async def test_the_fringe_amount_takes_the_currency_off_its_own_line(self) -> None:
        """This rule never read the currency, though its siblings read the same field."""
        line = _payroll_line(paid_fringe_rate="1234.50", fringe_election="")
        message = await _only(FringeElectionUnstatedRule(), {"lines": [line]})
        assert message == (
            "Dana Ruiz is shown with 1,234.50 USD an hour of fringe benefit money and the "
            "payroll does not say whether it went into a benefit plan or was paid in cash."
        )


# ── full_evm: the baseline payload carries a currency, the measure does not ─


def _baseline(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "baseline",
        "bac": "1E+6",
        "currency": "EUR",
        "periods": [
            {"ordinal": 1, "label": "P1", "period_end": "2026-01-31", "planned_value": "400000"},
            {"ordinal": 2, "label": "P2", "period_end": "2026-02-28", "planned_value": "1000000"},
        ],
    }
    payload.update(overrides)
    return payload


class TestFullEvmBaseline:
    async def test_an_exponent_budget_reaches_the_reader_as_an_amount(self) -> None:
        """``str(Decimal("1E+6"))`` is ``1E+6``; nobody reads that as a million."""
        assert str(Decimal("1E+6")) == "1E+6"
        assert await _only(BaselineBacPositive(), _baseline()) == "Budget At Completion is 1,000,000.00 EUR."

    async def test_a_negative_budget_is_grouped_and_coded(self) -> None:
        message = await _only(BaselineBacPositive(), _baseline(bac="-1234.50"))
        assert message == "Budget At Completion is -1,234.50 EUR; it must be greater than zero."

    async def test_the_curve_gap_names_its_currency_on_every_figure(self) -> None:
        payload = _baseline(
            bac="2000000",
            periods=[
                {"ordinal": 1, "label": "P1", "period_end": "2026-01-31", "planned_value": "400000"},
                {"ordinal": 2, "label": "P2", "period_end": "2026-02-28", "planned_value": "1234567.89"},
            ],
        )
        assert await _only(BaselinePvMatchesBac(), payload) == (
            "The curve ends at 1,234,567.89 EUR but the budget is 2,000,000.00 EUR, "
            "a gap of -765,432.11 EUR. Every schedule performance index is measured "
            "against this curve."
        )

    async def test_a_dropping_curve_quotes_both_amounts(self) -> None:
        payload = _baseline(
            periods=[
                {"ordinal": 1, "label": "P1", "period_end": "2026-01-31", "planned_value": "1234567.89"},
                {"ordinal": 2, "label": "P2", "period_end": "2026-02-28", "planned_value": "1000.00"},
            ],
        )
        messages = await _messages(BaselinePvMonotonic(), payload)
        assert messages == [
            "Cumulative planned value drops from 1,234,567.89 EUR to 1,000.00 EUR at period P2. "
            "A cumulative total cannot go down."
        ]

    async def test_a_planned_quantity_is_a_count_and_keeps_no_currency(self) -> None:
        """The sibling rule on the same curve measures units, not money."""
        payload = _baseline(
            periods=[
                {
                    "ordinal": 1,
                    "label": "P1",
                    "period_end": "2026-01-31",
                    "planned_value": "1",
                    "planned_quantity": "8765",
                },
                {
                    "ordinal": 2,
                    "label": "P2",
                    "period_end": "2026-02-28",
                    "planned_value": "2",
                    "planned_quantity": "1234",
                },
            ],
        )
        messages = await _messages(BaselineQuantityMonotonic(), payload)
        assert messages == ["Cumulative planned quantity drops from 8765 to 1234 at period P2."]


class TestFullEvmMeasure:
    async def test_a_measure_has_no_currency_so_the_amount_is_grouped_and_uncoded(self) -> None:
        """Nothing in the measure payload states a currency; none is invented."""
        payload = {"kind": "measure", "bac": "1000000", "ev": "1234567.89", "pv": "1", "ac": "1"}
        assert await _only(MeasureEvWithinBac(), payload) == (
            "Earned Value 1,234,567.89 exceeds the Budget At Completion 1,000,000.00. "
            "More value cannot be earned than the scope is worth."
        )

    async def test_a_performance_index_is_not_money(self) -> None:
        """TCPI and CPI are ratios; grouping or coding them would be a lie."""
        payload = {
            "kind": "measure",
            "bac": "1000000",
            "ev": "100000",
            "ac": "90000",
            "tcpi_bac": "1234.5",
            "cpi": "1111.25",
        }
        assert await _only(MeasureTcpiAchievable(), payload) == (
            "Remaining work must run at a cost efficiency of 1234.5 to finish on budget, "
            "against an efficiency to date of 1111.25."
        )


# ── tax_withholding: the currency is on the record, written once today ──────


def _deduction(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "record_type": "deduction",
        "currency_code": "GBP",
        "taxable_base": "1234.50",
        "tax_withheld": "9876.50",
    }
    record.update(overrides)
    return record


class TestTaxWithholdingWithheldWithinBase:
    async def test_both_amounts_are_grouped_and_coded(self) -> None:
        assert await _only(WithheldWithinBase(), _deduction()) == (
            "9,876.50 GBP is withheld from a base of 1,234.50 GBP. Withholding more than the base "
            "leaves the party paid less than the contract allows and the return unfilable."
        )

    async def test_a_negative_withholding_is_grouped_and_coded(self) -> None:
        assert await _only(WithheldWithinBase(), _deduction(tax_withheld="-1234.50")) == (
            "The amount withheld is negative (-1,234.50 GBP). A withholding is money kept back, never paid out."
        )

    async def test_a_record_without_a_currency_is_grouped_but_uncoded(self) -> None:
        assert await _only(WithheldWithinBase(), _deduction(currency_code="")) == (
            "9,876.50 is withheld from a base of 1,234.50. Withholding more than the base "
            "leaves the party paid less than the contract allows and the return unfilable."
        )


class TestTaxWithholdingTaxableBase:
    async def test_the_base_disagreement_quotes_all_three_figures(self) -> None:
        record = _deduction(
            gross_amount="9876.50",
            qualifying_materials="0",
            vat_amount="0",
            taxable_base="1234.50",
            materials_excluded=False,
            vat_excluded=False,
            rate_pct="20",
        )
        assert await _only(TaxableBaseIsCorrect(), record) == (
            "The base is recorded as 1,234.50 GBP but the scheme computes 9,876.50 GBP from a gross "
            "of 9,876.50 GBP. A deduction is only defensible if the base it was taken on is."
        )


# ── variations: the bill states its own base currency ───────────────────────


class TestVariationsTotalMatchesEstimate:
    async def test_the_headline_and_the_bill_are_quoted_in_the_bills_currency(self) -> None:
        data = {
            "variation_request_id": "vr-1",
            "base_currency": "CHF",
            "estimated_cost_impact": "1234.50",
            "grand_total": "9876.50",
            "is_mixed_currency": False,
        }
        assert await _only(VariationBOQTotalMatchesEstimate(), data) == (
            "The headline estimate on this request is 1,234.50 CHF, but its priced bill totals 9,876.50 CHF"
        )


# ── rfq_bidding: the comparison names the basis currency ────────────────────


class TestRfqQuoteLinesMatchTotal:
    async def test_a_decimal_string_amount_is_grouped_not_crashed(self) -> None:
        """The comparison serialises money as a Decimal *string*, never a Decimal."""
        data = {
            "comparison": {
                "basis_currency": "EUR",
                "ranked": [
                    {
                        "bid_id": "b1",
                        "bidder_contact_id": "Ridge Groundworks",
                        "headline_amount": "1234567.89",
                        "line_total": "1000.00",
                        "notes": ["lines_disagree_with_total"],
                    }
                ],
            }
        }
        assert await _only(RFQQuoteLinesMatchTotal(), data) == (
            "Quote from Ridge Groundworks offers 1,234,567.89 EUR but its lines add up to "
            "1,000.00 EUR, so the ranking and the detail behind it disagree."
        )


class TestRfqAwardFollowsRanking:
    async def test_the_award_sentence_codes_each_amount_once(self) -> None:
        data = {
            "candidate_bid_id": "b1",
            "comparison": {
                "basis_currency": "EUR",
                "recommended_bid_id": "b2",
                "ranked": [
                    {"bid_id": "b1", "bidder_contact_id": "Ridge", "normalised_amount": "1234567.89"},
                    {"bid_id": "b2", "bidder_contact_id": "Vale", "normalised_amount": "1000.00"},
                ],
            },
        }
        message = await _only(RFQAwardFollowsRanking(), data)
        assert message == (
            "The award goes to Ridge at 1,234,567.89 EUR, while the comparison ranks Vale first at 1,000.00 EUR."
        )
        assert "EUR EUR" not in message

    async def test_a_comparison_without_a_basis_currency_writes_no_code(self) -> None:
        """``basis_currency`` is nullable; the old template printed the word None."""
        data = {
            "candidate_bid_id": "b1",
            "comparison": {
                "basis_currency": None,
                "recommended_bid_id": "b2",
                "ranked": [
                    {"bid_id": "b1", "bidder_contact_id": "Ridge", "normalised_amount": "1234567.89"},
                    {"bid_id": "b2", "bidder_contact_id": "Vale", "normalised_amount": "1000.00"},
                ],
            },
        }
        message = await _only(RFQAwardFollowsRanking(), data)
        assert "None" not in message
        assert message == (
            "The award goes to Ridge at 1,234,567.89, while the comparison ranks Vale first at 1,000.00."
        )

    async def test_an_award_the_comparison_never_ranked_states_that_it_has_no_amount(self) -> None:
        """The awarded quote need not appear in the ranked table at all.

        ``rows`` is keyed on the quotes the comparison ranked, so an award made
        to something outside it leaves an empty row, and the amount the sentence
        wants is simply absent. The words say so. The earlier template reached
        the format spec with that absence still in hand and wrote ``None`` into
        the sentence as though it were a figure.
        """
        data = {
            "candidate_bid_id": "b9",
            "comparison": {
                "basis_currency": "EUR",
                "recommended_bid_id": "b2",
                "ranked": [
                    {"bid_id": "b2", "bidder_contact_id": "Vale", "normalised_amount": "1000.00"},
                ],
            },
        }
        message = await _only(RFQAwardFollowsRanking(), data)
        assert "None" not in message
        assert message == (
            "The award goes to ? at an unstated amount, while the comparison ranks Vale first at 1,000.00 EUR."
        )


# ── formwork: the assignment carries the catalogue system's currency ────────


class TestFormworkBoqPositionLinked:
    async def test_the_unbilled_total_is_grouped_and_coded(self) -> None:
        data = {
            "scope": "assignment",
            "assignment": {
                "id": "a1",
                "system_name": "Wall panel 2.4m",
                "notes": "",
                "boq_position_id": None,
                "computed_total": "1234567.89",
                "currency": "EUR",
            },
        }
        assert await _only(FormworkBoqPositionLinked(), data) == (
            "'Wall panel 2.4m' is not linked to a BOQ position, so its 1,234,567.89 EUR "
            "never reaches the bill of quantities."
        )

    async def test_an_assignment_without_a_currency_is_grouped_but_uncoded(self) -> None:
        data = {
            "scope": "assignment",
            "assignment": {
                "id": "a1",
                "system_name": "Wall panel 2.4m",
                "notes": "",
                "boq_position_id": None,
                "computed_total": "1234567.89",
                "currency": "",
            },
        }
        assert await _only(FormworkBoqPositionLinked(), data) == (
            "'Wall panel 2.4m' is not linked to a BOQ position, so its 1,234,567.89 "
            "never reaches the bill of quantities."
        )


# ── payment_clock: one spelling across the clock, the service and the rules ─


class TestPaymentClockWritesAmountsLikeEverythingElse:
    """``payment_clock.clock.format_money`` was a third way of writing an amount.

    It named the currency, which is more than most of the defects in this file
    did, but it never grouped the digits and never asked the currency how many
    decimals it keeps: ``1234.50 GBP``. Beside ``_fmt_money``'s ``1,234.50 GBP``
    that is a visible difference on one screen, and the module cannot be
    converted a call site at a time, because the same function writes the
    validation messages, the ``explanation`` prose the service returns and the
    ``params`` a screen translates.
    """

    def test_it_agrees_with_the_core_renderer_on_every_shape_of_currency(self) -> None:
        """The point of the change: two names, one spelling.

        Iterated over a two-decimal currency, two zero-decimal ones and a
        three-decimal one, because a second spelling never disagrees on the
        currency its author tested with.
        """
        probe = Decimal("1234567.891")
        for currency in ("EUR", "JPY", "IDR", "KWD", ""):
            assert format_money(probe, currency) == sentence_amount(probe, currency), currency

    def test_the_rendered_forms(self) -> None:
        assert format_money(Decimal("1234567.89"), "EUR") == "1,234,567.89 EUR"
        assert format_money(Decimal("1234567.89"), "JPY") == "1,234,568 JPY"
        assert format_money(Decimal("1234567.89"), "") == "1,234,567.89"

    def test_an_absent_amount_still_says_so_rather_than_printing_none(self) -> None:
        """This branch predates the change and has to survive it."""
        assert format_money(None, "EUR") == "an unstated amount"

    async def test_the_overdue_interest_sentence_groups_its_amount(self) -> None:
        data = {
            "as_of": "2026-05-01",
            "application": {
                "reference": "IA-014",
                "applied_amount": "1234567.89",
                "paid_amount": "1000.00",
                "currency": "EUR",
                "final_date": "2026-04-01",
            },
            "regime": {"statute": "the Housing Grants Act"},
        }
        assert await _only(PaymentClockStatutoryInterest(), data) == (
            "1,233,567.89 EUR has been outstanding for 30 day(s) past the final date for "
            "payment of 2026-04-01, measured against the sum applied for, 1,234,567.89 EUR. "
            "Statutory interest runs at the rate the contract specifies."
        )


# ── einvoice: the same defect, at the precision a document is written in ────


def _party(**over: Any) -> Party:
    base: dict[str, Any] = {
        "name": "Bau GmbH",
        "country_code": "DE",
        "vat_id": "DE123456789",
        "line1": "Baustrasse 1",
        "postcode": "10115",
        "city": "Berlin",
    }
    base.update(over)
    return Party(**base)


def _mismatched_invoice(currency: str) -> EInvoice:
    """An invoice whose VAT group basis disagrees with the lines under it."""
    return EInvoice(
        profile="zugferd",
        invoice_number="RE-2026-001",
        issue_date="2026-08-11",
        currency=currency,
        seller=_party(),
        buyer=_party(name="Stadtwerke AG", vat_id=None),
        lines=[
            EInvoiceLine(
                line_id="1",
                name="Concrete C25/30",
                quantity=Decimal("10"),
                unit="m3",
                net_unit_price=Decimal("123456.789"),
                line_net_amount=Decimal("1234567.89"),
                vat_rate=Decimal("19"),
                vat_category="S",
            )
        ],
        tax_subtotals=[TaxSubtotal(category="S", rate=Decimal("19"), basis=Decimal("1000"), tax_amount=Decimal("190"))],
        line_total=Decimal("1234567.89"),
        tax_basis_total=Decimal("1234567.89"),
        tax_total=Decimal("190"),
        grand_total=Decimal("1234757.89"),
        due_payable=Decimal("1234757.89"),
    )


class TestEinvoiceBreakdownBasisQuotesItsAmounts:
    """``rules.py`` is not a ``validators.py``, and carried the same raw slot.

    This message is prose a person reads while reconciling an invoice, so it is
    rendered rather than interpolated. It is rendered at the **document**
    precision, which is this module's own ``money_decimals`` and not the value
    layer's ``minor_units``: the comparison that produced the finding was made
    by ``_round`` at the document count, so writing the figures at any other
    count could show a reader two numbers that look equal above a sentence
    saying they differ.
    """

    def test_both_figures_are_grouped_and_carry_the_invoice_currency(self) -> None:
        violations = _check_breakdown_basis(_mismatched_invoice("EUR"))
        assert [v.message for v in violations] == [
            "The VAT group for category S at 19% says 1,000.00 EUR but its lines add up to 1,234,567.89 EUR."
        ]

    def test_a_three_decimal_currency_is_written_at_the_two_a_document_allows(self) -> None:
        """KWD keeps three decimals as a value and two on an invoice.

        This is the assertion that would fail if the message were rendered
        through the value layer, and it is the only currency class where the two
        layers part company.
        """
        violations = _check_breakdown_basis(_mismatched_invoice("KWD"))
        assert [v.message for v in violations] == [
            "The VAT group for category S at 19% says 1,000.00 KWD but its lines add up to 1,234,567.89 KWD."
        ]

    def test_a_currency_with_no_subunit_is_written_without_one(self) -> None:
        violations = _check_breakdown_basis(_mismatched_invoice("JPY"))
        assert [v.message for v in violations] == [
            "The VAT group for category S at 19% says 1,000 JPY but its lines add up to 1,234,568 JPY."
        ]
