"""Deletes high in the property chain no longer take money records with them.

A plot cascades to its sales contracts, their payment schedules and every
instalment. A development cascades to its plots, buyers, escrow accounts and
broker commissions. Each of those records is kept read-only by its own service
method once it holds money or a party relies on it, yet a delete one or two
levels up removed it anyway, and so did rebuilding a suspended payment schedule
and deleting a draft sales contract that had already been paid against.

Each group pairs the guard that was already there with the new refusal and
with the delete or rebuild that must still go through.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.property_dev.models import (
    Buyer,
    BuyerSelection,
    CommissionAccrual,
    CommissionAgreement,
    ContractParty,
    Development,
    EscrowAccount,
    EscrowTransaction,
    Handover,
    Instalment,
    PaymentSchedule,
    Plot,
    Reservation,
    SalesContract,
    WarrantyClaim,
)
from app.modules.property_dev.service import PropertyDevService
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A rolled-back session with FK triggers off, so rows can point at synthetic ids."""
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _add(session: AsyncSession, obj: Any) -> Any:
    session.add(obj)
    await session.flush()
    return obj


async def _exists(session: AsyncSession, model: Any, row_id: uuid.UUID) -> bool:
    return bool(await session.scalar(select(func.count()).select_from(model).where(model.id == row_id)))


async def _development(session: AsyncSession) -> Development:
    return await _add(session, Development(project_id=uuid.uuid4(), code=f"DEV-{uuid.uuid4().hex[:6]}"))


async def _plot(session: AsyncSession, development: Development) -> Plot:
    return await _add(session, Plot(development_id=development.id, plot_number=f"P-{uuid.uuid4().hex[:4]}"))


async def _contract(session: AsyncSession, plot: Plot, status: str = "draft") -> SalesContract:
    return await _add(
        session,
        SalesContract(
            contract_number=f"SPA-{uuid.uuid4().hex[:6]}",
            plot_id=plot.id,
            status=status,
            total_value=Decimal("300000.00"),
            currency="EUR",
        ),
    )


async def _schedule(
    session: AsyncSession,
    contract: SalesContract,
    rows: list[tuple[str, str]],
    *,
    status: str = "active",
    auto_created: bool = True,
) -> PaymentSchedule:
    """A schedule with one instalment per ``(status, amount_paid)`` pair."""
    schedule = await _add(
        session,
        PaymentSchedule(
            sales_contract_id=contract.id,
            currency="EUR",
            total_amount=Decimal("300000.00"),
            status=status,
            metadata_={"auto_created": auto_created},
        ),
    )
    for sequence, (row_status, paid) in enumerate(rows, start=1):
        await _add(
            session,
            Instalment(
                schedule_id=schedule.id,
                sequence=sequence,
                amount=Decimal("100000.00"),
                amount_paid=Decimal(paid),
                status=row_status,
            ),
        )
    return schedule


async def _refused(call: Any) -> str:
    with pytest.raises(HTTPException) as exc:
        await call
    assert exc.value.status_code == 409
    return str(exc.value.detail)


# ── Plot ─────────────────────────────────────────────────────────────────────


async def test_control_a_signed_contract_is_still_not_deleted_on_its_own(session: AsyncSession) -> None:
    svc = PropertyDevService(session)
    contract = await _contract(session, await _plot(session, await _development(session)), status="signed")

    detail = await _refused(svc.delete_spa(contract.id))

    assert "Only draft" in detail
    assert await _exists(session, SalesContract, contract.id)


async def test_a_plot_under_a_signed_contract_is_not_deleted(session: AsyncSession) -> None:
    svc = PropertyDevService(session)
    plot = await _plot(session, await _development(session))
    contract = await _contract(session, plot, status="signed")

    detail = await _refused(svc.delete_plot(plot.id))

    assert "1 sales contract past draft" in detail
    assert await _exists(session, Plot, plot.id)
    assert await _exists(session, SalesContract, contract.id)


async def test_a_plot_whose_draft_contract_was_paid_against_is_not_deleted(session: AsyncSession) -> None:
    svc = PropertyDevService(session)
    plot = await _plot(session, await _development(session))
    await _schedule(session, await _contract(session, plot), [("paid", "100000.00"), ("pending", "0")])

    detail = await _refused(svc.delete_plot(plot.id))

    assert "1 paid or waived instalment" in detail
    assert "sales contract past draft" not in detail, "the contract is still a draft, only its money holds"
    assert await _exists(session, Plot, plot.id)


