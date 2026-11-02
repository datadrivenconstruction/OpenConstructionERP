# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A flat bill becomes sections in one step, and a recurring line is priced once.

Run:
    cd backend
    python -m pytest tests/modules/boq/test_restructure_and_set_rate.py -q
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ
from app.modules.boq.restructure import plan_restructure
from app.modules.boq.schemas import BulkPositionUpdate, PositionCreate, RestructureRequest
from app.modules.boq.service import BOQService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

A, B, C, D, E = (uuid.uuid4() for _ in range(5))


def test_plan_hangs_sections_under_the_nearest_lower_level() -> None:
    plan = plan_restructure([(A, 1), (B, 2), (C, 0), (D, 1), (E, 0)], max_depth=8)
    assert [(p.parent_id, p.is_section) for p in plan] == [
        (None, True),
        (A, True),
        (B, False),
        (None, True),
        (D, False),
    ]
    assert [p.sort_order for p in plan] == [0, 1, 2, 3, 4]


def test_plan_lets_a_level_skip_and_closes_deeper_sections() -> None:
    plan = plan_restructure([(A, 1), (B, 3), (C, 2), (D, 0)], max_depth=8)
    assert [p.parent_id for p in plan] == [None, A, A, C]


def test_plan_refuses_repeats_and_too_deep_nesting() -> None:
    with pytest.raises(ValueError, match="twice"):
        plan_restructure([(A, 0), (A, 1)], max_depth=8)
    with pytest.raises(ValueError, match="deeper"):
        plan_restructure([(A, 1), (B, 2), (C, 3)], max_depth=2)


def test_set_rate_is_its_own_bulk_style() -> None:
    assert BulkPositionUpdate(ids=[A], set_rate=Decimal("95.50")).set_rate == Decimal("95.50")
    with pytest.raises(ValidationError):
        BulkPositionUpdate(ids=[A], set_rate=Decimal("1"), rate_factor=1.1)
    with pytest.raises(ValidationError):
        BulkPositionUpdate(ids=[A], set_rate=Decimal("-1"))


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _bill(session: AsyncSession) -> tuple[BOQService, uuid.UUID]:
    owner = User(email=f"restr-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="E", role="admin")
    session.add(owner)
    await session.flush()
    project = Project(name=f"Restr {uuid.uuid4().hex[:6]}", currency="EUR", region="FR", owner_id=owner.id)
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="DPGF", status="draft", metadata_={})
    session.add(boq)
    await session.flush()
    return BOQService(session), boq.id


async def _add(svc: BOQService, boq_id: uuid.UUID, ordinal: str, desc: str, unit: str, qty: float, rate: float):
    return await svc.add_position(
        PositionCreate(boq_id=boq_id, ordinal=ordinal, description=desc, unit=unit, quantity=qty, unit_rate=rate)
    )


@pytest.mark.asyncio
async def test_a_flat_pasted_bill_becomes_sections_and_back(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session)
    chapter = await _add(svc, boq_id, "1", "Gros oeuvre", "pcs", 1, 0)
    sub = await _add(svc, boq_id, "1.1", "Fondations", "pcs", 1, 0)
    line = await _add(svc, boq_id, "1.1.1", "Béton C25/30", "m3", 2.625, 120)

    req = RestructureRequest(
        rows=[
            {"position_id": chapter.id, "level": 1},
            {"position_id": sub.id, "level": 2},
            {"position_id": line.id, "level": 0},
        ]
    )
    res = await svc.restructure_positions(boq_id, req)
    assert (res.sections, res.positions, res.converted_to_section) == (2, 1, 2)
    assert chapter.unit == "section" and chapter.parent_id is None
    assert sub.parent_id == chapter.id and sub.quantity == "0"
    assert sub.metadata_["converted_from_position"]["unit"] == "pcs"
    assert line.parent_id == sub.id and line.unit == "m3"

    back = RestructureRequest(rows=[{"position_id": p.id, "level": 0} for p in (chapter, sub, line)])
    res = await svc.restructure_positions(boq_id, back)
    assert res.converted_to_position == 2
    assert sub.unit == "pcs" and sub.parent_id is None
    assert "converted_from_position" not in sub.metadata_


@pytest.mark.asyncio
async def test_restructure_must_list_every_row(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session)
    one = await _add(svc, boq_id, "1", "A", "m2", 1, 1)
    await _add(svc, boq_id, "2", "B", "m2", 1, 1)
    with pytest.raises(HTTPException) as exc:
        await svc.restructure_positions(boq_id, RestructureRequest(rows=[{"position_id": one.id, "level": 1}]))
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_set_rate_prices_every_occurrence_and_leaves_sections_alone(session: AsyncSession) -> None:
    svc, boq_id = await _bill(session)
    first = await _add(svc, boq_id, "1.1", "Béton C25/30", "m3", 10, 110)
    second = await _add(svc, boq_id, "2.1", "Béton C25/30", "m3", 4, 125)
    already = await _add(svc, boq_id, "3.1", "Béton C25/30", "m3", 2, 120)
    header = await _add(svc, boq_id, "3", "Bâtiment C", "section", 0, 0)

    res = await svc.bulk_update_positions(
        boq_id, BulkPositionUpdate(ids=[first.id, second.id, already.id, header.id], set_rate=Decimal("120"))
    )
    assert (res.updated, res.unchanged, res.skipped) == (2, 2, 0)
    assert Decimal(first.unit_rate) == Decimal("120")
    assert Decimal(second.total) == Decimal("480")
    assert Decimal(header.unit_rate) == 0
