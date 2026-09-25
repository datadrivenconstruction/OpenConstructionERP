# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A CVR payment application can be raised from a contract progress claim.

Until this link existed the CVR interim payment application was standalone: the
commercial team retyped the claim's gross and retention, and nothing recorded
which claim the application stood for. These tests pin the link and the
prefill: the claim's period gross and retention fill whatever the caller left
unset, the net stays ``gross - retention`` like every other application, and a
claim from another project is refused rather than silently linked.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import Contract, ProgressClaim
from app.modules.cvr.schemas import PaymentApplicationCreate, PaymentApplicationUpdate
from app.modules.cvr.service import CvrService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession, currency: str = "EUR") -> uuid.UUID:
    user = User(
        email=f"cvr-pc-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="CVR",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"CVR {uuid.uuid4().hex[:6]}", owner_id=user.id, currency=currency)
    session.add(proj)
    await session.flush()
    return proj.id


async def _claim(session: AsyncSession, project_id: uuid.UUID) -> ProgressClaim:
    contract = Contract(
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project_id,
        contract_type="lump_sum",
        currency="EUR",
        total_value=Decimal("200000"),
        retention_percent=Decimal("5"),
        status="active",
    )
    session.add(contract)
    await session.flush()
    claim = ProgressClaim(
        contract_id=contract.id,
        claim_number="PC-003",
        gross_amount=Decimal("40000"),
        retention_amount=Decimal("2000"),
        prior_claims_total=Decimal("60000"),
        net_due=Decimal("38000"),
        currency="EUR",
        status="certified",
        period_to=date(2026, 8, 31),
    )
    session.add(claim)
    await session.flush()
    return claim


@pytest.mark.asyncio
async def test_an_application_raised_from_a_claim_takes_its_figures(session: AsyncSession) -> None:
    pid = await _project(session)
    claim = await _claim(session, pid)
    svc = CvrService(session)

    app = await svc.create_payment_application(PaymentApplicationCreate(project_id=pid, progress_claim_id=claim.id))

    assert app.progress_claim_id == claim.id
    assert app.gross_value == Decimal("40000.00")
    assert app.retention == Decimal("2000.00")
    # The CVR rule holds: net is this period's gross less retention, the same
    # figure the claim itself states as net due.
    assert app.net_value == Decimal("38000.00")
    assert app.currency == "EUR"
    assert app.period == "2026-08"
    assert app.application_number == "PC-003"


@pytest.mark.asyncio
async def test_a_figure_the_caller_typed_wins_over_the_claim(session: AsyncSession) -> None:
    pid = await _project(session)
    claim = await _claim(session, pid)
    svc = CvrService(session)

    app = await svc.create_payment_application(
        PaymentApplicationCreate(
            project_id=pid,
            progress_claim_id=claim.id,
            period="2026-09",
            gross_value=Decimal("39000"),
        )
    )

    assert app.period == "2026-09"
    assert app.gross_value == Decimal("39000.00")
    assert app.retention == Decimal("2000.00")
    assert app.net_value == Decimal("37000.00")


@pytest.mark.asyncio
async def test_a_claim_from_another_project_is_refused(session: AsyncSession) -> None:
    pid = await _project(session)
    other = await _project(session)
    foreign_claim = await _claim(session, other)
    svc = CvrService(session)

    with pytest.raises(HTTPException) as exc:
        await svc.create_payment_application(
            PaymentApplicationCreate(project_id=pid, progress_claim_id=foreign_claim.id)
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_linking_on_update_is_checked_too(session: AsyncSession) -> None:
    pid = await _project(session)
    other = await _project(session)
    foreign_claim = await _claim(session, other)
    own_claim = await _claim(session, pid)
    svc = CvrService(session)
    app = await svc.create_payment_application(PaymentApplicationCreate(project_id=pid, period="2026-07"))

    with pytest.raises(HTTPException):
        await svc.update_payment_application(app.id, PaymentApplicationUpdate(progress_claim_id=foreign_claim.id))

    updated = await svc.update_payment_application(app.id, PaymentApplicationUpdate(progress_claim_id=own_claim.id))
    assert updated.progress_claim_id == own_claim.id


def test_period_is_required_without_a_claim() -> None:
    with pytest.raises(ValueError):
        PaymentApplicationCreate(project_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_the_picker_lists_only_this_projects_claims(session: AsyncSession) -> None:
    pid = await _project(session)
    other = await _project(session)
    own = await _claim(session, pid)
    await _claim(session, other)
    svc = CvrService(session)

    claims = await svc.list_progress_claims_for_project(pid)

    assert [c.id for c in claims] == [own.id]


@pytest.mark.asyncio
async def test_an_echoed_link_to_a_vanished_claim_does_not_block_an_edit(session: AsyncSession) -> None:
    pid = await _project(session)
    svc = CvrService(session)
    app = await svc.create_payment_application(PaymentApplicationCreate(project_id=pid, period="2026-07"))
    gone = uuid.uuid4()
    app.progress_claim_id = gone
    await session.flush()

    updated = await svc.update_payment_application(
        app.id, PaymentApplicationUpdate(notes="Resubmitted", progress_claim_id=gone)
    )

    assert updated.notes == "Resubmitted"
