# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A schedule of values line a claim has billed on stays as it was billed.

``ProgressClaimLine.contract_line_id`` is declared ``ondelete="CASCADE"`` and
has no ORM relationship, so the database is the only actor when a schedule
line goes: every claim line that billed against it is deleted with it. The
claim keeps its gross, retention and net due, and the breakdown that explains
them is gone, including on a claim that was certified and paid.

The guard in front of this used to be about the contract only. Line edits are
refused once the contract is signed, and a draft contract edits its schedule
freely, which is right while nothing has been billed. Nothing ties a claim to
the contract's status, though, so a draft contract can carry claims, and then
a delete destroyed their lines and a rate edit restated the value under a
certificate already issued. Whether a line may change is a fact about the
line, so the second guard asks the line.

This lives in the PG lane on purpose. The cascade is a PostgreSQL fact; SQLite
without its foreign key pragma leaves the claim line behind as an orphan
instead, and a test there would pass for the wrong reason.

Every read-back below is a fresh SELECT rather than ``session.get``. The
identity map would hand back the claim line still cached in memory after the
database had already cascaded it away, and the assertion would pass on the
very defect it is here to catch.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select

from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, ProgressClaimLine
from app.modules.contracts.schemas import ContractLineUpdate
from app.modules.contracts.service import ContractsService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()

#: The claim statuses a billed line is checked under. A draft claim's lines are
#: cascaded away exactly like a certified one's, so both are refused.
CLAIM_STATUSES = ("draft", "certified")


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"billed-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _draft_contract(session) -> Contract:
    """A contract still in draft, which is where the old guard let anything through."""
    project = Project(
        id=uuid.uuid4(),
        name="Billed",
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
        total_value=Decimal("200000"),
        retention_percent=Decimal("10"),
        status="draft",
    )
    session.add(contract)
    await session.flush()
    return contract


async def _line(session, contract: Contract, code: str) -> ContractLine:
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code=code,
        description=f"Line {code}",
        unit="m2",
        quantity=Decimal("100"),
        unit_rate=Decimal("1000"),
        total_value=Decimal("100000"),
        order_index=int(code),
    )
    session.add(line)
    await session.flush()
    return line


async def _claim_billing(session, contract: Contract, line: ContractLine, *, status: str) -> ProgressClaim:
    """One claim that billed a quarter of ``line`` this period."""
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number="PC-1",
        period_start="2026-03-01",
        period_end="2026-03-31",
        period_from=date(2026, 3, 1),
        period_to=date(2026, 3, 31),
        currency="USD",
        gross_amount=Decimal("25000"),
        retention_amount=Decimal("2500"),
        net_due=Decimal("22500"),
        status=status,
    )
    session.add(claim)
    await session.flush()
    session.add(
        ProgressClaimLine(
            id=uuid.uuid4(),
            progress_claim_id=claim.id,
            contract_line_id=line.id,
            period_completed_qty=Decimal("25"),
            period_completed_value=Decimal("25000"),
            period_completed_pct=Decimal("25"),
            prior_completed_value=Decimal("0"),
            cumulative_completed_value=Decimal("25000"),
        )
    )
    await session.flush()
    return claim


