# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A draft claim is not a previous certificate, and leaving it out never pays twice.

A draft has not left the contractor, so it certified nothing, and a payment
application built now leaves it out of column D and G702 line 7. Counting it
used to put work nobody had applied for into "previous certificates".

Leaving drafts out opens one order of events that counting them had closed: a
later claim goes out while an earlier one is still a draft, so the later one
bills that work, and the earlier one then goes out and bills it again. The
earlier draft is refused instead. The other order, the earlier one going out
first, is caught by ``pay_application.prior_matches_earlier_claims`` on the
later claim, which is blocked until it is generated again.

A claim that has left draft keeps the figures it went out with. The claims it
counted as previous are frozen onto it when it leaves draft, and a claim issued
before this rule, which carries no such set, still counts drafts as it did.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.contracts.models import Contract, ContractLine
from app.modules.contracts.repository import PRIOR_CLAIM_IDS_KEY
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
    owner = User(id=uuid.uuid4(), email=f"draft-prior-{suffix}@site.example", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(
        id=uuid.uuid4(),
        name="Drafts are not previous",
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


async def _march_draft_and_april(svc: ContractsService, contract: Contract, line: ContractLine):
    march = await _claim(svc, contract, "PC-1", "2026-03-01", "2026-03-31")
    march = await _generate(svc, march, line, "40")
    april = await _claim(svc, contract, "PC-2", "2026-04-01", "2026-04-30")
    april = await _generate(svc, april, line, "60")
    return march, april


async def test_a_draft_before_the_claim_is_not_previously_certified(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract, line = await _contract(pg_session)
    _march, april = await _march_draft_and_april(svc, contract, line)

    # March never went out, so April applies for all sixty per cent.
    [row] = await svc.claim_line_repo.list_for_claim(april.id)
    assert row.prior_completed_value == Decimal("0")
    assert row.period_completed_value == Decimal("60000")
    assert april.prior_claims_total == Decimal("0")
    application = await svc.build_aia_application(april.id)
    assert application["lines"][0]["previous_value"] == Decimal("0.00")
    assert application["summary"]["previous_certificates_total"] == Decimal("0.00")
    assert application["summary"]["current_payment_due"] == april.net_due == Decimal("54000")


async def test_the_earlier_draft_going_out_first_blocks_the_later_claim_until_it_is_regenerated(pg_session) -> None:
    register_contracts_validation_rules()
    svc = ContractsService(pg_session)
    contract, line = await _contract(pg_session)
    march, april = await _march_draft_and_april(svc, contract, line)

    await svc.transition_claim(march.id, "submitted")
    report = await svc.validate_claim(april.id)
    assert [f for f in report["errors"] if f["rule_id"] == "pay_application.prior_matches_earlier_claims"]
    with pytest.raises(HTTPException) as refused:
        await svc.transition_claim(april.id, "submitted")
    assert refused.value.status_code == 422

    april = await _generate(svc, april, line, "60")
    assert april.gross_amount == Decimal("20000")
    assert april.prior_claims_total == Decimal("36000")
    await svc.transition_claim(april.id, "submitted")


async def test_an_earlier_draft_cannot_go_out_behind_a_later_claim_that_already_billed_its_work(pg_session) -> None:
    register_contracts_validation_rules()
    svc = ContractsService(pg_session)
    contract, line = await _contract(pg_session)
    march, april = await _march_draft_and_april(svc, contract, line)
    await svc.transition_claim(april.id, "submitted")

    # April applied for all sixty per cent. March going out now would ask for
    # forty of them a second time.
    with pytest.raises(HTTPException) as refused:
        await svc.transition_claim(march.id, "submitted")
    assert refused.value.status_code == 409
    assert refused.value.detail["error"] == "later_claim_already_issued"
    assert refused.value.detail["later_claims"] == ["PC-2"]
    assert (await svc.claim_repo.get_by_id(march.id)).status == "draft"

    # A rejected later claim billed nothing, so it no longer stands in the way.
    await svc.transition_claim(april.id, "rejected")
    await svc.transition_claim(march.id, "submitted")


async def test_a_claim_that_left_draft_keeps_the_claims_it_counted(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract, line = await _contract(pg_session)
    march, april = await _march_draft_and_april(svc, contract, line)
    await svc.transition_claim(april.id, "submitted")
    april = await svc.claim_repo.get_by_id(april.id)
    assert april.metadata_[PRIOR_CLAIM_IDS_KEY] == []

    # A metadata write through the claim's own update path cannot change the
    # set: with March in it the issued claim would reprint with a line 7.
    await svc.update_progress_claim_fields(
        april, {"metadata_": {"note": "sent by post", PRIOR_CLAIM_IDS_KEY: [str(march.id)]}}
    )
    await pg_session.refresh(april)
    assert april.metadata_[PRIOR_CLAIM_IDS_KEY] == []
    assert april.metadata_["note"] == "sent by post"
    application = await svc.build_aia_application(april.id)
    assert application["summary"]["previous_certificates_total"] == Decimal("0.00")
    assert application["summary"]["current_payment_due"] == Decimal("54000.00")

    # Certification writes its own metadata and keeps the set as well.
    await svc.transition_claim(april.id, "approved")
    await svc.transition_claim(april.id, "certified", actor_id=str(uuid.uuid4()))
    april = await svc.claim_repo.get_by_id(april.id)
    assert april.metadata_[PRIOR_CLAIM_IDS_KEY] == []


async def test_an_earlier_claim_sent_back_to_draft_stays_previous_to_the_claim_that_counted_it(pg_session) -> None:
    register_contracts_validation_rules()
    svc = ContractsService(pg_session)
    contract, line = await _contract(pg_session)
    march = await _claim(svc, contract, "PC-1", "2026-03-01", "2026-03-31")
    march = await _generate(svc, march, line, "40")
    await svc.transition_claim(march.id, "submitted")
    april = await _claim(svc, contract, "PC-2", "2026-04-01", "2026-04-30")
    april = await _generate(svc, april, line, "60")
    await svc.transition_claim(april.id, "submitted")
    assert (await svc.claim_repo.get_by_id(april.id)).metadata_[PRIOR_CLAIM_IDS_KEY] == [str(march.id)]

    # March is rejected and reworked as a draft. April went out counting it,
    # so April still prints March as previous, and March may go out again:
    # April billed only the twenty per cent on top of it.
    await svc.transition_claim(march.id, "rejected")
    await svc.transition_claim(march.id, "draft")
    application = await svc.build_aia_application(april.id)
    assert application["summary"]["previous_certificates_total"] == Decimal("36000.00")
    assert application["summary"]["current_payment_due"] == Decimal("18000.00")
    await svc.transition_claim(march.id, "submitted")


async def test_a_claim_issued_before_the_rule_still_counts_the_drafts_it_counted(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract, line = await _contract(pg_session)
    march = await _claim(svc, contract, "PC-1", "2026-03-01", "2026-03-31")
    await _generate(svc, march, line, "40")
    april = await _claim(svc, contract, "PC-2", "2026-04-01", "2026-04-30")
    # Issued with no stamp, as a claim that left draft before the stamp
    # existed. Its certificate counted March, and every reprint must too.
    await svc.claim_repo.update_fields(april.id, status="certified")
    april = await svc.claim_repo.get_by_id(april.id)
    assert PRIOR_CLAIM_IDS_KEY not in (april.metadata_ or {})

    prior = await svc.claim_repo.prior_claims(contract.id, before_claim_id=april.id)
    assert [c.claim_number for c in prior] == ["PC-1"]
