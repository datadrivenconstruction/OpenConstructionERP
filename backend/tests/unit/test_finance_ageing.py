# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠AR / AP ageing arithmetic.

The ageing report answers "how much is owed, to whom, and how late", per legal
entity, which is the first screen an accounting team that runs several company
accounts opens every morning. The tests pin the definition of an open balance,
because the platform had none: the dashboard counts every unpaid invoice at its
full total, which overstates what is owed as soon as one partial payment lands.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.finance.ageing import (
    BUCKETS,
    AgeingInvoice,
    AgeingPayment,
    build_ageing,
    open_balance,
)

AS_OF = "2026-10-15"


def inv(**kw) -> AgeingInvoice:
    base = dict(
        invoice_id="i1",
        invoice_number="INV-1",
        project_id="p1",
        legal_entity_id="e1",
        contact_id="c1",
        direction="payable",
        status="approved",
        currency_code="CAD",
        invoice_date="2026-08-01",
        due_date="2026-08-31",
        amount_total=Decimal("1000.00"),
        retention_amount=Decimal("0"),
        payments=(),
    )
    base.update(kw)
    return AgeingInvoice(**base)


def test_an_unpaid_invoice_is_owed_in_full_and_aged_from_its_due_date() -> None:
    bal = open_balance(inv(), as_of=AS_OF)
    assert bal.due == Decimal("1000.00")
    assert bal.days_past_due == 45
    assert bal.bucket == "31_60"


def test_a_partial_payment_reduces_what_is_owed() -> None:
    bal = open_balance(inv(payments=(AgeingPayment(amount=Decimal("400"), payment_date="2026-09-10"),)), as_of=AS_OF)
    assert bal.due == Decimal("600.00")


def test_a_payment_after_the_cutoff_does_not_count_yet() -> None:
    bal = open_balance(inv(payments=(AgeingPayment(amount=Decimal("400"), payment_date="2026-10-20"),)), as_of=AS_OF)
    assert bal.due == Decimal("1000.00")


def test_a_refund_puts_the_money_back_on_the_balance() -> None:
    pays = (
        AgeingPayment(amount=Decimal("1000"), payment_date="2026-09-01"),
        AgeingPayment(amount=Decimal("250"), payment_date="2026-09-05", is_refund=True),
    )
    assert open_balance(inv(payments=pays), as_of=AS_OF).due == Decimal("250.00")


def test_holdback_is_owed_but_not_due_and_is_reported_apart() -> None:
    # Ontario: 10% holdback on a progress claim is a liability that is not
    # payable until the lien period ends, so it must not age as overdue.
    bal = open_balance(inv(retention_amount=Decimal("100")), as_of=AS_OF)
    assert bal.due == Decimal("900.00")
    assert bal.retention_held == Decimal("100.00")


def test_holdback_withheld_at_payment_stays_held_until_its_release_date() -> None:
    pay = AgeingPayment(
        amount=Decimal("900"), withholding=Decimal("100"), payment_date="2026-09-01", release_date="2026-12-01"
    )
    bal = open_balance(inv(retention_amount=Decimal("100"), payments=(pay,)), as_of=AS_OF)
    assert bal.due == Decimal("0.00")
    assert bal.retention_held == Decimal("100.00")
    assert bal.retention_released == Decimal("0.00")


def test_holdback_past_its_release_date_becomes_due() -> None:
    pay = AgeingPayment(
        amount=Decimal("900"), withholding=Decimal("100"), payment_date="2026-08-01", release_date="2026-09-15"
    )
    bal = open_balance(inv(retention_amount=Decimal("100"), payments=(pay,)), as_of=AS_OF)
    assert bal.retention_held == Decimal("0.00")
    assert bal.retention_released == Decimal("100.00")


def test_an_overpayment_is_a_credit_not_a_zero() -> None:
    # Clamping at zero would print the same line for an exact payment and for
    # a duplicate one; the second is money to recover.
    bal = open_balance(inv(payments=(AgeingPayment(amount=Decimal("1200"), payment_date="2026-09-01"),)), as_of=AS_OF)
    assert bal.due == Decimal("0.00")
    assert bal.credit == Decimal("200.00")


