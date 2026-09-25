# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests - the project cost position (committed, invoiced, paid) and the PO link.

``build_cost_position`` is pure, so every rule its docstring states is pinned
here without a database: the order and its invoice count once, a payment
application draws down its agreement, the VAT share leaves ``paid_net``,
currencies never blend. The end-to-end run through the HTTP API lives in
``tests/integration/test_finance_project_cost_position.py``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.modules.finance.cost_position import (
    AgreementRow,
    InvoiceRow,
    OrderRow,
    PayAppRow,
    PaymentRow,
    build_cost_position,
)
from app.modules.finance.po_link import invoice_po_link

D = Decimal


def _order(net: str, status: str = "issued", currency: str = "EUR") -> OrderRow:
    return OrderRow(id=uuid.uuid4(), status=status, currency=currency, net=D(net))


def _invoice(
    net: str, gross: str, *, po: OrderRow | None = None, status: str = "approved", currency: str = "EUR"
) -> InvoiceRow:
    return InvoiceRow(
        id=uuid.uuid4(),
        status=status,
        currency=currency,
        net=D(net),
        gross=D(gross),
        po_id=po.id if po else None,
    )


def _agreement(value: str, status: str = "active", currency: str = "EUR") -> AgreementRow:
    return AgreementRow(id=uuid.uuid4(), status=status, currency=currency, value=D(value))


def _pay_app(ag: AgreementRow, gross: str, cash: str, status: str = "finance_approved") -> PayAppRow:
    return PayAppRow(agreement_id=ag.id, status=status, currency=ag.currency, gross=D(gross), cash=D(cash))


def test_an_order_and_its_invoice_are_one_commitment() -> None:
    po = _order("50000")
    inv = _invoice("40000", "50000", po=po)
    pos = build_cost_position([po], [inv], [], [], [])
    assert pos.committed == {"EUR": D("50000")}
    assert pos.invoiced == {"EUR": D("40000")}


def test_an_order_invoiced_above_its_value_is_committed_at_the_invoiced_figure() -> None:
    po = _order("50000")
    pos = build_cost_position([po], [_invoice("30000", "37500", po=po), _invoice("25000", "31250", po=po)], [], [], [])
    assert pos.committed == {"EUR": D("55000")}


def test_an_invoice_without_an_order_is_committed_at_its_own_net() -> None:
    pos = build_cost_position([], [_invoice("2000", "2500")], [], [], [])
    assert pos.committed == {"EUR": D("2000")}
    assert pos.invoiced == {"EUR": D("2000")}


def test_an_invoice_linked_to_a_cancelled_order_stands_on_its_own() -> None:
    po = _order("50000", status="cancelled")
    pos = build_cost_position([po], [_invoice("1000", "1250", po=po)], [], [], [])
    assert pos.committed == {"EUR": D("1000")}


def test_a_draft_order_commits_nothing_and_an_approved_one_does() -> None:
    pos = build_cost_position([_order("10", status="draft"), _order("20", status="approved")], [], [], [], [])
    assert pos.committed == {"EUR": D("20")}


def test_draft_cancelled_and_credited_invoices_are_not_invoiced() -> None:
    invoices = [
        _invoice("1", "1", status="draft"),
        _invoice("2", "2", status="cancelled"),
        _invoice("4", "4", status="credit_note_issued"),
        _invoice("8", "10", status="pending"),
    ]
    pos = build_cost_position([], invoices, [], [], [])
    assert pos.invoiced == {"EUR": D("8")}
    assert pos.committed == {"EUR": D("8")}


def test_a_payment_application_draws_down_its_agreement() -> None:
    ag = _agreement("120000")
    app = _pay_app(ag, "30000", "28500", status="paid")
    pos = build_cost_position([], [], [], [ag], [app])
    assert pos.committed == {"EUR": D("120000")}
    assert pos.invoiced == {"EUR": D("30000")}
    assert pos.paid == {"EUR": D("28500")}
    assert pos.paid_net == {"EUR": D("28500")}


def test_an_unapproved_payment_application_is_not_invoiced() -> None:
    ag = _agreement("100")
    pos = build_cost_position([], [], [], [ag], [_pay_app(ag, "40", "38", status="foreman_approved")])
    assert pos.invoiced == {}


def test_a_terminated_agreement_keeps_only_what_was_approved() -> None:
    ag = _agreement("120000", status="terminated")
    pos = build_cost_position([], [], [], [ag], [_pay_app(ag, "30000", "28500")])
    assert pos.committed == {"EUR": D("30000")}


