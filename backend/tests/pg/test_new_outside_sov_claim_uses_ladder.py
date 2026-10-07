# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""New outside-SOV claims use the current ladder; issued history stays unchanged."""

from copy import deepcopy
from decimal import Decimal

import pytest

from app.modules.contracts.router import create_claim_line
from app.modules.contracts.schemas import ProgressClaimLineCreate
from app.modules.contracts.service import ContractsService
from tests.pg.test_retention_line5_counts_money_outside_the_schedule_once import (
    LADDER_ZERO_PAST_HALF,
    _certify,
    _claim,
    _job,
    _rules,  # noqa: F401 - register validation rules in this test module too.
    _schedule_month,
)

pytestmark = pytest.mark.asyncio
STAMP = "outside_sov_retention_version"


async def _new_lineless(service, session, job, month=2, gross="20000"):
    claim = await _claim(service, job, month)
    await service.claim_repo.update_fields(claim.id, gross_amount=Decimal(gross))
    return claim


async def test_new_claim_uses_ladder_without_rewriting_old_certificate(pg_session):
    service = ContractsService(pg_session)
    job = await _job(pg_session, [("A", "100000"), ("B", "100000")], ladder=LADDER_ZERO_PAST_HALF)
    earlier = await _schedule_month(service, pg_session, job, 1, {"A": "100000"})
    old = await _new_lineless(service, pg_session, job)
    await service.claim_repo.update_fields(old.id, metadata_={})  # Actual pre-feature persisted shape.
    await service.roll_claim_retention(old.id)
    old = await _certify(service, pg_session, old, engine_worked=False)
    before = deepcopy(await service.build_payment_application(old.id))
    old_money = (old.retention_amount, old.net_due, old.completed_stored_to_date, old.retention_held_to_date)

    new = await _new_lineless(service, pg_session, job, month=3)
    await service.roll_claim_retention(new.id)
    await pg_session.refresh(new)
    assert new.retention_amount == Decimal("0")  # Existing rate_at(50) remains the lower tier.
    assert new.net_due == Decimal("20000")
    assert await service.flat_claim_retention(job.contract, new, Decimal("20000")) == Decimal("2000")
    # The separate helper must not change SOV-line preview semantics.
    assert await service.build_payment_application(old.id) == before
    await pg_session.refresh(old)
    assert (old.retention_amount, old.net_due, old.completed_stored_to_date, old.retention_held_to_date) == old_money
    assert earlier.status == "certified"
    new = await _certify(service, pg_session, new, engine_worked=False)
    assert new.retention_amount == Decimal("0")
    assert new.status == "certified"


async def test_server_stamp_cannot_be_removed_or_added_to_legacy_by_patch(pg_session):
    service = ContractsService(pg_session)
    job = await _job(pg_session, [("A", "1000")], ladder=LADDER_ZERO_PAST_HALF)
    new = await _claim(service, job, 1)
    assert new.metadata_[STAMP] == 1
    for submitted in ({}, {STAMP: 0}, {STAMP: "forged"}):
        await service.update_progress_claim_fields(new, {"metadata_": submitted})
        assert new.metadata_[STAMP] == 1
    await service.claim_repo.update_fields(new.id, metadata_={"legacy": True})
    await pg_session.refresh(new)
    await service.update_progress_claim_fields(new, {"metadata_": {STAMP: 1, "note": "editable"}})
    assert STAMP not in new.metadata_
    assert new.metadata_["note"] == "editable"


async def test_create_overrides_client_supplied_stamp(pg_session):
    from types import SimpleNamespace

    service = ContractsService(pg_session)
    job = await _job(pg_session, [("A", "1000")], ladder=LADDER_ZERO_PAST_HALF)
    claim = await service.create_progress_claim(
        SimpleNamespace(
            contract_id=job.contract.id,
            claim_number="CLIENT",
            period_start="2026-01-01",
            period_end="2026-01-31",
            claim_date="2026-01-31",
            currency="USD",
            metadata={STAMP: "legacy", "note": "kept"},
        )
    )
    assert claim.metadata_[STAMP] == 1
    assert claim.metadata_["note"] == "kept"


