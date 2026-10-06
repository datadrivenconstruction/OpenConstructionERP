# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A signed contract's schedule of values is not editable in place.

The contract lines are what every claim bills against. A claim line points at
one of them, column D is assembled per line from what earlier claims billed,
and the tracker measures percent complete against the line's scheduled value.
Change a line on a signed contract and all of that is restated underneath
certificates that have already gone to the payer, with nothing recording that
anything moved. The instrument for changing a signed scope is a change order,
which is a document both sides see.

The screen already knows this. The contract page enables line editing only
while the contract is in draft. The server does not: ``update_line`` and
``delete_line`` load the line, never look at its contract, and will happily
rewrite or remove a line on an active, completed or terminated contract for
anybody who calls the route directly. A guard that lives only in the client is
a guard against the client.

The first two tests are red until the server refuses. The third passes today
and has to keep passing, because a draft contract is exactly where the
schedule of values is supposed to be edited freely.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user_payload, get_session
from app.modules.contracts import router as contracts_router
from app.modules.contracts.models import Contract, ContractLine
from app.modules.contracts.permissions import register_contracts_permissions
from app.modules.contracts.schemas import ContractLineUpdate
from app.modules.contracts.service import ContractsService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"frozen-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _contract_with_a_line(session, *, status: str) -> tuple[Contract, ContractLine]:
    project = Project(
        id=uuid.uuid4(),
        name="Frozen",
        owner_id=OWNER_ID,
        currency="USD",
        country_code="US",
    )
    session.add(project)
    await session.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        contract_type="lump_sum",
        currency="USD",
        total_value=Decimal("100000"),
        retention_percent=Decimal("10"),
        status=status,
    )
    session.add(contract)
    await session.flush()
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="01",
        description="Line A",
        unit="m2",
        quantity=Decimal("100"),
        unit_rate=Decimal("1000"),
        total_value=Decimal("100000"),
        order_index=0,
    )
    session.add(line)
    await session.flush()
    return contract, line


async def test_a_signed_contract_refuses_a_line_edit(session) -> None:
    svc = ContractsService(session)
    _contract, line = await _contract_with_a_line(session, status="active")

    with pytest.raises(HTTPException) as caught:
        await svc.update_line(line.id, ContractLineUpdate(unit_rate=Decimal("2000")))

    assert caught.value.status_code == 409
    # The refusal has to say what to do instead, or the next person works
    # around it by editing the row some other way.
    assert "change order" in str(caught.value.detail).lower()


async def test_a_signed_contract_refuses_a_line_deletion(session) -> None:
    svc = ContractsService(session)
    _contract, line = await _contract_with_a_line(session, status="active")

    with pytest.raises(HTTPException) as caught:
        await svc.delete_line(line.id)

    assert caught.value.status_code == 409
    # Deleting the line a claim points at is the worse of the two, because the
    # claim line survives it and then bills against nothing.
    assert await svc.line_repo.get_by_id(line.id) is not None


async def test_a_draft_contract_still_edits_its_lines(session) -> None:
    """The other direction, and the reason the write exists at all."""
    svc = ContractsService(session)
    _contract, line = await _contract_with_a_line(session, status="draft")

    updated = await svc.update_line(line.id, ContractLineUpdate(unit_rate=Decimal("2000")))

    assert updated.unit_rate == Decimal("2000")
    assert updated.total_value == Decimal("200000")
    await svc.delete_line(line.id)
    assert await svc.line_repo.get_by_id(line.id) is None


@pytest.mark.parametrize("contract_status", ["active", "suspended", "completed", "terminated", "draft"])
@pytest.mark.parametrize("bulk", [False, True])
async def test_direct_http_cannot_append_to_a_signed_schedule_of_values(session, contract_status, bulk) -> None:
    """Both append routes enforce the same boundary as edits and deletions."""
    register_contracts_permissions()
    contract, original = await _contract_with_a_line(session, status=contract_status)
    app = FastAPI()
    app.include_router(contracts_router.router, prefix="/contracts")

    async def current_session():
        yield session

    app.dependency_overrides[get_session] = current_session
    app.dependency_overrides[get_current_user_payload] = lambda: {"sub": str(OWNER_ID), "role": "editor"}
    line = {
        "contract_id": str(contract.id),
        "description": "Unapproved extra scope",
        "quantity": "2",
        "unit_rate": "50",
    }
    body = {"lines": [line, {**line, "description": "Second extra line"}]} if bulk else line
    endpoint = f"/contracts/contracts/{contract.id}/lines" + ("/bulk" if bulk else "")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(endpoint, json=body)

    rows = await ContractsService(session).line_repo.list_for_contract(contract.id)
    if contract_status == "draft":
        assert response.status_code == 201, response.text
        assert len(rows) == (3 if bulk else 2)
        assert all(row.total_value == Decimal("100") for row in rows if row.id != original.id)
    else:
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["error"] == "contract_lines_frozen"
        assert response.json()["detail"]["contract_status"] == contract_status
        assert [row.id for row in rows] == [original.id]
        assert original.total_value == Decimal("100000")
