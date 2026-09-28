# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A takeoff push does not write a quantity into a locked bill.

Every position writer in the BOQ module refuses a locked bill with 409
(``BOQService._ensure_not_locked``). Linking a PDF measurement or a DWG
annotation to a position with ``push_quantity`` wrote the position's quantity
and recomputed its total with no lock check, so a locked bill moved under a
takeoff link. The push is now refused with the same 409 before anything is
written: the link is not stored either, so nothing half-happens. A plain link
without the push is bookkeeping and still goes through on a locked bill.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

# ── Per-module temp data dir (MUST run BEFORE app imports) ────────────────
_PREVIOUS_DATA_DIR = os.environ.get("DATA_DIR")
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-locked-push-"))
os.environ["DATA_DIR"] = str(_TMP_DIR)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

import app.modules.boq.models  # noqa: E402, F401
import app.modules.dwg_takeoff.models  # noqa: E402, F401
import app.modules.projects.models  # noqa: E402, F401
import app.modules.takeoff.models  # noqa: E402, F401
import app.modules.users.models  # noqa: E402, F401
from app.modules.boq.models import BOQ, Position  # noqa: E402
from app.modules.dwg_takeoff.models import DwgAnnotation, DwgDrawing  # noqa: E402
from app.modules.dwg_takeoff.service import DwgTakeoffService  # noqa: E402
from app.modules.takeoff.models import TakeoffMeasurement  # noqa: E402
from app.modules.takeoff.service import TakeoffService  # noqa: E402

# Put it back: DATA_DIR is process wide and only the imports above read it.
if _PREVIOUS_DATA_DIR is None:
    os.environ.pop("DATA_DIR", None)
else:
    os.environ["DATA_DIR"] = _PREVIOUS_DATA_DIR

from tests._pg import transactional_session  # noqa: E402

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(email=f"locked-push-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x", full_name="Push")
    session.add(user)
    await session.flush()
    project = Project(name="Locked push", owner_id=user.id)
    session.add(project)
    await session.flush()
    return project.id


async def _position(session: AsyncSession, project_id: uuid.UUID, *, locked: bool) -> uuid.UUID:
    boq = BOQ(project_id=project_id, name="Bill", is_locked=locked)
    session.add(boq)
    await session.flush()
    position = Position(
        boq_id=boq.id,
        ordinal="01.001",
        description="Wall",
        unit="m",
        quantity="7",
        unit_rate="10",
        total="70",
    )
    session.add(position)
    await session.flush()
    return position.id


async def _quantity(session: AsyncSession, position_id: uuid.UUID) -> Decimal:
    from app.modules.boq.service import BOQService

    position = await BOQService(session).position_repo.get_by_id(position_id)
    assert position is not None
    await session.refresh(position)
    return Decimal(position.quantity)


async def _measurement(session: AsyncSession, project_id: uuid.UUID) -> TakeoffMeasurement:
    row = TakeoffMeasurement(project_id=project_id, type="distance", measurement_value=Decimal("32.5"))
    session.add(row)
    await session.flush()
    return row


async def _annotation(session: AsyncSession, project_id: uuid.UUID) -> DwgAnnotation:
    drawing = DwgDrawing(
        project_id=project_id, name="d", filename="d.dwg", file_format="dwg", file_path="x", status="ready"
    )
    session.add(drawing)
    await session.flush()
    row = DwgAnnotation(
        project_id=project_id,
        drawing_id=drawing.id,
        annotation_type="distance",
        geometry={"points": []},
        measurement_value=Decimal("32.5"),
    )
    session.add(row)
    await session.flush()
    return row


# ── PDF takeoff ─────────────────────────────────────────────────────────────


async def test_a_measurement_push_into_a_locked_bill_is_refused(session: AsyncSession) -> None:
    project_id = await _project(session)
    position_id = await _position(session, project_id, locked=True)
    measurement = await _measurement(session, project_id)

    with pytest.raises(HTTPException) as exc:
        await TakeoffService(session).link_measurement_to_boq(
            measurement.id, str(position_id), existing=measurement, push_quantity=True
        )
    assert exc.value.status_code == 409
    assert await _quantity(session, position_id) == Decimal("7")
    await session.refresh(measurement)
    assert measurement.linked_boq_position_id is None


async def test_a_measurement_link_without_push_still_reaches_a_locked_bill(session: AsyncSession) -> None:
    project_id = await _project(session)
    position_id = await _position(session, project_id, locked=True)
    measurement = await _measurement(session, project_id)

    item = await TakeoffService(session).link_measurement_to_boq(
        measurement.id, str(position_id), existing=measurement, push_quantity=False
    )
    assert str(item.linked_boq_position_id) == str(position_id)
    assert await _quantity(session, position_id) == Decimal("7")


# ── DWG takeoff ─────────────────────────────────────────────────────────────


async def test_an_annotation_push_into_a_locked_bill_is_refused(session: AsyncSession) -> None:
    project_id = await _project(session)
    position_id = await _position(session, project_id, locked=True)
    annotation = await _annotation(session, project_id)

    with pytest.raises(HTTPException) as exc:
        await DwgTakeoffService(session).link_annotation_to_boq(annotation.id, str(position_id), push_quantity=True)
    assert exc.value.status_code == 409
    assert await _quantity(session, position_id) == Decimal("7")
    await session.refresh(annotation)
    assert annotation.linked_boq_position_id is None


async def test_an_annotation_push_into_an_open_bill_still_writes(session: AsyncSession) -> None:
    project_id = await _project(session)
    position_id = await _position(session, project_id, locked=False)
    annotation = await _annotation(session, project_id)

    await DwgTakeoffService(session).link_annotation_to_boq(annotation.id, str(position_id), push_quantity=True)
    assert await _quantity(session, position_id) == Decimal("32.5")
