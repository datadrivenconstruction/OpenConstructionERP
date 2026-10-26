# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Guarantees​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ register against a real database, and across contracts, tendering and the demo.

Each test asks one cross-module question: does the register stay the only truth
for a bond the contract shows, does a certified claim reduce the advance
guarantee, does the first payment wait for the performance bond, are losing bid
bonds released at award, and does the daily job alert and lapse at the right days.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.contracts.models import Contract, ContractSecurity, ProgressClaim
from app.modules.contracts.schemas import ContractSecurityCreate, ContractSecurityUpdate
from app.modules.contracts.service import ContractsService
from app.modules.guarantees.models import Guarantee, GuaranteeEvent
from app.modules.guarantees.schemas import GuaranteeCreate, TransitionRequest
from app.modules.guarantees.service import GuaranteesService, first_payment_gate
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import isolated_engine

TODAY = date(2026, 10, 26)


@pytest.fixture(autouse=True)
def _rules_registered():
    from app.modules.guarantees.validators import register_guarantees_rules

    register_guarantees_rules()


@pytest_asyncio.fixture
async def ctx():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            owner = User(email=f"o-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", role="admin")
            session.add(owner)
            await session.flush()
            project = Project(name=f"P-{uuid.uuid4().hex[:6]}", owner_id=owner.id)
            session.add(project)
            await session.flush()
            contract = Contract(
                code=f"MC-{uuid.uuid4().hex[:6]}",
                title="Main contract",
                project_id=project.id,
                total_value=Decimal("10000000"),
                currency="AED",
                end_date="2027-12-31",
                terms={"defects_period_months": 12},
            )
            session.add(contract)
            await session.flush()
            yield session, project, contract, owner


async def _create(session, project, **kw) -> Guarantee:
    data = {"guarantee_type": "performance_bond", "amount": Decimal("1000000"), "currency": "AED", **kw}
    return await GuaranteesService(session).create(project.id, GuaranteeCreate(**data), "tester")


@pytest.mark.asyncio
async def test_bond_on_a_contract_is_one_record(ctx) -> None:
    session, project, contract, _ = ctx
    g = await _create(session, project, contract_id=contract.id, percent_of_contract=Decimal("10"))
    sec = await session.get(ContractSecurity, g.contract_security_id)
    assert sec.guarantee_id == g.id
    assert sec.amount == Decimal("1000000") and sec.status == "required"
    assert g.contract_value == Decimal("10000000")

    await GuaranteesService(session).transition(project.id, g.id, TransitionRequest(status="issued"))
    await session.refresh(sec)
    assert sec.status == "active"

    with pytest.raises(HTTPException) as exc:
        await ContractsService(session).update_security(sec.id, ContractSecurityUpdate(amount=Decimal("1")))
    assert exc.value.status_code == 409

    # A bond created from the contract side lands in the register too.
    created = await ContractsService(session).create_security(
        ContractSecurityCreate(contract_id=contract.id, security_type="retention_bond", amount=Decimal("500000"))
    )
    assert created.guarantee_id is not None
    reg = await session.get(Guarantee, created.guarantee_id)
    assert reg.guarantee_type == "retention_bond"


@pytest.mark.asyncio
async def test_certified_claim_reduces_advance_guarantee_and_audits(ctx) -> None:
    session, project, contract, _ = ctx
    g = await _create(
        session,
        project,
        guarantee_type="advance_payment",
        status="issued",
        contract_id=contract.id,
        advance_amount=Decimal("1000000"),
        advance_recovery_pct=Decimal("20"),
    )
    claim = ProgressClaim(
        contract_id=contract.id, claim_number="IPC-1", gross_amount=Decimal("2000000"), status="certified"
    )
    session.add(claim)
    await session.flush()
    service = GuaranteesService(session)
    assert await service.apply_certified_claim(claim.id) == 1
    assert g.amount == Decimal("600000.00") and g.status == "reduced"
    # Replaying the same certificate changes nothing.
    assert await service.apply_certified_claim(claim.id) == 0
    events = (await session.execute(select(GuaranteeEvent).where(GuaranteeEvent.guarantee_id == g.id))).scalars()
    reduced = [e for e in events if e.action == "reduced"]
    assert len(reduced) == 1 and reduced[0].amount_after == Decimal("600000.00")
    assert reduced[0].source == "progress_claim"


