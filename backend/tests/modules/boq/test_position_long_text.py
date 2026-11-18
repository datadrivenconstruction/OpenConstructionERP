"""Saving the Langtext of a position or section through ``PositionUpdate.long_text``.

The Langtext lives in ``metadata.gaeb_long_text`` (GAEB export and the bid
portal read it there). The top-level field lets the BOQ editor save it without
echoing the whole metadata blob, and keeps every other metadata key as stored.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ
from app.modules.boq.schemas import PositionCreate, PositionUpdate
from app.modules.boq.service import BOQService
from app.modules.projects.models import Project
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _position(session: AsyncSession, **extra: object) -> tuple[BOQService, uuid.UUID]:
    project = Project(name=f"LT {uuid.uuid4().hex[:6]}", currency="EUR", region="DACH", owner_id=uuid.uuid4())
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="LV", status="draft", metadata_={})
    session.add(boq)
    await session.flush()
    service = BOQService(session)
    pos = await service.add_position(
        PositionCreate(
            boq_id=boq.id,
            ordinal="39.1.10",
            description="Trennwand 125 mm",
            unit="m2",
            quantity=12,
            unit_rate=40,
            metadata={"gaeb_ordinal": "39.1.10", "gaeb_long_text": "Alt"},
            **extra,
        )
    )
    return service, pos.id


@pytest.mark.asyncio
async def test_long_text_is_saved_and_other_metadata_kept(session: AsyncSession) -> None:
    service, pos_id = await _position(session)
    updated = await service.update_position(pos_id, PositionUpdate(long_text="Zeile 1\r\nZeile 2"))
    assert updated.metadata_["gaeb_long_text"] == "Zeile 1\nZeile 2"
    assert updated.metadata_["gaeb_ordinal"] == "39.1.10"
    assert float(updated.unit_rate) == 40.0


@pytest.mark.asyncio
async def test_empty_long_text_removes_it(session: AsyncSession) -> None:
    service, pos_id = await _position(session)
    updated = await service.update_position(pos_id, PositionUpdate(long_text="   "))
    assert "gaeb_long_text" not in updated.metadata_
    assert updated.metadata_["gaeb_ordinal"] == "39.1.10"


@pytest.mark.asyncio
async def test_short_and_long_text_save_together(session: AsyncSession) -> None:
    service, pos_id = await _position(session)
    updated = await service.update_position(
        pos_id, PositionUpdate(description="Trennwand 150 mm", long_text="Beplankung 2x12,5")
    )
    assert updated.description == "Trennwand 150 mm"
    assert updated.metadata_["gaeb_long_text"] == "Beplankung 2x12,5"
