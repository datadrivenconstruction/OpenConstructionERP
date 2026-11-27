# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A supplier invoice is weighed against the order or subcontract it bills before it is approved.

Worked example the tests follow. An order for 10,000.00 USD net is issued. A
first invoice of 6,000.00 is approved, leaving 4,000.00 open. A second invoice
of 5,000.00 is 1,000.00 over and its approval is refused with the reason.
Once a change order of 1,000.00 naming that order is approved, the same
approval goes through: the commitment is now 11,000.00 and nothing is open.

The subcontract side reads the agreement value, which approved subcontract
changes already raised, and the retention the agreement agrees.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.ageing import AgeingInvoice
from app.modules.finance.commitment_rules import (
    check_commitment_currency,
    check_commitment_retention,
    check_duplicate_number,
    check_payment_date_before_invoice,
    check_possible_duplicate,
    check_within_commitment,
    is_generated_number,
)
from app.modules.finance.payment_runs import propose
from app.modules.finance.schemas import InvoiceCreate, InvoiceUpdate
from app.modules.finance.service import FinanceService
from tests._pg import transactional_session

VENDOR = str(uuid.uuid4())


def _commitment(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "kind": "purchase_order",
        "ref": "PO-0007",
        "currency_code": "USD",
        "original": "10000.00",
        "approved_changes": "1500.00",
        "invoiced": "9000.00",
        "tolerance": "0.01",
        "retention_percent": "0",
        "retain_on_receipt": False,
    }
    base.update(over)
    return base


def _payload(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "invoice_direction": "payable",
        "invoice_number": "S-1001",
        "contact_id": VENDOR,
        "currency_code": "USD",
        "amount_subtotal": "2500.00",
        "retention_amount": "0",
        "amount_total": "2500.00",
        "invoice_date": "2026-11-02",
        "commitment": _commitment(),
        "same_number": [],
        "same_amount_date": [],
    }
    base.update(over)
    return base


# ── pure checks ──────────────────────────────────────────────────────────────


def test_an_invoice_up_to_the_open_commitment_passes() -> None:
    # 10,000 + 1,500 approved - 9,000 invoiced = 2,500 open.
    assert check_within_commitment(_payload()) == []


def test_an_invoice_over_the_open_commitment_is_refused_with_the_excess() -> None:
    [finding] = check_within_commitment(_payload(amount_subtotal="2600.00"))
    assert finding.details["remaining_net"] == "2500.00"
    assert finding.params["commitment"] == "PO-0007"
    assert "100.00" in finding.params["excess"]


def test_the_order_tolerance_lets_a_small_overrun_through() -> None:
    assert check_within_commitment(_payload(amount_subtotal="2550.00", commitment=_commitment(tolerance="50"))) == []


def test_a_receivable_is_not_weighed() -> None:
    assert check_within_commitment(_payload(invoice_direction="receivable", amount_subtotal="99999")) == []


def test_an_invoice_in_another_currency_is_refused_and_not_weighed() -> None:
    payload = _payload(currency_code="EUR", amount_subtotal="99999")
    assert check_within_commitment(payload) == []
    [finding] = check_commitment_currency(payload)
    assert finding.params == {
        "invoice": "S-1001",
        "commitment": "PO-0007",
        "invoice_currency": "EUR",
        "commitment_currency": "USD",
    }


def test_retention_below_the_agreed_share_is_flagged() -> None:
    commitment = _commitment(kind="subcontract", ref="Concrete", retention_percent="5.00")
    [finding] = check_commitment_retention(
        _payload(amount_subtotal="10000.00", retention_amount="400.00", commitment=commitment)
    )
    assert finding.details["expected_retention"] == "500.00"
    assert (
        check_commitment_retention(
            _payload(amount_subtotal="10000.00", retention_amount="500.00", commitment=commitment)
        )
        == []
    )


def test_retention_taken_at_goods_receipt_is_not_asked_of_the_invoice() -> None:
    commitment = _commitment(retention_percent="5", retain_on_receipt=True)
    assert check_commitment_retention(_payload(amount_subtotal="10000", commitment=commitment)) == []


