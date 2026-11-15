"""Strike release inspection on a real session: sensor readings feed the checklist, a repeat call reuses it."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inspections import sensor_links
from app.modules.projects.models import Project
from app.modules.site_sensors.models import (
    FormworkStrip,
    SensorAlert,
    SensorDevice,
    sensor_reading,
    sensor_reading_hourly,
)
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


async def _strip(session: AsyncSession, *, strength: str | None = "22.5"):
    user = User(email=f"strike{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    project = Project(name="Strike project", owner_id=user.id, currency="EUR")
    session.add(project)
    await session.flush()
    device = SensorDevice(project_id=project.id, code="T1", kind="temperature", unit="degC")
    session.add(device)
    await session.flush()
    struck = datetime.now(UTC)
    strip = FormworkStrip(
        project_id=project.id,
        device_id=device.id,
        element="Slab L3",
        target_strength_mpa=Decimal("20"),
        strength_at_strike_mpa=Decimal(strength) if strength else None,
        struck_at=struck,
        status="struck",
    )
    session.add(strip)
    await session.flush()
    return project, device, strip, struck


async def test_checklist_is_filled_from_readings_and_alert_is_linked(session):
    project, device, strip, struck = await _strip(session)
    await session.execute(
        insert(sensor_reading).values(
            [
                {"device_id": device.id, "recorded_at": struck - timedelta(hours=48), "value": 9.0},
                {"device_id": device.id, "recorded_at": struck - timedelta(hours=1), "value": 15.0},
            ]
        )
    )
    await session.execute(
        insert(sensor_reading_hourly).values(
            device_id=device.id,
            hour=struck - timedelta(hours=72),
            v_min=4.0,
            v_max=12.0,
            v_avg=8.0,
            n=10,
        )
    )
    alert = SensorAlert(
        project_id=project.id, device_id=device.id, kind="strength_reached", raised_at=struck - timedelta(hours=2)
    )
    session.add(alert)
    await session.flush()

    insp = await sensor_links.create_strike_inspection(
        session, {"strip_id": str(strip.id), "project_id": str(project.id)}
    )

    assert insp is not None
    assert insp.status == "scheduled"
    assert insp.location == "Slab L3"
    notes = {line["id"]: line["notes"] for line in insp.checklist_data}
    assert notes == {"strength": "22.5 MPa / 20 MPa", "age": "72 h", "temperature": "min 4 degC"}
    assert insp.metadata_["strip_id"] == str(strip.id)
    assert alert.inspection_id == insp.id


async def test_repeat_call_returns_the_same_inspection(session):
    project, _device, strip, _struck = await _strip(session, strength=None)
    data = {"strip_id": str(strip.id), "project_id": str(project.id)}
    first = await sensor_links.create_strike_inspection(session, data)
    second = await sensor_links.create_strike_inspection(session, data)

    assert first is not None
    assert second is not None
    assert second.id == first.id
    notes = {line["id"]: line["notes"] for line in first.checklist_data}
    assert notes["strength"] == "- / 20 MPa"
    assert notes["age"] == "-"
