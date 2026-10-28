# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠What each supplier was paid over a reporting period, as an annual payee return reads it."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.finance.ageing import AgeingInvoice, AgeingPayment
from app.modules.finance.payee_totals import build_payee_totals, payee_return_for


def inv(**kw) -> AgeingInvoice:
    base = dict(
        invoice_id="i1",
        invoice_number="AP-1",
        project_id="p1",
        legal_entity_id="e1",
        contact_id="steel",
        direction="payable",
        status="paid",
        currency_code="CAD",
        invoice_date="2026-01-05",
        due_date="2026-02-05",
        amount_total=Decimal("10000"),
        retention_amount=Decimal("0"),
        payments=(),
    )
    base.update(kw)
    return AgeingInvoice(**base)


def pay(amount: str, on: str, *, refund: bool = False) -> AgeingPayment:
    return AgeingPayment(amount=Decimal(amount), payment_date=on, is_refund=refund)


YEAR = {"date_from": "2026-01-01", "date_to": "2026-12-31"}


def test_payments_in_the_period_add_up_per_payee_across_invoices_and_projects() -> None:
    rows = build_payee_totals(
        [
            inv(payments=(pay("4000", "2026-02-01"), pay("6000", "2026-03-01"))),
            inv(invoice_id="i2", project_id="p2", payments=(pay("2500", "2026-11-30"),)),
            inv(invoice_id="i3", contact_id="drywall", payments=(pay("800", "2026-06-01"),)),
        ],
        **YEAR,
    )
    assert [(r.contact_id, r.total, r.payment_count) for r in rows] == [
        ("steel", Decimal("12500.00"), 3),
        ("drywall", Decimal("800.00"), 1),
    ]
    assert rows[0].invoice_ids == {"i1", "i2"} and rows[0].project_ids == {"p1", "p2"}


def test_the_period_is_the_payment_date_not_the_invoice_date() -> None:
    rows = build_payee_totals(
        [inv(invoice_date="2025-12-20", payments=(pay("1000", "2025-12-31"), pay("3000", "2026-01-02")))], **YEAR
    )
    assert [r.total for r in rows] == [Decimal("3000.00")]


def test_a_refund_takes_money_back_and_a_payee_netting_to_nothing_is_left_out() -> None:
    rows = build_payee_totals(
        [
            inv(payments=(pay("1000", "2026-04-01"), pay("200", "2026-04-15", refund=True))),
            inv(
                invoice_id="i2",
                contact_id="gone",
                payments=(pay("50", "2026-05-01"), pay("50", "2026-05-02", refund=True)),
            ),
        ],
        **YEAR,
    )
    assert [(r.contact_id, r.total) for r in rows] == [("steel", Decimal("800.00"))]


def test_receivables_entities_and_currencies_stay_apart() -> None:
    rows = build_payee_totals(
        [
            inv(payments=(pay("1000", "2026-04-01"),)),
            inv(invoice_id="r", direction="receivable", payments=(pay("9000", "2026-04-01"),)),
            inv(invoice_id="u", currency_code="USD", payments=(pay("700", "2026-04-01"),)),
            inv(invoice_id="e2", legal_entity_id="e2", payments=(pay("300", "2026-04-01"),)),
        ],
        **YEAR,
    )
    assert sorted((r.legal_entity_id, r.currency_code, r.total) for r in rows) == [
        ("e1", "CAD", Decimal("1000.00")),
        ("e1", "USD", Decimal("700.00")),
        ("e2", "CAD", Decimal("300.00")),
    ]


def test_the_threshold_marks_small_payees_only_in_its_own_currency() -> None:
    rows = build_payee_totals(
        [
            inv(payments=(pay("499.99", "2026-04-01"),)),
            inv(invoice_id="i2", contact_id="big", payments=(pay("500", "2026-04-01"),)),
            inv(invoice_id="u", contact_id="usd", currency_code="USD", payments=(pay("10", "2026-04-01"),)),
        ],
        threshold=Decimal("500"),
        threshold_currency="CAD",
        **YEAR,
    )
    assert {r.contact_id: r.below_threshold for r in rows} == {"steel": True, "big": False, "usd": False}


def test_a_reversed_period_is_refused() -> None:
    with pytest.raises(ValueError):
        build_payee_totals([], date_from="2026-12-31", date_to="2026-01-01")


def test_canada_names_the_t5018_and_others_have_no_return_yet() -> None:
    ca = payee_return_for("ca")
    assert ca is not None and ca["form"] == "T5018" and ca["threshold"] == "500"
    assert payee_return_for("DE") is None and payee_return_for(None) is None