def test_a_supplier_number_entered_twice_is_refused_but_a_generated_one_is_not() -> None:
    assert check_duplicate_number(_payload(same_number=["x"]))
    assert check_duplicate_number(_payload(invoice_number="INV-P-003", same_number=["x"])) == []
    assert is_generated_number("DE01-INV-P-012")
    assert not is_generated_number("INV-2026-77")


def test_same_supplier_amount_and_date_is_pointed_out() -> None:
    [finding] = check_possible_duplicate(_payload(same_amount_date=["S-0999"]))
    assert finding.params["other"] == "S-0999"
    assert finding.params["on"] == "2026-11-02"


def test_a_payment_cannot_be_scheduled_before_the_invoice_date() -> None:
    assert check_payment_date_before_invoice(_payload(scheduled_payment_date="2026-11-01"))
    assert check_payment_date_before_invoice(_payload(scheduled_payment_date="2026-11-02")) == []


def test_a_payment_run_reads_the_scheduled_payment_date_before_the_due_date() -> None:
    invoice = AgeingInvoice(
        invoice_id="i1",
        invoice_number="S-1",
        project_id="p",
        legal_entity_id=None,
        contact_id=VENDOR,
        direction="payable",
        status="approved",
        currency_code="USD",
        invoice_date="2026-11-01",
        due_date="2026-11-10",
        amount_total="100.00",
        scheduled_payment_date="2026-11-30",
    )
    assert propose([invoice], currency_code="USD", payment_date="2026-11-15", due_by="2026-11-15") == []
    [picked] = propose([invoice], currency_code="USD", payment_date="2026-11-30", due_by="2026-11-30")
    assert picked.amount == Decimal("100.00")


def test_the_pay_summary_holds_retention_on_everything_completed_to_date() -> None:
    from app.modules.finance.commitment import Commitment

    # 20,000 agreed at 5 %; 10,000 billed before, 500 of it held. This invoice bills 4,000.
    commitment = Commitment(
        kind="subcontract",
        id=uuid.uuid4(),
        ref="Concrete",
        project_id=uuid.uuid4(),
        status="active",
        vendor_contact_id=VENDOR,
        currency_code="USD",
        original=Decimal("20000.00"),
        retention_percent=Decimal("5"),
        invoiced=Decimal("10000.00"),
        retained=Decimal("500.00"),
    )
    assert commitment.pay_summary("4000.00", "200.00") == {
        "completed_to_date": "14000.00",
        "retention": "700.00",
        "earned_less_retention": "13300.00",
        "previously_certified": "9500.00",
        "current_due": "3800.00",
        "balance_to_finish": "6000.00",
    }


# ── the gate, on PostgreSQL ──────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as sess:
        yield sess


async def _project(session: AsyncSession, currency: str = "USD") -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"chain-{uuid.uuid4().hex[:10]}@commitment.io",
        hashed_password="x",
        full_name="Commitment Owner",
        role="admin",
    )
    session.add(owner)
    await session.flush()
    project = Project(id=uuid.uuid4(), name="Commitment project", owner_id=owner.id, currency=currency, fx_rates=[])
    session.add(project)
    await session.flush()
    return project.id


async def _order(session: AsyncSession, project_id: uuid.UUID, net: str = "10000.00", **over: object) -> uuid.UUID:
    from app.modules.procurement.models import PurchaseOrder

    po = PurchaseOrder(
        id=uuid.uuid4(),
        project_id=project_id,
        vendor_contact_id=VENDOR,
        po_number=f"PO-{uuid.uuid4().hex[:4]}",
        currency_code="USD",
        amount_subtotal=net,
        tax_amount="0",
        amount_total=net,
        status="issued",
        **over,
    )
    session.add(po)
    await session.flush()
    return po.id


