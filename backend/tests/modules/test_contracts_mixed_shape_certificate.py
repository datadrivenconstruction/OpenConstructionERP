# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A flat-retention certificate asks for what the claim bills, whatever shape the months are.

Cost-plus and time-and-materials contracts keep a flat retention rate, and
that branch works the claim's net out from its own gross. The certificate
drawn over the same claim works line 8 out from the columns. The two agree
only while every claim on the contract has the same shape, and a cost-plus
job has two shapes available at once: a claim generated from the period's
costs writes no claim lines, and a claim filled in from the line table or
from site progress writes one per schedule-of-values line.

Mix them and the certificate stops matching the claim, because column D is
assembled per line from what earlier claims billed while line 7 is what the
earlier claim actually certified. A month that billed with no lines is
invisible to column D and fully visible to line 7, so line 8 subtracts a
certificate that was never added.

The first two cases here are fixed and now pass. The sheet carries a row for
what earlier claims billed that no schedule line carries, and that row stays
out of the retention snapshot, which reconciles to a line 5 measured on the
schedule alone. Both halves were needed: line 8 is floored at zero, so the
certificate could only ever report this as nothing due however large it was,
and column D on its own moved these cases from underpaying to overpaying by
the retention held on the lineless month.

The same divergence has a second entrance, which nothing can reach today: a
stored material value counts in line 4 and does not count in the claim's
gross. No request schema accepts the field, so the tests that use it write
it through the repository, which is what the next person to wire up the
StoredMaterial tables will effectively be doing.

Read the controls with the failures. The two passing cost-plus cases say the
flat branch is right on a uniform contract, and the passing lump-sum case is
here to localize the fault: the same stored value on the retention engine's
path produces a certificate that does agree, so the defect is the flat
branch in ``roll_claim_retention`` and not the certificate builder. Without
that case a reader can conclude ``build_aia_application`` is broken in
general and go and change the wrong file.

One xfail mark is left, on the stored-material case, and it is strict, so
that fix cannot land without removing it.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.core.events import event_bus
from app.modules.contracts.models import Contract, ContractLine, ProgressClaim
from app.modules.contracts.router import create_claim_line
from app.modules.contracts.schemas import AIAApplicationResponse, AutoGenerateClaimRequest, ProgressClaimLineCreate
from app.modules.contracts.service import BOQ_POSITION_META_KEY, ContractsService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"mixed-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


@pytest.fixture(autouse=True)
def _rules(monkeypatch):
    # Certifying a claim runs the pay_application rule set, which answers 503
    # when it is not registered, and an event published from inside this
    # still-open transaction writes from another session and fails on the FK.
    from app.modules.contracts.validators import register_contracts_validation_rules

    monkeypatch.setattr(event_bus, "publish_detached", lambda *a, **k: None)
    register_contracts_validation_rules()


async def _job(session, contract_type: str, *, value: str = "60000"):
    suffix = uuid.uuid4().hex[:8]
    project = Project(
        id=uuid.uuid4(), name="Mixed shape", owner_id=OWNER_ID, currency="USD", country_code="US", metadata_={}
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
        total_value=Decimal(value),
        original_contract_value=Decimal(value),
        retention_percent=Decimal("10"),
        status="active",
    )
    session.add(contract)
    await session.flush()
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="A",
        description="Cast-in-place concrete",
        quantity=Decimal("1"),
        unit_rate=Decimal(value),
        total_value=Decimal(value),
        order_index=0,
    )
    session.add(line)
    await session.flush()
    return SimpleNamespace(project=project, contract=contract, line=line)


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


async def _generated(session, job, number: str, month: int, costs: str) -> ProgressClaim:
    """The cost-plus shape: a period's costs, no schedule of values behind them."""
    return await ContractsService(session).auto_generate_claim_lines(
        (await _claim(session, job, number, month)).id,
        AutoGenerateClaimRequest(actual_costs_total=Decimal(costs)),
    )


