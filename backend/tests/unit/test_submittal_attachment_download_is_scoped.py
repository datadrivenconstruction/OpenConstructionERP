# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Downloading a submittal attachment is gated by project access and by the submittal's own list."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.modules.submittals import router as sub_router

pytestmark = pytest.mark.asyncio


def _service(attachments: list[dict]) -> SimpleNamespace:
    submittal = SimpleNamespace(project_id=uuid.uuid4(), metadata_={"attachments": attachments})
    return SimpleNamespace(get_submittal=AsyncMock(return_value=submittal))


async def test_a_user_without_project_access_is_refused(monkeypatch) -> None:
    doc = uuid.uuid4()
    deny = AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden"))
    monkeypatch.setattr(sub_router, "verify_project_access", deny)
    service = _service([{"document_id": str(doc), "path": "submittals/attachments/x.pdf"}])
    with pytest.raises(HTTPException) as exc:
        await sub_router.download_submittal_attachment(uuid.uuid4(), doc, session=None, user_id="u2", service=service)
    assert exc.value.status_code == 403
    deny.assert_awaited_once()


async def test_a_document_of_another_submittal_is_not_found(monkeypatch) -> None:
    monkeypatch.setattr(sub_router, "verify_project_access", AsyncMock())
    service = _service([{"document_id": str(uuid.uuid4()), "path": "submittals/attachments/x.pdf"}])
    with pytest.raises(HTTPException) as exc:
        await sub_router.download_submittal_attachment(
            uuid.uuid4(), uuid.uuid4(), session=None, user_id="u1", service=service
        )
    assert exc.value.status_code == 404


async def test_a_linked_document_without_a_stored_file_is_not_served(monkeypatch) -> None:
    doc = uuid.uuid4()
    monkeypatch.setattr(sub_router, "verify_project_access", AsyncMock())
    service = _service([{"document_id": str(doc)}])
    with pytest.raises(HTTPException) as exc:
        await sub_router.download_submittal_attachment(uuid.uuid4(), doc, session=None, user_id="u1", service=service)
    assert exc.value.status_code == 404
