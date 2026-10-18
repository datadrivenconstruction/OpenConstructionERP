# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment release against figures worked out by hand, to the cent.

Every amount below was computed on paper before the code ran; the comments
show the arithmetic so a reader can redo it. All figures are invented.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.payment_release.release_math import InvoiceEntry, PaymentTerms, PostingEntry, compute_releases

D = Decimal


def _inv(key: str, kind: str, net: str, vat: str, on: date) -> InvoiceEntry:
    return InvoiceEntry(key=key, kind=kind, on=on, net=D(net), vat=D(vat))


def test_incremental_net_retention_rounded_interims_settled_by_the_final() -> None:
    terms = PaymentTerms(
        invoice_mode="incremental",
        retention_percent=D("5"),
        retention_basis="net",
        rounding_enabled=True,
        rounding_step=D("100"),
        currency="EUR",
    )
    ledger = compute_releases(
        terms,
        [
            _inv("i1", "interim", "12345.67", "2345.68", date(2026, 2, 10)),
            _inv("i2", "interim", "8000.00", "1520.00", date(2026, 3, 10)),
            _inv("f", "final", "20345.67", "3865.68", date(2026, 4, 10)),
        ],
    )
    i1, i2, final = (row.effective for row in ledger.rows)
    # 14691.35 gross - 617.28 (5 % of 12345.67) = 14074.07, cut to 14000.
    assert (i1.retention, i1.release_before_rounding, i1.rounding, i1.release) == (
        D("617.28"),
        D("14074.07"),
        D("74.07"),
        D("14000.00"),
    )
    # 9520 - 400 = 9120, cut to 9100; an incremental interim ignores what went before.
    assert (i2.retention, i2.previous_counted, i2.rounding, i2.release) == (
        D("400.00"),
        False,
        D("20.00"),
        D("9100.00"),
    )
    # 24211.35 - 0 (no warranty) - 23100 = 1111.35: retention 1017.28 and rounding 94.07 come back.
    assert (final.retention, final.rounding, final.release) == (D("0.00"), D("0.00"), D("1111.35"))
    assert final.previous_releases == D("23100.00")
    assert ledger.retention_held == D("0.00")
    assert ledger.released_total == final.gross


def test_cumulative_gross_retention_discount_on_interims_and_warranty_on_the_final() -> None:
    terms = PaymentTerms(
        invoice_mode="cumulative",
        retention_percent=D("10"),
        retention_basis="gross",
        warranty_enabled=True,
        warranty_percent=D("3"),
        discount_enabled=True,
        discount_percent=D("2"),
        discount_days=10,
        discount_applies_to="interim",
        rounding_enabled=True,
        rounding_step=D("50"),
        currency="EUR",
    )
    ledger = compute_releases(
        terms,
        [
            _inv("i1", "interim", "10000.00", "1900.00", date(2026, 2, 1)),
            _inv("i2", "interim", "25000.00", "4750.00", date(2026, 3, 1)),
            _inv("f", "final", "30000.00", "5700.00", date(2026, 4, 15)),
        ],
        [PostingEntry(key="p", on=date(2026, 3, 25), amount=D("1000.00"))],
    )
    i1, i2, final = (row.effective for row in ledger.rows)
    # 11900 - 1190 = 10710, cut to 10700; 2 % discount 214, payable 10486, until 11 Feb.
    assert (i1.retention, i1.rounding, i1.release, i1.discount, i1.payable) == (
        D("1190.00"),
        D("10.00"),
        D("10700.00"),
        D("214.00"),
        D("10486.00"),
    )
    assert i1.discount_until == date(2026, 2, 11)
    # 29750 - 2975 - 10700 (before discount) = 16075, cut to 16050; discount 321, payable 15729.
    assert (i2.previous_releases, i2.release_before_rounding, i2.release, i2.discount, i2.payable) == (
        D("10700.00"),
        D("16075.00"),
        D("16050.00"),
        D("321.00"),
        D("15729.00"),
    )
    # 35700 - 1071 (3 % warranty on the gross) - (10700 + 16050 + 1000 posted) = 6879; no discount on a final.
    assert (final.retention, final.previous_releases, final.release, final.discount, final.payable) == (
        D("1071.00"),
        D("27750.00"),
        D("6879.00"),
        D("0.00"),
        D("6879.00"),
    )
    assert ledger.retention_held == D("1071.00")
    assert ledger.released_total + ledger.retention_held == final.gross


def test_a_posting_on_the_day_of_the_final_is_not_paid_twice() -> None:
    terms = PaymentTerms(invoice_mode="incremental", retention_percent=D("10"), currency="EUR")
    ledger = compute_releases(
        terms,
        [
            _inv("i1", "interim", "10000.00", "1900.00", date(2026, 1, 10)),
            _inv("f", "final", "10000.00", "1900.00", date(2026, 2, 1)),
        ],
        [PostingEntry(key="p", on=date(2026, 2, 1), amount=D("1000.00"))],
    )
    i1, final = (row.effective for row in ledger.rows)
    assert i1.release == D("10900.00")
    # 11900 - (10900 + 1000 posted that day) = 0: the retention was paid by the posting.
    assert final.previous_releases == D("11900.00")
    assert final.release == D("0.00")
    assert ledger.retention_held == D("0.00")
    assert ledger.released_total == D("11900.00")


def test_a_posting_on_the_day_of_a_cumulative_interim_is_counted_by_it() -> None:
    terms = PaymentTerms(invoice_mode="cumulative", retention_percent=D("10"), currency="EUR")
    ledger = compute_releases(
        terms,
        [
            _inv("i1", "interim", "10000.00", "1900.00", date(2026, 1, 10)),
            _inv("i2", "interim", "20000.00", "3800.00", date(2026, 2, 1)),
        ],
        [PostingEntry(key="p", on=date(2026, 2, 1), amount=D("500.00"))],
    )
    _i1, i2 = (row.effective for row in ledger.rows)
    # 23800 - 2000 - (10900 + 500) = 10400; paid in all 10900 + 500 + 10400 = 21800 = 23800 - 2000 held.
    assert i2.release == D("10400.00")
    assert ledger.retention_held == D("2000.00")
    assert ledger.released_total + ledger.retention_held == i2.gross
