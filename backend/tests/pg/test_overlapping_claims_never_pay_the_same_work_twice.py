# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Two claims waiting for certification at once never pay the same work twice.

G702 line 7 is what the earlier claims certified, and a claim's net due is
worked out against it when the claim is generated. The net due is not worked
out again at certification: the figure the claim carries is the figure the
certified event hands to finance.

Nothing stops a contractor from generating March's claim while February's
is still with the owner. February has certified nothing yet, so a line 7
that counted certified claims only would leave February's net inside
March's line 8. February is then certified and paid, March is certified with
the net it was generated with, and February's work is paid twice. The
submission check that compares a claim's stored previous certificates with
what they are now does not catch it, because both claims were submitted
while neither was certified.

Counting every earlier claim that was not rejected keeps the two claims from
overlapping: March subtracts what February asks for, and the three claims
together certify exactly the work done less its retention. Rejecting
February instead leaves March short until the next claim picks the work up
again, which underpays for a month rather than paying twice.

One lump sum line of 100,000, flat 10% retention. January bills 30%,
February takes it to 60% and March to 80%.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.contracts.models import Contract, ContractLine
from app.modules.contracts.schemas import AutoGenerateClaimRequest
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

LINE_VALUE = Decimal("100000")


@pytest.fixture(autouse=True)
def _rules():
    register_contracts_validation_rules()


async def _contract(session) -> tuple[Contract, ContractLine, uuid.UUID]:
    suffix = uuid.uuid4().hex[:8]
    owner = User(id=uuid.uuid4(), email=f"overlap-{suffix}@site.example", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(
        id=uuid.uuid4(),
        name="Overlapping claims",
        owner_id=owner.id,
        currency="USD",
        country_code="US",
        metadata_={},
    )
    session.add(project)
    await session.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{suffix}",
        title="Main works",
        project_id=project.id,
        contract_type="lump_sum",
        currency="USD",
        total_value=LINE_VALUE,
        original_contract_value=LINE_VALUE,
        retention_percent=Decimal("10"),
        status="active",
    )
    session.add(contract)
    await session.flush()
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="03 30 00",
        description="Cast-in-place concrete",
        quantity=Decimal("1"),
        unit_rate=LINE_VALUE,
        total_value=LINE_VALUE,
    )
    session.add(line)
    await session.flush()
    return contract, line, owner.id


async def _generated(svc, contract, line, number: str, month: int, pct: str):
    claim = await svc.create_progress_claim(
        SimpleNamespace(
            contract_id=contract.id,
            claim_number=number,
            period_start=f"2026-{month:02d}-01",
            period_end=f"2026-{month:02d}-28",
            claim_date=f"2026-{month:02d}-28",
            currency="USD",
            metadata={},
        )
    )
    return await svc.auto_generate_claim_lines(claim.id, AutoGenerateClaimRequest(completion={str(line.id): pct}))


async def _move(svc, claim, owner_id, *targets: str):
    for target in targets:
        claim = await svc.transition_claim(claim.id, target, str(owner_id))
    return claim


async def test_a_claim_generated_while_the_one_before_waits_does_not_bill_it_again(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract, line, owner_id = await _contract(pg_session)

    january = await _generated(svc, contract, line, "PC-1", 1, "30")
    january = await _move(svc, january, owner_id, "submitted", "approved", "certified")

    february = await _generated(svc, contract, line, "PC-2", 2, "60")
    february = await _move(svc, february, owner_id, "submitted")

    # March is generated and sent while February is still with the owner.
    march = await _generated(svc, contract, line, "PC-3", 3, "80")
    march = await _move(svc, march, owner_id, "submitted")

    february = await _move(svc, february, owner_id, "approved", "certified")
    march = await _move(svc, march, owner_id, "approved", "certified")

    certified = [Decimal(str(c.net_due)) for c in (january, february, march)]
    # 80% of the work less 10% retention, paid once.
    assert sum(certified, Decimal("0")) == Decimal("72000")
    assert certified == [Decimal("27000"), Decimal("27000"), Decimal("18000")]