@pytest.mark.asyncio
async def test_first_payment_waits_for_performance_bond(ctx) -> None:
    session, project, contract, _ = ctx
    g = await _create(session, project, contract_id=contract.id)
    with pytest.raises(HTTPException) as exc:
        await first_payment_gate(session, contract.id)
    assert exc.value.status_code == 409
    await GuaranteesService(session).transition(project.id, g.id, TransitionRequest(status="issued"))
    assert (await first_payment_gate(session, contract.id))["allowed"] is True

    findings = await GuaranteesService(session).findings(project.id)
    assert not [f for f in findings if f["rule_id"] == "guarantees.performance_bond_before_first_payment"]


@pytest.mark.asyncio
async def test_award_releases_losing_bid_bonds(ctx) -> None:
    session, project, _contract, _ = ctx
    package, win, lose = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    a = await _create(
        session,
        project,
        guarantee_type="bid_bond",
        status="issued",
        direction="received",
        tender_id=package,
        bid_id=win,
    )
    b = await _create(
        session,
        project,
        guarantee_type="bid_bond",
        status="issued",
        direction="received",
        tender_id=package,
        bid_id=lose,
    )
    assert await GuaranteesService(session).release_bid_bonds_for_award(package, win) == 1
    assert a.status == "issued" and b.status == "released"


@pytest.mark.asyncio
async def test_daily_job_alerts_once_per_band_and_lapses(ctx) -> None:
    session, project, _contract, _ = ctx
    soon = await _create(session, project, status="issued", expiry_date=TODAY + timedelta(days=25))
    gone = await _create(session, project, status="issued", expiry_date=TODAY - timedelta(days=1))
    rolling = await _create(
        session, project, status="issued", expiry_date=TODAY - timedelta(days=1), auto_extend=True, extension_months=12
    )
    service = GuaranteesService(session)
    counts = await service.run_daily(TODAY)
    assert counts == {"alerts": 1, "extended": 1, "expired": 1}
    assert soon.last_alert_band == 30
    assert gone.status == "expired"
    assert rolling.status == "extended" and rolling.expiry_date > TODAY
    assert (await service.run_daily(TODAY))["alerts"] == 0


@pytest.mark.asyncio
async def test_retention_bond_replaces_cash_retention(ctx) -> None:
    session, project, contract, _ = ctx
    service = ContractsService(session)
    assert await service._cash_retention_replaced_by_bond(contract) is False
    await _create(
        session,
        project,
        guarantee_type="retention_bond",
        status="issued",
        contract_id=contract.id,
        replaces_cash_retention=True,
    )
    assert await service._cash_retention_replaced_by_bond(contract) is True


@pytest.mark.asyncio
async def test_demo_seed_gives_reducing_expiring_and_released(ctx) -> None:
    session, project, _contract, owner = ctx
    from app.modules.guarantees.demo import seed_demo_guarantees

    n = await seed_demo_guarantees(
        session,
        project_id=project.id,
        currency="AED",
        client_name="Client",
        contractor_name="Contractor",
        bidders=["A", "B", "C"],
        total_months=18,
        created_by=str(owner.id),
        today=TODAY,
    )
    assert n >= 6
    rows = (await session.execute(select(Guarantee).where(Guarantee.project_id == project.id))).scalars().all()
    statuses = {r.reference: r.status for r in rows}
    assert statuses["APG-0001"] == "reduced"
    assert "released" in statuses.values()
    rb = next(r for r in rows if r.reference == "RB-0001")
    assert (rb.expiry_date - TODAY).days <= 30
    exposure = await GuaranteesService(session).exposure(None, TODAY)
    assert exposure["credit_lines"] and exposure["credit_lines"][0]["used_amount"] > 0
    assert (
        await seed_demo_guarantees(
            session,
            project_id=project.id,
            currency="AED",
            client_name="C",
            contractor_name="C",
            bidders=[],
            total_months=18,
        )
        == 0
    )
