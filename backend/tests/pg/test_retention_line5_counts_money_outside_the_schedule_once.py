# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""G702 line 5 counts retention held on money no schedule line carries exactly once.

Line 5 is the total of G703 column I: everything withheld to date less what
has been released. On a contract whose retention the engine works out (lump
sum, unit price and the like), a month billed with no schedule line behind it
withholds its own retention, and the continuation sheet carries that month on
a row of its own. The engine used to measure what the schedule requires
against everything the earlier claims held, that month included. Three things
followed:

* When the schedule's requirement fell behind (a ladder that stops retaining
  past half way), the lineless month's retention was ratcheted into the
  schedule's own figure and the sheet then added the row on top, printing it
  twice.
* When the requirement stayed ahead (a flat rate), the lineless month's
  retention was taken off this month's accrual, so the claim under-accrued and
  the next claim's line 7 over-counted by the same amount.
* The claim's net due subtracted a line 7 built over the whole job from a
  completed figure built over the schedule alone, so the figure the
  certificate event carries fell short of line 8 by the lineless month's net.

And a full release could never reach the row's retention.

Two contracts, 10% retention on both. Case L: lump sum, A 100,000 and B
100,000, retention 10% up to 50% complete then 0%. Month 1 bills A in full,
month 2 bills 20,000 with no line behind it, month 3 bills 40,000 on B, month
4 bills a final release of 12,000 and no work. Case F: flat 10%, A 60,000 and
B 40,000. Month 1 bills 20,000 with no line behind it, month 2 bills A, month
3 bills B.

The lineless month is written the way such a claim reaches an engine contract
in the product (a schedule line deleted under a certified claim takes its
claim lines with it): a gross on a claim with no lines, rolled through the
same method every writer ends in.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.contracts.models import Contract, ContractLine, RetentionRelease, RetentionSchedule
from app.modules.contracts.router import create_claim_line
from app.modules.contracts.schemas import ProgressClaimLineCreate
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

PERIODS = [
    ("2026-03-01", "2026-03-31"),
    ("2026-04-01", "2026-04-30"),
    ("2026-05-01", "2026-05-31"),
    ("2026-06-01", "2026-06-30"),
]

LADDER_ZERO_PAST_HALF = {
    "tiers": [
        {"from_percent_complete": 0, "rate": 10},
        {"from_percent_complete": 50, "rate": 0},
    ],
    "tier_mode": "prospective",
}


async def _job(session, lines, *, ladder=None):
    suffix = uuid.uuid4().hex[:8]
    owner = User(id=uuid.uuid4(), email=f"line5-{suffix}@site.example", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(
        id=uuid.uuid4(),
        name="Line 5",
        owner_id=owner.id,
        currency="USD",
        country_code="US",
        metadata_={},
    )
    session.add(project)
    await session.flush()
    total = sum((Decimal(v) for _c, v in lines), Decimal("0"))
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{suffix}",
        title="Main works",
        project_id=project.id,
        contract_type="lump_sum",
        currency="USD",
        total_value=total,
        original_contract_value=total,
        retention_percent=Decimal("10"),
        status="active",
    )
    session.add(contract)
    await session.flush()
    if ladder is not None:
        session.add(RetentionSchedule(contract_id=contract.id, accrual_rule=ladder, release_rule={}))
        await session.flush()
    built = []
    for index, (code, value) in enumerate(lines):
        line = ContractLine(
            id=uuid.uuid4(),
            contract_id=contract.id,
            code=code,
            description=f"Schedule line {code}",
            quantity=Decimal("1"),
            unit_rate=Decimal(value),
            total_value=Decimal(value),
            order_index=index,
        )
        session.add(line)
        built.append(line)
    await session.flush()
    return SimpleNamespace(project=project, contract=contract, lines={ln.code: ln for ln in built})


async def _claim(svc, job, month):
    start, end = PERIODS[month - 1]
    return await svc.create_progress_claim(
        SimpleNamespace(
            contract_id=job.contract.id,
            claim_number=f"PC-{month}",
            period_start=start,
            period_end=end,
            claim_date=end,
            currency="USD",
            metadata={},
        )
    )


@pytest.fixture(autouse=True)
def _rules():
    register_contracts_validation_rules()


async def _certify(svc, session, claim, *, engine_worked: bool):
    """Certify a claim after checking that no retention rule would stop it going out.

    A fix that pays the right figure but trips a retention rule would still
    block every such claim at submission, so the rules are asked here, on the
    draft, before the claim moves on. On a claim the engine worked out, the
    check that its stored retention is what the policy gives has to have run,
    or an empty list here would prove nothing.
    """
    await session.refresh(claim)
    report = await svc.run_claim_rules(claim)
    if engine_worked:
        assert "pay_application.retention_matches_policy" in {r.rule_id for r in report.results}
    tripped = [
        (r.rule_id, r.message)
        for r in report.errors + report.warnings
        if r.rule_id.startswith("pay_application.retention")
    ]
    assert tripped == [], tripped
    await svc.claim_repo.update_fields(claim.id, status="approved")
    return await svc.transition_claim(claim.id, "certified", "certifier")


async def _schedule_month(svc, session, job, month, bills):
    claim = await _claim(svc, job, month)
    for code, value in bills.items():
        await create_claim_line(
            ProgressClaimLineCreate(
                progress_claim_id=claim.id,
                contract_line_id=job.lines[code].id,
                period_completed_qty=Decimal("1"),
                period_completed_value=Decimal(value),
                period_completed_pct=Decimal("0"),
            ),
            session,
            str(job.project.owner_id),
        )
    return await _certify(svc, session, claim, engine_worked=True)


