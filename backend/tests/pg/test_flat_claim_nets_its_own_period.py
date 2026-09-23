# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The flat branch nets a period, and that is the right answer, not a defect.

This file looks like a test of nothing. It passes today, it asserts behaviour
nobody is changing, and the first instinct on meeting it is to delete it as
redundant. It exists to stop a specific wrong fix.

``roll_claim_retention`` has two branches that net differently. The engine
branch subtracts the previous certificates because it works from
``completed_stored_to_date``, a cumulative base, and without the subtraction it
would bill the whole job every month. The flat branch does not subtract them
because it works from this period's costs or this period's line values, a
period base, and if it did subtract them it would under-bill by everything
certified to date. Two correct answers to two different questions. The
docstring that once promised the second shape for both branches was the thing
that was actually wrong.

The asymmetry reads like a defect, and it was read as one: the red that was
nearly written here would have asserted the flat branch should subtract prior
certificates too. Had it been built and made to pass, the third month of the
job below would have billed 13500 instead of 22500 and the fourth would have
billed nothing at all, every month after the first short-paying the contractor
by the whole job to date, and it would have arrived looking like a cleanup.

Three months rather than two on purpose. Two can agree by luck; a drift of this
kind accumulates and cannot hide across three.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.events import event_bus
from app.modules.contracts.models import Contract, ContractLine, ProgressClaim
from app.modules.contracts.schemas import AutoGenerateClaimRequest
from app.modules.contracts.service import ContractsService
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    from app.modules.contracts.validators import register_contracts_validation_rules

    monkeypatch.setattr(event_bus, "publish_detached", lambda *a, **k: None)
    register_contracts_validation_rules()


async def _job(session, contract_type: str = "cost_plus"):
    suffix = uuid.uuid4().hex[:8]
    owner = User(id=uuid.uuid4(), email=f"net-{suffix}@site.example", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(
        id=uuid.uuid4(), name="Netting", owner_id=owner.id, currency="USD", country_code="US", metadata_={}
    )
    session.add(project)
    await session.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{suffix}",
        title="Cost of the work",
        project_id=project.id,
        contract_type=contract_type,
        currency="USD",
        total_value=Decimal("600000"),
        original_contract_value=Decimal("600000"),
        retention_percent=Decimal("10"),
        status="active",
    )
    session.add(contract)
    await session.flush()
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="A",
        description="Concrete",
        quantity=Decimal("1"),
        unit_rate=Decimal("600000"),
        total_value=Decimal("600000"),
        order_index=0,
    )
    session.add(line)
    await session.flush()
    return SimpleNamespace(owner=owner, project=project, contract=contract, line=line)


async def _claim(session, job, number: str, month: int) -> ProgressClaim:
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=job.contract.id,
        claim_number=number,
        period_start=f"2026-{month:02d}-01",
        period_end=f"2026-{month:02d}-28",
        period_from=date(2026, month, 1),
        period_to=date(2026, month, 28),
        currency="USD",
        status="draft",
    )
    session.add(claim)
    await session.flush()
    return claim


async def test_three_generated_cost_plus_months_do_not_drift(pg_session) -> None:
    """Each month bills its own period and the certificate agrees, three times."""
    svc = ContractsService(pg_session)
    job = await _job(pg_session)
    rows: list[str] = []
    costs = [Decimal("10000"), Decimal("25000"), Decimal("7000")]
    running_certified = Decimal("0")

    for index, cost in enumerate(costs, start=3):
        claim = await svc.auto_generate_claim_lines(
            (await _claim(pg_session, job, f"PC-{index - 2}", index)).id,
            AutoGenerateClaimRequest(actual_costs_total=cost),
        )
        summary = (await svc.build_aia_application(claim.id))["summary"]
        expected_period_net = (cost - cost / Decimal("10")).quantize(Decimal("0.0001"))
        rows.append(
            f"month {index}: cost={cost} claim_net={claim.net_due} L4={summary['total_completed_stored']} "
            f"L6={summary['total_earned_less_retainage']} L7={summary['previous_certificates_total']} "
            f"L8={summary['current_payment_due']} expected_period_net={expected_period_net} "
            f"prior_certified_so_far={running_certified}"
        )
        # The claim nets this period only, and does not subtract prior certificates.
        assert claim.net_due == expected_period_net, rows[-1]
        # The certificate reaches the same figure the other way, from a cumulative
        # base minus what was certified before. Two routes, one number.
        assert summary["previous_certificates_total"] == running_certified.quantize(Decimal("0.01")), rows[-1]
        assert summary["current_payment_due"] == claim.net_due, rows[-1]

        for target in ("submitted", "approved", "certified"):
            await svc.transition_claim(claim.id, target, "netting-test")
        running_certified += claim.net_due

    total_cost = sum(costs, Decimal("0"))
    rows.append(f"total cost={total_cost} total certified={running_certified}")
    # Nothing was billed twice and nothing was dropped.
    assert running_certified == (total_cost - total_cost / Decimal("10")).quantize(Decimal("0.0001")), rows[-1]