async def _with_line(session, job, number: str, month: int, value: str) -> ProgressClaim:
    """The schedule-of-values shape, written through the endpoint the editor calls."""
    claim = await _claim(session, job, number, month)
    await create_claim_line(
        ProgressClaimLineCreate(
            progress_claim_id=claim.id,
            contract_line_id=job.line.id,
            period_completed_qty=Decimal("1"),
            period_completed_value=Decimal(value),
            period_completed_pct=Decimal("0"),
        ),
        session,
        str(OWNER_ID),
    )
    await session.refresh(claim)
    return claim


async def _certify(session, claim: ProgressClaim) -> None:
    svc = ContractsService(session)
    for target in ("submitted", "approved", "certified"):
        await svc.transition_claim(claim.id, target, str(OWNER_ID))


async def _certificate(session, claim: ProgressClaim) -> dict:
    return (await ContractsService(session).build_aia_application(claim.id))["summary"]


# ── The rule holds while every month has the same shape ───────────────────


async def test_a_cost_plus_certificate_agrees_when_no_month_has_lines(session) -> None:
    """Both months generated from costs: the sheet is a single cost-of-work row."""
    job = await _job(session, "cost_plus")
    await _certify(session, await _generated(session, job, "PC-1", 3, "10000"))
    april = await _generated(session, job, "PC-2", 4, "10000")

    summary = await _certificate(session, april)
    assert summary["current_payment_due"] == april.net_due == Decimal("9000.0000")


async def test_a_cost_plus_certificate_agrees_when_every_month_has_lines(session) -> None:
    """Both months billed off the schedule of values: column D lines up with line 7."""
    job = await _job(session, "cost_plus")
    await _certify(session, await _with_line(session, job, "PC-1", 3, "10000"))
    april = await _with_line(session, job, "PC-2", 4, "10000")

    summary = await _certificate(session, april)
    assert summary["current_payment_due"] == april.net_due == Decimal("9000.0000")


# ── It breaks the moment the shapes differ ────────────────────────────────


async def test_a_cost_plus_certificate_agrees_when_the_months_differ_in_shape(session) -> None:
    """March generated from costs, April billed off the schedule of values."""
    job = await _job(session, "cost_plus")
    march = await _generated(session, job, "PC-1", 3, "10000")
    assert march.net_due == Decimal("9000.0000")
    await _certify(session, march)

    april = await _with_line(session, job, "PC-2", 4, "10000")
    summary = await _certificate(session, april)

    # Line 7 carries March's certificate, so column D has to carry March's work.
    assert summary["previous_certificates_total"] == Decimal("9000.00")
    assert summary["current_payment_due"] == april.net_due


async def test_the_row_carrying_march_leaves_scheduled_percent_and_balance_empty(session) -> None:
    """The same two months, read as the endpoint returns them.

    March's 10,000 has no schedule line, so its row has no scheduled value to
    measure a percent or a balance against, and prints those cells empty
    rather than as zero. The endpoint validates the payload through the
    response model, which is why the model has to accept the empty cells.
    """
    job = await _job(session, "cost_plus")
    await _certify(session, await _generated(session, job, "PC-1", 3, "10000"))
    april = await _with_line(session, job, "PC-2", 4, "10000")

    payload = await ContractsService(session).build_aia_application(april.id)
    lines = AIAApplicationResponse.model_validate(payload).model_dump(mode="json")["lines"]

    assert len(lines) == 2
    schedule, march = lines
    assert Decimal(schedule["scheduled_value"]) == Decimal("60000.00")
    assert Decimal(schedule["total_completed_stored"]) == Decimal("10000.00")
    assert Decimal(schedule["percent_complete"]) == Decimal("16.67")
    assert Decimal(schedule["balance_to_finish"]) == Decimal("50000.00")

    assert march["scheduled_value"] is None
    assert march["percent_complete"] is None
    assert march["balance_to_finish"] is None
    assert Decimal(march["previous_value"]) == Decimal("10000.00")
    assert Decimal(march["total_completed_stored"]) == Decimal("10000.00")
    assert payload["summary"]["total_completed_stored"] == Decimal("20000.00")


