# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure-logic unit tests for the finance retention / withholding ledger.

These tests touch no database and import nothing from SQLAlchemy or FastAPI.
They pin the exact Decimal arithmetic that rolls stored invoice retention and
payment withholding into held / released / outstanding figures per counterparty
and for the whole project. Money is asserted as exact Decimal (never float) - a
silent drift here would mis-state every retainage balance a project reports.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.finance.retention_ledger import (
    InvoiceRetention,
    PaymentWithholding,
    RetentionLedger,
    _is_released,
    _pct,
    _to_decimal,
    build_retention_ledger,
    summarize_retention,
)

# -- _to_decimal: tolerant coercion -------------------------------------------


def test_to_decimal_passthrough_decimal() -> None:
    assert _to_decimal(Decimal("1.5")) == Decimal("1.5")


def test_to_decimal_none_is_zero() -> None:
    assert _to_decimal(None) == Decimal("0")


def test_to_decimal_garbage_is_zero() -> None:
    assert _to_decimal("not-a-number") == Decimal("0")


def test_to_decimal_non_finite_is_zero() -> None:
    # NaN / Infinity must never poison a sum.
    assert _to_decimal(Decimal("NaN")) == Decimal("0")
    assert _to_decimal(Decimal("Infinity")) == Decimal("0")


def test_to_decimal_float_via_str_no_artifact() -> None:
    # Coercion goes through str(), so 0.1 stays 0.1 (not 0.1000000000000000055).
    assert _to_decimal(0.1) == Decimal("0.1")


def test_to_decimal_string_input() -> None:
    assert _to_decimal("2500.00") == Decimal("2500.00")


# -- _pct: guarded division ---------------------------------------------------


def test_pct_zero_denominator_returns_none() -> None:
    assert _pct(Decimal("1"), Decimal("0")) is None


def test_pct_both_zero_returns_none() -> None:
    assert _pct(Decimal("0"), Decimal("0")) is None


def test_pct_quarter_is_25() -> None:
    assert _pct(Decimal("250"), Decimal("1000")) == Decimal("25.00")


def test_pct_over_one_hundred() -> None:
    # An inconsistent ratio above 100% is reported truthfully, not capped.
    assert _pct(Decimal("150"), Decimal("100")) == Decimal("150.00")


# -- _is_released: release-date semantics -------------------------------------


def test_is_released_no_date_never() -> None:
    assert _is_released(None, "2026-07-16") is False
    assert _is_released("", "2026-07-16") is False


def test_is_released_no_cutoff_any_dated_counts() -> None:
    assert _is_released("2020-01-01", None) is True


def test_is_released_date_reached() -> None:
    assert _is_released("2026-01-01", "2026-07-16") is True


def test_is_released_date_equal_is_released() -> None:
    assert _is_released("2026-07-16", "2026-07-16") is True


def test_is_released_date_in_future_not_yet() -> None:
    assert _is_released("2027-01-01", "2026-07-16") is False


# -- summarize_retention: pure arithmetic core --------------------------------


def test_summarize_all_zero_guards_are_none() -> None:
    rollup = summarize_retention("0", "0")
    assert rollup.held_to_date == Decimal("0.00")
    assert rollup.released_to_date == Decimal("0.00")
    assert rollup.outstanding == Decimal("0.00")
    # Every ratio has a zero (or absent) denominator -> None, never a bogus 0%.
    assert rollup.released_pct is None
    assert rollup.outstanding_pct is None
    assert rollup.held_vs_scheduled_pct is None


def test_summarize_scheduled_zero_guard() -> None:
    rollup = summarize_retention("100", "0", scheduled="0")
    # held is non-zero so released/outstanding ratios resolve...
    assert rollup.released_pct == Decimal("0.00")
    assert rollup.outstanding_pct == Decimal("100.00")
    # ...but scheduled is zero, so held-vs-scheduled stays guarded.
    assert rollup.held_vs_scheduled_pct is None


def test_summarize_normal_case() -> None:
    rollup = summarize_retention("1000", "250", scheduled="1000", payment_count=3)
    assert rollup.held_to_date == Decimal("1000.00")
    assert rollup.released_to_date == Decimal("250.00")
    assert rollup.outstanding == Decimal("750.00")
    assert rollup.scheduled == Decimal("1000.00")
    assert rollup.released_pct == Decimal("25.00")
    assert rollup.outstanding_pct == Decimal("75.00")
    assert rollup.held_vs_scheduled_pct == Decimal("100.00")
    assert rollup.payment_count == 3


