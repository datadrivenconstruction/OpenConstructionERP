# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The SoV tracker agrees with the payment applications, through the real path.

The unit tests beside this one prove the arithmetic with stub objects. They
cannot prove that the pieces fit: that the repository hands back the claim
rather than its status, that ``claim_order_key`` reads a real ``ProgressClaim``
whose ``period_to`` is a date column and whose ``created_at`` comes from the
Base, and that the claims the generator writes actually carry a
``retention_to_date`` for the tracker to find. Every one of those is a place
where a green unit suite and a wrong screen can live together, so this file
calls ``sov_status`` on a signed contract with two certified claims behind it
and reads the money out of the answer.

The contract here is signed through ``transition_contract``, which writes the
country's ladder onto it, so the figures are the laddered ones and the flat
rate is genuinely not what the answer should be.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.contracts.models import Contract, ContractLine, ProgressClaim
from app.modules.contracts.schemas import AutoGenerateClaimRequest
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()

#: 10 per cent of the first 50,000 and 5 per cent of the next 10,000.
LADDER_RETENTION_AT_SIXTY = Decimal("5500")
#: The contract's own rate on everything billed, which is what the tracker
#: reported before it started reading the claims.
FLAT_RETENTION_AT_SIXTY = Decimal("6000")


@pytest_asyncio.fixture
async def session():
    # The contracts rule set is registered by the module's startup hook, which
    # no test process runs. See tests/pg/test_retention_policy_editing.py.
    register_contracts_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"sov-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _signed_contract(session, *, country_code: str | None = "US") -> Contract:
    """A 100,000 contract of one line, signed through the compliance gate."""
    project = Project(
        id=uuid.uuid4(),
        name="Tracker",
        owner_id=OWNER_ID,
        currency="USD",
        country_code=country_code,
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
        status="draft",
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
    await ContractsService(session).transition_contract(contract.id, "active", actor_id=str(OWNER_ID))
    return contract


async def _certified_claim(
    session,
    svc: ContractsService,
    contract: Contract,
    *,
    number: str,
    period: tuple[date, date],
    percent: str,
) -> ProgressClaim:
    """One claim billed to ``percent`` complete and certified."""
    frm, to = period
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number=number,
        period_start=frm.isoformat(),
        period_end=to.isoformat(),
        period_from=frm,
        period_to=to,
        currency="USD",
        status="draft",
    )
    session.add(claim)
    await session.flush()
    claim = await svc.auto_generate_claim_lines(
        claim.id,
        AutoGenerateClaimRequest(completion={str(contract.line.id): Decimal(percent)}),
    )
    await svc.claim_repo.update_fields(claim.id, status="certified")
    await session.refresh(claim)
    return claim


async def test_the_tracker_shows_what_the_second_claim_certified(session) -> None:
    # The money. Two certified claims, forty per cent then sixty, and the
    # tracker has to show the ladder's 5,500 rather than the contract rate's
    # 6,000, which is what the same screen showed while it did its own sum.
    svc = ContractsService(session)
    contract = await _signed_contract(session)
    await _certified_claim(
        session, svc, contract, number="PC-0001", period=(date(2026, 3, 1), date(2026, 3, 31)), percent="40"
    )
    second = await _certified_claim(
        session, svc, contract, number="PC-0002", period=(date(2026, 4, 1), date(2026, 4, 30)), percent="60"
    )
    # The premise: the claim actually recorded a figure for the tracker to
    # read. Without this the test would pass on the flat fallback and prove
    # nothing about the path it is here to cover.
    assert second.retention_held_to_date == Decimal("5500.0000")

    status = await svc.sov_status(contract.id)

    row = status["by_line"][str(contract.line.id)]
    assert row["billed"] == Decimal("60000.0000")
    assert row["retained"] == LADDER_RETENTION_AT_SIXTY
    assert row["retained"] != FLAT_RETENTION_AT_SIXTY
    assert status["totals"]["retained"] == LADDER_RETENTION_AT_SIXTY


async def test_a_contract_with_no_ladder_reports_the_same_figure_as_before(session) -> None:
    """The population the change must not move, and it is most of the tree.

    A project with no country gets no ladder at signing, but its claims still
    record a per-line retention figure, because the engine runs on a flat
    policy when there are no tiers rather than stepping aside. So the tracker
    reads the recorded figure here too and simply gets the same answer it used
    to compute, which is a better reason for the number not moving than a
    fallback would have been.
    """
    svc = ContractsService(session)
    contract = await _signed_contract(session, country_code=None)
    claim = await _certified_claim(
        session, svc, contract, number="PC-0001", period=(date(2026, 3, 1), date(2026, 3, 31)), percent="60"
    )
    assert claim.retention_held_to_date == Decimal("6000.0000")

    status = await svc.sov_status(contract.id)

    assert status["by_line"][str(contract.line.id)]["retained"] == FLAT_RETENTION_AT_SIXTY


async def test_a_line_no_claim_ever_priced_falls_back_to_the_contract_rate(session) -> None:
    """The fallback, on the one population that really has no figure.

    A cost-plus contract bills off recorded cost, so the retention engine is
    not asked for a per-line share at all and nothing writes the column. A
    line added to such a claim by hand is the case the fallback exists for,
    and it has to produce the contract's own rate rather than zero.
    """
    from app.modules.contracts.models import ProgressClaimLine

    svc = ContractsService(session)
    contract = await _signed_contract(session, country_code=None)
    await svc.contract_repo.update_fields(contract.id, contract_type="cost_plus", terms={"fee_percent": "0"})
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number="PC-0001",
        period_start="2026-03-01",
        period_end="2026-03-31",
        period_from=date(2026, 3, 1),
        period_to=date(2026, 3, 31),
        currency="USD",
        status="draft",
    )
    session.add(claim)
    await session.flush()
    fields = {
        "progress_claim_id": claim.id,
        "contract_line_id": contract.line.id,
        "period_completed_value": Decimal("60000"),
    }
    fields.update(await svc.claim_line_running_totals(claim, contract.line.id, Decimal("60000")))
    line = ProgressClaimLine(**fields)
    session.add(line)
    await session.flush()
    await svc.claim_repo.update_fields(claim.id, status="certified")
    assert line.retention_to_date is None

    status = await svc.sov_status(contract.id)

    assert status["by_line"][str(contract.line.id)]["retained"] == FLAT_RETENTION_AT_SIXTY