async def _invoice(
    service: FinanceService,
    project_id: uuid.UUID,
    net: str,
    *,
    number: str | None = None,
    currency: str = "USD",
    **links: object,
) -> uuid.UUID:
    invoice = await service.create_invoice(
        InvoiceCreate(
            project_id=project_id,
            contact_id=VENDOR,
            invoice_direction="payable",
            invoice_number=number or f"S-{uuid.uuid4().hex[:6]}",
            invoice_date="2026-11-02",
            currency_code=currency,
            amount_subtotal=net,
            tax_amount="0",
            **links,
        )
    )
    return invoice.id


@pytest.mark.asyncio
async def test_partial_invoices_on_an_order_stop_at_the_commitment_until_a_change_order_covers_it(
    session: AsyncSession,
) -> None:
    from app.modules.changeorders.models import ChangeOrder

    project_id = await _project(session)
    po_id = await _order(session, project_id)
    service = FinanceService(session)
    actor = str(uuid.uuid4())

    first = await _invoice(service, project_id, "6000.00", purchase_order_id=po_id)
    await service.approve_invoice(first, actor_id=actor)

    second = await _invoice(service, project_id, "5000.00", purchase_order_id=po_id)
    check = await service.posting_check(
        {
            "project_id": project_id,
            "invoice_direction": "payable",
            "purchase_order_id": po_id,
            "currency_code": "USD",
            "amount_subtotal": "5000.00",
            "contact_id": VENDOR,
        },
        exclude_invoice_id=second,
    )
    assert check["blocking"] is True
    assert check["commitment"]["remaining"] == "4000.00"
    assert check["summary"]["previously_certified"] == "6000.00"
    assert check["summary"]["current_due"] == "5000.00"
    assert check["summary"]["balance_to_finish"] == "-1000.00"
    with pytest.raises(HTTPException) as refused:
        await service.approve_invoice(second, actor_id=actor)
    assert refused.value.status_code == 422
    assert refused.value.detail["rule_id"] == "invoice_posting.within_commitment"
    assert "1,000.00" in refused.value.detail["message"]

    session.add(
        ChangeOrder(
            project_id=project_id,
            code="CO-001",
            title="Extra rebar",
            status="approved",
            cost_impact=Decimal("1000.00"),
            currency="USD",
            linked_po_ids=[str(po_id)],
        )
    )
    await session.flush()
    approved = await service.approve_invoice(second, actor_id=actor)
    assert approved.status == "approved"
    assert str(approved.approved_by) == actor
    assert approved.approved_at


@pytest.mark.asyncio
async def test_a_change_order_shared_by_several_orders_does_not_raise_either(session: AsyncSession) -> None:
    from app.modules.changeorders.models import ChangeOrder
    from app.modules.finance.commitment import load_commitment

    project_id = await _project(session)
    po_a = await _order(session, project_id)
    po_b = await _order(session, project_id)
    session.add(
        ChangeOrder(
            project_id=project_id,
            code="CO-002",
            title="Shared",
            status="approved",
            cost_impact=Decimal("900"),
            currency="USD",
            linked_po_ids=[str(po_a), str(po_b)],
        )
    )
    await session.flush()
    commitment = await load_commitment(session, purchase_order_id=po_a)
    assert commitment is not None
    assert commitment.approved_changes == Decimal("0")
    assert commitment.shared_change_orders == 1


@pytest.mark.asyncio
async def test_an_invoice_in_another_currency_is_refused_and_not_counted(session: AsyncSession) -> None:
    project_id = await _project(session)
    po_id = await _order(session, project_id)
    service = FinanceService(session)

    eur = await _invoice(service, project_id, "100.00", currency="EUR", purchase_order_id=po_id)
    with pytest.raises(HTTPException) as refused:
        await service.approve_invoice(eur)
    assert refused.value.detail["rule_id"] == "invoice_posting.commitment_currency"

    # Moved to pending (counted as invoiced on the dashboard), it still does not eat the USD commitment.
    await service.update_invoice(eur, InvoiceUpdate(status="pending"))
    usd = await _invoice(service, project_id, "10000.00", purchase_order_id=po_id)
    check = await service.posting_check(
        {
            "project_id": project_id,
            "invoice_direction": "payable",
            "purchase_order_id": po_id,
            "currency_code": "USD",
            "amount_subtotal": "10000.00",
        },
        exclude_invoice_id=usd,
    )
    assert check["commitment"]["invoiced"] == "0"
    assert check["commitment"]["invoices_in_other_currency"] == 1
    assert check["blocking"] is False


