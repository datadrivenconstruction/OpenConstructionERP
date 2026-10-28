# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Statement of account: lines, running balance, brought and carried forward."""

from __future__ import annotations

from decimal import Decimal

from app.modules.finance.account_statement import build_statement
from app.modules.finance.ageing import AgeingInvoice, AgeingPayment


def inv(**kw) -> AgeingInvoice:
    base = dict(
        invoice_id="i1",
        invoice_number="AR-1",
        project_id="p1",
        legal_entity_id="e1",
        contact_id="c1",
        direction="receivable",
        status="sent",
        currency_code="CAD",
        invoice_date="2026-09-05",
        due_date="2026-10-05",
        amount_total=Decimal("1000.00"),
        retention_amount=Decimal("0"),
        payments=(),
    )
    base.update(kw)
    return AgeingInvoice(**base)


def pay(amount: str, on: str, *, refund: bool = False) -> AgeingPayment:
    return AgeingPayment(amount=Decimal(amount), payment_date=on, is_refund=refund)


def test_lines_run_in_date_order_with_a_running_balance() -> None:
    rows = [
        inv(invoice_id="a", invoice_number="AR-1", invoice_date="2026-09-05", payments=(pay("400", "2026-09-20"),)),
        inv(invoice_id="b", invoice_number="AR-2", invoice_date="2026-09-10", amount_total=Decimal("250")),
    ]
    st = build_statement(rows, date_from="2026-09-01", date_to="2026-09-30")
    assert [(l.entry_date, l.kind, l.reference, l.balance) for l in st.lines] == [
        ("2026-09-05", "invoice", "AR-1", Decimal("1000.00")),
        ("2026-09-10", "invoice", "AR-2", Decimal("1250.00")),
        ("2026-09-20", "payment", "AR-1", Decimal("850.00")),
    ]
    assert st.opening_balance == Decimal("0")
    assert st.closing_balance == Decimal("850.00")
    assert st.total_charged == Decimal("1250.00") and st.total_credited == Decimal("400.00")


def test_what_happened_before_the_period_is_brought_forward() -> None:
    rows = [
        inv(invoice_id="old", invoice_date="2026-08-01", payments=(pay("300", "2026-08-15"),)),
        inv(invoice_id="new", invoice_number="AR-2", invoice_date="2026-09-03", amount_total=Decimal("200")),
    ]
    st = build_statement(rows, date_from="2026-09-01", date_to="2026-09-30")
    assert st.opening_balance == Decimal("700.00")
    assert [l.reference for l in st.lines] == ["AR-2"]
    assert st.lines[0].balance == Decimal("900.00")
    assert st.closing_balance == Decimal("900.00")


def test_what_happens_after_the_period_is_left_out() -> None:
    st = build_statement([inv(payments=(pay("1000", "2026-10-02"),))], date_from="2026-09-01", date_to="2026-09-30")
    assert st.closing_balance == Decimal("1000.00")
    assert [l.kind for l in st.lines] == ["invoice"]


def test_a_refund_puts_money_back_on_the_balance() -> None:
    st = build_statement(
        [inv(payments=(pay("1000", "2026-09-10"), pay("100", "2026-09-12", refund=True)))],
        date_from=None,
        date_to="2026-09-30",
    )
    assert [(l.kind, l.balance) for l in st.lines] == [
        ("invoice", Decimal("1000.00")),
        ("payment", Decimal("0.00")),
        ("refund", Decimal("100.00")),
    ]


def test_a_same_day_invoice_and_payment_never_dip_below_zero() -> None:
    st = build_statement([inv(payments=(pay("1000", "2026-09-05"),))], date_from=None, date_to="2026-09-30")
    assert [l.balance for l in st.lines] == [Decimal("1000.00"), Decimal("0.00")]


def test_a_paid_invoice_stays_on_the_statement_but_drafts_and_cancelled_do_not() -> None:
    rows = [
        inv(invoice_id="p", status="paid", payments=(pay("1000", "2026-09-10"),)),
        inv(invoice_id="d", invoice_number="AR-D", status="draft"),
        inv(invoice_id="x", invoice_number="AR-X", status="cancelled"),
    ]
    st = build_statement(rows, date_from=None, date_to="2026-09-30")
    assert {l.invoice_id for l in st.lines} == {"p"}
    assert st.closing_balance == Decimal("0.00")


def test_the_ageing_below_the_lines_keeps_retention_apart() -> None:
    st = build_statement(
        [inv(retention_amount=Decimal("100"), due_date="2026-08-20")], date_from=None, date_to="2026-09-30"
    )
    assert st.closing_balance == Decimal("1000.00")  # retention is owed, so it is on the balance
    assert st.ageing is not None
    (total,) = st.ageing.totals
    assert total.total_due == Decimal("900.00")
    assert total.retention_held == Decimal("100.00")
    assert total.buckets["31_60"] == Decimal("900.00")
