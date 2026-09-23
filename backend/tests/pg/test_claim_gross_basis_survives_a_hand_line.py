# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A claim billed off the cost of work keeps that basis when a line is added.

A cost-plus claim is generated from costs and carries no schedule-of-values
lines: the generator returns an empty line list on purpose, because there is no
schedule behind the money. ``roll_claim_retention`` used to re-read the claim's
gross from its lines whenever it had any, which is right for a claim made of
lines and was wrong for this one. One line added by hand, and a claim for fifty
thousand of recorded cost became a claim for the value of that single line. The
claim now records what its gross is made of, and a cost basis is not re-read
from lines somebody typed against it.

Adding the line by hand is not a hypothetical route: it is a button on the
claim, enabled on any draft claim whatever the contract type, and the endpoint
behind it rolls retention with ``gross_follows_lines=True`` exactly as these
tests do.

The assertion here is deliberately about the money and not about the mechanism.
Whether the server ends up refusing the line or keeping the basis alongside it,
a gross of one thousand on a fifty thousand claim is wrong either way, so the
test survives that decision.

This is one end of a defect that is already pinned from the other, and the
boundary is worth stating exactly, because the file that pins it covers two
different defects and only one of them is this one.
``tests/modules/test_contracts_mixed_shape_certificate.py`` has a stored
material test that is the same statement as this file: a value that counts in
line 4 of the certificate and not in the claim's gross, because the gross is
re-read from the lines and the lines' stored value is not in that sum. Its
mixed shape and populate tests are not this defect. Those fail in the
certificate builder, where column D is assembled per line and a month billed
with no lines is invisible to it while remaining fully visible to line 7. A
reader who goes looking for all three in the same twelve lines will not find
them.

This file asserts the claim's own gross instead of the certificate drawn over
it, which is the shorter path to the money and the one a reader can check by
hand.

The two that name the defect carried ``xfail(strict=True)`` while the defect
was open, and the marks came off in the commit that closed it, because a
strict xfail that passes is a failure and would have turned ci-postgres red on
main. The figures they were measured against are the ones asserted below: a
gross of one thousand where fifty thousand of cost was recorded, and retention
of one hundred where five thousand is due.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, ProgressClaimLine
from app.modules.contracts.schemas import AutoGenerateClaimRequest, ProgressClaimCommitLine
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()

#: This period's recorded cost of work, and the whole of the claim's basis.
COST_OF_WORK = Decimal("50000")
#: One line typed in afterwards, worth a fraction of it.
HAND_LINE_VALUE = Decimal("1000")


@pytest_asyncio.fixture
async def session():
    # The contracts rule set is registered by the module's startup hook, which
    # no test process runs. See tests/pg/test_retention_policy_editing.py.
    register_contracts_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"basis-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _contract(session, *, contract_type: str) -> Contract:
    """An active contract of one line, whatever it bills off."""
    project = Project(
        id=uuid.uuid4(),
        name="Basis",
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
        contract_type=contract_type,
        currency="USD",
        total_value=Decimal("100000"),
        retention_percent=Decimal("10"),
        # A cost-plus contract has to state its fee; zero keeps the arithmetic
        # in these tests about the cost of work and nothing else.
        terms={"fee_percent": "0"},
        status="active",
    )
    session.add(contract)
    await session.flush()
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="01",
        description="Line A",
        unit="m2",
        quantity=Decimal("1"),
        unit_rate=Decimal("100000"),
        total_value=Decimal("100000"),
        order_index=0,
    )
    session.add(line)
    await session.flush()
    contract.line = line  # type: ignore[attr-defined]
    return contract


async def _draft_claim(session, contract: Contract) -> ProgressClaim:
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number="PC-1",
        period_start="2026-03-01",
        period_end="2026-03-31",
        period_from=date(2026, 3, 1),
        period_to=date(2026, 3, 31),
        currency="USD",
        status="draft",
    )
    session.add(claim)
    await session.flush()
    return claim


async def _add_line_by_hand(
    session,
    svc: ContractsService,
    claim: ProgressClaim,
    contract_line_id: uuid.UUID,
    value: Decimal,
) -> None:
    """What the create-claim-line endpoint does, minus the HTTP layer.

    Kept in step with router.py's POST /progress-claim-lines/: derive the
    running totals, write the row, then roll the claim with
    ``gross_follows_lines`` set, because the caller has just written a line.
    """
    fields = {
        "progress_claim_id": claim.id,
        "contract_line_id": contract_line_id,
        "period_completed_value": value,
    }
    fields.update(await svc.claim_line_running_totals(claim, contract_line_id, value))
    session.add(ProgressClaimLine(**fields))
    await session.flush()
    await svc.roll_claim_retention(claim.id, gross_follows_lines=True)


