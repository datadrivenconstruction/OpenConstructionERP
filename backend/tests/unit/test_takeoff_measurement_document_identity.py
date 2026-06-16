from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.modules.takeoff.models import TakeoffMeasurement
from app.modules.takeoff.schemas import TakeoffMeasurementCreate, TakeoffMeasurementUpdate
from app.modules.takeoff.service import TakeoffService


def _measurement_create(project_id: uuid.UUID, document_id: str | None) -> TakeoffMeasurementCreate:
    return TakeoffMeasurementCreate(
        project_id=project_id,
        document_id=document_id,
        page=1,
        type="count",
        points=[],
        count_value=1,
        measurement_value=1,
        measurement_unit="pcs",
    )


@pytest.mark.asyncio
async def test_create_measurement_accepts_takeoff_document_in_same_project() -> None:
    project_id = uuid.uuid4()
    document_id = uuid.uuid4()
    service = TakeoffService(AsyncMock())
    service.repo.get_by_id = AsyncMock(return_value=SimpleNamespace(project_id=project_id))  # type: ignore[method-assign]
    service.session.get = AsyncMock(return_value=None)  # type: ignore[method-assign]
    service.measurement_repo.create = AsyncMock(side_effect=lambda m: m)  # type: ignore[method-assign]

    created = await service.create_measurement(_measurement_create(project_id, str(document_id)))

    assert created.document_id == str(document_id)

@pytest.mark.asyncio
async def test_create_measurement_rejects_uuid_document_from_another_project() -> None:
    project_id = uuid.uuid4()
    document_id = uuid.uuid4()
    service = TakeoffService(AsyncMock())
    service.repo.get_by_id = AsyncMock(return_value=SimpleNamespace(project_id=uuid.uuid4()))  # type: ignore[method-assign]
    service.session.get = AsyncMock(return_value=None)  # type: ignore[method-assign]

    with pytest.raises(HTTPException) as exc:
        await service.create_measurement(_measurement_create(project_id, str(document_id)))

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "invalid_measurement_document_id"


@pytest.mark.asyncio
async def test_update_measurement_rejects_uuid_document_from_another_project() -> None:
    project_id = uuid.uuid4()
    document_id = uuid.uuid4()
    service = TakeoffService(AsyncMock())
    service.repo.get_by_id = AsyncMock(return_value=None)  # type: ignore[method-assign]
    service.session.get = AsyncMock(return_value=SimpleNamespace(project_id=uuid.uuid4()))  # type: ignore[method-assign]
    existing = TakeoffMeasurement(project_id=project_id, document_id=str(uuid.uuid4()), type="count", points=[])

    with pytest.raises(HTTPException) as exc:
        await service.update_measurement(
            uuid.uuid4(),
            TakeoffMeasurementUpdate(document_id=str(document_id)),
            existing=existing,
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_bulk_create_validates_each_stable_document_identity_once() -> None:
    project_id = uuid.uuid4()
    document_id = uuid.uuid4()
    service = TakeoffService(AsyncMock())
    service.repo.get_by_id = AsyncMock(return_value=SimpleNamespace(project_id=project_id))  # type: ignore[method-assign]
    service.session.get = AsyncMock(return_value=None)  # type: ignore[method-assign]
    service.measurement_repo.create_bulk = AsyncMock(side_effect=lambda rows: rows)  # type: ignore[method-assign]

    await service.bulk_create_measurements(
        [
            _measurement_create(project_id, str(document_id)),
            _measurement_create(project_id, str(document_id)),
        ],
    )

    service.repo.get_by_id.assert_awaited_once_with(document_id)


@pytest.mark.asyncio
async def test_legacy_filename_document_id_remains_passthrough() -> None:
    project_id = uuid.uuid4()
    service = TakeoffService(AsyncMock())
    service.repo.get_by_id = AsyncMock()  # type: ignore[method-assign]
    service.session.get = AsyncMock()  # type: ignore[method-assign]
    service.measurement_repo.create = AsyncMock(side_effect=lambda m: m)  # type: ignore[method-assign]

    created = await service.create_measurement(_measurement_create(project_id, "abc.pdf"))

    assert created.document_id == "abc.pdf"
    service.repo.get_by_id.assert_not_awaited()
    service.session.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_measurement_accepts_project_files_document_in_same_project() -> None:
    project_id = uuid.uuid4()
    document_id = uuid.uuid4()
    service = TakeoffService(AsyncMock())
    service.repo.get_by_id = AsyncMock(return_value=None)  # type: ignore[method-assign]
    service.session.get = AsyncMock(return_value=SimpleNamespace(project_id=project_id))  # type: ignore[method-assign]
    service.measurement_repo.create = AsyncMock(side_effect=lambda m: m)  # type: ignore[method-assign]

    created = await service.create_measurement(_measurement_create(project_id, str(document_id)))

    assert created.document_id == str(document_id)


@pytest.mark.asyncio
async def test_create_measurement_prefers_takeoff_document_before_project_files_lookup() -> None:
    project_id = uuid.uuid4()
    document_id = uuid.uuid4()
    service = TakeoffService(AsyncMock())
    service.repo.get_by_id = AsyncMock(return_value=SimpleNamespace(project_id=project_id))  # type: ignore[method-assign]
    service.session.get = AsyncMock(return_value=SimpleNamespace(project_id=project_id))  # type: ignore[method-assign]
    service.measurement_repo.create = AsyncMock(side_effect=lambda m: m)  # type: ignore[method-assign]

    created = await service.create_measurement(_measurement_create(project_id, str(document_id)))

    assert created.document_id == str(document_id)
    service.session.get.assert_not_awaited()
