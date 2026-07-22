# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""From-source takeoff is concurrency-safe (issue #369).

``POST /documents/from-source`` find-or-creates a takeoff document per
``(project_id, source_document_id)``. The lookup-then-insert used to race, so
two concurrent opens of one source PDF could both miss and both insert,
minting duplicate rows and stranding measurements on an unreachable duplicate.
A unique index now rejects the second insert, and the service resolves that
``IntegrityError`` to the winning row instead of surfacing it, so both callers
converge on one shared document.

Hermetic: the session and repositories are mocked, so these pin the service
logic without a database (mirrors test_takeoff_measurement_document_identity).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import IntegrityError


def _make_service() -> object:
    """A TakeoffService over a mocked session (no DB)."""
    from app.modules.takeoff.service import TakeoffService

    return TakeoffService(AsyncMock())


def _kwargs(source_document_id: str, project_id: uuid.UUID) -> dict:
    return {
        "source_document_id": source_document_id,
        "source_project_id": str(project_id),
        "filename": "plan.pdf",
        "content": b"%PDF-1.4 fake",
        "size_bytes": 12,
        "owner_id": str(uuid.uuid4()),
    }


def _integrity_error() -> IntegrityError:
    """A unique-violation shaped like SQLAlchemy raises one on flush."""
    return IntegrityError("INSERT INTO oe_takeoff_document", {}, Exception("unique_violation"))


@pytest.mark.asyncio
async def test_returns_existing_without_uploading() -> None:
    """Idempotent happy path: an existing row is returned, nothing is uploaded
    or re-parsed."""
    service = _make_service()
    project_id = uuid.uuid4()
    existing = object()
    with (
        patch.object(
            service.repo,
            "get_by_source_document_id",
            new=AsyncMock(return_value=existing),
        ) as lookup,
        patch.object(service, "upload_document", new=AsyncMock()) as upload,
    ):
        result = await service.get_or_create_takeoff_from_source(**_kwargs("src-1", project_id))
    assert result is existing
    assert upload.await_count == 0
    assert lookup.await_count == 1


@pytest.mark.asyncio
async def test_race_loser_resolves_to_winner() -> None:
    """A concurrent request wins the unique index: our insert raises
    IntegrityError, so we roll back and return the winner - one shared row, no
    duplicate, no stranded measurement."""
    service = _make_service()
    project_id = uuid.uuid4()
    winner = object()
    # First lookup misses; after the failed insert + rollback the re-lookup
    # finds the row the winning request committed.
    lookup = AsyncMock(side_effect=[None, winner])
    upload = AsyncMock(side_effect=_integrity_error())
    with (
        patch.object(service.repo, "get_by_source_document_id", new=lookup),
        patch.object(service, "upload_document", new=upload),
    ):
        result = await service.get_or_create_takeoff_from_source(**_kwargs("src-2", project_id))
    assert result is winner
    assert lookup.await_count == 2  # initial miss + post-rollback re-lookup
    assert upload.await_count == 1
    service.session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_integrity_error_without_winner_reraises() -> None:
    """If the re-lookup still finds nothing, the violation was something other
    than the source unique index, so it must propagate, not be swallowed."""
    service = _make_service()
    project_id = uuid.uuid4()
    lookup = AsyncMock(side_effect=[None, None])
    upload = AsyncMock(side_effect=_integrity_error())
    with (
        patch.object(service.repo, "get_by_source_document_id", new=lookup),
        patch.object(service, "upload_document", new=upload),
        pytest.raises(IntegrityError),
    ):
        await service.get_or_create_takeoff_from_source(**_kwargs("src-3", project_id))
    assert lookup.await_count == 2
    service.session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_first_writer_uploads_normally() -> None:
    """When the lookup misses and the insert succeeds, the fresh document is
    returned and no rollback happens (the common, uncontended path)."""
    service = _make_service()
    project_id = uuid.uuid4()
    fresh = object()
    lookup = AsyncMock(return_value=None)
    upload = AsyncMock(return_value=fresh)
    with (
        patch.object(service.repo, "get_by_source_document_id", new=lookup),
        patch.object(service, "upload_document", new=upload),
    ):
        result = await service.get_or_create_takeoff_from_source(**_kwargs("src-4", project_id))
    assert result is fresh
    assert lookup.await_count == 1
    assert upload.await_count == 1
    service.session.rollback.assert_not_awaited()