async def test_a_cost_plus_claim_keeps_its_cost_basis_when_a_line_is_added(session) -> None:
    # The money, first. A claim for fifty thousand of recorded cost must not
    # become a claim for one thousand because somebody added a line to it.
    svc = ContractsService(session)
    contract = await _contract(session, contract_type="cost_plus")
    claim = await _draft_claim(session, contract)
    generated = await svc.auto_generate_claim_lines(
        claim.id,
        AutoGenerateClaimRequest(actual_costs_total=COST_OF_WORK),
    )
    assert generated.gross_amount == COST_OF_WORK

    await _add_line_by_hand(session, svc, claim, contract.line.id, HAND_LINE_VALUE)

    await session.refresh(claim)
    assert claim.gross_amount != HAND_LINE_VALUE
    assert claim.gross_amount >= COST_OF_WORK


async def test_the_retention_follows_the_basis_and_not_the_line(session) -> None:
    # Retention is ten per cent of the gross on this contract, so the wrong
    # gross bills the wrong retention and the wrong net, and a payer reading
    # the certificate sees a consistent set of wrong numbers rather than
    # anything that looks like an error.
    svc = ContractsService(session)
    contract = await _contract(session, contract_type="cost_plus")
    claim = await _draft_claim(session, contract)
    await svc.auto_generate_claim_lines(
        claim.id,
        AutoGenerateClaimRequest(actual_costs_total=COST_OF_WORK),
    )

    await _add_line_by_hand(session, svc, claim, contract.line.id, HAND_LINE_VALUE)

    await session.refresh(claim)
    assert claim.retention_amount == Decimal("5000.0000")


async def test_a_populate_rewrites_the_basis_along_with_the_gross(session) -> None:
    """A populate makes the claim's gross its lines, and the claim has to say so.

    Nothing stops a populate on a cost-plus contract that also carries a
    schedule of values, and it replaces the claim's gross with the sum of the
    lines it writes. A claim left recording a cost basis after that is this
    defect inside out: a claim genuinely made of lines that refuses to follow
    them, frozen at whatever the populate put there and held to the weaker
    totals rule for the rest of its life.
    """
    svc = ContractsService(session)
    contract = await _contract(session, contract_type="cost_plus")
    claim = await _draft_claim(session, contract)
    await svc.auto_generate_claim_lines(
        claim.id,
        AutoGenerateClaimRequest(actual_costs_total=COST_OF_WORK),
    )
    await session.refresh(claim)
    assert claim.gross_basis == "cost"

    await svc.commit_preview_to_claim(
        claim.id,
        [ProgressClaimCommitLine(contract_line_id=contract.line.id, period_completed_pct=Decimal("20"))],
    )
    await session.refresh(claim)
    assert claim.gross_amount == Decimal("20000.0000")
    assert claim.gross_basis == "lines"

    # And it behaves like a line claim from here, which is the whole point of
    # rewriting the basis: editing the row the populate wrote moves the claim.
    lines = await svc.claim_line_repo.list_for_claim(claim.id)
    assert len(lines) == 1
    await svc.claim_line_repo.update_fields(lines[0].id, period_completed_value=Decimal("30000"))
    await svc.roll_claim_retention(claim.id, gross_follows_lines=True)
    await session.refresh(claim)
    assert claim.gross_amount == Decimal("30000.0000")


async def test_a_lump_sum_claim_still_bills_what_its_lines_say(session) -> None:
    """The other direction, and the reason the current behaviour exists.

    A claim that is made of lines has to follow them, including down to zero
    when the last one is deleted. A fix that stopped the gross following the
    lines everywhere would trade this defect for a worse one, so this test
    passes today and has to keep passing.
    """
    svc = ContractsService(session)
    contract = await _contract(session, contract_type="lump_sum")
    claim = await _draft_claim(session, contract)

    await _add_line_by_hand(session, svc, claim, contract.line.id, HAND_LINE_VALUE)

    await session.refresh(claim)
    assert claim.gross_amount == HAND_LINE_VALUE
    assert claim.retention_amount == Decimal("100.0000")
