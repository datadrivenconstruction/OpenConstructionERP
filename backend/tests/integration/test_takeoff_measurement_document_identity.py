# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Document-identity validation on measurement writes (issue #238).

PDF takeoff measurements used to be identified by the PDF *filename*, so two
same-named PDFs shared a measurement namespace. The invariant is now
``project_id`` + a stable document UUID; the filename is display-only.

These tests pin the backend half (defence-in-depth): ``document_id`` on a
measurement write must either be null/empty (legacy rows + freshly dropped
local files) or a UUID that references a document *in the same project*, in
either the takeoff table (``oe_takeoff_document``) or the Project Files table
(``oe_documents_document``). Anything else is rejected: a non-UUID string is a
422 (a filename slipped through), a foreign / unknown UUID is a 404.

Hermetic: the SQLAlchemy session and repositories are mocked, so the suite
runs without a database (mirrors test_takeoff_measurement_no_duplicate_query).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException


def _make_service() -> object:
    """A TakeoffService over a mocked session (no DB)."""
    from app.modules.takeoff.service import TakeoffService

    return TakeoffService(AsyncMock())


@pytest.mark.asyncio
async def test_null_document_id_is_allowed() -> None:
    """A null/empty document_id is allowed (legacy rows, fresh local drops)."""
    service = _make_service()
    project_id = uuid.uuid4()
    # Neither table should even be consulted for a null id.
    with (
        patch.object(service.repo, "get_by_id", new=AsyncMock()) as takeoff_get,
        patch.object(service.session, "get", new=AsyncMock()) as session_get,
    ):
        await service._validate_document_id(None, project_id)
        await service._validate_document_id("", project_id)
        assert takeoff_get.await_count == 0
        assert session_get.await_count == 0


@pytest.mark.asyncio
async def test_non_uuid_document_id_is_422() -> None:
    """A filename (non-UUID) string must raise 422, not silently persist."""
    service = _make_service()
    with pytest.raises(HTTPException) as exc:
        await service._validate_document_id("floor-plan.pdf", uuid.uuid4())
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_valid_uuid_in_takeoff_table_same_project_passes() -> None:
    """A UUID matching a takeoff document in this project is accepted."""
    service = _make_service()
    project_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    takeoff_doc = type("Doc", (), {"project_id": project_id})()
    with patch.object(service.repo, "get_by_id", new=AsyncMock(return_value=takeoff_doc)):
        # Must not raise.
        await service._validate_document_id(str(doc_id), project_id)


@pytest.mark.asyncio
async def test_valid_uuid_in_documents_table_same_project_passes() -> None:
    """A UUID absent from the takeoff table but present in Project Files
    (oe_documents_document) for this project is accepted (polymorphic ref)."""
    service = _make_service()
    project_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    project_doc = type("Document", (), {"project_id": project_id})()
    with (
        # Not a takeoff document.
        patch.object(service.repo, "get_by_id", new=AsyncMock(return_value=None)),
        # But it is a Project Files document in the same project.
        patch.object(service.session, "get", new=AsyncMock(return_value=project_doc)),
    ):
        await service._validate_document_id(str(doc_id), project_id)


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_foreign_project_uuid_is_404() -> None:
    """A real document UUID belonging to ANOTHER project is a 404, so it can't
    be used to attach a measurement across the project boundary, and can't act
    as an existence oracle (same code as 'document missing')."""
    service = _make_service()
    project_id = uuid.uuid4()
    other_project_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    # The document exists in both repos but under a DIFFERENT project.
    foreign_takeoff = type("Doc", (), {"project_id": other_project_id})()
    foreign_document = type("Document", (), {"project_id": other_project_id})()
    with (
        patch.object(service.repo, "get_by_id", new=AsyncMock(return_value=foreign_takeoff)),
        patch.object(service.session, "get", new=AsyncMock(return_value=foreign_document)),
        pytest.raises(HTTPException) as exc,
    ):
        await service._validate_document_id(str(doc_id), project_id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_unknown_uuid_is_404() -> None:
    """A well-formed UUID that matches no document in either table -> 404."""
    service = _make_service()
    with (
        patch.object(service.repo, "get_by_id", new=AsyncMock(return_value=None)),
        patch.object(service.session, "get", new=AsyncMock(return_value=None)),
        pytest.raises(HTTPException) as exc,
    ):
        await service._validate_document_id(str(uuid.uuid4()), uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_measurement_validates_document_id() -> None:
    """create_measurement runs the document-id gate before writing the row,
    so a filename-keyed create is rejected with 422."""
    from app.modules.takeoff.schemas import TakeoffMeasurementCreate
    from app.modules.takeoff.service import TakeoffService

    service = TakeoffService(AsyncMock())
    data = TakeoffMeasurementCreate(
        project_id=uuid.uuid4(),
        document_id="some-file.pdf",  # not a UUID
        type="distance",
        points=[{"x": 0, "y": 0}, {"x": 10, "y": 0}],
    )
    with (
        patch.object(service.measurement_repo, "create", new=AsyncMock()) as create_mock,
        pytest.raises(HTTPException) as exc,
    ):
        await service.create_measurement(data)
    assert exc.value.status_code == 422
    # The row must never reach the repository when validation fails.
    assert create_mock.await_count == 0


@pytest.mark.asyncio
async def test_bulk_create_validates_each_distinct_document_id_once() -> None:
    """bulk_create_measurements validates each distinct (project, document)
    pair exactly once (a bulk import is usually one document)."""
    from app.modules.takeoff.schemas import TakeoffMeasurementCreate
    from app.modules.takeoff.service import TakeoffService

    service = TakeoffService(AsyncMock())
    project_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    rows = [
        TakeoffMeasurementCreate(
            project_id=project_id,
            document_id=str(doc_id),
            type="count",
            points=[{"x": 1, "y": 1}],
            count_value=1,
        )
        for _ in range(5)
    ]

    validate_mock = AsyncMock()
    with (
        patch.object(service, "_validate_document_id", new=validate_mock),
        patch.object(service.measurement_repo, "create_bulk", new=AsyncMock(return_value=[])),
    ):
        await service.bulk_create_measurements(rows)
    # Five rows, one distinct (project, document) pair -> exactly one check.
    assert validate_mock.await_count == 1