def test_summarize_released_exceeds_held_clamped() -> None:
    # A released figure larger than held (inconsistent input) must never produce
    # a negative outstanding liability - it clamps to zero.
    rollup = summarize_retention("100", "150")
    assert rollup.held_to_date == Decimal("100.00")
    assert rollup.released_to_date == Decimal("150.00")
    assert rollup.outstanding == Decimal("0.00")
    assert rollup.released_pct == Decimal("150.00")
    assert rollup.outstanding_pct == Decimal("0.00")


def test_summarize_scheduled_none_omitted() -> None:
    rollup = summarize_retention("500", "100")
    assert rollup.scheduled == Decimal("0")
    assert rollup.held_vs_scheduled_pct is None


# -- build_retention_ledger: empty inputs -------------------------------------


def test_build_empty_no_invoices() -> None:
    ledger = build_retention_ledger([])
    assert isinstance(ledger, RetentionLedger)
    assert ledger.groups == []
    assert ledger.totals == []
    assert ledger.as_of is None


def test_build_empty_echoes_as_of() -> None:
    ledger = build_retention_ledger([], as_of="2026-07-16")
    assert ledger.as_of == "2026-07-16"
    assert ledger.groups == []
    assert ledger.totals == []


# -- build_retention_ledger: the normal case ----------------------------------


def test_build_normal_single_contract_fully_released() -> None:
    ledger = build_retention_ledger(
        [
            InvoiceRetention(
                contact_id="c1",
                currency_code="EUR",
                direction="receivable",
                retention_amount="5000",
                payments=[
                    PaymentWithholding(withholding_amount="5000", release_date="2026-01-01"),
                ],
            )
        ],
        as_of="2026-07-16",
    )
    assert len(ledger.groups) == 1
    group = ledger.groups[0]
    assert group.contact_id == "c1"
    assert group.currency_code == "EUR"
    assert group.direction == "receivable"
    assert group.scheduled == Decimal("5000.00")
    assert group.held_to_date == Decimal("5000.00")
    assert group.released_to_date == Decimal("5000.00")
    assert group.outstanding == Decimal("0.00")
    assert group.released_pct == Decimal("100.00")
    assert group.held_vs_scheduled_pct == Decimal("100.00")
    assert group.payment_count == 1
    assert group.earliest_release_date == "2026-01-01"
    assert group.latest_release_date == "2026-01-01"
    # A single-contract project rolls up to exactly one total mirroring it.
    assert len(ledger.totals) == 1
    total = ledger.totals[0]
    assert total.contact_id is None
    assert total.held_to_date == Decimal("5000.00")
    assert total.outstanding == Decimal("0.00")


def test_build_release_date_in_future_stays_outstanding() -> None:
    ledger = build_retention_ledger(
        [
            InvoiceRetention(
                contact_id="c1",
                currency_code="EUR",
                direction="receivable",
                retention_amount="5000",
                payments=[
                    PaymentWithholding(withholding_amount="5000", release_date="2027-01-01"),
                ],
            )
        ],
        as_of="2026-07-16",
    )
    group = ledger.groups[0]
    assert group.held_to_date == Decimal("5000.00")
    assert group.released_to_date == Decimal("0.00")
    assert group.outstanding == Decimal("5000.00")
    assert group.released_pct == Decimal("0.00")
    assert group.outstanding_pct == Decimal("100.00")


def test_build_release_date_none_never_released() -> None:
    ledger = build_retention_ledger(
        [
            InvoiceRetention(
                contact_id="c1",
                currency_code="EUR",
                direction="payable",
                retention_amount="0",
                payments=[
                    PaymentWithholding(withholding_amount="1200", release_date=None),
                ],
            )
        ],
        as_of="2026-07-16",
    )
    group = ledger.groups[0]
    assert group.held_to_date == Decimal("1200.00")
    assert group.released_to_date == Decimal("0.00")
    assert group.outstanding == Decimal("1200.00")
    assert group.earliest_release_date is None
    assert group.latest_release_date is None