@pytest.mark.parametrize("kind,basis", [("cost_plus", "cost"), ("tm", "cost"), ("lump_sum", "milestone")])
async def test_cost_and_instalment_claims_keep_existing_rate(pg_session, kind, basis):
    service = ContractsService(pg_session)
    job = await _job(pg_session, [("A", "100000"), ("B", "100000")], ladder=LADDER_ZERO_PAST_HALF)
    await _schedule_month(service, pg_session, job, 1, {"A": "100000"})
    job.contract.contract_type = kind
    await pg_session.flush()
    claim = await _new_lineless(service, pg_session, job)
    await service.claim_repo.update_fields(claim.id, gross_basis=basis)
    await service.roll_claim_retention(claim.id)
    await pg_session.refresh(claim)
    assert claim.retention_amount == Decimal("2000")


@pytest.mark.parametrize(
    "currency,gross,expected", [("JPY", "123", "6"), ("USD", "12.35", "0.62"), ("KWD", "12.345", "0.617")]
)
async def test_new_rate_uses_currency_precision(pg_session, currency, gross, expected):
    service = ContractsService(pg_session)
    ladder = {
        **LADDER_ZERO_PAST_HALF,
        "tiers": [
            {"from_percent_complete": "0", "rate": "10"},
            {"from_percent_complete": "50", "rate": "5"},
        ],
    }
    job = await _job(pg_session, [("A", "100000"), ("B", "100000")], ladder=ladder, currency=currency)
    await _schedule_month(service, pg_session, job, 1, {"A": "100000"})
    claim = await _new_lineless(service, pg_session, job, gross=gross)
    await service.roll_claim_retention(claim.id)
    await pg_session.refresh(claim)
    assert claim.retention_amount == Decimal(expected)


async def test_new_ladder_rate_respects_cap_and_prior_draft_accrual(pg_session):
    service = ContractsService(pg_session)
    ladder = {
        **LADDER_ZERO_PAST_HALF,
        "tiers": [{"from_percent_complete": "0", "rate": "10"}, {"from_percent_complete": "50", "rate": "5"}],
        "cap": {"percent_of_contract_sum": "6"},
    }
    job = await _job(pg_session, [("A", "100000"), ("B", "100000")], ladder=ladder)
    await _schedule_month(service, pg_session, job, 1, {"A": "100000"})
    first = await _new_lineless(service, pg_session, job, gross="100000")
    await service.roll_claim_retention(first.id)
    await pg_session.refresh(first)
    assert first.retention_amount == Decimal("2000")  # 12,000 cap less 10,000 already held.
    second = await _new_lineless(service, pg_session, job, month=3, gross="100000")
    await service.roll_claim_retention(second.id)
    await pg_session.refresh(second)
    assert second.retention_amount == Decimal("0")
    assert first.status == "draft"


@pytest.mark.parametrize("stored", ["0", "40000"])
async def test_outside_gross_and_stored_materials_do_not_advance_the_ladder(pg_session, stored):
    service = ContractsService(pg_session)
    job = await _job(pg_session, [("A", "120000"), ("B", "80000")], ladder=LADDER_ZERO_PAST_HALF)
    prior = await _claim(service, job, 1)
    await create_claim_line(
        ProgressClaimLineCreate(
            progress_claim_id=prior.id,
            contract_line_id=job.lines["A"].id,
            period_completed_qty=Decimal("0.8"),
            period_completed_value=Decimal("80000"),
            period_completed_pct=Decimal("0"),
            materials_stored_value=Decimal(stored),
        ),
        pg_session,
        str(job.project.owner_id),
    )
    await _certify(service, pg_session, prior, engine_worked=True)
    claim = await _new_lineless(service, pg_session, job, gross="40000")
    await service.roll_claim_retention(claim.id)
    await pg_session.refresh(claim)
    # Work is still 40%, not 60% after adding the outside gross or materials.
    assert claim.retention_amount == Decimal("4000")
