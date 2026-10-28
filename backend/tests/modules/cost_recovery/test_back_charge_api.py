# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the cost recovery service (PostgreSQL, py3.12).

Exercises the persistence layer end to end on real PostgreSQL: recording
back-charges (including currency stamped from the project), the per-party /
per-currency recovery ledger over the pure engine, the agreed / recovered
timestamp stamping on update, and that the ledger is fenced to one project.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cost_recovery.schemas import BackChargeCreate, BackChargeUpdate
from app.modules.cost_recovery.service import (
    build_recovery_ledger,
    create_back_charge,
    update_back_charge,
)
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession, *, currency: str = "") -> uuid.UUID:
    user = User(
        email=f"cr-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="CR",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"CR {uuid.uuid4().hex[:6]}", owner_id=user.id, currency=currency)
    session.add(proj)
    await session.flush()
    return proj.id


@pytest.mark.asyncio
async def test_create_and_build_ledger(session: AsyncSession) -> None:
    pid = await _project(session)
    await create_back_charge(
        session,
        pid,
        BackChargeCreate(
            responsible_party="sub-a",
            description="Rework after defect",
            basis="NCR-12",
            gross_amount=Decimal("1000"),
            chargeable_pct=Decimal("0.5"),
            currency="USD",
        ),
    )
    await create_back_charge(
        session,
        pid,
        BackChargeCreate(
            responsible_party="sub-b",
            gross_amount=Decimal("400"),
            chargeable_pct=Decimal("1"),
            currency="USD",
        ),
    )

    ledger = await build_recovery_ledger(session, pid)

    assert ledger.item_count == 2
    assert ledger.open_count == 2
    assert ledger.primary_currency == "USD"
    # 500 outstanding from sub-a (1000 * 0.5) + 400 from sub-b.
    assert ledger.primary_outstanding == Decimal("900.00")

    loads = {row.party: row for row in ledger.by_party}
    assert set(loads) == {"sub-a", "sub-b"}
    assert loads["sub-a"].chargeable_total == Decimal("500.00")
    assert loads["sub-b"].chargeable_total == Decimal("400.00")
    # Most outstanding ranks first.
    assert ledger.by_party[0].party == "sub-a"
    assert len(ledger.by_currency) == 1
    assert ledger.by_currency[0].currency == "USD"


@pytest.mark.asyncio
async def test_currency_resolved_from_project(session: AsyncSession) -> None:
    pid = await _project(session, currency="GBP")
    back_charge = await create_back_charge(
        session,
        pid,
        BackChargeCreate(responsible_party="sub-c", gross_amount=Decimal("250"), currency=""),
    )
    assert back_charge.currency == "GBP"


@pytest.mark.asyncio
async def test_update_stamps_and_closes(session: AsyncSession) -> None:
    pid = await _project(session)
    back_charge = await create_back_charge(
        session,
        pid,
        BackChargeCreate(
            responsible_party="sub-d",
            gross_amount=Decimal("800"),
            chargeable_pct=Decimal("1"),
            currency="EUR",
        ),
    )

    updated = await update_back_charge(
        session,
        pid,
        back_charge.id,
        BackChargeUpdate(status="recovered", recovered_amount=Decimal("800")),
    )
    assert updated is not None
    assert updated.status == "recovered"
    assert updated.recovered_at is not None

    # A recovered back-charge has nothing outstanding and is excluded from open.
    ledger = await build_recovery_ledger(session, pid)
    assert ledger.open_count == 0
    assert ledger.primary_outstanding == Decimal("0.00")


@pytest.mark.asyncio
async def test_update_missing_returns_none(session: AsyncSession) -> None:
    pid = await _project(session)
    result = await update_back_charge(
        session,
        pid,
        uuid.uuid4(),
        BackChargeUpdate(status="agreed"),
    )
    assert result is None


@pytest.mark.asyncio
async def test_ledger_scoped_to_project(session: AsyncSession) -> None:
    pid = await _project(session)
    other = await _project(session)
    await create_back_charge(
        session, pid, BackChargeCreate(responsible_party="mine", gross_amount=Decimal("100"), currency="USD")
    )
    await create_back_charge(
        session, other, BackChargeCreate(responsible_party="theirs", gross_amount=Decimal("999"), currency="USD")
    )

    ledger = await build_recovery_ledger(session, pid)
    assert ledger.item_count == 1
    assert {row.party for row in ledger.by_party} == {"mine"}


# --- Traceability band stamped from a linked change subject (A4) --------------


@pytest.mark.asyncio
async def test_create_stamps_traceability_band_from_subject(session: AsyncSession) -> None:
    """Linking a back-charge to a real change subject stamps a provability band."""
    from app.modules.changeorders.models import ChangeOrder

    pid = await _project(session)
    change_order = ChangeOrder(project_id=pid, code=f"CO-{uuid.uuid4().hex[:6]}", title="Variation A")
    session.add(change_order)
    await session.flush()

    bc = await create_back_charge(
        session,
        pid,
        BackChargeCreate(
            responsible_party="sub-a",
            gross_amount=Decimal("1000"),
            chargeable_pct=Decimal("1"),
            currency="USD",
            subject_kind="change_order",
            subject_id=change_order.id,
        ),
    )

    meta = bc.metadata_ if isinstance(bc.metadata_, dict) else {}
    assert meta.get("traceability_band") in {"weak", "moderate", "strong"}
    assert meta.get("traceability_subject") == f"change_order:{change_order.id}"


@pytest.mark.asyncio
async def test_create_without_subject_leaves_band_unstamped(session: AsyncSession) -> None:
    pid = await _project(session)
    bc = await create_back_charge(
        session, pid, BackChargeCreate(responsible_party="x", gross_amount=Decimal("1"), currency="USD")
    )
    meta = bc.metadata_ if isinstance(bc.metadata_, dict) else {}
    assert "traceability_band" not in meta


@pytest.mark.asyncio
async def test_create_rejects_unknown_subject_kind(session: AsyncSession) -> None:
    from app.modules.cost_recovery.service import InvalidSubjectLink

    pid = await _project(session)
    with pytest.raises(InvalidSubjectLink) as excinfo:
        await create_back_charge(
            session,
            pid,
            BackChargeCreate(
                responsible_party="x",
                gross_amount=Decimal("1"),
                subject_kind="not_a_kind",
                subject_id=uuid.uuid4(),
            ),
        )
    assert excinfo.value.not_found is False


@pytest.mark.asyncio
async def test_create_rejects_missing_subject(session: AsyncSession) -> None:
    from app.modules.cost_recovery.service import InvalidSubjectLink

    pid = await _project(session)
    with pytest.raises(InvalidSubjectLink) as excinfo:
        await create_back_charge(
            session,
            pid,
            BackChargeCreate(
                responsible_party="x",
                gross_amount=Decimal("1"),
                subject_kind="change_order",
                subject_id=uuid.uuid4(),
            ),
        )
    assert excinfo.value.not_found is True
