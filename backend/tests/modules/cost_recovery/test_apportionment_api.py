# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for cost-recovery apportionment (PostgreSQL, py3.12).

Exercises the persistence layer end to end on real PostgreSQL: splitting a
back-charge's chargeable amount across parties (reconciled to the cent),
reading the split back, re-apportioning (replacing the previous split),
rejecting shares that do not sum to 1.0, the not-found path, and that the split
is fenced to one project.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cost_recovery.schemas import ApportionmentShareIn, BackChargeCreate
from app.modules.cost_recovery.service import (
    apportion_back_charge,
    create_back_charge,
    list_apportionment,
)
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession, *, currency: str = "USD") -> uuid.UUID:
    user = User(
        email=f"cra-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="CRA",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"CRA {uuid.uuid4().hex[:6]}", owner_id=user.id, currency=currency)
    session.add(proj)
    await session.flush()
    return proj.id


async def _back_charge(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    gross: Decimal,
    pct: Decimal = Decimal("1"),
    currency: str = "USD",
) -> uuid.UUID:
    bc = await create_back_charge(
        session,
        project_id,
        BackChargeCreate(
            responsible_party="sub-a",
            gross_amount=gross,
            chargeable_pct=pct,
            currency=currency,
        ),
    )
    return bc.id


@pytest.mark.asyncio
async def test_apportion_splits_and_persists(session: AsyncSession) -> None:
    pid = await _project(session)
    bc_id = await _back_charge(session, pid, gross=Decimal("1000.00"))

    rows = await apportion_back_charge(
        session,
        pid,
        bc_id,
        [
            ApportionmentShareIn(party="sub", share_pct=Decimal("0.6"), basis="NCR-7"),
            ApportionmentShareIn(party="designer", share_pct=Decimal("0.4")),
        ],
    )
    assert rows is not None
    by_party = {r.party: r for r in rows}
    assert by_party["sub"].share_amount == Decimal("600.00")
    assert by_party["designer"].share_amount == Decimal("400.00")
    assert by_party["sub"].share_pct == Decimal("0.6000")
    assert by_party["sub"].basis == "NCR-7"
    # Currency copied from the parent back-charge.
    assert by_party["sub"].currency == "USD"
    # The split reconciles to the chargeable amount exactly.
    assert sum(r.share_amount for r in rows) == Decimal("1000.00")


@pytest.mark.asyncio
async def test_apportion_reconciles_residual_to_largest(session: AsyncSession) -> None:
    pid = await _project(session)
    # 100.00 split three ways at a third each leaves a rounding residual that
    # must land on the largest share so the parts sum to exactly 100.00.
    bc_id = await _back_charge(session, pid, gross=Decimal("100.00"))
    rows = await apportion_back_charge(
        session,
        pid,
        bc_id,
        [
            ApportionmentShareIn(party="a", share_pct=Decimal("0.34")),
            ApportionmentShareIn(party="b", share_pct=Decimal("0.33")),
            ApportionmentShareIn(party="c", share_pct=Decimal("0.33")),
        ],
    )
    assert rows is not None
    assert sum(r.share_amount for r in rows) == Decimal("100.00")
    by_party = {r.party: r.share_amount for r in rows}
    # Largest share (a) absorbs the residual.
    assert by_party["a"] == Decimal("34.00")


@pytest.mark.asyncio
async def test_apportion_merges_duplicate_parties(session: AsyncSession) -> None:
    pid = await _project(session)
    bc_id = await _back_charge(session, pid, gross=Decimal("1000.00"))
    rows = await apportion_back_charge(
        session,
        pid,
        bc_id,
        [
            ApportionmentShareIn(party="sub", share_pct=Decimal("0.3")),
            ApportionmentShareIn(party="sub", share_pct=Decimal("0.3")),
            ApportionmentShareIn(party="designer", share_pct=Decimal("0.4")),
        ],
    )
    assert rows is not None
    by_party = {r.party: r for r in rows}
    assert set(by_party) == {"sub", "designer"}
    assert by_party["sub"].share_pct == Decimal("0.6000")
    assert by_party["sub"].share_amount == Decimal("600.00")


@pytest.mark.asyncio
async def test_apportion_replaces_previous(session: AsyncSession) -> None:
    pid = await _project(session)
    bc_id = await _back_charge(session, pid, gross=Decimal("1000.00"))
    await apportion_back_charge(
        session,
        pid,
        bc_id,
        [
            ApportionmentShareIn(party="sub", share_pct=Decimal("0.5")),
            ApportionmentShareIn(party="designer", share_pct=Decimal("0.5")),
        ],
    )
    # Re-apportion: the previous split is replaced, not doubled.
    await apportion_back_charge(
        session,
        pid,
        bc_id,
        [ApportionmentShareIn(party="sub", share_pct=Decimal("1"))],
    )
    rows = await list_apportionment(session, pid, bc_id)
    assert len(rows) == 1
    assert rows[0].party == "sub"
    assert rows[0].share_amount == Decimal("1000.00")


@pytest.mark.asyncio
async def test_apportion_invalid_shares_raises(session: AsyncSession) -> None:
    pid = await _project(session)
    bc_id = await _back_charge(session, pid, gross=Decimal("1000.00"))
    with pytest.raises(ValueError):
        await apportion_back_charge(
            session,
            pid,
            bc_id,
            [
                ApportionmentShareIn(party="sub", share_pct=Decimal("0.5")),
                ApportionmentShareIn(party="designer", share_pct=Decimal("0.2")),
            ],
        )


@pytest.mark.asyncio
async def test_apportion_missing_back_charge_returns_none(session: AsyncSession) -> None:
    pid = await _project(session)
    result = await apportion_back_charge(
        session,
        pid,
        uuid.uuid4(),
        [ApportionmentShareIn(party="sub", share_pct=Decimal("1"))],
    )
    assert result is None


@pytest.mark.asyncio
async def test_apportion_scoped_to_project(session: AsyncSession) -> None:
    pid = await _project(session)
    other = await _project(session)
    bc_id = await _back_charge(session, pid, gross=Decimal("500.00"))
    await apportion_back_charge(
        session,
        pid,
        bc_id,
        [ApportionmentShareIn(party="sub", share_pct=Decimal("1"))],
    )
    # The same back-charge id read under another project returns nothing.
    assert await list_apportionment(session, other, bc_id) == []
    # Apportioning it under the wrong project is a not-found no-op.
    assert (
        await apportion_back_charge(
            session,
            other,
            bc_id,
            [ApportionmentShareIn(party="sub", share_pct=Decimal("1"))],
        )
        is None
    )


@pytest.mark.asyncio
async def test_apportion_on_partial_chargeable(session: AsyncSession) -> None:
    pid = await _project(session)
    # Gross 1000 at 50% chargeable -> 500 chargeable is what gets split.
    bc_id = await _back_charge(session, pid, gross=Decimal("1000.00"), pct=Decimal("0.5"))
    rows = await apportion_back_charge(
        session,
        pid,
        bc_id,
        [
            ApportionmentShareIn(party="sub", share_pct=Decimal("0.5")),
            ApportionmentShareIn(party="designer", share_pct=Decimal("0.5")),
        ],
    )
    assert rows is not None
    assert sum(r.share_amount for r in rows) == Decimal("500.00")
    assert all(r.share_amount == Decimal("250.00") for r in rows)