async def test_a_plot_with_a_deposit_a_handover_and_a_claim_names_all_three(session: AsyncSession) -> None:
    svc = PropertyDevService(session)
    plot = await _plot(session, await _development(session))
    await _add(session, Reservation(plot_id=plot.id, reservation_number="R-1", deposit_amount=Decimal("5000.00")))
    await _add(session, Handover(plot_id=plot.id, completed_at="2026-09-01"))
    await _add(session, WarrantyClaim(plot_id=plot.id, buyer_id=uuid.uuid4(), description="Leak"))

    detail = await _refused(svc.delete_plot(plot.id))

    assert "1 reservation with a deposit, 1 completed handover and 1 warranty claim" in detail
    assert await _exists(session, Plot, plot.id)


async def test_a_plot_without_a_sales_history_is_deleted(session: AsyncSession) -> None:
    svc = PropertyDevService(session)
    plot = await _plot(session, await _development(session))
    await _schedule(session, await _contract(session, plot), [("pending", "0"), ("due", "0")])
    await _add(session, Reservation(plot_id=plot.id, reservation_number="R-2", deposit_amount=Decimal("0")))
    await _add(session, Handover(plot_id=plot.id, scheduled_at="2026-12-01"))

    await svc.delete_plot(plot.id)

    assert not await _exists(session, Plot, plot.id)


# ── Development ──────────────────────────────────────────────────────────────


async def test_a_development_with_a_signed_plot_is_not_deleted(session: AsyncSession) -> None:
    svc = PropertyDevService(session)
    development = await _development(session)
    await _contract(session, await _plot(session, development), status="countersigned")
    await _plot(session, development)

    detail = await _refused(svc.delete_development(development.id))

    assert "1 sales contract past draft" in detail
    assert "completed or paused" in detail
    assert await _exists(session, Development, development.id)


async def test_a_development_with_escrow_commission_and_a_locked_selection_is_not_deleted(
    session: AsyncSession,
) -> None:
    svc = PropertyDevService(session)
    development = await _development(session)
    account = await _add(session, EscrowAccount(development_id=development.id))
    await _add(session, EscrowTransaction(escrow_account_id=account.id, amount=Decimal("100000.00")))
    broker_id = uuid.uuid4()
    agreement = await _add(session, CommissionAgreement(broker_id=broker_id, development_id=development.id))
    await _add(session, CommissionAccrual(agreement_id=agreement.id, broker_id=broker_id))
    buyer = await _add(session, Buyer(development_id=development.id))
    await _add(session, BuyerSelection(buyer_id=buyer.id, status="locked"))

    detail = await _refused(svc.delete_development(development.id))

    assert "1 escrow transaction, 1 broker commission accrual and 1 locked option selection" in detail
    assert await _exists(session, Development, development.id)


async def test_a_development_that_took_no_money_is_deleted(session: AsyncSession) -> None:
    svc = PropertyDevService(session)
    development = await _development(session)
    plot = await _plot(session, development)
    await _contract(session, plot)
    buyer = await _add(session, Buyer(development_id=development.id))
    await _add(session, BuyerSelection(buyer_id=buyer.id, status="submitted"))

    await svc.delete_development(development.id)

    assert not await _exists(session, Development, development.id)


# ── Draft sales contract ─────────────────────────────────────────────────────


@pytest.mark.parametrize(("row_status", "paid"), [("paid", "100000.00"), ("waived", "0"), ("due", "25000.00")])
async def test_a_draft_contract_that_holds_money_is_not_deleted(
    session: AsyncSession, row_status: str, paid: str
) -> None:
    svc = PropertyDevService(session)
    contract = await _contract(session, await _plot(session, await _development(session)))
    await _schedule(session, contract, [(row_status, paid)])

    detail = await _refused(svc.delete_spa(contract.id))

    assert "1 paid or waived instalment" in detail
    assert "Cancel it instead" in detail
    assert await _exists(session, SalesContract, contract.id)


async def test_a_draft_contract_with_nothing_paid_is_deleted(session: AsyncSession) -> None:
    svc = PropertyDevService(session)
    contract = await _contract(session, await _plot(session, await _development(session)))
    await _schedule(session, contract, [("pending", "0"), ("due", "0")])

    await svc.delete_spa(contract.id)

    assert not await _exists(session, SalesContract, contract.id)


# ── Payment schedule rebuild ─────────────────────────────────────────────────