async def _agreement(session: AsyncSession, project_id: uuid.UUID, *, status: str = "active") -> uuid.UUID:
    from app.modules.subcontractors.models import SubcontractAgreement, SubcontractChange, Subcontractor

    sub = Subcontractor(id=uuid.uuid4(), legal_name="Concrete Works", contact_id=uuid.UUID(VENDOR))
    session.add(sub)
    await session.flush()
    agreement = SubcontractAgreement(
        id=uuid.uuid4(),
        subcontractor_id=sub.id,
        project_id=project_id,
        title="Concrete package",
        total_value=Decimal("22000.00"),
        currency="USD",
        retention_percent=Decimal("5.00"),
        status=status,
    )
    session.add(agreement)
    await session.flush()
    session.add(
        SubcontractChange(
            agreement_id=agreement.id,
            project_id=project_id,
            code="SC-01",
            title="Extra slab",
            amount=Decimal("2000.00"),
            currency="USD",
            status="approved",
            applied_amount=Decimal("2000.00"),
        )
    )
    await session.flush()
    return agreement.id


@pytest.mark.asyncio
async def test_a_subcontract_invoice_is_weighed_against_the_revised_agreement(session: AsyncSession) -> None:
    project_id = await _project(session)
    agreement_id = await _agreement(session, project_id)
    service = FinanceService(session)

    over = await _invoice(service, project_id, "22001.00", subcontract_agreement_id=agreement_id)
    with pytest.raises(HTTPException) as refused:
        await service.approve_invoice(over)
    assert refused.value.detail["rule_id"] == "invoice_posting.within_commitment"

    exact = await _invoice(service, project_id, "22000.00", subcontract_agreement_id=agreement_id)
    check = await service.posting_check(
        {
            "project_id": project_id,
            "invoice_direction": "payable",
            "subcontract_agreement_id": agreement_id,
            "currency_code": "USD",
            "amount_subtotal": "22000.00",
            "retention_amount": "0",
        },
        exclude_invoice_id=exact,
    )
    assert check["commitment"]["original"] == "20000.00"
    # A 22,000, B 5 % = 1,100, nothing certified before, so 20,900 is due and nothing is left to finish.
    assert check["summary"] == {
        "completed_to_date": "22000.00",
        "retention": "1100.00",
        "earned_less_retention": "20900.00",
        "previously_certified": "0",
        "current_due": "20900.00",
        "balance_to_finish": "0.00",
    }
    assert check["commitment"]["approved_changes"] == "2000.00"
    assert check["blocking"] is False
    retention = [r for r in check["report"]["results"] if r["rule_id"] == "invoice_posting.commitment_retention"]
    assert retention and retention[0]["passed"] is False
    assert (await service.approve_invoice(exact)).status == "approved"


@pytest.mark.asyncio
async def test_a_subcontract_link_is_refused_on_a_draft_agreement_or_beside_an_order(session: AsyncSession) -> None:
    project_id = await _project(session)
    draft = await _agreement(session, project_id, status="draft")
    po_id = await _order(session, project_id)
    service = FinanceService(session)
    with pytest.raises(HTTPException) as refused:
        await _invoice(service, project_id, "1.00", subcontract_agreement_id=draft)
    assert refused.value.status_code == 422
    active = await _agreement(session, project_id)
    with pytest.raises(HTTPException):
        await _invoice(service, project_id, "1.00", subcontract_agreement_id=active, purchase_order_id=po_id)


@pytest.mark.asyncio
async def test_the_same_supplier_number_on_another_project_is_refused_at_approval(session: AsyncSession) -> None:
    service = FinanceService(session)
    first_project = await _project(session)
    second_project = await _project(session)
    await _invoice(service, first_project, "50.00", number="A-77")
    copy = await _invoice(service, second_project, "60.00", number="a 77")
    with pytest.raises(HTTPException) as refused:
        await service.approve_invoice(copy)
    assert refused.value.detail["rule_id"] == "invoice_posting.duplicate_number"


