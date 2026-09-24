# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Closing a contract does not restate a final account somebody signed off.

``close_contract`` creates the final account, or updates the one already
there, and completes the contract. It used to write the request's figures and
status over an existing account whatever state it was in. The Close button
stated the contract value, so an account agreed at a negotiated figure was
overwritten with the contract sum the moment somebody pressed Close, and a
second close through the API could restate a closed account, move it back to
agreed, or skip the lifecycle from draft straight to closed. The final-account
lifecycle check existed and nothing called it.

Now an existing account moves only along its lifecycle, an agreed or closed
one keeps its figures (a restated different figure is 409 and writes nothing)
and its sign-off and notes when the request leaves them out. What the button
posts, a status and no figures, closes every one of these cleanly.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select

from app.modules.contracts.models import Contract, FinalAccount
from app.modules.contracts.schemas import FinalAccountCreate
from app.modules.contracts.service import ContractsService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()
CONTRACT_SUM = Decimal("10000")
#: What the parties agreed, deliberately unlike the contract sum so a
#: restatement from the contract cannot pass for the agreed figure.
AGREED_VALUE = Decimal("9800")
AGREED_PAID = Decimal("9000")
AGREED_BALANCE = Decimal("800")
SIGNED_ON = "2026-09-01"
SIGNED_BY = "Commercial manager"
NOTES = "Agreed at the close-out meeting"


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"fa-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _contract_with_final_account(s, fa_status: str) -> tuple[Contract, FinalAccount]:
    project = Project(id=uuid.uuid4(), name="Close-out", owner_id=OWNER_ID, currency="EUR")
    s.add(project)
    await s.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        currency="EUR",
        total_value=CONTRACT_SUM,
        status="active",
    )
    s.add(contract)
    await s.flush()
    account = FinalAccount(
        contract_id=contract.id,
        final_contract_value=AGREED_VALUE,
        total_paid=AGREED_PAID,
        retention_held=Decimal("490"),
        retention_released=Decimal("0"),
        final_balance=AGREED_BALANCE,
        sign_off_date=SIGNED_ON,
        sign_off_by=SIGNED_BY,
        status=fa_status,
        notes=NOTES,
    )
    s.add(account)
    await s.flush()
    return contract, account


def _payload(contract: Contract, **fields: str) -> FinalAccountCreate:
    return FinalAccountCreate.model_validate({"contract_id": str(contract.id), **fields})


def _button(contract: Contract) -> FinalAccountCreate:
    """What the Close button posts: a status and no figures."""
    return _payload(contract, status="agreed")


async def _reread(s, contract: Contract, account: FinalAccount) -> tuple[Contract, FinalAccount]:
    await s.refresh(contract)
    await s.refresh(account)
    return contract, account


def _figures(account: FinalAccount) -> tuple[Decimal, Decimal, Decimal]:
    return (
        Decimal(str(account.final_contract_value)),
        Decimal(str(account.total_paid)),
        Decimal(str(account.final_balance)),
    )


async def test_the_button_closes_a_contract_whose_final_account_is_agreed(session) -> None:
    contract, account = await _contract_with_final_account(session, "agreed")

    final = await ContractsService(session).close_contract(contract.id, _button(contract), "someone-else")

    contract, account = await _reread(session, contract, account)
    assert contract.status == "completed"
    assert final.id == account.id
    assert account.status == "agreed"
    # The agreed figure, not the contract sum.
    assert _figures(account) == (AGREED_VALUE, AGREED_PAID, AGREED_BALANCE)
    # Who signed it off and when is part of what was agreed.
    assert (account.sign_off_date, account.sign_off_by, account.notes) == (SIGNED_ON, SIGNED_BY, NOTES)


@pytest.mark.parametrize("fa_status", ["agreed", "closed"])
async def test_a_different_figure_is_refused_and_nothing_is_written(session, fa_status: str) -> None:
    contract, account = await _contract_with_final_account(session, fa_status)

    with pytest.raises(HTTPException) as refused:
        await ContractsService(session).close_contract(
            contract.id, _payload(contract, status=fa_status, final_contract_value=str(CONTRACT_SUM)), "u1"
        )

    assert refused.value.status_code == 409
    assert refused.value.detail["error"] == "final_account_settled"
    assert refused.value.detail["fields"] == ["final_contract_value"]
    contract, account = await _reread(session, contract, account)
    assert _figures(account) == (AGREED_VALUE, AGREED_PAID, AGREED_BALANCE)
    assert account.status == fa_status
    assert contract.status == "active"


async def test_stating_the_agreed_figure_itself_is_no_restatement(session) -> None:
    contract, account = await _contract_with_final_account(session, "agreed")

    await ContractsService(session).close_contract(
        contract.id, _payload(contract, status="agreed", final_contract_value="9800.00"), "u1"
    )

    contract, account = await _reread(session, contract, account)
    assert _figures(account) == (AGREED_VALUE, AGREED_PAID, AGREED_BALANCE)
    assert contract.status == "completed"