def test_a_draft_agreement_commits_nothing() -> None:
    assert build_cost_position([], [], [], [_agreement("5", status="draft")], []).committed == {}


def test_paid_is_cash_and_paid_net_takes_the_vat_share_out() -> None:
    inv = _invoice("40000", "50000")
    pay = PaymentRow(invoice_id=inv.id, currency="EUR", amount=D("25000"), is_refund=False)
    pos = build_cost_position([], [inv], [pay], [], [])
    assert pos.paid == {"EUR": D("25000")}
    assert pos.paid_net == {"EUR": D("20000")}


def test_a_refund_is_netted_out_of_paid() -> None:
    inv = _invoice("100", "125")
    pays = [
        PaymentRow(invoice_id=inv.id, currency="EUR", amount=D("125"), is_refund=False),
        PaymentRow(invoice_id=inv.id, currency="EUR", amount=D("25"), is_refund=True),
    ]
    pos = build_cost_position([], [inv], pays, [], [])
    assert pos.paid == {"EUR": D("100")}
    assert pos.paid_net == {"EUR": D("80")}


def test_currencies_are_never_blended() -> None:
    po = _order("100", currency="EUR")
    inv_usd = _invoice("90", "90", po=po, currency="USD")
    pos = build_cost_position([po], [inv_usd], [], [_agreement("50", currency="HUF")], [])
    assert pos.committed == {"EUR": D("100"), "USD": D("90"), "HUF": D("50")}
    assert pos.currencies() == {"EUR", "USD", "HUF"}


def test_the_po_link_reads_the_column_first_and_the_legacy_stamp_second() -> None:
    column, stamped = uuid.uuid4(), uuid.uuid4()
    assert invoice_po_link(column, {"po_id": str(stamped)}) == column
    assert invoice_po_link(None, {"po_id": str(stamped)}) == stamped
    assert invoice_po_link(str(column), {}) == column
    assert invoice_po_link(None, {"po_id": "not-a-uuid"}) is None
    assert invoice_po_link(None, None) is None
    assert invoice_po_link("", {"po_id": ""}) is None


def test_an_invoice_marked_paid_without_a_payment_row_still_counts_as_paid() -> None:
    inv = _invoice("40000", "50000", status="paid")
    pos = build_cost_position([], [inv], [], [], [])
    assert pos.paid == {"EUR": D("50000")}
    assert pos.paid_net == {"EUR": D("40000")}


def test_an_invoice_with_its_payments_is_not_counted_again() -> None:
    inv = _invoice("40000", "50000", status="paid")
    pay = PaymentRow(invoice_id=inv.id, currency="EUR", amount=D("50000"), is_refund=False)
    assert build_cost_position([], [inv], [pay], [], []).paid == {"EUR": D("50000")}


def _sub_invoice(ag: AgreementRow, net: str, gross: str, *, pay_app: uuid.UUID | None = None) -> InvoiceRow:
    return InvoiceRow(
        id=uuid.uuid4(),
        status="approved",
        currency=ag.currency,
        net=D(net),
        gross=D(gross),
        po_id=None,
        commitment_id=ag.id,
        pay_app_id=pay_app,
    )


def test_a_subcontract_invoice_draws_down_its_agreement_instead_of_adding_to_it() -> None:
    ag = _agreement("120000")
    pos = build_cost_position([], [_sub_invoice(ag, "30000", "37500")], [], [ag], [])
    assert pos.committed == {"EUR": D("120000")}
    assert pos.invoiced == {"EUR": D("30000")}
    assert pos.subcontract_open == {"EUR": D("90000")}


def test_a_payment_application_with_its_own_invoice_is_counted_once() -> None:
    ag = _agreement("120000")
    app_id = uuid.uuid4()
    app = PayAppRow(
        agreement_id=ag.id, status="finance_approved", currency="EUR", gross=D("30000"), cash=D("28500"), id=app_id
    )
    pos = build_cost_position([], [_sub_invoice(ag, "30000", "37500", pay_app=app_id)], [], [ag], [app])
    assert pos.invoiced == {"EUR": D("30000")}
    assert pos.subcontract_open == {"EUR": D("90000")}


def test_open_subcontract_commitment_never_goes_below_zero() -> None:
    ag = _agreement("100")
    pos = build_cost_position([], [_sub_invoice(ag, "150", "150")], [], [ag], [])
    assert pos.subcontract_open == {"EUR": D("0")}