async def test_a_cost_plus_claim_populated_from_progress_agrees_with_its_certificate(session) -> None:
    """Reachability, not arithmetic: the defect above without touching the API by hand.

    This is the only test in the file that reaches outside contracts, for the
    BOQ position and the progress observation that populate reads. A failure
    here that is an import or a schema drift in those modules is not a money
    bug; the arithmetic is pinned by the test above it.
    """
    from app.modules.boq.models import BOQ, Position
    from app.modules.progress.models import ProgressEntry

    job = await _job(session, "cost_plus")
    await _certify(session, await _generated(session, job, "PC-1", 3, "10000"))

    boq = BOQ(id=uuid.uuid4(), project_id=job.project.id, name="BOQ")
    session.add(boq)
    await session.flush()
    position = Position(
        id=uuid.uuid4(),
        boq_id=boq.id,
        ordinal="01",
        description="Concrete",
        unit="m3",
        quantity="1",
        unit_rate="60000",
        total="60000",
    )
    session.add(position)
    await session.flush()
    svc = ContractsService(session)
    await svc.line_repo.update_fields(job.line.id, metadata_={BOQ_POSITION_META_KEY: str(position.id)})
    session.add(
        ProgressEntry(
            id=uuid.uuid4(),
            project_id=job.project.id,
            boq_position_id=position.id,
            period_label="2026-04",
            percent_complete=Decimal("20"),
        )
    )
    await session.flush()

    april = await _claim(session, job, "PC-2", 4)
    await svc.populate_claim_from_progress(april.id)
    april = await svc.commit_preview_to_claim(
        april.id,
        [
            SimpleNamespace(
                contract_line_id=job.line.id, period_completed_pct=Decimal("20"), period_completed_value=None
            )
        ],
    )

    summary = await _certificate(session, april)
    assert summary["current_payment_due"] == april.net_due


# ── Stored material: nothing can set it today, so guard the day something can ──


@pytest.mark.xfail(
    strict=True,
    reason=(
        "The flat branch works net out of period_completed_value alone, so column F is in "
        "line 4 and not in what the claim bills. Certificate says 13500.00, claim bills "
        "9000.0000. Unreachable today only because no request schema accepts the field."
    ),
)
async def test_a_flat_retention_claim_bills_the_stored_material_its_certificate_counts(session) -> None:
    """Cost-plus, 10000 of work and 5000 of material delivered but not installed."""
    job = await _job(session, "cost_plus")
    claim = await _with_line(session, job, "PC-1", 3, "10000")
    svc = ContractsService(session)
    line = (await svc.claim_line_repo.list_for_claim(claim.id))[0]

    # No request schema carries this column, so this is the repository write
    # that wiring up the StoredMaterial tables amounts to.
    await svc.claim_line_repo.update_fields(line.id, materials_stored_value=Decimal("5000"))
    claim = await svc.roll_claim_retention(claim.id, gross_follows_lines=True)

    summary = await _certificate(session, claim)
    assert summary["total_completed_stored"] == Decimal("15000.00")
    assert summary["current_payment_due"] == claim.net_due


async def test_the_retention_engine_bills_the_stored_material_its_certificate_counts(session) -> None:
    """The same figures on a lump-sum job, which localizes the fault.

    The retention engine works from completed-and-stored less held less prior,
    so it counts column F. This passing beside the failure above is what says
    the defect is the flat branch rather than the certificate builder.
    """
    job = await _job(session, "lump_sum")
    claim = await _with_line(session, job, "PC-1", 3, "10000")
    svc = ContractsService(session)
    line = (await svc.claim_line_repo.list_for_claim(claim.id))[0]

    await svc.claim_line_repo.update_fields(line.id, materials_stored_value=Decimal("5000"))
    claim = await svc.roll_claim_retention(claim.id, gross_follows_lines=True)

    summary = await _certificate(session, claim)
    assert summary["total_completed_stored"] == Decimal("15000.00")
    assert summary["current_payment_due"] == claim.net_due == Decimal("13500.0000")
