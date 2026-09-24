# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Closing a contract must not forget the retention it holds.

The Close button posted the final value and a status and nothing else. The
schema filled the rest with 0, so closing a contract that held retention
wrote a final account saying none was ever held, or overwrote an agreed one
with zeros. The checklist reads retention from the final account once it
exists, so from then on it reported "No retention was withheld on this
contract" and the money dropped out of every close-out view.

Each test posts exactly what the button posts, built through the request
schema so an omitted field is omitted, and reads the result back through the
checklist, which is where the loss showed.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.contracts.models import Contract, FinalAccount, ProgressClaim
from app.modules.contracts.schemas import FinalAccountCreate
from app.modules.contracts.service import ContractsService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"close-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _contract_holding_retention(s) -> Contract:
    """Total 10,000; an approved claim holds 500 and a paid one 200 (net 1,800)."""
    project = Project(id=uuid.uuid4(), name="Close", owner_id=OWNER_ID, currency="USD", country_code="US")
    s.add(project)
    await s.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        currency="USD",
        total_value=Decimal("10000"),
        retention_percent=Decimal("10"),
        status="active",
    )
    s.add(contract)
    await s.flush()
    for number, (gross, status) in enumerate([("5000", "approved"), ("2000", "paid")], start=1):
        amount = Decimal(gross)
        s.add(
            ProgressClaim(
                id=uuid.uuid4(),
                contract_id=contract.id,
                claim_number=f"PC-{number}",
                currency="USD",
                status=status,
                gross_amount=amount,
                retention_amount=amount / 10,
                net_due=amount - amount / 10,
            )
        )
    await s.flush()
    return contract


def _what_the_close_button_posts(contract: Contract) -> FinalAccountCreate:
    # A status and no figures: restating the contract value overwrote a final
    # account agreed at a negotiated figure, so the button stopped sending it.
    return FinalAccountCreate.model_validate({"contract_id": str(contract.id), "status": "agreed"})


async def _retention_item(svc: ContractsService, contract: Contract) -> dict:
    checklist = await svc.final_account_checklist(contract.id)
    [item] = [i for i in checklist["items"] if i["key"] == "retention_released"]
    return item


async def test_closing_keeps_the_retention_the_claims_hold(session) -> None:
    svc = ContractsService(session)
    contract = await _contract_holding_retention(session)

    final = await svc.close_contract(contract.id, _what_the_close_button_posts(contract), "u1")
    assert final.retention_held == Decimal("700")
    assert final.retention_released == Decimal("0")
    assert final.total_paid == Decimal("1800")
    assert final.final_balance == Decimal("8200")

    item = await _retention_item(svc, contract)
    assert item["status"] == "fail"
    assert item["based_on"]["retention_outstanding"] == "700.0000"


async def test_closing_again_keeps_an_agreed_final_account(session) -> None:
    svc = ContractsService(session)
    contract = await _contract_holding_retention(session)
    session.add(
        FinalAccount(
            contract_id=contract.id,
            final_contract_value=Decimal("10000"),
            total_paid=Decimal("5000"),
            retention_held=Decimal("900"),
            retention_released=Decimal("100"),
            final_balance=Decimal("5000"),
            status="draft",
        )
    )
    await session.flush()

    final = await svc.close_contract(contract.id, _what_the_close_button_posts(contract), "u1")
    # The agreed figures stand; the button said nothing about them.
    assert (final.retention_held, final.retention_released, final.total_paid) == (
        Decimal("900"),
        Decimal("100"),
        Decimal("5000"),
    )
    assert final.final_balance == Decimal("5000")
    assert final.status == "agreed"
    assert (await _retention_item(svc, contract))["based_on"]["retention_outstanding"] == "800.0000"


async def test_a_figure_the_request_states_is_the_figure_even_when_zero(session) -> None:
    svc = ContractsService(session)
    contract = await _contract_holding_retention(session)
    payload = FinalAccountCreate.model_validate(
        {
            "contract_id": str(contract.id),
            "final_contract_value": "10000",
            "retention_held": "700",
            "retention_released": "700",
            "total_paid": "10000",
            "final_balance": "0",
            "status": "agreed",
        }
    )
    final = await svc.close_contract(contract.id, payload, "u1")
    assert (final.retention_released, final.final_balance) == (Decimal("700"), Decimal("0"))
    assert (await _retention_item(svc, contract))["status"] == "pass"


async def test_creating_a_final_account_without_figures_reads_them_from_the_claims(session) -> None:
    svc = ContractsService(session)
    contract = await _contract_holding_retention(session)
    created = await svc.create_final_account(FinalAccountCreate.model_validate({"contract_id": str(contract.id)}))
    assert (created.final_contract_value, created.retention_held, created.total_paid) == (
        Decimal("10000"),
        Decimal("700"),
        Decimal("1800"),
    )
