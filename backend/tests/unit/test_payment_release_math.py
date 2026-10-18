# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The payment release computation, to the cent.

All figures are invented. Each case walks one contract's invoices in order and
checks every step the release view prints: net, deductions, VAT, gross,
previous releases, retention, rounding, release, early payment discount and
the amount to pay.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.payment_release.release_math import (
    InvoiceEntry,
    PaymentTerms,
    PostingEntry,
    VatLine,
    compute_releases,
    measured_value,
    vat_on_deduction,
)

D = Decimal


def _inv(key: str, kind: str, net: str, vat: str, on: date | None = None, **kw) -> InvoiceEntry:
    return InvoiceEntry(key=key, kind=kind, on=on, net=D(net), vat=D(vat), **kw)


# ── Cumulative mode: each interim states the total to date ───────────────


def test_cumulative_interim_then_final_with_retention_rounding_and_discount() -> None:
    terms = PaymentTerms(
        invoice_mode="cumulative",
        retention_percent=D("10"),
        retention_basis="gross",
        rounding_enabled=True,
        rounding_step=D("1000"),
        discount_enabled=True,
        discount_percent=D("2"),
        discount_days=14,
        discount_applies_to="final",
        interim_due_days=21,
        final_due_days=30,
    )
    ledger = compute_releases(
        terms,
        [
            _inv("i1", "interim", "6000.00", "1140.00", date(2026, 3, 1)),
            _inv("f", "final", "10000.00", "1900.00", date(2026, 6, 1)),
        ],
    )
    first, final = (row.effective for row in ledger.rows)

    assert first.gross == D("7140.00")
    assert first.previous_releases == D("0.00")
    assert first.retention == D("714.00")
    assert first.release_before_rounding == D("6426.00")
    assert first.rounding == D("426.00")
    assert first.release == D("6000.00")
    assert first.discount == D("0.00")  # the discount is agreed on the final only
    assert first.payable == D("6000.00")
    assert first.due_on == date(2026, 3, 22)

    assert final.gross == D("11900.00")
    assert final.previous_releases == D("6000.00")
    assert final.previous_counted is True
    assert final.retention_percent == D("0")  # no warranty retention agreed
    assert final.retention == D("0.00")
    assert final.rounding == D("0.00")  # a final is never rounded, nothing would follow it
    assert final.release == D("5900.00")
    assert final.discount == D("118.00")
    assert final.payable == D("5782.00")
    assert final.discount_until == date(2026, 6, 15)
    assert final.due_on == date(2026, 7, 1)
    assert ledger.retention_held == D("0.00")


def test_the_rounding_remainder_comes_back_on_the_next_cumulative_invoice() -> None:
    terms = PaymentTerms(invoice_mode="cumulative", rounding_enabled=True, rounding_step=D("100"))
    ledger = compute_releases(
        terms,
        [
            _inv("a", "interim", "1234.56", "0"),
            _inv("b", "interim", "2000.00", "0"),
        ],
    )
    a, b = (row.effective for row in ledger.rows)
    assert (a.release, a.rounding) == (D("1200.00"), D("34.56"))
    # 2000 - 1200 = 800 exactly: the 34.56 held back last time is part of it.
    assert (b.previous_releases, b.release, b.rounding) == (D("1200.00"), D("800.00"), D("0.00"))


def test_a_warranty_retention_is_held_on_the_final_and_released_by_a_posting() -> None:
    terms = PaymentTerms(
        invoice_mode="cumulative", retention_percent=D("10"), warranty_enabled=True, warranty_percent=D("5")
    )
    ledger = compute_releases(
        terms,
        [
            _inv("i1", "interim", "50000.00", "0", date(2026, 1, 31)),
            _inv("f", "final", "80000.00", "0", date(2026, 5, 31)),
        ],
        [PostingEntry(key="p", on=date(2027, 6, 1), amount=D("4000.00"))],
    )
    i1, final = (row.effective for row in ledger.rows)
    assert i1.retention == D("5000.00")
    assert i1.retention_held_after == D("5000.00")
    assert final.retention_percent == D("5")
    assert final.retention == D("4000.00")
    assert final.release == D("80000.00") - D("4000.00") - D("45000.00")
    # The final replaces the interim holding: 5000 held becomes 4000.
    assert final.retention_held_after == D("4000.00")
    assert ledger.retention_posted == D("4000.00")
    assert ledger.retention_held == D("0.00")


