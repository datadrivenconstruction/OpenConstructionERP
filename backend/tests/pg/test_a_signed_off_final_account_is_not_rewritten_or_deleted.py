# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The final-account routes keep to the rule Close keeps.

``PATCH /final-accounts/{id}`` wrote whatever the request sent over the
account, figures and status alike, and ``DELETE`` removed it, whatever state
it was in. So an agreed or closed final account, which Close no longer
restates, could still be rewritten or deleted one route over, and its status
could jump anywhere, closed back to draft included.

Now PATCH moves the status only along the final-account lifecycle and leaves
the figures of an agreed or closed account as signed off, and DELETE refuses
an agreed or closed account. A draft or disputed account stays open to both:
that is where figures are negotiated. The tests call the route functions, so
what is asserted is what a request reaches.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.modules.contracts import router as contracts_router
from app.modules.contracts.models import Contract, FinalAccount
from app.modules.contracts.schemas import FinalAccountUpdate
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()
AGREED_VALUE = Decimal("9800")
AGREED_PAID = Decimal("9000")
AGREED_BALANCE = Decimal("800")


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"fa-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _final_account(s, fa_status: str) -> FinalAccount:
    project = Project(id=uuid.uuid4(), name="Close-out", owner_id=OWNER_ID, currency="EUR")
    s.add(project)
    await s.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        currency="EUR",
        total_value=Decimal("10000"),
        status="completed",
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
        status=fa_status,
        notes="As agreed",
    )
    s.add(account)
    await s.flush()
    return account


async def _patch(s, account: FinalAccount, **fields: str):
    return await contracts_router.update_final_account(
        account_id=account.id,
        data=FinalAccountUpdate.model_validate(fields),
        session=s,
        user_id=str(OWNER_ID),
        _perm=None,
    )


async def _delete(s, account_id: uuid.UUID) -> None:
    await contracts_router.delete_final_account(account_id=account_id, session=s, user_id=str(OWNER_ID), _perm=None)


def _figures(account: FinalAccount) -> tuple[Decimal, Decimal, Decimal]:
    return (
        Decimal(str(account.final_contract_value)),
        Decimal(str(account.total_paid)),
        Decimal(str(account.final_balance)),
    )


async def _still_there(s, account_id: uuid.UUID) -> bool:
    return (
        await s.execute(select(FinalAccount.id).where(FinalAccount.id == account_id))
    ).scalar_one_or_none() is not None


# ── PATCH ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("fa_status", ["agreed", "closed"])
async def test_patch_does_not_restate_a_signed_off_figure(session, fa_status: str) -> None:
    account = await _final_account(session, fa_status)

    with pytest.raises(HTTPException) as refused:
        await _patch(session, account, final_contract_value="10000", total_paid="9800")

    assert refused.value.status_code == 409
    assert refused.value.detail["error"] == "final_account_settled"
    assert refused.value.detail["fields"] == ["final_contract_value", "total_paid"]
    await session.refresh(account)
    assert _figures(account) == (AGREED_VALUE, AGREED_PAID, AGREED_BALANCE)
    assert account.status == fa_status


async def test_patch_still_edits_the_words_on_an_agreed_account(session) -> None:
    account = await _final_account(session, "agreed")

    response = await _patch(session, account, notes="Signed copy filed", sign_off_by="Commercial manager")

    assert response.notes == "Signed copy filed"
    await session.refresh(account)
    assert _figures(account) == (AGREED_VALUE, AGREED_PAID, AGREED_BALANCE)


async def test_an_agreed_account_is_disputed_to_reopen_its_figures(session) -> None:
    account = await _final_account(session, "agreed")

    await _patch(session, account, status="disputed")
    await _patch(session, account, final_contract_value="9900", final_balance="900")
    response = await _patch(session, account, status="agreed")

    assert response.status == "agreed"
    assert (Decimal(str(response.final_contract_value)), Decimal(str(response.final_balance))) == (
        Decimal("9900"),
        Decimal("900"),
    )


@pytest.mark.parametrize(
    ("fa_status", "requested"),
    [
        ("draft", "closed"),  # skips agreeing it
        ("agreed", "draft"),  # takes the sign-off back
        ("closed", "agreed"),  # reopens a final account
    ],
)
async def test_patch_moves_the_status_only_along_the_lifecycle(session, fa_status: str, requested: str) -> None:
    account = await _final_account(session, fa_status)

    with pytest.raises(HTTPException) as refused:
        await _patch(session, account, status=requested)

    assert refused.value.status_code == 409
    assert refused.value.detail["error"] == "final_account_transition_invalid"
    await session.refresh(account)
    assert account.status == fa_status


async def test_patch_edits_the_figures_of_a_draft_account(session) -> None:
    account = await _final_account(session, "draft")

    response = await _patch(session, account, final_contract_value="9500", status="agreed")

    assert Decimal(str(response.final_contract_value)) == Decimal("9500")
    assert response.status == "agreed"


# ── DELETE ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("fa_status", ["agreed", "closed"])
async def test_delete_refuses_a_signed_off_account(session, fa_status: str) -> None:
    account = await _final_account(session, fa_status)

    with pytest.raises(HTTPException) as refused:
        await _delete(session, account.id)

    assert refused.value.status_code == 409
    assert refused.value.detail["error"] == "final_account_settled"
    assert await _still_there(session, account.id)


@pytest.mark.parametrize("fa_status", ["draft", "disputed"])
async def test_delete_removes_an_account_still_being_negotiated(session, fa_status: str) -> None:
    account = await _final_account(session, fa_status)

    await _delete(session, account.id)

    assert not await _still_there(session, account.id)


async def test_a_final_account_that_is_not_there_is_a_404(session) -> None:
    with pytest.raises(HTTPException) as missing:
        await _delete(session, uuid.uuid4())
    assert missing.value.status_code == 404
