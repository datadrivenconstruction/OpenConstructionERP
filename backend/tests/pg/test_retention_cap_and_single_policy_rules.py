# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Two checks on the rule a contract holds retention by: its ceiling, and how many there are.

The engine applies a cap last, so a claim it worked out is never over one.
Claims get their figures from elsewhere as well, and the one that matters here
is a cap tightened after the claim was written: nothing recomputes an existing
draft, so the claim goes on holding what the contract no longer allows.

The second branch of the cap rule is about a cap this module cannot read at
all. Several states of the United States limit retainage by statute, the state
packs carry those limits, and reading one needs an ISO 3166-2 code that no
project has a field to hold. On a contract in such a country the check says so
once, as information, instead of passing in silence. Passing would be a claim
about the law rather than about this claim.

The policy count is the other half. The engine takes the newest schedule that
carries tiers and ignores the rest with no word anywhere, which is how a
correction can sit beside the thing it was meant to correct while the money
follows whichever was written last.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio

from app.core.validation.engine import Severity
from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, RetentionSchedule
from app.modules.contracts.schemas import AutoGenerateClaimRequest, RetentionPolicyUpdate
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import (
    CONTRACTS_RULE_SET,
    PAY_APPLICATION_RULE_SET,
    register_contracts_validation_rules,
)
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()
CAP_RULE = "pay_application.retention_above_cap"
SINGLE_RULE = "contracts.retention_policy_single"