def test_a_posting_before_the_final_counts_as_a_previous_release() -> None:
    terms = PaymentTerms(invoice_mode="cumulative", retention_percent=D("10"), retention_basis="gross")
    ledger = compute_releases(
        terms,
        [
            _inv("i1", "interim", "6000.00", "1140.00", date(2026, 3, 1)),
            _inv("f", "final", "10000.00", "1900.00", date(2026, 9, 1)),
        ],
        [PostingEntry(key="p", on=date(2026, 6, 1), amount=D("714.00"))],
    )
    i1, final = (row.effective for row in ledger.rows)
    assert i1.release == D("6426.00")
    assert final.previous_releases == D("7140.00")
    assert final.release == D("4760.00")
    # Paid in all: 6426 + 714 + 4760 = 11900, the final gross.
    assert i1.release + D("714.00") + final.release == final.gross


def test_a_falling_cumulative_total_gives_a_negative_release_without_rounding_or_discount() -> None:
    terms = PaymentTerms(
        invoice_mode="cumulative",
        rounding_enabled=True,
        rounding_step=D("100"),
        discount_enabled=True,
        discount_percent=D("3"),
    )
    ledger = compute_releases(terms, [_inv("a", "interim", "1000", "0"), _inv("b", "interim", "800", "0")])
    a, b = (row.effective for row in ledger.rows)
    assert a.release == D("1000.00")
    assert b.release_before_rounding == D("-200.00")
    assert (b.rounding, b.discount, b.release, b.payable) == (D("0.00"), D("0.00"), D("-200.00"), D("-200.00"))


# ── Incremental mode: each interim bills only the new work ──────────────


def test_incremental_interims_ignore_previous_releases_and_the_final_settles_them() -> None:
    terms = PaymentTerms(invoice_mode="incremental", retention_percent=D("5"))
    ledger = compute_releases(
        terms,
        [
            _inv("i1", "interim", "4000.00", "760.00"),
            _inv("i2", "interim", "3000.00", "570.00"),
            _inv("f", "final", "10000.00", "1900.00"),
        ],
    )
    i1, i2, final = (row.effective for row in ledger.rows)
    assert (i1.retention, i1.release, i1.previous_counted) == (D("200.00"), D("4560.00"), False)
    assert (i2.previous_releases, i2.release) == (D("4560.00"), D("3420.00"))
    assert i2.retention_held_after == D("350.00")
    # The final is a statement of the whole contract: everything held comes back.
    assert final.previous_counted is True
    assert final.previous_releases == D("7980.00")
    assert final.release == D("11900.00") - D("7980.00")
    assert final.retention_held_after == D("0.00")


def test_retention_on_the_net_is_the_default_basis() -> None:
    terms = PaymentTerms(retention_percent=D("10"))
    (row,) = compute_releases(terms, [_inv("a", "interim", "1000.00", "190.00")]).rows
    assert row.effective.retention_base == D("1000.00")
    assert row.effective.retention == D("100.00")
    assert row.effective.release == D("1090.00")


def test_daywork_and_credit_notes_add_to_the_contract_and_skip_the_series() -> None:
    terms = PaymentTerms(
        invoice_mode="cumulative",
        retention_percent=D("10"),
        rounding_enabled=True,
        rounding_step=D("100"),
        discount_enabled=True,
        discount_percent=D("2"),
        discount_applies_to="interim",
    )
    ledger = compute_releases(
        terms,
        [
            _inv("i1", "interim", "1000.00", "0"),
            _inv("dw", "daywork", "333.33", "0"),
            _inv("cn", "credit_note", "-50.00", "0"),
            _inv("i2", "interim", "2000.00", "0"),
        ],
    )
    i1, dw, cn, i2 = (row.effective for row in ledger.rows)
    assert (dw.retention, dw.rounding, dw.release) == (D("0.00"), D("0.00"), D("333.33"))
    assert dw.discount == D("6.67")
    assert (cn.release, cn.discount, cn.payable) == (D("-50.00"), D("0.00"), D("-50.00"))
    # Day work and credit notes stay out of the cumulative series' previous releases.
    assert i2.previous_releases == i1.release == D("900.00")
    assert i2.release == D("1800.00") - D("900.00")


