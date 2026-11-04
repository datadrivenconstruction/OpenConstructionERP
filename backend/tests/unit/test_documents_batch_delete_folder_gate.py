# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bulk document delete applies the same access and folder checks as the single delete."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.documents import router as documents_router
from app.modules.documents.schemas import DocumentBatchDeleteRequest

CALLER = str(uuid.uuid4())


def _session(rows: list[tuple]) -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    return session


def _service() -> AsyncMock:
    service = AsyncMock()
    service.get_references_batch = AsyncMock(return_value=SimpleNamespace(severs=False, model_dump=lambda **_: {}))
    service.delete_document = AsyncMock()
    return service


async def _run(rows, role, member=True):
    service = _service()
    ids = [r[0] for r in rows]
    membership = AsyncMock(return_value=None)
    if not member:
        membership = AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found"))
    with (
        patch.object(documents_router, "_verify_project_membership_or_404", new=membership),
        patch(
            "app.modules.documents.folder_permissions_service.folder_access_for",
            new=AsyncMock(return_value=role),
        ),
    ):
        out = await documents_router.batch_delete_documents(
            DocumentBatchDeleteRequest(ids=ids), CALLER, _session(rows), service
        )
    return out, service


@pytest.mark.asyncio
async def test_non_owner_project_member_with_write_role_deletes() -> None:
    rows = [(uuid.uuid4(), uuid.uuid4(), "drawing", uuid.UUID(CALLER))]
    out, service = await _run(rows, "editor")
    assert out["deleted"] == 1
    service.delete_document.assert_awaited_once()


@pytest.mark.asyncio
async def test_viewer_folder_grant_deletes_nothing() -> None:
    rows = [(uuid.uuid4(), uuid.uuid4(), "drawing", uuid.UUID(CALLER))]
    out, service = await _run(rows, "viewer")
    assert out["deleted"] == 0
    service.delete_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_folder_access_deletes_nothing() -> None:
    rows = [(uuid.uuid4(), uuid.uuid4(), "drawing", uuid.UUID(CALLER))]
    out, service = await _run(rows, None)
    assert out["deleted"] == 0
    service.delete_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_editor_cannot_delete_another_members_upload() -> None:
    rows = [(uuid.uuid4(), uuid.uuid4(), "drawing", uuid.uuid4())]
    out, service = await _run(rows, "editor")
    assert out["deleted"] == 0
    service.delete_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_folder_owner_deletes_another_members_upload() -> None:
    rows = [(uuid.uuid4(), uuid.uuid4(), "drawing", uuid.uuid4())]
    out, _ = await _run(rows, "owner")
    assert out["deleted"] == 1


@pytest.mark.asyncio
async def test_non_member_deletes_nothing() -> None:
    rows = [(uuid.uuid4(), uuid.uuid4(), "drawing", uuid.UUID(CALLER))]
    out, service = await _run(rows, "owner", member=False)
    assert out["deleted"] == 0
    service.delete_document.assert_not_awaited()