async def _claim_lines_on(session, line_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(ProgressClaimLine).where(ProgressClaimLine.contract_line_id == line_id)
    return (await session.execute(stmt)).scalar_one()


async def _lines_with_id(session, line_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(ContractLine).where(ContractLine.id == line_id)
    return (await session.execute(stmt)).scalar_one()


async def _rate_and_value(session, line_id: uuid.UUID) -> tuple[Decimal, Decimal]:
    stmt = select(ContractLine.unit_rate, ContractLine.total_value).where(ContractLine.id == line_id)
    row = (await session.execute(stmt)).one()
    return Decimal(row.unit_rate), Decimal(row.total_value)


@pytest.mark.parametrize("claim_status", CLAIM_STATUSES)
async def test_a_billed_line_is_not_deleted_and_its_claim_lines_survive(session, claim_status: str) -> None:
    svc = ContractsService(session)
    contract = await _draft_contract(session)
    line = await _line(session, contract, "1")
    await _claim_billing(session, contract, line, status=claim_status)

    refused: HTTPException | None = None
    try:
        await svc.delete_line(line.id)
    except HTTPException as exc:
        refused = exc

    # The money first: the claim's breakdown is still there to explain its
    # gross. Before the guard this read 0, because the database had cascaded
    # the claim line away with the schedule line.
    assert await _claim_lines_on(session, line.id) == 1
    assert await _lines_with_id(session, line.id) == 1
    assert refused is not None
    assert refused.status_code == 409
    assert refused.detail["error"] == "contract_line_billed"
    assert refused.detail["contract_line_ids"] == [str(line.id)]


@pytest.mark.parametrize("claim_status", CLAIM_STATUSES)
async def test_a_billed_line_keeps_the_rate_it_was_billed_at(session, claim_status: str) -> None:
    svc = ContractsService(session)
    contract = await _draft_contract(session)
    line = await _line(session, contract, "1")
    await _claim_billing(session, contract, line, status=claim_status)

    refused: HTTPException | None = None
    try:
        await svc.update_line(line.id, ContractLineUpdate(unit_rate=Decimal("2000")))
    except HTTPException as exc:
        refused = exc

    # Percent complete, column D and the certificate all read the line's
    # value. Before the guard this read (2000, 200000): the value under a
    # claim already billed had doubled and nothing recorded that it moved.
    assert await _rate_and_value(session, line.id) == (Decimal("1000"), Decimal("100000"))
    assert refused is not None
    assert refused.status_code == 409
    assert refused.detail["error"] == "contract_line_billed"


async def test_a_billed_line_refuses_a_change_to_its_wording_too(session) -> None:
    """Every field, not only the money ones, the same as on a signed contract.

    The description and code print on the certificate's continuation sheet,
    so rewording a billed line rewrites a document the payer already holds.
    """
    svc = ContractsService(session)
    contract = await _draft_contract(session)
    line = await _line(session, contract, "1")
    await _claim_billing(session, contract, line, status="certified")

    with pytest.raises(HTTPException) as caught:
        await svc.update_line(line.id, ContractLineUpdate(description="Something else"))

    assert caught.value.status_code == 409
    described = (await session.execute(select(ContractLine.description).where(ContractLine.id == line.id))).scalar_one()
    assert described == "Line 1"


async def test_an_unbilled_line_on_a_billed_contract_still_edits_and_deletes(session) -> None:
    """The control. The guard is about the line, not about the contract.

    Line 1 is billed on a certified claim. Line 2 is on the same draft
    contract and nothing has billed on it, so correcting and removing it is
    the ordinary thing to do and has to keep working.
    """
    svc = ContractsService(session)
    contract = await _draft_contract(session)
    billed = await _line(session, contract, "1")
    unbilled = await _line(session, contract, "2")
    await _claim_billing(session, contract, billed, status="certified")

    updated = await svc.update_line(unbilled.id, ContractLineUpdate(unit_rate=Decimal("2000")))
    assert updated.unit_rate == Decimal("2000")
    assert await _rate_and_value(session, unbilled.id) == (Decimal("2000"), Decimal("200000"))

    await svc.delete_line(unbilled.id)
    assert await _lines_with_id(session, unbilled.id) == 0
    # And removing line 2 took nothing from the claim on line 1.
    assert await _claim_lines_on(session, billed.id) == 1


async def test_the_listing_marks_the_same_lines_the_server_refuses(session) -> None:
    """The screen locks what the listing calls billed, so the two must agree.

    The line listing and the refusal read one repository method. This pins
    what it answers: the billed line with the claim that billed it, and the
    unbilled line absent rather than present and empty.
    """
    svc = ContractsService(session)
    contract = await _draft_contract(session)
    billed = await _line(session, contract, "1")
    unbilled = await _line(session, contract, "2")
    await _claim_billing(session, contract, billed, status="draft")

    assert await svc.claim_line_repo.claims_billing_lines([billed.id, unbilled.id]) == {billed.id: ["PC-1"]}


async def _claims_on(session, contract_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(ProgressClaim).where(ProgressClaim.contract_id == contract_id)
    return (await session.execute(stmt)).scalar_one()


async def _contracts_with_id(session, contract_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(Contract).where(Contract.id == contract_id)
    return (await session.execute(stmt)).scalar_one()


@pytest.mark.parametrize("claim_status", CLAIM_STATUSES)
async def test_a_draft_contract_a_claim_has_billed_on_is_not_deleted(session, claim_status: str) -> None:
    """Deleting the contract deletes every line on it, so it asks the same question.

    Only a draft contract may be deleted at all, and that used to be the whole
    check. A draft can carry claims, though, and the cascade from the contract
    took them away whole, a certified and paid one included: the claim, its
    lines and the schedule line they billed on, in one call.
    """
    svc = ContractsService(session)
    contract = await _draft_contract(session)
    line = await _line(session, contract, "1")
    await _claim_billing(session, contract, line, status=claim_status)

    refused: HTTPException | None = None
    try:
        await svc.delete_contract(contract.id)
    except HTTPException as exc:
        refused = exc

    # Before the guard every one of these read 0.
    assert await _contracts_with_id(session, contract.id) == 1
    assert await _claims_on(session, contract.id) == 1
    assert await _claim_lines_on(session, line.id) == 1
    assert refused is not None
    assert refused.status_code == 409
    assert refused.detail["error"] == "contract_line_billed"
    assert refused.detail["contract_line_ids"] == [str(line.id)]
    assert refused.detail["claim_numbers"] == ["PC-1"]


async def test_a_draft_contract_nothing_has_billed_on_still_deletes(session) -> None:
    """The control: a draft's lines are still its own until a claim bills them."""
    svc = ContractsService(session)
    contract = await _draft_contract(session)
    line = await _line(session, contract, "1")

    await svc.delete_contract(contract.id)

    assert await _contracts_with_id(session, contract.id) == 0
    assert await _lines_with_id(session, line.id) == 0