async def test_the_button_does_not_move_a_closed_final_account_back_to_agreed(session) -> None:
    contract, account = await _contract_with_final_account(session, "closed")

    await ContractsService(session).close_contract(contract.id, _button(contract), "u1")

    contract, account = await _reread(session, contract, account)
    assert account.status == "closed"
    assert _figures(account) == (AGREED_VALUE, AGREED_PAID, AGREED_BALANCE)
    assert contract.status == "completed"


async def test_an_agreed_final_account_can_still_be_closed(session) -> None:
    contract, account = await _contract_with_final_account(session, "agreed")

    await ContractsService(session).close_contract(contract.id, _payload(contract, status="closed"), "u1")

    contract, account = await _reread(session, contract, account)
    assert account.status == "closed"
    assert _figures(account) == (AGREED_VALUE, AGREED_PAID, AGREED_BALANCE)


@pytest.mark.parametrize(
    ("fa_status", "requested"),
    [
        ("draft", "closed"),  # skips agreeing it
        ("agreed", "draft"),  # takes the sign-off back
        ("closed", "disputed"),  # reopens a final account
    ],
)
async def test_a_move_off_the_lifecycle_is_refused(session, fa_status: str, requested: str) -> None:
    contract, account = await _contract_with_final_account(session, fa_status)

    with pytest.raises(HTTPException) as refused:
        await ContractsService(session).close_contract(contract.id, _payload(contract, status=requested), "u1")

    assert refused.value.status_code == 409
    assert refused.value.detail["error"] == "final_account_transition_invalid"
    assert refused.value.detail["final_account_status"] == fa_status
    contract, account = await _reread(session, contract, account)
    assert account.status == fa_status
    assert contract.status == "active"


async def test_a_draft_final_account_is_agreed_at_its_own_figures(session) -> None:
    """The button used to restate the contract sum over a draft being negotiated."""
    contract, account = await _contract_with_final_account(session, "draft")

    await ContractsService(session).close_contract(contract.id, _button(contract), "u1")

    contract, account = await _reread(session, contract, account)
    assert account.status == "agreed"
    assert _figures(account) == (AGREED_VALUE, AGREED_PAID, AGREED_BALANCE)
    assert contract.status == "completed"


# ── A final account that does not exist yet ────────────────────────────────


async def _contract_without_final_account(s) -> Contract:
    project = Project(id=uuid.uuid4(), name="Close-out", owner_id=OWNER_ID, currency="EUR")
    s.add(project)
    await s.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        currency="EUR",
        total_value=CONTRACT_SUM,
        status="active",
    )
    s.add(contract)
    await s.flush()
    return contract


async def _final_accounts_on(s, contract: Contract) -> int:
    stmt = select(func.count()).select_from(FinalAccount).where(FinalAccount.contract_id == contract.id)
    return (await s.execute(stmt)).scalar_one()


async def test_close_does_not_create_a_final_account_already_closed(session) -> None:
    """With no account yet, a close asking for ``closed`` skipped agreeing it."""
    contract = await _contract_without_final_account(session)

    with pytest.raises(HTTPException) as refused:
        await ContractsService(session).close_contract(contract.id, _payload(contract, status="closed"), "u1")

    assert refused.value.status_code == 409
    assert refused.value.detail["error"] == "final_account_initial_status_invalid"
    assert await _final_accounts_on(session, contract) == 0
    await session.refresh(contract)
    assert contract.status == "active"


async def test_a_final_account_is_not_created_closed(session) -> None:
    """``POST /final-accounts`` took the status it was sent, closed included."""
    contract = await _contract_without_final_account(session)

    with pytest.raises(HTTPException) as refused:
        await ContractsService(session).create_final_account(_payload(contract, status="closed"))

    assert refused.value.status_code == 409
    assert refused.value.detail["error"] == "final_account_initial_status_invalid"
    assert await _final_accounts_on(session, contract) == 0


@pytest.mark.parametrize("status", ["draft", "agreed", "disputed"])
async def test_a_final_account_starts_where_the_lifecycle_lets_it(session, status: str) -> None:
    """The control: draft, and what draft moves to, still create."""
    contract = await _contract_without_final_account(session)

    account = await ContractsService(session).create_final_account(_payload(contract, status=status))

    assert account.status == status
    assert await _final_accounts_on(session, contract) == 1


async def test_the_button_still_closes_a_contract_with_no_final_account_yet(session) -> None:
    contract = await _contract_without_final_account(session)

    final = await ContractsService(session).close_contract(contract.id, _button(contract), "u1")

    assert final.status == "agreed"
    await session.refresh(contract)
    assert contract.status == "completed"