def test_build_as_of_none_treats_dated_as_released() -> None:
    ledger = build_retention_ledger(
        [
            InvoiceRetention(
                contact_id="c1",
                currency_code="EUR",
                direction="receivable",
                retention_amount="0",
                payments=[
                    PaymentWithholding(withholding_amount="1000", release_date="2020-01-01"),
                    PaymentWithholding(withholding_amount="500", release_date=None),
                ],
            )
        ],
    )
    group = ledger.groups[0]
    assert group.held_to_date == Decimal("1500.00")
    # No cutoff: the dated 1000 counts as released, the undated 500 does not.
    assert group.released_to_date == Decimal("1000.00")
    assert group.outstanding == Decimal("500.00")
    assert group.payment_count == 2


def test_build_scheduled_only_no_payments() -> None:
    # Retention planned on the invoice but nothing paid / withheld yet.
    ledger = build_retention_ledger(
        [
            InvoiceRetention(
                contact_id="c1",
                currency_code="EUR",
                direction="receivable",
                retention_amount="1000",
                payments=[],
            )
        ],
        as_of="2026-07-16",
    )
    group = ledger.groups[0]
    assert group.scheduled == Decimal("1000.00")
    assert group.held_to_date == Decimal("0.00")
    assert group.outstanding == Decimal("0.00")
    assert group.payment_count == 0
    # held is zero -> the released ratio is guarded, but held-vs-scheduled is 0%.
    assert group.released_pct is None
    assert group.outstanding_pct is None
    assert group.held_vs_scheduled_pct == Decimal("0.00")


def test_build_zero_withholding_payment_skipped() -> None:
    ledger = build_retention_ledger(
        [
            InvoiceRetention(
                contact_id="c1",
                currency_code="EUR",
                direction="receivable",
                retention_amount="0",
                payments=[
                    PaymentWithholding(withholding_amount="0", release_date="2026-01-01"),
                ],
            )
        ],
        as_of="2026-07-16",
    )
    group = ledger.groups[0]
    assert group.held_to_date == Decimal("0.00")
    assert group.payment_count == 0
    assert group.earliest_release_date is None


# -- build_retention_ledger: Decimal exactness --------------------------------


def test_build_decimal_exactness_point_one_plus_point_two() -> None:
    # The classic float trap: 0.1 + 0.2 must sum to exactly 0.30, not
    # 0.30000000000000004. Held is accumulated as Decimal, then quantized.
    ledger = build_retention_ledger(
        [
            InvoiceRetention(
                contact_id="c1",
                currency_code="EUR",
                direction="receivable",
                retention_amount="0",
                payments=[
                    PaymentWithholding(withholding_amount=Decimal("0.1"), release_date=None),
                    PaymentWithholding(withholding_amount=Decimal("0.2"), release_date=None),
                ],
            )
        ],
        as_of="2026-07-16",
    )
    assert ledger.groups[0].held_to_date == Decimal("0.30")


def test_build_decimal_exactness_string_inputs() -> None:
    ledger = build_retention_ledger(
        [
            InvoiceRetention(
                contact_id="c1",
                currency_code="EUR",
                direction="receivable",
                retention_amount="0",
                payments=[
                    PaymentWithholding(withholding_amount="0.1", release_date=None),
                    PaymentWithholding(withholding_amount="0.2", release_date=None),
                ],
            )
        ],
    )
    assert ledger.groups[0].held_to_date == Decimal("0.30")


# -- build_retention_ledger: multi-contract rollup ----------------------------


def test_build_multi_contract_rollup() -> None:
    ledger = build_retention_ledger(
        [
            InvoiceRetention(
                contact_id="c2",
                currency_code="EUR",
                direction="receivable",
                retention_amount="700",
                payments=[
                    PaymentWithholding(withholding_amount="700", release_date="2027-06-01"),
                ],
            ),
            InvoiceRetention(
                contact_id="c1",
                currency_code="EUR",
                direction="receivable",
                retention_amount="300",
                payments=[
                    PaymentWithholding(withholding_amount="300", release_date="2026-01-01"),
                ],
            ),
        ],
        as_of="2026-07-16",
    )
    # Two contact lines, sorted deterministically by contact id (c1 before c2).
    assert [g.contact_id for g in ledger.groups] == ["c1", "c2"]
    c1, c2 = ledger.groups
    assert c1.held_to_date == Decimal("300.00")
    assert c1.released_to_date == Decimal("300.00")  # release date reached
    assert c1.outstanding == Decimal("0.00")
    assert c2.held_to_date == Decimal("700.00")
    assert c2.released_to_date == Decimal("0.00")  # release date still future
    assert c2.outstanding == Decimal("700.00")
    # One combined total across both contacts (same currency + direction).
    assert len(ledger.totals) == 1
    total = ledger.totals[0]
    assert total.contact_id is None
    assert total.held_to_date == Decimal("1000.00")
    assert total.released_to_date == Decimal("300.00")
    assert total.outstanding == Decimal("700.00")
    assert total.scheduled == Decimal("1000.00")
    assert total.payment_count == 2
    assert total.released_pct == Decimal("30.00")