def test_an_invoice_without_a_due_date_falls_due_after_its_terms() -> None:
    bal = open_balance(inv(due_date=None, payment_terms_days="30"), as_of=AS_OF)
    assert bal.effective_due_date == "2026-08-31"
    no_terms = open_balance(inv(due_date="", payment_terms_days=None), as_of=AS_OF)
    assert no_terms.effective_due_date == "2026-08-01"


@pytest.mark.parametrize(
    ("due", "bucket"),
    [
        ("2026-10-20", "current"),
        ("2026-10-15", "current"),
        ("2026-10-14", "1_30"),
        ("2026-09-15", "1_30"),
        ("2026-09-14", "31_60"),
        ("2026-08-16", "31_60"),
        ("2026-08-15", "61_90"),
        ("2026-07-17", "61_90"),
        ("2026-07-16", "over_90"),
    ],
)
def test_bucket_edges(due: str, bucket: str) -> None:
    assert open_balance(inv(due_date=due), as_of=AS_OF).bucket == bucket


@pytest.mark.parametrize("status", ["draft", "paid", "cancelled", "credit_note_issued"])
def test_only_posted_unsettled_invoices_are_aged(status: str) -> None:
    report = build_ageing([inv(status=status)], as_of=AS_OF)
    assert report.groups == []
    if status == "draft":
        assert report.drafts_excluded == 1


def test_groups_never_blend_entity_currency_or_direction() -> None:
    rows = [
        inv(invoice_id="a", legal_entity_id="e1", currency_code="CAD", direction="payable"),
        inv(invoice_id="b", legal_entity_id="e2", currency_code="CAD", direction="payable"),
        inv(invoice_id="c", legal_entity_id="e1", currency_code="USD", direction="payable"),
        inv(invoice_id="d", legal_entity_id="e1", currency_code="CAD", direction="receivable"),
    ]
    report = build_ageing(rows, as_of=AS_OF)
    keys = {(t.legal_entity_id, t.currency_code, t.direction) for t in report.totals}
    assert keys == {
        ("e1", "CAD", "payable"),
        ("e2", "CAD", "payable"),
        ("e1", "USD", "payable"),
        ("e1", "CAD", "receivable"),
    }


def test_a_counterparty_line_adds_up_to_its_buckets_and_the_total_to_its_lines() -> None:
    rows = [
        inv(invoice_id="a", contact_id="c1", due_date="2026-10-30", amount_total=Decimal("100")),
        inv(invoice_id="b", contact_id="c1", due_date="2026-09-01", amount_total=Decimal("200")),
        inv(
            invoice_id="c",
            contact_id="c2",
            due_date="2026-06-01",
            amount_total=Decimal("300"),
            retention_amount=Decimal("30"),
        ),
    ]
    report = build_ageing(rows, as_of=AS_OF)
    c1 = next(g for g in report.groups if g.contact_id == "c1")
    assert c1.buckets["current"] == Decimal("100.00")
    assert c1.buckets["31_60"] == Decimal("200.00")
    assert c1.total_due == sum(c1.buckets.values()) == Decimal("300.00")
    (total,) = report.totals
    assert total.total_due == sum(g.total_due for g in report.groups) == Decimal("570.00")
    assert total.buckets["over_90"] == Decimal("270.00")
    assert total.retention_held == Decimal("30.00")
    assert set(total.buckets) == set(BUCKETS)


def test_a_counterparty_line_lists_its_invoices_oldest_first() -> None:
    rows = [inv(invoice_id="new", due_date="2026-10-01"), inv(invoice_id="old", due_date="2026-06-01")]
    (group,) = build_ageing(rows, as_of=AS_OF).groups
    assert [line.invoice_id for line in group.invoices] == ["old", "new"]
    assert group.oldest_days_past_due == 136


def test_a_corrupt_amount_does_not_poison_the_report() -> None:
    report = build_ageing([inv(amount_total="not a number"), inv(invoice_id="ok")], as_of=AS_OF)
    (total,) = report.totals
    assert total.total_due == Decimal("1000.00")
