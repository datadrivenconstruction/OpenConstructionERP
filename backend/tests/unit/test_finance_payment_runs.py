# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Payment run rules: what is proposed, what blocks, what the bank receives."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.finance.ageing import AgeingInvoice, AgeingPayment
from app.modules.finance.payment_runs import (
    BANK_CSV_COLUMNS,
    RunLine,
    bank_csv,
    check_run,
    has_errors,
    propose,
)

PAY_ON = "2026-10-23"


def inv(**kw) -> AgeingInvoice:
    base = dict(
        invoice_id="i1",
        invoice_number="AP-1",
        project_id="p1",
        legal_entity_id="e1",
        contact_id="c1",
        direction="payable",
        status="approved",
        currency_code="CAD",
        invoice_date="2026-09-01",
        due_date="2026-10-01",
        amount_total=Decimal("1000.00"),
        retention_amount=Decimal("0"),
        payments=(),
    )
    base.update(kw)
    return AgeingInvoice(**base)


def line(invoice_id: str = "i1", amount: str = "1000.00") -> RunLine:
    return RunLine(
        item_id=f"item-{invoice_id}", invoice_id=invoice_id, invoice_number=f"AP-{invoice_id}", amount=Decimal(amount)
    )


# -- propose ------------------------------------------------------------------


def test_a_partly_paid_invoice_is_proposed_for_what_is_still_open() -> None:
    paid = inv(payments=(AgeingPayment(amount=Decimal("400"), payment_date="2026-10-02"),))
    (proposal,) = propose([paid], currency_code="CAD", payment_date=PAY_ON, due_by=PAY_ON)
    assert proposal.amount == Decimal("600.00")


def test_held_retention_stays_out_of_the_run() -> None:
    (proposal,) = propose(
        [inv(retention_amount=Decimal("100"))], currency_code="CAD", payment_date=PAY_ON, due_by=PAY_ON
    )
    assert proposal.amount == Decimal("900.00")


@pytest.mark.parametrize(
    "other",
    [
        {"direction": "receivable"},
        {"status": "draft"},
        {"status": "paid"},
        {"status": "cancelled"},
        {"currency_code": "USD"},
        {"due_date": "2026-11-15"},
        {"payments": (AgeingPayment(amount=Decimal("1000"), payment_date="2026-10-02"),)},
    ],
)
def test_what_is_not_proposed(other: dict) -> None:
    assert propose([inv(**other)], currency_code="CAD", payment_date=PAY_ON, due_by=PAY_ON) == []


def test_an_invoice_in_another_open_run_is_not_proposed_twice() -> None:
    assert propose([inv()], currency_code="CAD", payment_date=PAY_ON, due_by=PAY_ON, taken=["i1"]) == []


def test_proposals_come_oldest_due_first() -> None:
    rows = [inv(invoice_id="new", due_date="2026-10-20"), inv(invoice_id="old", due_date="2026-08-01")]
    assert [p.invoice_id for p in propose(rows, currency_code="CAD", payment_date=PAY_ON, due_by=PAY_ON)] == [
        "old",
        "new",
    ]


# -- check_run ----------------------------------------------------------------


def codes(issues) -> set[str]:
    return {issue.code for issue in issues}


def test_a_clean_run_has_no_findings() -> None:
    issues = check_run([line()], currency_code="CAD", payment_date=PAY_ON, invoices={"i1": inv()})
    assert issues == []


def test_an_empty_run_cannot_be_approved() -> None:
    issues = check_run([], currency_code="CAD", payment_date=PAY_ON, invoices={})
    assert codes(issues) == {"empty_run"} and has_errors(issues)


def test_paying_more_than_is_open_is_blocked() -> None:
    # A payment recorded by hand after the run was drawn up shrinks what is open.
    paid_meanwhile = inv(payments=(AgeingPayment(amount=Decimal("300"), payment_date="2026-10-10"),))
    issues = check_run([line()], currency_code="CAD", payment_date=PAY_ON, invoices={"i1": paid_meanwhile})
    assert codes(issues) == {"amount_over_open"}
    assert "700.00" in issues[0].message


@pytest.mark.parametrize(
    ("state", "code"),
    [
        ({"status": "cancelled"}, "invoice_not_payable"),
        ({"status": "paid"}, "invoice_not_payable"),
        ({"direction": "receivable"}, "not_a_supplier_invoice"),
        ({"currency_code": "USD"}, "currency_mismatch"),
    ],
)
def test_an_invoice_that_changed_since_the_run_was_drawn_up_blocks_it(state: dict, code: str) -> None:
    issues = check_run([line()], currency_code="CAD", payment_date=PAY_ON, invoices={"i1": inv(**state)})
    assert code in codes(issues) and has_errors(issues)


def test_a_missing_invoice_blocks_the_run() -> None:
    issues = check_run([line()], currency_code="CAD", payment_date=PAY_ON, invoices={})
    assert codes(issues) == {"invoice_missing"}


def test_the_same_invoice_in_two_runs_blocks() -> None:
    issues = check_run(
        [line()], currency_code="CAD", payment_date=PAY_ON, invoices={"i1": inv()}, taken_elsewhere={"i1"}
    )
    assert codes(issues) == {"in_another_run"}


def test_a_zero_amount_blocks() -> None:
    issues = check_run([line(amount="0")], currency_code="CAD", payment_date=PAY_ON, invoices={"i1": inv()})
    assert "amount_not_positive" in codes(issues)


def test_approving_your_own_run_is_a_warning_not_a_block() -> None:
    issues = check_run(
        [line()], currency_code="CAD", payment_date=PAY_ON, invoices={"i1": inv()}, created_by="u1", approver="u1"
    )
    assert codes(issues) == {"same_person"}
    assert not has_errors(issues)


def test_findings_name_the_item_they_belong_to() -> None:
    (issue,) = check_run([line(amount="0")], currency_code="CAD", payment_date=PAY_ON, invoices={"i1": inv()})
    assert issue.item_id == "item-i1" and issue.invoice_id == "i1"


# -- bank_csv -----------------------------------------------------------------


def test_the_remittance_list_has_a_header_and_one_line_per_invoice() -> None:
    text = bank_csv(
        [
            {
                "run_number": "PAY-0001",
                "payment_date": PAY_ON,
                "payee": "Lakeshore Steel, Inc.",
                "payee_id": "c1",
                "invoice_number": "AP-1",
                "amount": "600.00",
                "currency": "CAD",
                "reference": "PAY-0001 AP-1",
            }
        ]
    )
    lines = text.splitlines()
    assert lines[0] == ",".join(BANK_CSV_COLUMNS)
    assert lines[1] == 'PAY-0001,2026-10-23,"Lakeshore Steel, Inc.",c1,AP-1,600.00,CAD,PAY-0001 AP-1'


def test_a_payee_name_that_reads_as_a_formula_is_neutralised() -> None:
    text = bank_csv([{"payee": "=HYPERLINK(1)", "amount": "1.00"}])
    assert "'=HYPERLINK(1)" in text