@pytest_asyncio.fixture
async def session():
    # Without this the rule sets are unregistered, and an unregistered set is
    # serialised as an empty report: every assertion of the form "no errors"
    # would pass whether a rule ran or not.
    register_contracts_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"cap-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _contract(session, *, country_code: str | None = "US", status: str = "active") -> Contract:
    project = Project(
        id=uuid.uuid4(),
        name="Caps",
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
        original_contract_value=Decimal("100000") if status == "active" else None,
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


def _ladder(*steps: tuple[str, str]) -> list[dict[str, Decimal]]:
    return [{"from_percent_complete": Decimal(at), "rate": Decimal(rate)} for at, rate in steps]


async def _claim_report(svc: ContractsService, claim: ProgressClaim):
    report = await svc.run_claim_rules(claim)
    assert PAY_APPLICATION_RULE_SET not in report.unsupported_rule_sets
    return report


async def _contract_report(svc: ContractsService, contract: Contract):
    report = await svc.run_contract_rules(contract)
    assert CONTRACTS_RULE_SET not in report.unsupported_rule_sets
    return report


def _findings(report, rule_id: str) -> list:
    return [r for r in report.results if r.rule_id == rule_id]


async def test_a_cap_tightened_after_a_claim_was_written_is_an_error_on_that_claim(session) -> None:
    # The order is the point. The claim is worked out under a policy with no
    # cap and holds 6,000, then the cap arrives at 3 per cent of the contract
    # sum, which is 3,000. Nothing recomputes a draft that is already written,
    # so without this rule the claim goes to the owner holding twice what the
    # contract allows.
    svc = ContractsService(session)
    contract = await _contract(session)
    await svc.set_retention_policy(contract, RetentionPolicyUpdate(tiers=_ladder(("0", "10"))))
    claim = await _claim_at(session, svc, contract, "60")
    assert claim.retention_held_to_date == Decimal("6000.0000")

    await svc.set_retention_policy(
        contract,
        RetentionPolicyUpdate(tiers=_ladder(("0", "10")), cap_percent_of_contract_sum=Decimal("3")),
    )

    report = await _claim_report(svc, claim)
    findings = _findings(report, CAP_RULE)
    assert len(findings) == 1
    assert findings[0].passed is False
    assert findings[0].severity == Severity.ERROR
    assert "3%" in findings[0].message
    assert CAP_RULE in {e.rule_id for e in report.errors}


async def test_a_claim_inside_its_cap_passes_the_rule_rather_than_going_unchecked(session) -> None:
    # The same claim against a cap it meets. A rule that returned nothing here
    # would leave the screen unable to tell "checked and fine" from "not
    # checked", which is the whole difference this rule is for.
    svc = ContractsService(session)
    contract = await _contract(session)
    await svc.set_retention_policy(
        contract,
        RetentionPolicyUpdate(tiers=_ladder(("0", "10")), cap_percent_of_contract_sum=Decimal("10")),
    )
    claim = await _claim_at(session, svc, contract, "60")

    report = await _claim_report(svc, claim)
    findings = _findings(report, CAP_RULE)
    assert len(findings) == 1
    assert findings[0].passed is True
    assert not report.has_errors


async def test_a_united_states_claim_with_no_cap_says_the_state_limit_was_not_read(session) -> None:
    # No cap in the policy, and a country whose packs do carry retainage
    # statutes. The finding is information rather than a refusal: the claim is
    # not wrong, the check is incomplete, and saying which is which is the
    # difference between a gate and a guess.
    svc = ContractsService(session)
    contract = await _contract(session)
    claim = await _claim_at(session, svc, contract, "60")

    report = await _claim_report(svc, claim)
    findings = _findings(report, CAP_RULE)
    assert len(findings) == 1
    assert findings[0].passed is False
    assert findings[0].severity == Severity.INFO
    # It has to name its own remedy. A line that says only that something was
    # not checked teaches nobody anything and gets skipped from the second
    # reading on; naming the missing field means the first person who reads it
    # knows what would remove it, and it stops appearing the day they do.
    assert "US" in findings[0].message
    assert "subdivision code" in findings[0].message
    # It must not block, and it must not be counted as a warning either.
    assert not report.has_errors
    assert CAP_RULE not in {w.rule_id for w in report.warnings}
    assert CAP_RULE in {i.rule_id for i in report.infos}


async def test_a_country_with_no_state_retainage_law_hears_nothing_about_caps(session) -> None:
    # Germany has no subdivision packs carrying retainage, so there is no cap
    # anywhere to miss. Silence here is the correct answer, and saying the
    # same sentence on every claim in the world would bury the countries where
    # there is something to say.
    svc = ContractsService(session)
    contract = await _contract(session, country_code="DE")
    claim = await _claim_at(session, svc, contract, "60")

    report = await _claim_report(svc, claim)
    assert _findings(report, CAP_RULE) == []


async def test_signing_over_an_older_untiered_schedule_leaves_two_and_says_so(session) -> None:
    # The interaction worth pinning. A contract carrying the older shape, a
    # schedule with no tiers, is signed: the seeding writes the country's
    # ladder beside it rather than into it, and from then on the engine reads
    # the newer row and ignores the older one without a word. This is the word.
    svc = ContractsService(session)
    contract = await _contract(session, status="draft")
    session.add(
        RetentionSchedule(
            id=uuid.uuid4(),
            contract_id=contract.id,
            accrual_rule={"per_claim_percent": 5},
            release_rule={},
        )
    )
    await session.flush()

    await svc.transition_contract(contract.id, "active", actor_id=str(OWNER_ID))

    assert len(await svc.retention_repo.list_for_contract(contract.id)) == 2
    report = await _contract_report(svc, contract)
    findings = _findings(report, SINGLE_RULE)
    assert len(findings) == 1
    assert findings[0].passed is False
    assert findings[0].severity == Severity.WARNING
    assert "2 retention schedules" in findings[0].message
    assert "1 of them with tiers" in findings[0].message
    # A warning, so it does not stop the contract being executed. Stated about
    # this rule rather than about the report, which carries the other contract
    # rules and their own errors: a bare has_errors assertion here would be
    # testing whether the fixture bothered to add a party.
    assert SINGLE_RULE not in {e.rule_id for e in report.errors}


async def test_one_policy_on_a_contract_passes_the_count(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    await svc.set_retention_policy(contract, RetentionPolicyUpdate(tiers=_ladder(("0", "10"))))

    report = await _contract_report(svc, contract)
    findings = _findings(report, SINGLE_RULE)
    assert len(findings) == 1
    assert findings[0].passed is True


async def test_a_contract_with_no_schedule_is_not_asked_how_many_it_has(session) -> None:
    # Nothing written is not one policy and not two. The rule stays out of it
    # rather than reporting a pass on a question that was never asked.
    svc = ContractsService(session)
    contract = await _contract(session)

    report = await _contract_report(svc, contract)
    assert _findings(report, SINGLE_RULE) == []
