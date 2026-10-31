"""Required certificates of a machine: written through the update API, read back, merged with other metadata."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.schemas import EquipmentCreate, EquipmentResponse, EquipmentUpdate
from app.modules.equipment.service import EquipmentService
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as sess:
        yield sess


async def test_required_certificates_round_trip(session: AsyncSession) -> None:
    svc = EquipmentService(session)
    unit = await svc.create_equipment(EquipmentCreate(code=f"EX-{uuid.uuid4().hex[:8]}", name="Excavator"))
    assert EquipmentResponse.model_validate(unit).required_certificates == []

    unit.metadata_ = {"keep": 1}
    await svc.update_equipment(
        unit.id, EquipmentUpdate(required_certificates=[" Crane Operator ", "crane operator", "First Aid"])
    )
    out = EquipmentResponse.model_validate(unit)
    assert out.required_certificates == ["Crane Operator", "First Aid"]
    assert out.metadata["keep"] == 1
    assert out.model_dump()["required_certificates"] == ["Crane Operator", "First Aid"]

    await svc.update_equipment(unit.id, EquipmentUpdate(name="Excavator 2"))
    assert EquipmentResponse.model_validate(unit).required_certificates == ["Crane Operator", "First Aid"]

    await svc.update_equipment(unit.id, EquipmentUpdate(required_certificates=[]))
    out = EquipmentResponse.model_validate(unit)
    assert out.required_certificates == []
    assert "required_certificates" not in out.metadata


async def test_create_stores_required_certificates(session: AsyncSession) -> None:
    svc = EquipmentService(session)
    unit = await svc.create_equipment(
        EquipmentCreate(code=f"CR-{uuid.uuid4().hex[:8]}", name="Crane", required_certificates=["Crane Operator"])
    )
    assert unit.metadata_["required_certificates"] == ["Crane Operator"]


async def test_certification_types_list(session: AsyncSession) -> None:
    from app.modules.resources.models import Certification, Resource
    from app.modules.resources.service import ResourcesService

    res = Resource(code=f"P-{uuid.uuid4().hex[:8]}", name="Fitter", resource_type="person")
    session.add(res)
    await session.flush()
    for t in ("Welding Class A", "First Aid", "First Aid"):
        session.add(Certification(resource_id=res.id, cert_type=t, status="valid"))
    await session.flush()
    types = await ResourcesService(session).list_certification_types()
    assert {"Welding Class A", "First Aid"} <= set(types)
    assert types.count("First Aid") == 1