async def test_control_a_live_schedule_with_a_due_row_is_still_not_rebuilt(session: AsyncSession) -> None:
    svc = PropertyDevService(session)
    contract = await _contract(session, await _plot(session, await _development(session)))
    await _schedule(session, contract, [("due", "0")], auto_created=False)

    detail = await _refused(svc.generate_payment_schedule_from_template(contract.id, template_key="single_balance"))

    assert "suspend it first" in detail


@pytest.mark.parametrize(
    ("schedule_status", "row_status", "paid"),
    [("suspended", "paid", "100000.00"), ("cancelled", "pending", "40000.00"), ("suspended", "waived", "0")],
)
async def test_a_schedule_that_holds_money_is_not_rebuilt_in_any_state(
    session: AsyncSession, schedule_status: str, row_status: str, paid: str
) -> None:
    svc = PropertyDevService(session)
    contract = await _contract(session, await _plot(session, await _development(session)))
    schedule = await _schedule(session, contract, [(row_status, paid), ("pending", "0")], status=schedule_status)

    detail = await _refused(svc.generate_payment_schedule_from_template(contract.id, template_key="single_balance"))

    assert "1 paid or waived instalment" in detail
    assert "new SPA revision" in detail
    rows = (await session.execute(select(Instalment).where(Instalment.schedule_id == schedule.id))).scalars().all()
    assert sorted((r.status, r.amount_paid) for r in rows) == sorted([(row_status, Decimal(paid)), ("pending", 0)])


async def test_a_suspended_schedule_with_nothing_paid_is_rebuilt(session: AsyncSession) -> None:
    svc = PropertyDevService(session)
    contract = await _contract(session, await _plot(session, await _development(session)))
    schedule = await _schedule(
        session, contract, [("due", "0"), ("overdue", "0"), ("pending", "0")], status="suspended"
    )

    rebuilt = await svc.generate_payment_schedule_from_template(contract.id, template_key="single_balance")

    assert rebuilt.id == schedule.id
    rows = (await session.execute(select(Instalment).where(Instalment.schedule_id == schedule.id))).scalars().all()
    assert [r.amount for r in rows] == [Decimal("300000.00")]


# ── Buyer and option selection ───────────────────────────────────────────────


async def test_a_buyer_on_a_signed_contract_with_a_locked_selection_and_a_claim_is_not_deleted(
    session: AsyncSession,
) -> None:
    svc = PropertyDevService(session)
    development = await _development(session)
    plot = await _plot(session, development)
    buyer = await _add(session, Buyer(development_id=development.id, full_name="A. Buyer"))
    await _add(
        session, ContractParty(sales_contract_id=(await _contract(session, plot, "signed")).id, buyer_id=buyer.id)
    )
    await _add(session, BuyerSelection(buyer_id=buyer.id, status="locked"))
    await _add(session, WarrantyClaim(plot_id=plot.id, buyer_id=buyer.id, description="Crack"))

    detail = await _refused(svc.delete_buyer(buyer.id))

    assert "1 sales contract past draft, 1 locked option selection and 1 warranty claim" in detail
    assert await _exists(session, Buyer, buyer.id)


async def test_a_buyer_on_a_draft_contract_only_is_deleted(session: AsyncSession) -> None:
    svc = PropertyDevService(session)
    development = await _development(session)
    buyer = await _add(session, Buyer(development_id=development.id))
    contract = await _contract(session, await _plot(session, development))
    await _add(session, ContractParty(sales_contract_id=contract.id, buyer_id=buyer.id))
    await _add(session, BuyerSelection(buyer_id=buyer.id, status="draft"))

    await svc.delete_buyer(buyer.id)

    assert not await _exists(session, Buyer, buyer.id)


async def test_a_locked_selection_is_not_deleted_and_a_submitted_one_is(session: AsyncSession) -> None:
    svc = PropertyDevService(session)
    buyer = await _add(session, Buyer(development_id=(await _development(session)).id))
    locked = await _add(session, BuyerSelection(buyer_id=buyer.id, status="locked"))
    submitted = await _add(session, BuyerSelection(buyer_id=buyer.id, status="submitted"))

    detail = await _refused(svc.delete_selection(locked.id))
    await svc.delete_selection(submitted.id)

    assert "Cancel it instead" in detail
    assert await _exists(session, BuyerSelection, locked.id)
    assert not await _exists(session, BuyerSelection, submitted.id)