@pytest.mark.asyncio
async def test_a_scheduled_payment_date_before_the_invoice_date_blocks_approval(session: AsyncSession) -> None:
    project_id = await _project(session)
    service = FinanceService(session)
    invoice_id = await _invoice(service, project_id, "10.00", scheduled_payment_date="2026-11-01")
    with pytest.raises(HTTPException) as refused:
        await service.update_invoice(invoice_id, InvoiceUpdate(status="approved"))
    assert refused.value.detail["rule_id"] == "invoice_posting.payment_date_before_invoice"
    await service.update_invoice(invoice_id, InvoiceUpdate(scheduled_payment_date="2026-11-20"))
    approved = await service.update_invoice(invoice_id, InvoiceUpdate(status="approved"), actor_id=None)
    assert approved.status == "approved"
    assert approved.scheduled_payment_date == "2026-11-20"


# ── order lines as a schedule of values ──────────────────────────────────────


def test_an_order_line_billed_past_its_balance_is_refused_unless_changes_cover_it() -> None:
    from app.modules.finance.commitment_rules import check_po_lines_within_balance

    # Rebar scheduled at 6,000: 5,000 billed before, 2,000 now, so 1,000 over.
    lines = [
        {
            "po_line_id": "a",
            "description": "Rebar",
            "scheduled": "6000",
            "previously_invoiced": "5000",
            "this_invoice": "2000",
            "total": "7000",
        },
        {
            "po_line_id": "b",
            "description": "Formwork",
            "scheduled": "4000",
            "previously_invoiced": "0",
            "this_invoice": "0",
            "total": "0",
        },
    ]
    [finding] = check_po_lines_within_balance(_payload(po_lines=lines, commitment=_commitment(approved_changes="0")))
    assert finding.params["line"] == "Rebar"
    assert "1,000.00" in finding.params["excess"]
    assert "1,000.00" in finding.params["balance"]
    covered = _payload(po_lines=lines, commitment=_commitment(approved_changes="1000"))
    assert check_po_lines_within_balance(covered) == []


def test_unallocated_change_orders_are_pointed_out() -> None:
    from app.modules.finance.commitment_rules import check_unallocated_change_orders

    [finding] = check_unallocated_change_orders(_payload(commitment=_commitment(shared_change_orders=2)))
    assert finding.params == {"commitment": "PO-0007", "count": 2}
    assert check_unallocated_change_orders(_payload()) == []


def test_an_approved_invoice_past_its_payment_date_and_not_released_is_flagged() -> None:
    from app.modules.finance.commitment_rules import check_release_overdue

    due = {
        "invoice_direction": "payable",
        "invoice_number": "S-1",
        "status": "approved",
        "scheduled_payment_date": "2026-11-20",
        "today": "2026-11-27",
    }
    assert check_release_overdue(due)
    assert check_release_overdue({**due, "released_at": "2026-11-21T10:00:00+00:00"}) == []
    assert check_release_overdue({**due, "today": "2026-11-20"}) == []
    assert check_release_overdue({**due, "status": "pending"}) == []


@pytest.mark.asyncio
async def test_change_order_allocations_must_add_up_and_a_split_one_must_be_allocated() -> None:
    from app.core.validation.engine import validation_engine
    from app.modules.changeorders.validators import CHANGEORDERS_RULE_SET, register_changeorders_validation_rules

    register_changeorders_validation_rules()
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    base = {
        "id": "co",
        "project_id": "p",
        "code": "CO-003",
        "status": "draft",
        "previous_status": "draft",
        "cost_impact": "900.00",
        "currency": "USD",
        "linked_po_ids": [a, b],
    }

    async def failed(change_order: dict[str, object]) -> set[str]:
        report = await validation_engine.validate(
            data={"change_order": change_order, "items": []}, rule_sets=[CHANGEORDERS_RULE_SET]
        )
        return {r.rule_id for r in report.results if not r.passed}

    assert "changeorders.allocation_needed" in await failed(base)
    short = [{"kind": "purchase_order", "id": a, "amount": "600"}, {"kind": "purchase_order", "id": b, "amount": "200"}]
    assert "changeorders.allocation_matches_amount" in await failed({**base, "commitment_allocations": short})
    exact = [{"kind": "purchase_order", "id": a, "amount": "600"}, {"kind": "purchase_order", "id": b, "amount": "300"}]
    rules = {"changeorders.allocation_matches_amount", "changeorders.allocation_needed"}
    assert not rules & await failed({**base, "commitment_allocations": exact})


