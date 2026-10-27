# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Supply-chain tracking of prefab units: QR receipt, delivery note, element link, rebar cage demo."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.solution_package_demos import load_rebar_cage_scenario, seed_rebar_cage_demo
from app.modules.prefab.guard import STAGE_ORDER, UNIT_TYPES, receipt_allowed
from app.modules.prefab.schemas import AdvanceStageRequest, PrefabUnitCreate, ReceiveByQrRequest
from app.modules.prefab.service import PrefabService
from tests._pg import transactional_session


def test_only_a_dispatched_unit_can_be_received() -> None:
    for stage in STAGE_ORDER:
        allowed, reason = receipt_allowed(stage)
        assert allowed is (stage == "dispatched")
        assert allowed or stage in reason


def test_rebar_cage_scenario_is_valid_data() -> None:
    scenario = load_rebar_cage_scenario()
    assert scenario["unit_type"] in UNIT_TYPES
    assert tuple(scenario["stages"]) == STAGE_ORDER
    statuses = {u["status"] for u in scenario["units"]}
    assert {"installed", "delivered", "dispatched"} <= statuses
    for unit in scenario["units"]:
        assert unit["status"] in STAGE_ORDER and unit["element_ref"]
        reached_delivery = STAGE_ORDER.index(unit["status"]) >= STAGE_ORDER.index("delivered")
        assert bool(unit.get("delivery_note_ref")) is reached_delivery


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner = User(id=uuid.uuid4(), email=f"sc-{uuid.uuid4().hex[:6]}@test.io", hashed_password="x", full_name="O")
        s.add(owner)
        await s.flush()
        project = Project(id=uuid.uuid4(), name="Piles", owner_id=owner.id, currency="EUR")
        s.add(project)
        await s.commit()
        s.info["project_id"] = project.id
        s.info["owner_id"] = owner.id
        yield s


@pytest.mark.asyncio
async def test_receive_by_qr_books_delivery(session: AsyncSession) -> None:
    service = PrefabService(session)
    unit = await service.create_unit(
        PrefabUnitCreate(project_id=session.info["project_id"], ref="RC-1", unit_type="rebar_cage", element_ref="BP-1")
    )
    assert unit.qr_token and unit.element_ref == "BP-1"
    request = ReceiveByQrRequest(qr_token=unit.qr_token, delivery_note_ref="DN-1")
    with pytest.raises(HTTPException) as early:
        await service.receive_by_qr(request)
    assert early.value.status_code == 400

    for _ in range(4):
        await service.advance_stage(unit.id, AdvanceStageRequest())
    received = await service.receive_by_qr(request)
    assert received.status == "delivered" and received.delivery_note_ref == "DN-1"

    with pytest.raises(HTTPException) as unknown:
        await service.receive_by_qr(ReceiveByQrRequest(qr_token="no-such-token", delivery_note_ref="DN-2"))
    assert unknown.value.status_code == 404


@pytest.mark.asyncio
async def test_rebar_cage_demo_seeds_once(session: AsyncSession) -> None:
    from app.modules.prefab.models import PrefabUnit

    owner = str(session.info["owner_id"])
    first = await seed_rebar_cage_demo(session, owner_id=owner)
    again = await seed_rebar_cage_demo(session, owner_id=owner)
    assert first["already_installed"] is False and again["already_installed"] is True
    assert again["project_id"] == first["project_id"]
    units = (
        (await session.execute(select(PrefabUnit).where(PrefabUnit.project_id == uuid.UUID(first["project_id"]))))
        .scalars()
        .all()
    )
    assert len(units) == len(load_rebar_cage_scenario()["units"])
    assert all(u.qr_token for u in units)