async def _lineless_month(svc, session, job, month, gross):
    claim = await _claim(svc, job, month)
    await svc.claim_repo.update_fields(claim.id, gross_amount=Decimal(gross))
    await svc.roll_claim_retention(claim.id)
    return await _certify(svc, session, claim, engine_worked=False)


async def _release_month(svc, session, job, month, amount):
    claim = await _claim(svc, job, month)
    session.add(
        RetentionRelease(
            contract_id=job.contract.id,
            event="final_completion",
            status="billed",
            amount=Decimal(amount),
            withheld_for_open_items=Decimal("0"),
            progress_claim_id=claim.id,
            document_ids=[],
            metadata_={},
        )
    )
    await session.flush()
    await svc.roll_claim_retention(claim.id)
    return await _certify(svc, session, claim, engine_worked=True)


def _cents(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


async def _sheet(svc, claim):
    """The G702 face, the out-of-schedule row's column I, and the claim's stored net due."""
    application = await svc.build_aia_application(claim.id)
    summary = application["summary"]
    outside = [row for row in application["lines"] if row["item_number"] == ""]
    return SimpleNamespace(
        line4=_cents(summary["total_completed_stored"]),
        line5=_cents(summary["retainage"]),
        line7=_cents(summary["previous_certificates_total"]),
        line8=_cents(summary["current_payment_due"]),
        row_i=_cents(outside[0]["retainage"]) if outside else None,
        net_due=_cents(claim.net_due),
        retention_amount=_cents(claim.retention_amount),
        held=_cents(claim.retention_held_to_date),
    )


async def test_a_ladder_that_stops_retaining_counts_the_lineless_month_once(pg_session) -> None:
    """Case L. Month 3 used to print line 5 at 14,000 and pay 20,000; month 4 kept 2,000 nothing could release."""
    svc = ContractsService(pg_session)
    job = await _job(pg_session, [("A", "100000"), ("B", "100000")], ladder=LADDER_ZERO_PAST_HALF)

    m1 = await _sheet(svc, await _schedule_month(svc, pg_session, job, 1, {"A": "100000"}))
    assert (m1.line4, m1.line5, m1.line7, m1.line8, m1.net_due) == (
        Decimal("100000.00"),
        Decimal("10000.00"),
        Decimal("0.00"),
        Decimal("90000.00"),
        Decimal("90000.00"),
    )

    m2 = await _sheet(svc, await _lineless_month(svc, pg_session, job, 2, "20000"))
    assert (m2.line4, m2.line5, m2.line7, m2.line8, m2.net_due) == (
        Decimal("120000.00"),
        Decimal("12000.00"),
        Decimal("90000.00"),
        Decimal("18000.00"),
        Decimal("18000.00"),
    )

    m3 = await _sheet(svc, await _schedule_month(svc, pg_session, job, 3, {"B": "40000"}))
    # 10% of the first 100,000 on the schedule, nothing on the 40,000 past half
    # way, plus the lineless month's 2,000 on its own row.
    assert m3.line4 == Decimal("160000.00")
    assert m3.line5 == Decimal("12000.00")
    assert m3.row_i == Decimal("2000.00")
    assert m3.held == Decimal("10000.00")
    assert m3.line7 == Decimal("108000.00")
    assert m3.line8 == Decimal("40000.00")
    assert m3.net_due == Decimal("40000.00")

    m4 = await _sheet(svc, await _release_month(svc, pg_session, job, 4, "12000"))
    # The final release takes everything held, the row's 2,000 included.
    assert m4.line5 == Decimal("0.00")
    assert m4.row_i == Decimal("0.00")
    assert m4.line7 == Decimal("148000.00")
    assert m4.line8 == Decimal("12000.00")
    assert m4.net_due == Decimal("12000.00")


async def test_a_flat_rate_accrues_the_schedule_in_full_after_a_lineless_month(pg_session) -> None:
    """Case F. Month 2 used to accrue 4,000 and pay 36,000; month 3's line 7 then over-counted by 2,000."""
    svc = ContractsService(pg_session)
    job = await _job(pg_session, [("A", "60000"), ("B", "40000")])

    m1 = await _sheet(svc, await _lineless_month(svc, pg_session, job, 1, "20000"))
    assert (m1.line4, m1.line5, m1.line8, m1.net_due) == (
        Decimal("20000.00"),
        Decimal("2000.00"),
        Decimal("18000.00"),
        Decimal("18000.00"),
    )

    m2 = await _sheet(svc, await _schedule_month(svc, pg_session, job, 2, {"A": "60000"}))
    assert m2.retention_amount == Decimal("6000.00")
    assert m2.line5 == Decimal("8000.00")
    assert m2.line7 == Decimal("18000.00")
    assert m2.line8 == Decimal("54000.00")
    assert m2.net_due == Decimal("54000.00")

    m3 = await _sheet(svc, await _schedule_month(svc, pg_session, job, 3, {"B": "40000"}))
    assert m3.retention_amount == Decimal("4000.00")
    assert m3.line5 == Decimal("12000.00")
    assert m3.line7 == Decimal("72000.00")
    assert m3.line8 == Decimal("36000.00")
    assert m3.net_due == Decimal("36000.00")