@pytest.mark.asyncio
async def test_an_allocated_change_order_raises_each_order_by_its_share(session: AsyncSession) -> None:
    from app.modules.changeorders.models import ChangeOrder
    from app.modules.finance.commitment import load_commitment

    project_id = await _project(session)
    po_a = await _order(session, project_id)
    po_b = await _order(session, project_id)
    session.add(
        ChangeOrder(
            project_id=project_id,
            code="CO-004",
            title="Split",
            status="approved",
            cost_impact=Decimal("900"),
            currency="USD",
            linked_po_ids=[str(po_a), str(po_b)],
            commitment_allocations=[
                {"kind": "purchase_order", "id": str(po_a), "amount": "600"},
                {"kind": "purchase_order", "id": str(po_b), "amount": "300"},
            ],
        )
    )
    await session.flush()
    first = await load_commitment(session, purchase_order_id=po_a)
    second = await load_commitment(session, purchase_order_id=po_b)
    assert first is not None and second is not None
    assert (first.approved_changes, second.approved_changes) == (Decimal("600"), Decimal("300"))
    assert first.shared_change_orders == 0


async def _order_with_lines(session: AsyncSession, project_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    from app.modules.procurement.models import PurchaseOrderItem

    po_id = await _order(session, project_id)
    rebar, formwork = uuid.uuid4(), uuid.uuid4()
    session.add_all(
        [
            PurchaseOrderItem(
                id=rebar, po_id=po_id, description="Rebar", quantity="1", unit_rate="6000", amount="6000.00"
            ),
            PurchaseOrderItem(
                id=formwork,
                po_id=po_id,
                description="Formwork",
                quantity="1",
                unit_rate="4000",
                amount="4000.00",
                sort_order=1,
            ),
        ]
    )
    await session.flush()
    return po_id, rebar, formwork


@pytest.mark.asyncio
async def test_invoice_lines_bill_order_lines_and_stop_at_each_line_balance(session: AsyncSession) -> None:
    from app.modules.changeorders.models import ChangeOrder
    from app.modules.finance.schemas import InvoiceLineItemCreate

    project_id = await _project(session)
    po_id, rebar, _formwork = await _order_with_lines(session, project_id)
    service = FinanceService(session)

    first = await _invoice(
        service,
        project_id,
        "5000.00",
        purchase_order_id=po_id,
        line_items=[InvoiceLineItemCreate(description="Rebar", amount="5000.00", po_line_id=rebar)],
    )
    await service.approve_invoice(first)
    second = await _invoice(
        service,
        project_id,
        "2000.00",
        purchase_order_id=po_id,
        line_items=[InvoiceLineItemCreate(description="Rebar", amount="2000.00", po_line_id=rebar)],
    )
    check = await service.posting_check(
        {
            "project_id": project_id,
            "invoice_direction": "payable",
            "purchase_order_id": po_id,
            "currency_code": "USD",
            "amount_subtotal": "2000.00",
            "lines": [{"po_line_id": rebar, "amount": "2000.00"}],
        },
        exclude_invoice_id=second,
    )
    by_line = {row["description"]: row for row in check["po_lines"]}
    assert by_line["Rebar"] == {
        "po_line_id": str(rebar),
        "description": "Rebar",
        "scheduled": "6000.00",
        "previously_invoiced": "5000.00",
        "previously_paid": "0.00",
        "this_invoice": "2000.00",
        "total": "7000.00",
        "percent_complete": "116.7",
        "balance_to_complete": "-1000.00",
    }
    assert by_line["Formwork"]["balance_to_complete"] == "4000.00"
    assert check["blocking"] is True
    with pytest.raises(HTTPException) as refused:
        await service.approve_invoice(second)
    assert refused.value.detail["rule_id"] == "invoice_posting.po_line_within_balance"

    session.add(
        ChangeOrder(
            project_id=project_id,
            code="CO-005",
            title="More rebar",
            status="approved",
            cost_impact=Decimal("1000.00"),
            currency="USD",
            linked_po_ids=[str(po_id)],
        )
    )
    await session.flush()
    assert (await service.approve_invoice(second)).status == "approved"


@pytest.mark.asyncio
async def test_an_invoice_line_cannot_bill_a_line_of_another_order(session: AsyncSession) -> None:
    from app.modules.finance.schemas import InvoiceLineItemCreate

    project_id = await _project(session)
    _other_po, rebar, _formwork = await _order_with_lines(session, project_id)
    po_id = await _order(session, project_id)
    with pytest.raises(HTTPException) as refused:
        await _invoice(
            FinanceService(session),
            project_id,
            "10.00",
            purchase_order_id=po_id,
            line_items=[InvoiceLineItemCreate(description="Rebar", amount="10.00", po_line_id=rebar)],
        )
    assert refused.value.status_code == 422


@pytest.mark.asyncio
async def test_a_booking_export_releases_an_approved_invoice_once(session: AsyncSession) -> None:
    from app.modules.finance.booking_service import BookingService
    from app.modules.finance.invoice_capture_models import CapturedInvoice
    from app.modules.finance.models import Invoice

    project_id = await _project(session)
    service = FinanceService(session)
    invoice_id = await _invoice(service, project_id, "10.00")
    await service.approve_invoice(invoice_id)
    captured = CapturedInvoice(id=uuid.uuid4(), project_id=project_id, posted_invoice_id=invoice_id)
    session.add(captured)
    await session.flush()
    actor, first_batch, second_batch = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    booking = BookingService(session)
    await booking._mark_released([str(captured.id)], first_batch, str(actor), "2026-11-27T09:00:00+00:00")
    await booking._mark_released([str(captured.id)], second_batch, None, "2026-11-28T09:00:00+00:00")
    invoice = await session.get(Invoice, invoice_id)
    assert invoice is not None
    assert (invoice.released_export_id, invoice.released_by) == (first_batch, actor)
    assert invoice.released_at == "2026-11-27T09:00:00+00:00"


@pytest.mark.asyncio
async def test_an_approved_change_order_can_still_be_split_but_not_repriced(session: AsyncSession) -> None:
    from app.modules.changeorders.models import ChangeOrder
    from app.modules.changeorders.schemas import ChangeOrderUpdate
    from app.modules.changeorders.service import ChangeOrderService
    from app.modules.finance.commitment import load_commitment

    project_id = await _project(session)
    po_a = await _order(session, project_id)
    po_b = await _order(session, project_id)
    order = ChangeOrder(
        project_id=project_id,
        code="CO-006",
        title="Shared",
        status="approved",
        cost_impact=Decimal("900"),
        currency="USD",
        linked_po_ids=[str(po_a), str(po_b)],
    )
    session.add(order)
    await session.flush()
    before = await load_commitment(session, purchase_order_id=po_a)
    assert before is not None
    assert (before.approved_changes, before.shared_change_orders) == (Decimal("0"), 1)

    service = ChangeOrderService(session)
    split = [
        {"kind": "purchase_order", "id": str(po_a), "amount": "700.00"},
        {"kind": "purchase_order", "id": str(po_b), "amount": "200.00"},
    ]
    await service.update_order(order.id, ChangeOrderUpdate(commitment_allocations=split))
    after = await load_commitment(session, purchase_order_id=po_a)
    assert after is not None
    assert (after.approved_changes, after.shared_change_orders) == (Decimal("700.00"), 0)
    with pytest.raises(HTTPException):
        await service.update_order(order.id, ChangeOrderUpdate(cost_impact="1000.00"))