def test_a_claim_invoice_keeps_the_retention_its_claim_certified() -> None:
    terms = PaymentTerms(retention_percent=D("10"))
    (row,) = compute_releases(terms, [_inv("c", "interim", "1000.00", "0", fixed_retention=D("25.00"))]).rows
    assert row.effective.retention == D("25.00")
    assert row.effective.retention_source == "claim"
    assert row.effective.release == D("975.00")


# ── Deductions and VAT ──────────────────────────────────────────────────


def test_a_net_deduction_takes_its_vat_line_by_line() -> None:
    lines = (VatLine(net=D("600.00"), rate=D("19")), VatLine(net=D("400.00"), rate=D("7")))
    assert vat_on_deduction(D("100.00"), net=D("1000.00"), vat=D("142.00"), lines=lines) == D("14.20")
    terms = PaymentTerms()
    (row,) = compute_releases(
        terms,
        [
            _inv(
                "a",
                "interim",
                "1000.00",
                "142.00",
                net_deduction=D("100.00"),
                gross_deduction=D("20.00"),
                vat_lines=lines,
            )
        ],
    ).rows
    r = row.effective
    assert (r.net_after, r.vat_deduction, r.vat_after) == (D("900.00"), D("14.20"), D("127.80"))
    assert (r.gross, r.gross_after, r.release) == (D("1027.80"), D("1007.80"), D("1007.80"))


def test_a_reverse_charged_invoice_carries_no_vat_on_its_deduction() -> None:
    lines = (VatLine(net=D("500.00"), rate=D("0")),)
    assert vat_on_deduction(D("50.00"), net=D("500.00"), vat=D("0"), lines=lines) == D("0.00")


def test_lines_without_a_rate_take_the_rate_the_invoice_states() -> None:
    lines = (VatLine(net=D("1000.00"), rate=None),)
    assert vat_on_deduction(D("10.00"), net=D("1000.00"), vat=D("190.00"), lines=lines) == D("1.90")
    assert vat_on_deduction(D("10.00"), net=D("1000.00"), vat=D("190.00"), lines=()) == D("1.90")


def test_currency_without_minor_units_rounds_to_whole_units() -> None:
    terms = PaymentTerms(retention_percent=D("5"), currency="JPY")
    (row,) = compute_releases(terms, [_inv("a", "interim", "12345", "1234")]).rows
    assert row.effective.retention == D("617")
    assert row.effective.release == D("12962")


# ── Frozen releases ─────────────────────────────────────────────────────


def test_a_released_invoice_keeps_its_figures_and_the_next_one_builds_on_them() -> None:
    terms = PaymentTerms(invoice_mode="cumulative", retention_percent=D("10"))
    first = compute_releases(terms, [_inv("a", "interim", "1000.00", "0")]).rows[0].computed
    # The terms change after the release: the frozen figures stay, the recomputed ones differ.
    later = PaymentTerms(invoice_mode="cumulative", retention_percent=D("5"))
    ledger = compute_releases(
        later,
        [_inv("a", "interim", "1000.00", "0", frozen=first), _inv("b", "interim", "2000.00", "0")],
    )
    a, b = ledger.rows
    assert a.effective.release == D("900.00")
    assert a.computed.release == D("950.00")
    assert a.differs is True
    assert b.effective.previous_releases == D("900.00")
    assert b.effective.release == D("2000.00") - D("100.00") - D("900.00")


def test_unknown_kind_or_mode_is_refused() -> None:
    with pytest.raises(ValueError):
        compute_releases(PaymentTerms(invoice_mode="sideways"), [])
    with pytest.raises(ValueError):
        compute_releases(PaymentTerms(), [_inv("a", "advance", "1", "0")])


# ── Measured value ──────────────────────────────────────────────────────


def test_measured_value_is_quantity_times_rate_to_the_cent() -> None:
    assert measured_value(D("12.345"), D("10.10")) == D("124.68")
    assert measured_value(D("0"), D("99")) == D("0.00")
    assert measured_value(D("3"), D("1000"), currency="JPY") == D("3000")
