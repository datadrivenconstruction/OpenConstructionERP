# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate check against a real PostgreSQL database.

Does an estimate get rated against the company's other estimates, does an
accepted finding leave the counts and land in the activity log, and does the
display preference default to the quiet badge.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.boq.models import BOQ, BOQActivityLog, BOQMarkup, Position
from app.modules.estimate_checks.service import EstimateCheckService, clear_caches
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import isolated_engine


def _position(boq_id, n, qty, rate, labour_h=1.0):
    return Position(
        boq_id=boq_id,
        ordinal=f"01.{n:03d}",
        description=f"Item {n}",
        unit="m2",
        quantity=str(qty),
        unit_rate=str(rate),
        total=str(qty * rate),
        sort_order=n,
        metadata_={
            "resources": [
                {"type": "labor", "unit": "h", "quantity": labour_h, "unit_rate": 40},
                {"type": "material", "unit": "m2", "quantity": 1, "unit_rate": rate - 40 * labour_h},
            ]
        },
    )


@pytest_asyncio.fixture
async def ctx():
    clear_caches()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            owner = User(email=f"e-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", role="admin")
            session.add(owner)
            await session.flush()
            project = Project(name="Depot", owner_id=owner.id, currency="EUR", region="DACH")
            session.add(project)
            await session.flush()
            boqs = []
            for i in range(6):
                b = BOQ(project_id=project.id, name=f"Past {i}")
                session.add(b)
                await session.flush()
                session.add_all([_position(b.id, n, 10, 100) for n in range(1, 4)])
                session.add(BOQMarkup(boq_id=b.id, name="OH", category="overhead", percentage=str(9 + i % 3)))
                boqs.append(b)
            active = BOQ(project_id=project.id, name="Tender")
            session.add(active)
            await session.flush()
            # Labour 2 h x 40 = 80 of 100: far above the 40% of past estimates.
            session.add_all([_position(active.id, n, 10, 100, labour_h=2.0) for n in range(1, 4)])
            session.add(_position(active.id, 9, 5, 0))
            session.add(BOQMarkup(boq_id=active.id, name="OH", category="overhead", percentage="10"))
            await session.flush()
            yield session, active, str(owner.id)


@pytest.mark.asyncio
async def test_check_rates_against_past_estimates(ctx):
    session, active, _ = ctx
    res = await EstimateCheckService(session).check(active.id)
    kpis = {k["kpi_id"]: k for k in res["kpis"]}
    assert res["comparables_pool"] == 6
    assert kpis["labour_share"]["compared"] == 6
    assert kpis["labour_share"]["status"] == "warning"
    assert kpis["overhead_pct"]["status"] == "normal"
    assert kpis["zero_rate"]["status"] in ("suspect", "warning")
    assert kpis["zero_rate"]["positions"][0]["ordinal"] == "01.009"
    assert res["counts"]["warning"] >= 1


@pytest.mark.asyncio
async def test_accept_moves_finding_out_of_counts_and_into_audit(ctx):
    session, active, user_id = ctx
    svc = EstimateCheckService(session)
    before = await svc.check(active.id)
    res = await svc.accept(active.id, "labour_share", "Night shifts priced on purpose", user_id)
    labour = next(k for k in res["kpis"] if k["kpi_id"] == "labour_share")
    assert labour["accepted"]["reason"] == "Night shifts priced on purpose"
    assert res["counts"]["accepted"] == before["counts"]["accepted"] + 1
    log = (await session.execute(select(BOQActivityLog).where(BOQActivityLog.boq_id == active.id))).scalars().all()
    assert any(e.action == "estimate_check.accepted" for e in log)
    res = await svc.withdraw(active.id, "labour_share", user_id)
    assert next(k for k in res["kpis"] if k["kpi_id"] == "labour_share")["accepted"] is None


@pytest.mark.asyncio
async def test_normal_finding_cannot_be_accepted(ctx):
    session, active, user_id = ctx
    with pytest.raises(HTTPException) as exc:
        await EstimateCheckService(session).accept(active.id, "overhead_pct", "No reason needed", user_id)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_preference_defaults_to_badge_and_settings_disable_a_kpi(ctx):
    session, active, user_id = ctx
    svc = EstimateCheckService(session)
    assert await svc.preference(user_id) == "badge"
    assert await svc.save_preference(user_id, "off") == "off"
    await svc.save_settings({"kpis": {"labour_share": {"enabled": False}}}, user_id)
    res = await svc.check(active.id)
    assert "labour_share" not in {k["kpi_id"] for k in res["kpis"]}
