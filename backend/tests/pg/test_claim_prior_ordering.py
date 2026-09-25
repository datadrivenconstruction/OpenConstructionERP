# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Money invariants of a payment application, against the database.

Three defects shared one symptom, a certificate asking the owner for the wrong
amount, and this file holds all three shut on the lane that blocks:

* "Prior" meant every other claim on the contract, so regenerating or
  re-rendering claim N after claim N+1 existed counted N+1 as previous
  (G703 column D and G702 line 7).
* A percent complete TO DATE was stored as the value for the period, so a
  line at 40% and then 60% billed 40 and then 60.
* G702 line 7 was the prior claims' gross, which left their retention in it
  and under-billed line 8 by that retention every month.

Every figure is asserted through the service the screens call, and the last
assertion of each test is the one that matters to the owner: G702 line 8
equals the net due the claim stores.
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


@pytest.fixture(autouse=True)
def _pay_application_rules() -> None:
    # Submitting a claim runs the pay_application gate, which refuses when the
    # rule set is not loaded; registering here keeps the file order-independent.
    register_contracts_validation_rules()


LINE_VALUE = Decimal("100000")


async def _contract(session) -> tuple[Contract, ContractLine]:
    suffix = uuid.uuid4().hex[:8]
    owner = User(id=uuid.uuid4(), email=f"prior-order-{suffix}@site.example", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(
        id=uuid.uuid4(),
        name="Prior ordering",
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
    return contract, line


async def _claim(svc: ContractsService, contract: Contract, number: str, start: str, end: str):
    return await svc.create_progress_claim(
        SimpleNamespace(
            contract_id=contract.id,
            claim_number=number,
            period_start=start,
            period_end=end,
            claim_date=end,
            currency="USD",
            metadata={},
        )
    )


async def _generate(svc: ContractsService, claim, line: ContractLine, pct: str):
    return await svc.auto_generate_claim_lines(
        claim.id, AutoGenerateClaimRequest(completion={str(line.id): Decimal(pct)})
    )


async def _only_line(svc: ContractsService, claim):
    [row] = await svc.claim_line_repo.list_for_claim(claim.id)
    return row


async def test_forty_then_sixty_bills_forty_then_twenty_and_the_certificate_agrees(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract, line = await _contract(pg_session)
    march = await _claim(svc, contract, "PC-1", "2026-03-01", "2026-03-31")
    april = await _claim(svc, contract, "PC-2", "2026-04-01", "2026-04-30")

    march = await _generate(svc, march, line, "40")
    # March goes out before April is drawn: a draft is not a previous
    # certificate, so April would otherwise bill all sixty per cent.
    await svc.transition_claim(march.id, "submitted")
    april = await _generate(svc, april, line, "60")

    first, second = await _only_line(svc, march), await _only_line(svc, april)
    assert first.period_completed_value == Decimal("40000")
    assert second.prior_completed_value == Decimal("40000")
    assert second.period_completed_value == Decimal("20000")
    assert second.cumulative_completed_value == Decimal("60000")
    assert (april.gross_amount, april.retention_amount, april.net_due) == (
        Decimal("20000"),
        Decimal("2000"),
        Decimal("18000"),
    )
    # "Prior claims" is what the earlier claims certified, net of retention.
    assert april.prior_claims_total == Decimal("36000")

    application = await svc.build_aia_application(april.id)
    [row] = application["lines"]
    assert row["previous_value"] == Decimal("40000.00")
    assert row["this_period_value"] == Decimal("20000.00")
    assert row["total_completed_stored"] == Decimal("60000.00")
    summary = application["summary"]
    assert summary["previous_certificates_total"] == Decimal("36000.00")
    # March was worked out by the retention engine, so its certificate
    # snapshot is line 7, not a reconstruction.
    assert summary["previous_certificates_basis"] == "snapshot"
    assert summary["current_payment_due"] == april.net_due


async def test_an_earlier_claim_regenerated_later_counts_only_what_came_before_it(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract, line = await _contract(pg_session)
    # Created out of billing order on purpose: "before" is by period.
    april = await _claim(svc, contract, "PC-2", "2026-04-01", "2026-04-30")
    march = await _claim(svc, contract, "PC-1", "2026-03-01", "2026-03-31")
    march = await _generate(svc, march, line, "40")
    await svc.transition_claim(march.id, "submitted")
    april = await _generate(svc, april, line, "60")
    # April has gone out, so it is not left out as a draft: only billing
    # order can keep it from being previous to March.
    await svc.transition_claim(april.id, "submitted")

    # March sent back and regenerated after April exists: April is not
    # previous to it.
    await svc.transition_claim(march.id, "rejected")
    await svc.transition_claim(march.id, "draft")
    march = await _generate(svc, march, line, "40")
    row = await _only_line(svc, march)
    assert row.prior_completed_value == Decimal("0")
    assert row.period_completed_value == Decimal("40000")
    assert march.prior_claims_total == Decimal("0")

    application = await svc.build_aia_application(march.id)
    assert application["lines"][0]["previous_value"] == Decimal("0.00")
    assert application["summary"]["previous_certificates_total"] == Decimal("0.00")
    assert application["summary"]["current_payment_due"] == march.net_due == Decimal("36000")

    # And April, which went out counting March, still reads March, and only
    # March, as previous.
    application = await svc.build_aia_application(april.id)
    assert application["lines"][0]["previous_value"] == Decimal("40000.00")
    assert application["summary"]["previous_certificates_total"] == Decimal("36000.00")


async def test_a_rejected_claim_certified_nothing(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract, line = await _contract(pg_session)
    march = await _claim(svc, contract, "PC-1", "2026-03-01", "2026-03-31")
    await _generate(svc, march, line, "40")
    await svc.claim_repo.update_fields(march.id, status="rejected")
    april = await _claim(svc, contract, "PC-2", "2026-04-01", "2026-04-30")
    april = await _generate(svc, april, line, "60")

    row = await _only_line(svc, april)
    assert row.prior_completed_value == Decimal("0")
    assert row.period_completed_value == Decimal("60000")
    assert april.prior_claims_total == Decimal("0")


async def test_a_percent_that_goes_backwards_bills_nothing_and_the_report_says_so(pg_session) -> None:
    register_contracts_validation_rules()
    svc = ContractsService(pg_session)
    contract, line = await _contract(pg_session)
    march = await _claim(svc, contract, "PC-1", "2026-03-01", "2026-03-31")
    await _generate(svc, march, line, "40")
    await svc.transition_claim(march.id, "submitted")
    april = await _claim(svc, contract, "PC-2", "2026-04-01", "2026-04-30")
    april = await _generate(svc, april, line, "30")

    row = await _only_line(svc, april)
    assert row.period_completed_value == Decimal("0")
    assert row.cumulative_completed_value == Decimal("40000")
    assert april.gross_amount == Decimal("0")

    report = await svc.validate_claim(april.id)
    regressed = [w for w in report["warnings"] if w["rule_id"] == "pay_application.percent_regressed"]
    assert len(regressed) == 1
    assert regressed[0]["element_ref"] == str(line.id)

    # Regenerated at a percent that moves forward, the finding goes with it.
    april = await _generate(svc, april, line, "70")
    assert "percent_regressed" not in (april.metadata_ or {})
    report = await svc.validate_claim(april.id)
    assert not [w for w in report["warnings"] if w["rule_id"] == "pay_application.percent_regressed"]


async def test_committing_a_progress_preview_bills_on_the_same_basis(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract, line = await _contract(pg_session)
    march = await _claim(svc, contract, "PC-1", "2026-03-01", "2026-03-31")
    await _generate(svc, march, line, "40")
    await svc.transition_claim(march.id, "submitted")
    april = await _claim(svc, contract, "PC-2", "2026-04-01", "2026-04-30")

    april = await svc.commit_preview_to_claim(
        april.id,
        [SimpleNamespace(contract_line_id=line.id, period_completed_pct=Decimal("60"), period_completed_value=None)],
    )
    row = await _only_line(svc, april)
    assert row.prior_completed_value == Decimal("40000")
    assert row.period_completed_value == Decimal("20000")
    assert april.net_due == Decimal("18000")
    assert april.prior_claims_total == Decimal("36000")
