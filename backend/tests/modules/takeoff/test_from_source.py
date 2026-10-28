# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Project-Files -> takeoff bridge: idempotent find-or-create.

DB-free tests for ``TakeoffService.get_or_create_takeoff_from_source``. Opening
a Project-Files PDF in takeoff must create exactly one real takeoff document for
a given source id in a project, reuse it on every later open (no duplicate, no
re-parse), and keep separate projects separate. The parse itself is stubbed so
no real PDF work or subprocess runs.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from app.modules.takeoff import service as takeoff_service


class _FakeRepo:
    """In-memory stand-in for TakeoffRepository keyed like the real query."""

    def __init__(self) -> None:
        self.by_source: dict[tuple[str, str], object] = {}
        self.created: list[object] = []

    async def get_by_source_document_id(self, source_document_id, *, project_id):
        return self.by_source.get((source_document_id, str(project_id)))

    async def create(self, doc):
        self.created.append(doc)
        if doc.source_document_id is not None:
            self.by_source[(doc.source_document_id, str(doc.project_id))] = doc
        return doc


def _make_service() -> takeoff_service.TakeoffService:
    svc = object.__new__(takeoff_service.TakeoffService)
    svc.session = MagicMock()
    svc.measurement_repo = MagicMock()
    svc.repo = _FakeRepo()
    return svc


@pytest.fixture
def _stub_parse(monkeypatch, tmp_path):
    """Redirect the upload dir and count isolated-parse invocations."""
    monkeypatch.setattr(takeoff_service, "_takeoff_documents_dir", lambda: tmp_path / "td")
    calls = {"n": 0}

    async def _fake_parse(*_a, **_k):
        calls["n"] += 1
        return (1, [{"page": 1, "text": "hello", "tables": [], "has_text": True}], False, None)

    monkeypatch.setattr(takeoff_service, "_parse_pdf_isolated", _fake_parse)
    return calls


@pytest.mark.asyncio
async def test_second_open_reuses_row_without_reparsing(_stub_parse):
    svc = _make_service()
    src_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    owner_id = str(uuid.uuid4())
    content = b"%PDF-1.4\nbody"

    first = await svc.get_or_create_takeoff_from_source(
        source_document_id=src_id,
        source_project_id=project_id,
        source_file_path="/srv/uploads/plan.pdf",
        filename="plan.pdf",
        content=content,
        size_bytes=len(content),
        owner_id=owner_id,
    )
    second = await svc.get_or_create_takeoff_from_source(
        source_document_id=src_id,
        source_project_id=project_id,
        source_file_path="/srv/uploads/plan.pdf",
        filename="plan.pdf",
        content=content,
        size_bytes=len(content),
        owner_id=owner_id,
    )

    # Same row, stamped with the source id, parsed exactly once.
    assert second is first
    assert first.source_document_id == src_id
    assert first.project_id == uuid.UUID(project_id)
    assert first.filename == "plan.pdf"
    assert _stub_parse["n"] == 1
    assert len(svc.repo.created) == 1


@pytest.mark.asyncio
async def test_same_source_in_two_projects_is_two_rows(_stub_parse):
    svc = _make_service()
    src_id = str(uuid.uuid4())
    owner_id = str(uuid.uuid4())
    content = b"%PDF-1.4\nbody"

    a = await svc.get_or_create_takeoff_from_source(
        source_document_id=src_id,
        source_project_id=str(uuid.uuid4()),
        source_file_path="/srv/uploads/plan.pdf",
        filename="plan.pdf",
        content=content,
        size_bytes=len(content),
        owner_id=owner_id,
    )
    b = await svc.get_or_create_takeoff_from_source(
        source_document_id=src_id,
        source_project_id=str(uuid.uuid4()),
        source_file_path="/srv/uploads/plan.pdf",
        filename="plan.pdf",
        content=content,
        size_bytes=len(content),
        owner_id=owner_id,
    )

    # Idempotency is per project - a different project gets its own takeoff row.
    assert b is not a
    assert _stub_parse["n"] == 2
    assert len(svc.repo.created) == 2


@pytest.mark.asyncio
async def test_created_row_carries_source_and_is_indexable(_stub_parse):
    """The new row sets source_document_id so the repo lookup can find it."""
    svc = _make_service()
    src_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    content = b"%PDF-1.4\nbody"

    doc = await svc.get_or_create_takeoff_from_source(
        source_document_id=src_id,
        source_project_id=project_id,
        source_file_path="/srv/uploads/plan.pdf",
        filename="plan.pdf",
        content=content,
        size_bytes=len(content),
        owner_id=str(uuid.uuid4()),
    )

    found = await svc.repo.get_by_source_document_id(src_id, project_id=uuid.UUID(project_id))
    assert found is doc