def test_build_multiple_payments_same_contract_widens_date_span() -> None:
    ledger = build_retention_ledger(
        [
            InvoiceRetention(
                contact_id="c1",
                currency_code="EUR",
                direction="receivable",
                retention_amount="0",
                payments=[
                    PaymentWithholding(withholding_amount="100", release_date="2026-03-01"),
                    PaymentWithholding(withholding_amount="200", release_date="2026-09-01"),
                    PaymentWithholding(withholding_amount="300", release_date="2026-06-01"),
                ],
            )
        ],
        as_of="2026-07-16",
    )
    group = ledger.groups[0]
    assert group.held_to_date == Decimal("600.00")
    # Only the two payments dated on/before 2026-07-16 are released (100 + 300).
    assert group.released_to_date == Decimal("400.00")
    assert group.outstanding == Decimal("200.00")
    assert group.payment_count == 3
    assert group.earliest_release_date == "2026-03-01"
    assert group.latest_release_date == "2026-09-01"


# -- build_retention_ledger: never blend currency or direction ----------------


def test_build_never_blends_currencies() -> None:
    ledger = build_retention_ledger(
        [
            InvoiceRetention(
                contact_id="c1",
                currency_code="EUR",
                direction="receivable",
                retention_amount="0",
                payments=[PaymentWithholding(withholding_amount="100", release_date=None)],
            ),
            InvoiceRetention(
                contact_id="c1",
                currency_code="USD",
                direction="receivable",
                retention_amount="0",
                payments=[PaymentWithholding(withholding_amount="200", release_date=None)],
            ),
        ],
        as_of="2026-07-16",
    )
    # Same contact, two currencies -> two separate groups and two separate
    # totals; EUR 100 and USD 200 are never summed into one blended figure.
    assert len(ledger.groups) == 2
    assert len(ledger.totals) == 2
    by_currency = {t.currency_code: t.held_to_date for t in ledger.totals}
    assert by_currency == {"EUR": Decimal("100.00"), "USD": Decimal("200.00")}


def test_build_never_blends_direction() -> None:
    ledger = build_retention_ledger(
        [
            InvoiceRetention(
                contact_id="c1",
                currency_code="EUR",
                direction="payable",
                retention_amount="0",
                payments=[PaymentWithholding(withholding_amount="100", release_date=None)],
            ),
            InvoiceRetention(
                contact_id="c1",
                currency_code="EUR",
                direction="receivable",
                retention_amount="0",
                payments=[PaymentWithholding(withholding_amount="200", release_date=None)],
            ),
        ],
        as_of="2026-07-16",
    )
    assert len(ledger.totals) == 2
    by_direction = {t.direction: t.held_to_date for t in ledger.totals}
    assert by_direction == {"payable": Decimal("100.00"), "receivable": Decimal("200.00")}


def test_build_none_contact_sorts_last() -> None:
    ledger = build_retention_ledger(
        [
            InvoiceRetention(
                contact_id=None,
                currency_code="EUR",
                direction="receivable",
                retention_amount="0",
                payments=[PaymentWithholding(withholding_amount="50", release_date=None)],
            ),
            InvoiceRetention(
                contact_id="c1",
                currency_code="EUR",
                direction="receivable",
                retention_amount="0",
                payments=[PaymentWithholding(withholding_amount="60", release_date=None)],
            ),
        ],
        as_of="2026-07-16",
    )
    # Named contact first, the unattributed (None) line last.
    assert [g.contact_id for g in ledger.groups] == ["c1", None]
