# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The country's retention ladder is written onto a contract when it is signed.

The regional packs have declared a retention policy per country for a long
time, and the engine applies one only from a ``RetentionSchedule`` row. Nothing
ever wrote that row, so the two never met: a United States contract retained
its opening rate to the end of the job while the pack beside it said the rate
halves at half complete. The rule was declared and never applied, which is the
worst of both, because the pack reads as though it were in force.

Signing is where it is written, for the same reason the contract value is
frozen there. What a signed contract withholds then cannot be rewritten by a
later correction to a pack or by somebody changing the project's country.

It is written only when the pack's opening rate is the rate the parties agreed,
and these tests pin both halves of that. A ladder opening below the agreed rate
would release money early and one opening above it would withhold more than was
agreed; neither is ours to decide. Where they agree, the parties took the
country's standard opening rate, so the country's standard step-down comes with
it, and from there the ladder can only reduce what is held.

Every test here signs through ``transition_contract``, compliance gate and all,
rather than building an active contract by hand. A fixture that skips the path
is how this gap got here.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio

from app.core.regional_packs import resolve_progress_billing
from app.modules.contracts.models import Contract, ContractLine, ProgressClaim
from app.modules.contracts.schemas import AutoGenerateClaimRequest, RetentionPolicyUpdate
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    # The contracts rule set is registered by the module's startup hook, which
    # no test process runs. See tests/pg/test_retention_policy_editing.py.
    register_contracts_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"seed-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _draft_contract(
    session,
    *,
    country_code: str | None = "US",
    retention_percent: str = "10",
    contract_type: str = "lump_sum",
) -> Contract:
    """A draft contract with one clean line, ready for the compliance gate."""
    project = Project(
        id=uuid.uuid4(),
        name="Seeding",
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
        contract_type=contract_type,
        currency="USD",
        total_value=Decimal("100000"),
        retention_percent=Decimal(retention_percent),
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
    return contract


async def _claim_at(session, svc: ContractsService, contract: Contract, percent: str) -> ProgressClaim:
    """One claim on this contract, billed to ``percent`` complete."""
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
    return await svc.auto_generate_claim_lines(
        claim.id,
        AutoGenerateClaimRequest(completion={str(contract.line.id): Decimal(percent)}),
    )


async def test_the_pack_declares_a_ladder_the_engine_can_read() -> None:
    # The premise of everything below. If the pack stopped answering, or lost
    # its second tier, the seeding tests would go green for the wrong reason:
    # no ladder to write is indistinguishable from a ladder we declined to
    # write, once you are only looking at the schedule table.
    policy = (resolve_progress_billing(country_code="US") or {}).get("retention_policy")
    assert policy is not None
    assert policy["tiers"] == [
        {"from_percent_complete": "0", "rate": "10"},
        {"from_percent_complete": "50", "rate": "5"},
    ]
    assert policy["tier_mode"] == "prospective"


async def test_a_signed_united_states_contract_retains_at_the_countrys_ladder(session) -> None:
    # The money, first, because a schedule row that exists and a policy the
    # engine applies are different claims and only the second one is the point.
    # At 60% of a 100,000 contract, prospective mode holds 10% of the first
    # half and 5% of the work past it, 5,000 plus 500. Before this the same
    # contract held 6,000, its opening rate carried to the end of the job,
    # while the pack beside it said the rate halves at half complete.
    svc = ContractsService(session)
    contract = await _draft_contract(session)
    await svc.transition_contract(contract.id, "active", actor_id=str(OWNER_ID))

    claim = await _claim_at(session, svc, contract, "60")

    assert claim.retention_held_to_date == Decimal("5500.0000")


async def test_signing_records_which_ladder_it_wrote_and_where_it_came_from(session) -> None:
    svc = ContractsService(session)
    contract = await _draft_contract(session)

    signed = await svc.transition_contract(contract.id, "active", actor_id=str(OWNER_ID))

    stamp = signed.metadata_["retention_policy_seed"]
    assert stamp["seeded"] is True
    assert stamp["reason"] == "seeded"
    assert stamp["country_code"] == "US"
    assert stamp["tier_count"] == 2
    # The signing audit is written into the same metadata dict. Assigning the
    # seed stamp separately would have dropped it with nothing to say so.
    assert signed.metadata_["compliance_validation"]["blocked"] is False

    view = await svc.retention_policy_view(contract)
    assert str(view["retention_schedule_id"]) == stamp["retention_schedule_id"]
    assert view["source"] == "industry_practice"
    assert view["tiers"] == [
        {"from_percent_complete": Decimal("0"), "rate": Decimal("10")},
        {"from_percent_complete": Decimal("50"), "rate": Decimal("5")},
    ]


async def test_a_contract_that_agreed_another_rate_keeps_the_rate_it_agreed(session) -> None:
    # Five percent against a pack that opens at ten. The ladder is not this
    # contract's, and half of it would withhold less than the parties agreed,
    # so nothing is written and the refusal says which two numbers disagreed.
    svc = ContractsService(session)
    contract = await _draft_contract(session, retention_percent="5")

    signed = await svc.transition_contract(contract.id, "active", actor_id=str(OWNER_ID))

    stamp = signed.metadata_["retention_policy_seed"]
    assert stamp["seeded"] is False
    assert stamp["reason"] == "contract_rate_differs"
    # Both at the scale of the column the agreed rate lives in, so the stamp
    # reads the same whether or not the row had been read back by then.
    assert stamp["pack_opening_rate"] == "10.00"
    assert stamp["contract_rate"] == "5.00"
    assert await svc.retention_repo.list_for_contract(contract.id) == []

    view = await svc.retention_policy_view(contract)
    assert view["source"] == "contract.retention_percent"
    claim = await _claim_at(session, svc, contract, "60")
    assert claim.retention_held_to_date == Decimal("3000.0000")


async def test_a_policy_somebody_wrote_already_is_not_overwritten(session) -> None:
    # The pack is a default, not an override. A ladder agreed before signing
    # is the agreement, and signing must not quietly replace it.
    svc = ContractsService(session)
    contract = await _draft_contract(session)
    written = await svc.set_retention_policy(
        contract,
        RetentionPolicyUpdate(
            tiers=[
                {"from_percent_complete": Decimal("0"), "rate": Decimal("10")},
                {"from_percent_complete": Decimal("80"), "rate": Decimal("2")},
            ],
        ),
    )

    signed = await svc.transition_contract(contract.id, "active", actor_id=str(OWNER_ID))

    stamp = signed.metadata_["retention_policy_seed"]
    assert stamp["seeded"] is False
    assert stamp["reason"] == "policy_already_set"
    assert stamp["retention_schedule_id"] == str(written["retention_schedule_id"])
    assert len(await svc.retention_repo.list_for_contract(contract.id)) == 1
    assert (await svc.retention_policy_view(contract))["tiers"] == [
        {"from_percent_complete": Decimal("0"), "rate": Decimal("10")},
        {"from_percent_complete": Decimal("80"), "rate": Decimal("2")},
    ]


async def test_a_cost_plus_contract_is_given_no_ladder(session) -> None:
    # Cost-plus and time and materials bill work that no schedule of values
    # measures, so percent complete has nothing to stand on and the ladder is
    # never consulted. Writing one would make the stamp claim a step-down that
    # cannot happen.
    svc = ContractsService(session)
    contract = await _draft_contract(session, contract_type="cost_plus")

    signed = await svc.transition_contract(contract.id, "active", actor_id=str(OWNER_ID))

    stamp = signed.metadata_["retention_policy_seed"]
    assert stamp["seeded"] is False
    assert stamp["reason"] == "flat_retention_contract_type"
    assert await svc.retention_repo.list_for_contract(contract.id) == []


async def test_a_project_with_no_country_is_given_no_ladder(session) -> None:
    # No pack answers, and no pack answering is not a reason to reach for
    # somebody else's country. The contract keeps its own rate and the stamp
    # says the packs were silent rather than leaving the question blank.
    svc = ContractsService(session)
    contract = await _draft_contract(session, country_code=None)

    signed = await svc.transition_contract(contract.id, "active", actor_id=str(OWNER_ID))

    stamp = signed.metadata_["retention_policy_seed"]
    assert stamp["seeded"] is False
    assert stamp["reason"] == "pack_silent"
    assert stamp["country_code"] is None
    assert await svc.retention_repo.list_for_contract(contract.id) == []
    assert (await svc.retention_policy_view(contract))["source"] == "contract.retention_percent"
