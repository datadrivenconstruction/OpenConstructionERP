"""Valuation grid of a client claim and of a sub pay application, on PostgreSQL.

Worked example: footings, 100 m3 at 120 per m3.
Claim 1 certified 30 m3 with a running total of 4000. Claim 2 submits 20 m3
(2400), assesses 18, certifies 15, and its running total falls to 3800, so the
grid warns until a note says why. Assessed 18 x 120 = 2160, certified 15 x 120
= 1800, cumulative certified 45 m3.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

pytestmark = pytest.mark.asyncio

_T0 = datetime(2026, 5, 1, tzinfo=UTC)


async def _client_world(session: Any) -> dict[str, Any]:
    from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, ProgressClaimLine
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    sfx = uuid.uuid4().hex[:8]
    owner = User(id=uuid.uuid4(), email=f"vgrid-{sfx}@site.example", hashed_password="x", full_name="QS")
    project = Project(id=uuid.uuid4(), name="Valuation grid", owner_id=owner.id, currency="USD")
    contract = Contract(
        id=uuid.uuid4(),
        project_id=project.id,
        code=f"VG-{sfx}",
        title="Prime",
        currency="USD",
        counterparty_type="client",
        status="active",
    )
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="03.10",
        description="Footings",
        unit="m3",
        quantity=Decimal("100"),
        unit_rate=Decimal("120"),
        total_value=Decimal("12000"),
    )
    c1 = ProgressClaim(
        id=uuid.uuid4(), contract_id=contract.id, claim_number="PC-1", currency="USD", status="certified"
    )
    c2 = ProgressClaim(
        id=uuid.uuid4(), contract_id=contract.id, claim_number="PC-2", currency="USD", status="submitted"
    )
    c1.created_at = _T0
    c2.created_at = _T0 + timedelta(days=30)
    l1 = ProgressClaimLine(
        id=uuid.uuid4(),
        progress_claim_id=c1.id,
        contract_line_id=line.id,
        period_completed_qty=Decimal("30"),
        period_completed_value=Decimal("3600"),
        cumulative_completed_value=Decimal("4000"),
        assessed_qty=Decimal("30"),
        certified_qty=Decimal("30"),
    )
    l2 = ProgressClaimLine(
        id=uuid.uuid4(),
        progress_claim_id=c2.id,
        contract_line_id=line.id,
        period_completed_qty=Decimal("20"),
        period_completed_value=Decimal("2400"),
        cumulative_completed_value=Decimal("3800"),
        assessed_qty=Decimal("18"),
        certified_qty=Decimal("15"),
    )
    for batch in ([owner], [project], [contract], [line, c1, c2], [l1, l2]):
        session.add_all(batch)
        await session.flush()
    return {"claim": c2, "line": l2}


async def test_client_claim_grid_prices_stages_and_flags_a_drop_until_noted(pg_session) -> None:
    from app.modules.contracts.valuation_grid import NOTE_KEY, build_claim_grid

    world = await _client_world(pg_session)
    grid = await build_claim_grid(pg_session, world["claim"])
    (row,) = grid["rows"]
    assert row["label"] == "03.10 Footings"
    submitted = row["stages"]["submitted"]["amount"]
    assert (submitted["source"], submitted["field"]) == ("stored", "period_completed_value")
    assert Decimal(submitted["value"]) == Decimal("2400")
    assert row["stages"]["assessed"]["amount"]["value"] == "2160.00"
    assert row["stages"]["certified"]["amount"]["value"] == "1800.00"
    assert Decimal(row["cumulative_certified_qty"]) == Decimal("45")
    assert Decimal(row["prior_cumulative"]) == Decimal("4000")
    assert [f["rule_id"] for f in row["findings"]] == ["valuation.cumulative_not_decreasing"]

    world["claim"].metadata_ = {NOTE_KEY: "Footing F3 remeasured after survey"}
    await pg_session.flush()
    noted = await build_claim_grid(pg_session, world["claim"])
    assert noted["rows"][0]["findings"] == []
    assert noted["note"].startswith("Footing F3")


async def test_sub_application_grid_uses_stored_amounts_and_the_claimed_rate(pg_session) -> None:
    from app.modules.projects.models import Project
    from app.modules.subcontractors.models import (
        PaymentApplication,
        PaymentApplicationLine,
        SubcontractAgreement,
        Subcontractor,
        WorkPackage,
    )
    from app.modules.subcontractors.valuation_grid import build_application_grid
    from app.modules.users.models import User

    sfx = uuid.uuid4().hex[:8]
    owner = User(id=uuid.uuid4(), email=f"vgrid-sub-{sfx}@site.example", hashed_password="x", full_name="QS")
    project = Project(id=uuid.uuid4(), name="Valuation grid sub", owner_id=owner.id, currency="USD")
    sub = Subcontractor(id=uuid.uuid4(), legal_name=f"Example Concrete {sfx}")
    agreement = SubcontractAgreement(
        id=uuid.uuid4(),
        subcontractor_id=sub.id,
        project_id=project.id,
        title="Concrete",
        currency="USD",
        total_value=Decimal("8000"),
        status="active",
    )
    wp = WorkPackage(id=uuid.uuid4(), agreement_id=agreement.id, name="Footings")
    pa1 = PaymentApplication(
        id=uuid.uuid4(), agreement_id=agreement.id, application_number="PA-1", status="paid", currency="USD"
    )
    pa2 = PaymentApplication(
        id=uuid.uuid4(),
        agreement_id=agreement.id,
        application_number="PA-2",
        status="submitted",
        currency="USD",
        period_end=date(2026, 6, 30),
    )
    pa1.created_at = _T0
    pa2.created_at = _T0 + timedelta(days=30)
    ln1 = PaymentApplicationLine(
        id=uuid.uuid4(),
        payment_application_id=pa1.id,
        work_package_id=wp.id,
        claimed_qty=Decimal("10"),
        certified_qty=Decimal("10"),
        claimed_amount=Decimal("1000"),
    )
    ln2 = PaymentApplicationLine(
        id=uuid.uuid4(),
        payment_application_id=pa2.id,
        work_package_id=wp.id,
        claimed_qty=Decimal("8"),
        assessed_qty=Decimal("7"),
        certified_qty=Decimal("6"),
        claimed_amount=Decimal("800"),
        certified_amount=Decimal("600"),
    )
    for batch in ([owner], [project, sub], [agreement], [wp], [pa1, pa2], [ln1, ln2]):
        session = pg_session
        session.add_all(batch)
        await session.flush()

    grid = await build_application_grid(pg_session, pa2)
    (row,) = grid["rows"]
    assert row["label"] == "Footings"
    assert row["stages"]["submitted"]["amount"]["field"] == "claimed_amount"
    assert row["stages"]["assessed"]["amount"] == {
        "value": "700.00",
        "source": "computed",
        "field": "claimed_amount/claimed_qty",
    }
    assert row["stages"]["certified"]["amount"]["source"] == "stored"
    assert Decimal(row["cumulative"]) == Decimal("18")
    assert Decimal(row["cumulative_certified_qty"]) == Decimal("16")
    assert row["findings"] == []
