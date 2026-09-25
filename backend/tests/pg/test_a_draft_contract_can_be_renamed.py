# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A draft contract can be renamed; a signed one keeps its code.

The code could not be changed through PATCH at all, so a code typed by mistake
was freed only by deleting the draft and writing it again. A draft's code is a
working name until the contract is signed, and after that it is what the
certificates and invoices quote the contract by. Codes remain unique across
the database, so taking a code another contract holds is a 409 either way.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.contracts.models import Contract
from app.modules.contracts.schemas import ContractUpdate
from app.modules.contracts.service import ContractsService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"rename-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _contract(s, *, status: str, code: str | None = None) -> Contract:
    project = Project(id=uuid.uuid4(), name="Rename", owner_id=OWNER_ID, currency="EUR", country_code="DE")
    s.add(project)
    await s.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=code or f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        contract_type="lump_sum",
        currency="EUR",
        total_value=Decimal("1000"),
        retention_percent=Decimal("5"),
        status=status,
    )
    s.add(contract)
    await s.flush()
    return contract


async def test_a_draft_takes_a_new_code(session) -> None:
    contract = await _contract(session, status="draft")
    new_code = f"SC-{uuid.uuid4().hex[:6]}"

    renamed = await ContractsService(session).update_contract(contract.id, ContractUpdate(code=new_code))

    assert renamed.code == new_code


async def test_a_signed_contract_keeps_its_code(session) -> None:
    contract = await _contract(session, status="active")

    with pytest.raises(HTTPException) as caught:
        await ContractsService(session).update_contract(contract.id, ContractUpdate(code="SC-NEW"))

    assert caught.value.status_code == 409
    assert caught.value.detail["error"] == "contract_code_locked"


async def test_a_code_another_contract_holds_is_refused(session) -> None:
    taken = await _contract(session, status="active")
    draft = await _contract(session, status="draft")

    with pytest.raises(HTTPException) as caught:
        await ContractsService(session).update_contract(draft.id, ContractUpdate(code=taken.code))

    assert caught.value.status_code == 409
    assert caught.value.detail["error"] == "contract_code_in_use"


async def test_sending_the_same_code_back_is_not_a_rename(session) -> None:
    contract = await _contract(session, status="active")

    same = await ContractsService(session).update_contract(
        contract.id, ContractUpdate(code=contract.code, title="Main works, phase 2")
    )

    assert same.title == "Main works, phase 2"
