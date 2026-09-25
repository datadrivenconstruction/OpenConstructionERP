# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A schedule of values line is linked to the bill it measures, from the app, at any stage.

"Populate from progress" reads each schedule line's link to a BOQ position and
bills the position's latest reading. Nothing on screen could make that link,
so a monthly claim could only be filled in through the API. The link is
reference data, not money: it moves no quantity, rate or total, and restates
nothing a certificate already carries. It therefore has to be settable on a
signed contract and on a line a claim has billed, which is exactly where the
general line guard refuses every write.

The guard stays whole for everything else. A write that carries money beside
the link is still refused on a signed contract, a position from another
project is refused as a link, and a closed contract takes no new links.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.boq.models import BOQ, Position
from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, ProgressClaimLine
from app.modules.contracts.schemas import ContractLineUpdate
from app.modules.contracts.service import BOQ_POSITION_META_KEY, ContractsService
from app.modules.progress.models import ProgressEntry
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"link-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _project_with_position(s) -> tuple[Project, Position]:
    project = Project(id=uuid.uuid4(), name="Link", owner_id=OWNER_ID, currency="USD", country_code="US")
    s.add(project)
    await s.flush()
    boq = BOQ(id=uuid.uuid4(), project_id=project.id, name="Main BOQ")
    s.add(boq)
    await s.flush()
    pos = Position(
        id=uuid.uuid4(),
        boq_id=boq.id,
        ordinal="03.001",
        description="Cast-in-place concrete",
        unit="m3",
        quantity="100",
        unit_rate="50",
        total="5000",
    )
    s.add(pos)
    await s.flush()
    return project, pos


async def _contract_with_line(s, project: Project, *, status: str) -> tuple[Contract, ContractLine]:
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        contract_type="lump_sum",
        currency="USD",
        total_value=Decimal("1000"),
        retention_percent=Decimal("5"),
        status=status,
    )
    s.add(contract)
    await s.flush()
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="L1",
        description="Concrete",
        unit="m3",
        quantity=Decimal("10"),
        unit_rate=Decimal("100"),
        total_value=Decimal("1000"),
        order_index=0,
        metadata_={},
    )
    s.add(line)
    await s.flush()
    return contract, line


def _link(position_id: uuid.UUID | str, code: str = "03 30 00") -> ContractLineUpdate:
    return ContractLineUpdate(
        metadata={BOQ_POSITION_META_KEY: str(position_id), "classification": {"masterformat": code}}
    )


async def test_a_signed_contract_line_is_linked_and_the_claim_populates(session) -> None:
    project, pos = await _project_with_position(session)
    contract, line = await _contract_with_line(session, project, status="active")
    svc = ContractsService(session)

    updated = await svc.update_line(line.id, _link(pos.id))

    assert updated.metadata_[BOQ_POSITION_META_KEY] == str(pos.id)
    assert updated.metadata_["classification"] == {"masterformat": "03 30 00"}
    # The money on the line is exactly what it was.
    assert updated.total_value == Decimal("1000")

    session.add(
        ProgressEntry(
            id=uuid.uuid4(),
            project_id=project.id,
            boq_position_id=pos.id,
            period_label="2026-09",
            percent_complete=Decimal("40"),
            recorded_at=datetime.now(UTC),
        )
    )
    claim = ProgressClaim(id=uuid.uuid4(), contract_id=contract.id, claim_number="PC-1", currency="USD")
    session.add(claim)
    await session.flush()

    preview = await svc.populate_claim_from_progress(claim.id)

    assert [item["contract_line_id"] for item in preview["items"]] == [line.id]
    assert preview["items"][0]["period_completed_value"] == Decimal("400.0000")
    assert preview["skipped_unlinked"] == 0


async def test_a_billed_line_is_still_linked(session) -> None:
    project, pos = await _project_with_position(session)
    contract, line = await _contract_with_line(session, project, status="active")
    claim = ProgressClaim(id=uuid.uuid4(), contract_id=contract.id, claim_number="PC-1", currency="USD")
    session.add(claim)
    await session.flush()
    session.add(
        ProgressClaimLine(
            id=uuid.uuid4(),
            progress_claim_id=claim.id,
            contract_line_id=line.id,
            period_completed_value=Decimal("100"),
            cumulative_completed_value=Decimal("100"),
        )
    )
    await session.flush()

    updated = await ContractsService(session).update_line(line.id, _link(pos.id))

    assert updated.metadata_[BOQ_POSITION_META_KEY] == str(pos.id)


async def test_money_beside_the_link_is_still_refused_on_a_signed_contract(session) -> None:
    project, pos = await _project_with_position(session)
    _contract, line = await _contract_with_line(session, project, status="active")

    with pytest.raises(HTTPException) as caught:
        await ContractsService(session).update_line(
            line.id,
            ContractLineUpdate(unit_rate=Decimal("200"), metadata={BOQ_POSITION_META_KEY: str(pos.id)}),
        )

    assert caught.value.status_code == 409


async def test_a_position_from_another_project_is_not_a_link(session) -> None:
    project, _pos = await _project_with_position(session)
    _other_project, foreign = await _project_with_position(session)
    _contract, line = await _contract_with_line(session, project, status="active")

    with pytest.raises(HTTPException) as caught:
        await ContractsService(session).update_line(line.id, _link(foreign.id))

    assert caught.value.status_code == 422


async def test_a_closed_contract_takes_no_new_link(session) -> None:
    project, pos = await _project_with_position(session)
    _contract, line = await _contract_with_line(session, project, status="terminated")

    with pytest.raises(HTTPException) as caught:
        await ContractsService(session).update_line(line.id, _link(pos.id))

    assert caught.value.status_code == 409


async def test_the_link_is_cleared_the_same_way(session) -> None:
    project, pos = await _project_with_position(session)
    _contract, line = await _contract_with_line(session, project, status="active")
    svc = ContractsService(session)
    await svc.update_line(line.id, _link(pos.id))

    cleared = await svc.update_line(line.id, ContractLineUpdate(metadata={BOQ_POSITION_META_KEY: None}))

    assert not cleared.metadata_.get(BOQ_POSITION_META_KEY)
